import { DEFAULT_PROJECT_ID, type EpisodeSummary } from '@/lib/scene-state';
import { listEpisodeSummaries, upsertEpisodeSummary } from '@/lib/scene-db';

export const runtime = 'edge';

export async function GET(request: Request) {
  try {
    const projectId = new URL(request.url).searchParams.get('projectId')?.trim() || DEFAULT_PROJECT_ID;
    const summaries = await listEpisodeSummaries(projectId);
    return Response.json({ summaries });
  } catch (error) {
    console.error('Episode summary list failed', error instanceof Error ? error.message : 'unknown error');
    return Response.json({ error: '集数总结暂时不可用。' }, { status: 500 });
  }
}

export async function PATCH(request: Request) {
  try {
    const body = await request.json() as Partial<EpisodeSummary> & { projectId?: string };
    const episodeNumber = Number(body.episodeNumber);
    if (!Number.isFinite(episodeNumber) || episodeNumber < 1 || episodeNumber > 999) {
      return Response.json({ error: '集数必须是 1 到 999 之间的数字。' }, { status: 400 });
    }
    const summary = await upsertEpisodeSummary({
      projectId: body.projectId,
      episodeNumber,
      title: body.title,
      objective: body.objective,
      conflict: body.conflict,
      notes: body.notes,
    });
    if (!summary) return Response.json({ error: '集数总结保存失败。' }, { status: 500 });
    return Response.json({ summary });
  } catch (error) {
    console.error('Episode summary update failed', error instanceof Error ? error.message : 'unknown error');
    return Response.json({ error: '集数总结保存失败，请稍后重试。' }, { status: 500 });
  }
}
