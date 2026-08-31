import { DEFAULT_PROJECT_ID } from '@/lib/scene-state';
import { buildEpisodeSourceHash, passesEpisodeAIReviewGate } from '@/lib/episode-ai-review';
import { buildEpisodeReview } from '@/lib/episode-review';
import { getProject, listEpisodeAIReviews, listEpisodeSummaries, listSceneDetails, setProjectApproval, updateProjectName } from '@/lib/scene-db';

export const runtime = 'edge';

export async function GET() {
  try {
    const project = await getProject();
    if (!project) return Response.json({ error: '项目尚未初始化。' }, { status: 404 });
    return Response.json({ project });
  } catch (error) {
    console.error('Project load failed', error instanceof Error ? error.message : 'unknown error');
    return Response.json({ error: '项目资料暂时不可用。' }, { status: 500 });
  }
}

export async function PATCH(request: Request) {
  try {
    const body = await request.json() as { name?: string; approved?: boolean };
    if (typeof body.approved === 'boolean') {
      if (body.approved) {
        const [scenes, summaries, aiReviews] = await Promise.all([
          listSceneDetails(DEFAULT_PROJECT_ID, 500),
          listEpisodeSummaries(DEFAULT_PROJECT_ID),
          listEpisodeAIReviews(DEFAULT_PROJECT_ID),
        ]);
        if (scenes.length === 0) return Response.json({ error: '至少保存一个场次后才能完成整部项目终审。' }, { status: 409 });
        const episodeNumbers = Array.from(new Set([
          ...scenes.map((scene) => scene.episodeNumber),
          ...summaries.map((summary) => summary.episodeNumber),
        ])).sort((a, b) => a - b);
        const reviews = episodeNumbers.map((episodeNumber) => buildEpisodeReview(
          episodeNumber,
          scenes,
          summaries.find((summary) => summary.episodeNumber === episodeNumber) ?? null,
        ));
        const incompleteReviews = reviews.filter((review) => review.status !== 'ready');
        if (incompleteReviews.length > 0) {
          return Response.json({
            error: `还有 ${incompleteReviews.length} 集未通过结构与制作门禁。`,
            reviews: incompleteReviews,
          }, { status: 409 });
        }
        const aiIncomplete = [];
        for (const episodeNumber of episodeNumbers) {
          const summary = summaries.find((item) => item.episodeNumber === episodeNumber) ?? null;
          const sourceHash = await buildEpisodeSourceHash(episodeNumber, scenes, summary);
          const aiReview = aiReviews.find((review) => review.episodeNumber === episodeNumber && review.sourceHash === sourceHash);
          if (!passesEpisodeAIReviewGate(aiReview)) aiIncomplete.push(episodeNumber);
        }
        if (aiIncomplete.length > 0) {
          return Response.json({
            error: `第 ${aiIncomplete.join('、')} 集缺少最新AI审查或仍有结构阻断。`,
          }, { status: 409 });
        }
      }
      const project = await setProjectApproval(body.approved, DEFAULT_PROJECT_ID);
      if (!project) return Response.json({ error: '项目尚未初始化。' }, { status: 404 });
      return Response.json({ project });
    }
    const name = body.name?.trim() ?? '';
    if (!name) return Response.json({ error: '项目名称不能为空。' }, { status: 400 });
    const project = await updateProjectName(name, DEFAULT_PROJECT_ID);
    if (!project) return Response.json({ error: '项目尚未初始化。' }, { status: 404 });
    return Response.json({ project });
  } catch (error) {
    console.error('Project update failed', error instanceof Error ? error.message : 'unknown error');
    return Response.json({ error: '项目资料保存失败，请稍后重试。' }, { status: 500 });
  }
}
