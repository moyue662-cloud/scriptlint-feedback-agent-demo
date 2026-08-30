import { buildSceneSnapshot, sceneContinuityContext } from '@/lib/scene-state';
import { getLatestScene, listScenes, saveScene, updateSceneDeliveryTracking } from '@/lib/scene-db';
import type { AnalysisResult } from '@/lib/script-engine';
import type { StoryboardResult } from '@/lib/storyboard-engine';

export const runtime = 'edge';

async function hashSource(script: string) {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(script.trim()));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

export async function GET() {
  try {
    const scenes = await listScenes();
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
    const saved = await saveScene({
      title: body.title?.trim().slice(0, 80) || '未命名场次',
      sourceHash: await hashSource(script),
      script,
      analysis: body.analysis,
      storyboard: body.storyboard,
      deliveryTracking: body.deliveryTracking,
      snapshot,
    });
    const latest = await getLatestScene();
    return Response.json({ saved, latest, continuityContext: latest ? sceneContinuityContext(latest) : null });
  } catch (error) {
    console.error('Scene state save failed', error instanceof Error ? error.message : 'unknown error');
    return Response.json({ error: '场次状态保存失败，请稍后重试。' }, { status: 500 });
  }
}

export async function PATCH(request: Request) {
  try {
    const body = await request.json() as { sceneId?: string; deliveryTracking?: unknown };
    const sceneId = body.sceneId?.trim() ?? '';
    if (!sceneId || body.deliveryTracking === undefined) {
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
