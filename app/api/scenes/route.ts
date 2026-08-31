import { buildSceneSnapshot, DEFAULT_PROJECT_ID, sceneContinuityContext } from '@/lib/scene-state';
import { deleteScene, getEpisodeSceneNumber, getLatestScene, getPreviousScene, getSceneById, listScenes, moveScene, moveSceneBefore, saveScene, updateSceneDeliveryTracking } from '@/lib/scene-db';
import type { AnalysisResult } from '@/lib/script-engine';
import { finalizeStoryboard, type StoryboardResult } from '@/lib/storyboard-engine';

export const runtime = 'edge';

async function hashSource(script: string) {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(script.trim()));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function hasStringFields(value: unknown, fields: string[]) {
  return isRecord(value) && fields.every((field) => typeof value[field] === 'string');
}

const analysisIssueTypes = new Set([
  'missing_character', 'abstract_emotion', 'missing_response', 'weak_action',
  'knowledge_risk', 'emotion_jump', 'continuity', 'dialogue_logic',
  'character_consistency',
]);

const continuityIssueTypes = new Set([
  'beat_coverage', 'character_position', 'gaze_direction', 'prop_state',
  'space_state', 'time_state', 'shot_density', 'shot_identity',
]);

function isValidScriptIssue(value: unknown) {
  if (!isRecord(value)) return false;
  return hasStringFields(value, ['id', 'targetId', 'title', 'detail', 'suggestion'])
    && (value.severity === 'hard' || value.severity === 'soft')
    && typeof value.type === 'string' && analysisIssueTypes.has(value.type)
    && typeof value.resolved === 'boolean';
}

function isValidContinuityIssue(value: unknown) {
  if (!isRecord(value)) return false;
  return hasStringFields(value, ['id', 'fromShotId', 'toShotId', 'detail', 'suggestion'])
    && (value.severity === 'hard' || value.severity === 'soft')
    && typeof value.type === 'string' && continuityIssueTypes.has(value.type)
    && typeof value.resolved === 'boolean';
}

function isValidAnalysis(value: unknown): value is AnalysisResult {
  if (!isRecord(value) || !Array.isArray(value.characters) || !Array.isArray(value.beats) || !Array.isArray(value.issues)) return false;
  if (value.characters.length > 12 || value.beats.length < 1 || value.beats.length > 30 || value.issues.length > 40) return false;
  if (!value.characters.every((character) => typeof character === 'string' && character.trim().length > 0)) return false;
  if (typeof value.score !== 'number' || !Number.isFinite(value.score) || value.score < 0 || value.score > 100 || typeof value.executionPrompt !== 'string') return false;
  if (!value.issues.every(isValidScriptIssue)) return false;
  return value.beats.every((beat) => hasStringFields(beat, [
    'id', 'source', 'actor', 'receiver', 'trigger', 'goal', 'action', 'dialogue',
    'reaction', 'response', 'stateBefore', 'stateAfter',
  ]));
}

function isValidStoryboard(value: unknown): value is StoryboardResult {
  if (!isRecord(value) || !Array.isArray(value.shots) || !Array.isArray(value.issues)) return false;
  if (value.shots.length < 1 || value.shots.length > 60 || value.issues.length > 40) return false;
  if (typeof value.modelPrompt !== 'string') return false;
  if (!value.issues.every(isValidContinuityIssue)) return false;
  return value.shots.every((shot) => {
    if (!isRecord(shot) || typeof shot.durationSec !== 'number' || !Number.isFinite(shot.durationSec)) return false;
    if (shot.durationSec < 1 || shot.durationSec > 15) return false;
    if (!hasStringFields(shot, [
      'id', 'beatId', 'shotSize', 'cameraAngle', 'cameraMovement', 'focus', 'action',
      'dialogue', 'sound', 'transition', 'continuityReason', 'videoPrompt',
    ])) return false;
    return hasStringFields(shot.startState, ['characterPositions', 'gazeDirection', 'propState', 'spaceState', 'timeState'])
      && hasStringFields(shot.endState, ['characterPositions', 'gazeDirection', 'propState', 'spaceState', 'timeState']);
  });
}

export async function GET(request: Request) {
  try {
    const sceneId = new URL(request.url).searchParams.get('id')?.trim() ?? '';
    const projectId = new URL(request.url).searchParams.get('projectId')?.trim() || DEFAULT_PROJECT_ID;
    if (sceneId) {
      const scene = await getSceneById(sceneId, projectId);
      if (!scene) return Response.json({ error: '找不到要载入的场次。' }, { status: 404 });
      return Response.json({ scene });
    }
    const scenes = await listScenes(projectId);
    return Response.json({
      scenes,
      continuityContext: scenes[0] ? sceneContinuityContext(scenes[0]) : null,
    });
  } catch (error) {
    console.error('Scene state list failed', error instanceof Error ? error.message : 'unknown error');
    return Response.json({ error: '场次状态库暂时不可用。' }, { status: 500 });
  }
}

