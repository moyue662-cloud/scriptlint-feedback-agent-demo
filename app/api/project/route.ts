import { DEFAULT_PROJECT_ID } from '@/lib/scene-state';
import { getProject, updateProjectName } from '@/lib/scene-db';

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
    const body = await request.json() as { name?: string };
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
