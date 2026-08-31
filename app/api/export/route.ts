import { buildEpisodeReview } from '@/lib/episode-review';
import { buildEpisodeSourceHash } from '@/lib/episode-ai-review';
import { getProject, listEpisodeAIReviews, listEpisodeSummaries, listSceneDetails } from '@/lib/scene-db';
import { DEFAULT_PROJECT_ID } from '@/lib/scene-state';

export const runtime = 'edge';

export async function GET() {
  try {
    const [project, summaries, scenes, aiReviews] = await Promise.all([
      getProject(DEFAULT_PROJECT_ID),
      listEpisodeSummaries(DEFAULT_PROJECT_ID),
      listSceneDetails(DEFAULT_PROJECT_ID, 500),
      listEpisodeAIReviews(DEFAULT_PROJECT_ID),
    ]);
    if (!project) return Response.json({ error: '项目尚未初始化。' }, { status: 404 });
    const episodeNumbers = Array.from(new Set([
      ...scenes.map((scene) => scene.episodeNumber),
      ...summaries.map((summary) => summary.episodeNumber),
    ])).sort((a, b) => a - b);
    const episodes = await Promise.all(episodeNumbers.map(async (episodeNumber) => {
      const summary = summaries.find((item) => item.episodeNumber === episodeNumber) ?? null;
      const review = buildEpisodeReview(episodeNumber, scenes, summary);
      const sourceHash = await buildEpisodeSourceHash(episodeNumber, scenes, summary);
      const aiReview = aiReviews.find((item) => item.episodeNumber === episodeNumber && item.sourceHash === sourceHash) ?? null;
      return {
        episodeNumber,
        summary,
        review,
        aiReview,
        scenes: scenes.filter((scene) => scene.episodeNumber === episodeNumber),
      };
    }));
    const ready = episodes.length > 0 && episodes.every((episode) => episode.review.status === 'ready' && episode.aiReview?.status === 'ready');
    return Response.json({
      schemaVersion: 1,
      packageType: project.approvedAt && ready ? 'final' : 'review-draft',
      project,
      readiness: {
        ready,
        approved: Boolean(project.approvedAt),
        episodeCount: episodes.length,
        sceneCount: scenes.length,
        blockedEpisodeCount: episodes.filter((episode) => episode.review.status === 'blocked').length,
        attentionEpisodeCount: episodes.filter((episode) => episode.review.status === 'attention').length,
      },
      episodes,
      generatedAt: new Date().toISOString(),
    });
  } catch (error) {
    console.error('Project package export failed', error instanceof Error ? error.message : 'unknown error');
    return Response.json({ error: '项目执行包生成失败，请稍后重试。' }, { status: 500 });
  }
}
