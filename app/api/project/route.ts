import { DEFAULT_PROJECT_ID } from '@/lib/scene-state';
import { buildEpisodeSourceHash, passesEpisodeAIReviewGate } from '@/lib/episode-ai-review';
import { buildEpisodeReview } from '@/lib/episode-review';
import { archiveProject, createProject, getProject, listEpisodeAIReviews, listEpisodeSummaries, listProjects, listSceneDetails, setProjectApproval, updateProjectName } from '@/lib/scene-db';
import { requireAuth } from '@/lib/auth';

export const runtime = 'edge';

export async function GET(request: Request) {
  const unauthorized = await requireAuth(request);
  if (unauthorized) return unauthorized;
  try {
    const url = new URL(request.url);
    const projects = await listProjects();
    const requestedId = url.searchParams.get('projectId')?.trim() || DEFAULT_PROJECT_ID;
    const project = await getProject(requestedId) ?? projects[0] ?? null;
    if (!project) return Response.json({ error: '项目尚未初始化。' }, { status: 404 });
    return Response.json({ project, projects });
  } catch (error) {
    console.error('Project load failed', error instanceof Error ? error.message : 'unknown error');
    return Response.json({ error: '项目资料暂时不可用。' }, { status: 500 });
  }
}

export async function PATCH(request: Request) {
  const unauthorized = await requireAuth(request);
  if (unauthorized) return unauthorized;
  try {
    const body = await request.json() as { name?: string; approved?: boolean; projectId?: string };
    const projectId = body.projectId?.trim() || DEFAULT_PROJECT_ID;
    if (typeof body.approved === 'boolean') {
      if (body.approved) {
        const [scenes, summaries, aiReviews] = await Promise.all([
          listSceneDetails(projectId, 500),
          listEpisodeSummaries(projectId),
          listEpisodeAIReviews(projectId),
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
      const project = await setProjectApproval(body.approved, projectId);
      if (!project) return Response.json({ error: '项目尚未初始化。' }, { status: 404 });
      return Response.json({ project });
    }
    const name = body.name?.trim() ?? '';
    if (!name) return Response.json({ error: '项目名称不能为空。' }, { status: 400 });
    const project = await updateProjectName(name, projectId);
    if (!project) return Response.json({ error: '项目尚未初始化。' }, { status: 404 });
    return Response.json({ project });
  } catch (error) {
    console.error('Project update failed', error instanceof Error ? error.message : 'unknown error');
    return Response.json({ error: '项目资料保存失败，请稍后重试。' }, { status: 500 });
  }
}

export async function POST(request: Request) {
  const unauthorized = await requireAuth(request);
  if (unauthorized) return unauthorized;
  try {
    const body = await request.json() as { name?: string };
    const name = body.name?.trim() ?? '';
    if (!name || name.length > 80) return Response.json({ error: '请输入不超过80字的项目名称。' }, { status: 400 });
    const project = await createProject(name);
    return Response.json({ project, projects: await listProjects() });
  } catch (error) {
    console.error('Project create failed', error instanceof Error ? error.message : 'unknown error');
    return Response.json({ error: '新项目创建失败，请稍后重试。' }, { status: 500 });
  }
}

export async function DELETE(request: Request) {
  const unauthorized = await requireAuth(request);
  if (unauthorized) return unauthorized;
  try {
    const projectId = new URL(request.url).searchParams.get('projectId')?.trim() ?? '';
    if (!projectId) return Response.json({ error: '缺少要归档的项目。' }, { status: 400 });
    const projects = await archiveProject(projectId);
    return Response.json({ projects, project: projects[0] ?? null });
  } catch (error) {
    const message = error instanceof Error ? error.message : '项目归档失败';
    return Response.json({ error: message }, { status: message.includes('至少保留') ? 409 : 500 });
  }
}
