import { getSceneById, listSceneVisualReviews, saveSceneVisualReview } from '@/lib/scene-db';
import { isVisualDataUrl, type VisualIssueType, type VisualReview } from '@/lib/visual-review';

export const runtime = 'edge';

const API_URL = 'https://api.deepseek.com/chat/completions';
const DEFAULT_MODEL = 'deepseek-v4-flash-vision-exp';
const MODEL_TIMEOUT_MS = 50000;
const issueTypes: VisualIssueType[] = ['identity', 'wardrobe', 'prop', 'position', 'gaze', 'space', 'time', 'shot'];

const instructions = `你是短剧成片连续性检查器。你只能根据用户提供的画面帧和“应当呈现的镜头状态”判断，不得猜测画面外事实，不得把拍摄风格偏好当成错误。只输出 JSON 对象，不要 Markdown。

检查：人物身份/外观、服装、关键道具、站位与视线、空间、时间连续性，以及画面是否表达了镜头要求。多帧时按 frameIndex 顺序判断状态是否发生了有依据的变化；只有影响剧情理解或连续性的身份、主要道具、站位、空间错误才标记 hard；轻微构图或表演偏差标记 soft。
每条问题必须指向真实存在的 frameIndex（从0开始）和可选的 shotId；如果无法确认就不要创建问题。不要杜撰未出现在画面中的人物、道具或变化。

输出格式：{"overview":"简短总结","score":0到100的整数,"framesAnalyzed":帧数,"issues":[{"id":"V01","severity":"hard或soft","type":"identity|wardrobe|prop|position|gaze|space|time|shot","frameIndex":0,"shotId":"S01或null","title":"问题标题","detail":"只描述可见证据","suggestion":"最小修复建议"}]}`;

function outputText(payload: Record<string, unknown>) {
  const choices = Array.isArray(payload.choices) ? payload.choices : [];
  const first = choices[0];
  if (first && typeof first === 'object') {
    const message = (first as { message?: unknown }).message;
    if (message && typeof message === 'object' && typeof (message as { content?: unknown }).content === 'string') {
      return (message as { content: string }).content;
    }
  }
  return typeof payload.output_text === 'string' ? payload.output_text : '';
}

function parseJson(text: string) {
  const cleaned = text.replace(/^\uFEFF/, '').replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '').trim();
  const start = cleaned.indexOf('{');
  const end = cleaned.lastIndexOf('}');
  return JSON.parse(start >= 0 && end > start ? cleaned.slice(start, end + 1) : cleaned) as Record<string, unknown>;
}

function text(value: unknown, fallback: string, max = 500) {
  return typeof value === 'string' && value.trim() ? value.trim().slice(0, max) : fallback;
}

function normaliseReview(value: Record<string, unknown>, frameCount: number, shotIds: Set<string>): VisualReview {
  const rawIssues = Array.isArray(value.issues) ? value.issues : [];
  const issues = rawIssues.flatMap((raw, index) => {
    if (!raw || typeof raw !== 'object') return [];
    const item = raw as Record<string, unknown>;
    const frameIndex = Number.isInteger(item.frameIndex) ? Number(item.frameIndex) : -1;
    const shotId = typeof item.shotId === 'string' && shotIds.has(item.shotId) ? item.shotId : null;
    const type = issueTypes.includes(item.type as VisualIssueType) ? item.type as VisualIssueType : null;
    if (frameIndex < 0 || frameIndex >= frameCount || !type) return [];
    return [{
      id: text(item.id, `V${String(index + 1).padStart(2, '0')}`, 40),
      severity: item.severity === 'hard' ? 'hard' as const : 'soft' as const,
      type,
      frameIndex,
      shotId,
      title: text(item.title, '画面连续性问题'),
      detail: text(item.detail, '画面与镜头状态不一致。', 800),
      suggestion: text(item.suggestion, '回到对应镜头，保持人物、道具和站位连续。', 500),
    }];
  });
  const score = Number(value.score);
  return {
    overview: text(value.overview, issues.length ? '发现需要复核的画面连续性问题。' : '未发现明显的画面连续性问题。', 800),
    score: Number.isFinite(score) ? Math.max(0, Math.min(100, Math.round(score))) : Math.max(0, 100 - issues.length * 12),
    framesAnalyzed: frameCount,
    issues: issues.slice(0, 40),
  };
}

async function sourceHash(source: string) {
  const bytes = new TextEncoder().encode(source);
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(digest)).map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

export async function GET(request: Request) {
  const url = new URL(request.url);
  const sceneId = url.searchParams.get('sceneId')?.trim();
  const projectId = url.searchParams.get('projectId')?.trim() || 'default';
  if (!sceneId) return Response.json({ reviews: [] });
  try {
    return Response.json({ reviews: await listSceneVisualReviews(sceneId, projectId) });
  } catch (error) {
    console.error('Visual review history failed', error instanceof Error ? error.message : 'unknown error');
    return Response.json({ error: '视觉检查记录暂时不可用。' }, { status: 500 });
  }
}

