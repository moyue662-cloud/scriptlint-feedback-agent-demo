import { buildSceneSnapshot, DEFAULT_PROJECT_ID, sceneContinuityContext } from '@/lib/scene-state';
import { getLatestScene, getSceneById, listScenes, moveScene, saveScene, updateSceneDeliveryTracking } from '@/lib/scene-db';
import type { AnalysisResult } from '@/lib/script-engine';
import type { StoryboardResult } from '@/lib/storyboard-engine';

export const runtime = 'edge';

async function hashSource(script: string) {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(script.trim()));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

export async function GET(request: Request) {
  try {
    const sceneId = new URL(request.url).searchParams.get('id')?.trim() ?? '';
    if (sceneId) {
      const scene = await getSceneById(sceneId);
      if (!scene) return Response.json({ error: '找不到要载入的场次。' }, { status: 404 });
      return Response.json({ scene });
    }
    const projectId = new URL(request.url).searchParams.get('projectId')?.trim() || DEFAULT_PROJECT_ID;
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
      episodeNumber?: number;
      script?: string;
      analysis?: AnalysisResult;
      storyboard?: StoryboardResult;
      deliveryTracking?: unknown;
    };
    const script = body.script?.trim() ?? '';
    if (!script || !body.analysis?.beats?.length || !body.storyboard?.shots?.length) {
      return Response.json({ error: '请先完成本场剧本分析和分镜，再保存场次状态。' }, { status: 400 });
    }
    const snapshot = buildSceneSnapshot(body.analysis, body.storyboard);
    const projectId = body.projectId?.trim() || DEFAULT_PROJECT_ID;
    const saved = await saveScene({
      title: body.title?.trim().slice(0, 80) || '未命名场次',
      projectId,
      episodeNumber: body.episodeNumber,
      sourceHash: await hashSource(script),
      script,
      analysis: body.analysis,
      storyboard: body.storyboard,
      deliveryTracking: body.deliveryTracking,
      snapshot,
    });
    const latest = await getLatestScene(projectId);
    return Response.json({ saved, latest, continuityContext: latest ? sceneContinuityContext(latest) : null });
  } catch (error) {
    console.error('Scene state save failed', error instanceof Error ? error.message : 'unknown error');
    return Response.json({ error: '场次状态保存失败，请稍后重试。' }, { status: 500 });
  }
}

export async function PATCH(request: Request) {
  try {
    const body = await request.json() as { sceneId?: string; deliveryTracking?: unknown; action?: 'move-up' | 'move-down' };
    const sceneId = body.sceneId?.trim() ?? '';
    if (!sceneId) {
      return Response.json({ error: '缺少场次或制作进度信息。' }, { status: 400 });
    }
    if (body.action === 'move-up' || body.action === 'move-down') {
      const moved = await moveScene({ sceneId, direction: body.action === 'move-up' ? 'up' : 'down' });
      if (!moved) return Response.json({ error: '找不到要调整的场次。' }, { status: 404 });
      return Response.json({ moved: moved.moved });
    }
    if (body.deliveryTracking === undefined) {
      return Response.json({ error: '缺少场次或制作进度信息。' }, { status: 400 });
    }
    const tracking = await updateSceneDeliveryTracking({ sceneId, tracking: body.deliveryTracking });
    if (!tracking) return Response.json({ error: '找不到要更新的场次。' }, { status: 404 });
    return Response.json({ tracking });
  } catch (error) {
    console.error('Delivery tracking update failed', error instanceof Error ? error.message : 'unknown error');
    return Response.json({ error: '制作进度保存失败，请稍后重试。' }, { status: 500 });
  }
}
