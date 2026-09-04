import { requireAuth } from '@/lib/auth';
import { isBatchCompilePhase, type BatchCompileItem } from '@/lib/batch-run';
import type { ImportedSceneDraft } from '@/lib/batch-import';
import type { NovelAdaptationResult } from '@/lib/novel-adaptation';
import { cancelBatchCompileRun, checkpointBatchCompileRun, createBatchCompileRun, getResumableBatchCompileRun } from '@/lib/scene-db';
import { DEFAULT_PROJECT_ID } from '@/lib/scene-state';

export const runtime = 'edge';

function validDrafts(value: unknown): value is ImportedSceneDraft[] {
  return Array.isArray(value) && value.length > 0 && value.length <= 24 && value.every((draft) => {
    if (!draft || typeof draft !== 'object') return false;
    const item = draft as Partial<ImportedSceneDraft>;
    return Number.isFinite(item.episodeNumber) && Number(item.episodeNumber) >= 1 && Number(item.episodeNumber) <= 999
      && typeof item.title === 'string' && item.title.trim().length > 0 && item.title.length <= 80
      && typeof item.script === 'string' && item.script.trim().length > 0 && item.script.length <= 12000;
  });
}

function cleanDrafts(drafts: ImportedSceneDraft[]) {
  return drafts.map((draft) => ({
    episodeNumber: Math.round(Number(draft.episodeNumber)),
    title: draft.title.trim().slice(0, 80),
    script: draft.script.trim(),
    ...(draft.splitReason ? { splitReason: draft.splitReason } : {}),
    ...(Number.isFinite(draft.estimatedDurationSec) ? { estimatedDurationSec: Math.max(1, Math.min(600, Math.round(Number(draft.estimatedDurationSec)))) } : {}),
    ...(typeof draft.narrativeRole === 'string' ? { narrativeRole: draft.narrativeRole.trim().slice(0, 30) } : {}),
    ...(Array.isArray(draft.retainedHighlights) ? { retainedHighlights: draft.retainedHighlights.filter((item) => typeof item === 'string').slice(0, 12).map((item) => item.slice(0, 120)) } : {}),
    ...(Array.isArray(draft.appearingCharacters) ? { appearingCharacters: draft.appearingCharacters.filter((item) => typeof item === 'string').slice(0, 20).map((item) => item.slice(0, 40)) } : {}),
    ...(Array.isArray(draft.establishedFacts) ? { establishedFacts: draft.establishedFacts.filter((item) => typeof item === 'string').slice(0, 20).map((item) => item.slice(0, 160)) } : {}),
    ...(typeof draft.timeMarker === 'string' ? { timeMarker: draft.timeMarker.trim().slice(0, 60) } : {}),
  } satisfies ImportedSceneDraft));
}

function validItem(value: unknown): value is BatchCompileItem {
  if (!value || typeof value !== 'object') return false;
  const item = value as Partial<BatchCompileItem>;
  return isBatchCompilePhase(item.phase) && typeof item.detail === 'string' && item.detail.length <= 300
    && (item.error === undefined || typeof item.error === 'string' && item.error.length <= 500)
    && (item.sceneId === undefined || typeof item.sceneId === 'string' && item.sceneId.length <= 100);
}

export async function GET(request: Request) {
  const unauthorized = await requireAuth(request);
  if (unauthorized) return unauthorized;
  const projectId = new URL(request.url).searchParams.get('projectId')?.trim() || DEFAULT_PROJECT_ID;
  try {
    return Response.json({ run: await getResumableBatchCompileRun(projectId) });
  } catch (error) {
    console.error('Batch run load failed', error instanceof Error ? error.message : 'unknown error');
    return Response.json({ error: '无法读取批量任务。' }, { status: 500 });
  }
}

export async function POST(request: Request) {
  const unauthorized = await requireAuth(request);
  if (unauthorized) return unauthorized;
  try {
    const body = await request.json() as { projectId?: string; drafts?: unknown; adaptation?: NovelAdaptationResult | null };
    if (!validDrafts(body.drafts)) return Response.json({ error: '批量场次草稿格式无效。' }, { status: 400 });
    if (body.adaptation && JSON.stringify(body.adaptation).length > 250_000) return Response.json({ error: '改编提纲过大。' }, { status: 413 });
    const run = await createBatchCompileRun({ projectId: body.projectId, drafts: cleanDrafts(body.drafts), adaptation: body.adaptation ?? null });
    return Response.json({ run });
  } catch (error) {
    console.error('Batch run create failed', error instanceof Error ? error.message : 'unknown error');
    return Response.json({ error: error instanceof Error && error.message === '项目不存在' ? error.message : '无法创建批量任务。' }, { status: 500 });
  }
}

export async function PATCH(request: Request) {
  const unauthorized = await requireAuth(request);
  if (unauthorized) return unauthorized;
  try {
    const body = await request.json() as { id?: string; projectId?: string; index?: number; item?: unknown; action?: string };
    const id = body.id?.trim() ?? '';
    if (!id) return Response.json({ error: '缺少批量任务编号。' }, { status: 400 });
    if (body.action === 'cancel') {
      await cancelBatchCompileRun(id, body.projectId?.trim() || DEFAULT_PROJECT_ID);
      return Response.json({ cancelled: true });
    }
    if (!Number.isInteger(body.index) || !validItem(body.item)) return Response.json({ error: '批量任务进度格式无效。' }, { status: 400 });
    const run = await checkpointBatchCompileRun({ id, projectId: body.projectId, index: body.index!, item: body.item });
    return Response.json({ run });
  } catch (error) {
    console.error('Batch run checkpoint failed', error instanceof Error ? error.message : 'unknown error');
    return Response.json({ error: error instanceof Error ? error.message : '无法保存批量任务进度。' }, { status: 409 });
  }
}