export async function POST(request: Request) {
  try {
    const body = await request.json() as {
      projectId?: string;
      sceneId?: string;
      images?: Array<{ name?: string; mimeType?: string; dataUrl?: string }>;
      expected?: { title?: string; snapshot?: unknown; shots?: unknown[] };
    };
    const images = Array.isArray(body.images) ? body.images : [];
    if (images.length < 1 || images.length > 6) return Response.json({ error: '请提供 1 至 6 个图片帧。' }, { status: 400 });
    const validImages = images.filter((image) => isVisualDataUrl(image?.dataUrl));
    if (validImages.length !== images.length) return Response.json({ error: '仅支持 PNG、JPG 或 WebP 图片帧。视频请先在浏览器中抽帧。' }, { status: 400 });
    const totalSize = validImages.reduce((total, image) => total + (image.dataUrl?.length ?? 0), 0);
    if (validImages.some((image) => (image.dataUrl?.length ?? 0) > 7_000_000) || totalSize > 24_000_000) {
      return Response.json({ error: '图片总大小请控制在 24 MB 以内。' }, { status: 413 });
    }

    const projectId = body.projectId?.trim() || 'default';
    let scene = null;
    if (body.sceneId?.trim()) {
      scene = await getSceneById(body.sceneId.trim(), projectId);
      if (!scene) return Response.json({ error: '找不到要检查的场次。' }, { status: 404 });
    }
    const expected = scene
      ? {
          title: scene.title,
          snapshot: scene.snapshot,
          shots: scene.storyboard.shots.map((shot) => ({
            id: shot.id, focus: shot.focus, action: shot.action, dialogue: shot.dialogue,
            startState: shot.startState, endState: shot.endState,
          })),
        }
      : body.expected ?? { title: '当前镜头', snapshot: {}, shots: [] };
    const shotIds = new Set((expected.shots ?? []).flatMap((shot) => {
      if (!shot || typeof shot !== 'object' || typeof (shot as { id?: unknown }).id !== 'string') return [];
      return [(shot as { id: string }).id];
    }));
    const sourceNames = validImages.map((image, index) => image.name?.trim() || `frame-${index + 1}`);
    const apiKey = process.env.DEEPSEEK_API_KEY;
    if (!apiKey) return Response.json({ error: '视觉模型尚未配置。' }, { status: 503 });
    const model = process.env.DEEPSEEK_VISION_MODEL || DEFAULT_MODEL;
    const content = [
      { type: 'text', text: `应当呈现的镜头状态：\n${JSON.stringify(expected)}\n\n请逐帧检查，frameIndex 必须对应输入帧顺序。` },
      ...validImages.map((image) => ({ type: 'image_url', image_url: { url: image.dataUrl, detail: 'high' } })),
    ];
    let response: Response;
    try {
      response = await fetch(API_URL, {
        method: 'POST',
        headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ model, messages: [{ role: 'system', content: instructions }, { role: 'user', content }], response_format: { type: 'json_object' }, temperature: 0.1, max_tokens: 3200, stream: false }),
        signal: AbortSignal.timeout(MODEL_TIMEOUT_MS),
      });
    } catch (error) {
      console.warn('DeepSeek visual review unavailable', error instanceof Error ? error.message : 'unknown error');
      return Response.json({ error: '视觉检查响应超时或暂时不可用。' }, { status: 504 });
    }
    const payload = await response.json() as Record<string, unknown>;
    if (!response.ok) {
      console.error('DeepSeek visual review failed', response.status);
      return Response.json({ error: '视觉模型暂时不可用，请检查视觉模型配置。' }, { status: 502 });
    }
    const output = outputText(payload);
    if (!output) return Response.json({ error: '视觉模型没有返回可用报告。' }, { status: 502 });
    const review = normaliseReview(parseJson(output), validImages.length, shotIds);
    const sourceHashValue = await sourceHash(`${body.sceneId ?? ''}|${sourceNames.join('|')}|${validImages.map((image) => image.dataUrl?.length ?? 0).join(',')}`);
    let saved = null;
    if (body.sceneId?.trim()) {
      saved = await saveSceneVisualReview({ projectId, sceneId: body.sceneId.trim(), sourceName: sourceNames.join(', '), sourceHash: sourceHashValue, review: review as unknown as Record<string, unknown> });
    }
    return Response.json({ review, saved: saved ? { id: saved.id, createdAt: saved.createdAt } : null, meta: { provider: 'deepseek', model, sourceCount: validImages.length, persistedMedia: false } });
  } catch (error) {
    console.error('Visual review failed', error instanceof Error ? error.message : 'unknown error');
    return Response.json({ error: '视觉检查失败，请确认图片内容后重试。' }, { status: 500 });
  }
}