export async function POST(request: Request) {
  try {
    const body = await request.json() as {
      title?: string;
      projectId?: string;
      sceneId?: string | null;
      episodeNumber?: number;
      script?: string;
      analysis?: AnalysisResult;
      storyboard?: StoryboardResult;
      deliveryTracking?: unknown;
    };
    const script = body.script?.trim() ?? '';
    if (!script || script.length > 12000 || !isValidAnalysis(body.analysis) || !isValidStoryboard(body.storyboard)) {
      return Response.json({ error: '请先完成本场剧本分析和分镜，再保存场次状态。' }, { status: 400 });
    }
    const validatedStoryboard = finalizeStoryboard({
      shots: body.storyboard.shots,
      issues: body.storyboard.issues,
      modelPrompt: body.storyboard.modelPrompt,
    }, body.analysis);
    if (validatedStoryboard.issues.some((issue) => !issue.resolved && issue.severity === 'hard')) {
      return Response.json({ error: '场次仍存在未解决的硬性连续性问题，不能保存。' }, { status: 409 });
    }
    const projectId = body.projectId?.trim() || DEFAULT_PROJECT_ID;
    const previousScene = body.sceneId?.trim()
      ? await getPreviousScene(body.sceneId.trim(), projectId)
      : await getLatestScene(projectId);
    const snapshot = buildSceneSnapshot(body.analysis, validatedStoryboard, previousScene?.snapshot ?? null);
    const saved = await saveScene({
      sceneId: body.sceneId?.trim() || undefined,
      title: body.title?.trim().slice(0, 80) || '未命名场次',
      projectId,
      episodeNumber: body.episodeNumber,
      sourceHash: await hashSource(script),
      script,
      analysis: body.analysis,
      storyboard: validatedStoryboard,
      deliveryTracking: body.deliveryTracking,
      snapshot,
    });
    const episodeSceneNumber = await getEpisodeSceneNumber(saved.id, projectId);
    const latest = await getLatestScene(projectId);
    return Response.json({ saved: { ...saved, episodeSceneNumber }, latest, continuityContext: latest ? sceneContinuityContext(latest) : null });
  } catch (error) {
    console.error('Scene state save failed', error instanceof Error ? error.message : 'unknown error');
    if (error instanceof Error && error.message.includes('场次不存在')) {
      return Response.json({ error: error.message }, { status: 404 });
    }
    return Response.json({ error: '场次状态保存失败，请稍后重试。' }, { status: 500 });
  }
}

export async function DELETE(request: Request) {
  try {
    const url = new URL(request.url);
    const sceneId = url.searchParams.get('id')?.trim() ?? '';
    const projectId = url.searchParams.get('projectId')?.trim() || DEFAULT_PROJECT_ID;
    if (!sceneId) return Response.json({ error: '缺少要删除的场次。' }, { status: 400 });
    const deleted = await deleteScene({ sceneId, projectId });
    if (!deleted) return Response.json({ error: '找不到要删除的场次。' }, { status: 404 });
    const scenes = await listScenes(projectId);
    return Response.json({ deleted, scenes });
  } catch (error) {
    console.error('Scene deletion failed', error instanceof Error ? error.message : 'unknown error');
    return Response.json({ error: '场次删除失败，请稍后重试。' }, { status: 500 });
  }
}

export async function PATCH(request: Request) {
  try {
    const body = await request.json() as { projectId?: string; sceneId?: string; targetSceneId?: string; deliveryTracking?: unknown; action?: 'move-up' | 'move-down' | 'move-before' };
    const sceneId = body.sceneId?.trim() ?? '';
    const projectId = body.projectId?.trim() || DEFAULT_PROJECT_ID;
    if (!sceneId) {
      return Response.json({ error: '缺少场次或制作进度信息。' }, { status: 400 });
    }
    if (body.action === 'move-up' || body.action === 'move-down') {
      const moved = await moveScene({ sceneId, projectId, direction: body.action === 'move-up' ? 'up' : 'down' });
      if (!moved) return Response.json({ error: '找不到要调整的场次。' }, { status: 404 });
      return Response.json({ moved: moved.moved });
    }
    if (body.action === 'move-before') {
      const targetSceneId = body.targetSceneId?.trim() ?? '';
      if (!targetSceneId) return Response.json({ error: '缺少目标场次。' }, { status: 400 });
      const moved = await moveSceneBefore({ sceneId, targetSceneId, projectId });
      if (!moved) return Response.json({ error: '找不到要调整的场次。' }, { status: 404 });
      return Response.json({ moved: moved.moved });
    }
    if (body.deliveryTracking === undefined) {
      return Response.json({ error: '缺少场次或制作进度信息。' }, { status: 400 });
    }
    const tracking = await updateSceneDeliveryTracking({ sceneId, projectId, tracking: body.deliveryTracking });
    if (!tracking) return Response.json({ error: '找不到要更新的场次。' }, { status: 404 });
    return Response.json({ tracking });
  } catch (error) {
    console.error('Delivery tracking update failed', error instanceof Error ? error.message : 'unknown error');
    return Response.json({ error: '制作进度保存失败，请稍后重试。' }, { status: 500 });
  }
}
