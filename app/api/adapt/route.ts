import { normalizeNovelAdaptation, type RawNovelAdaptation } from '@/lib/novel-adaptation';

export const runtime = 'edge';

const MODEL = 'deepseek-v4-flash';
const API_URL = 'https://api.deepseek.com/chat/completions';
const MODEL_TIMEOUT_MS = 48000;

const schema = {
  type: 'object',
  additionalProperties: false,
  properties: {
    theme: { type: 'string' },
    logline: { type: 'string' },
    characters: { type: 'array', items: { type: 'string' }, maxItems: 12 },
    retainedPlotPoints: { type: 'array', items: { type: 'string' }, maxItems: 10 },
    omittedContent: { type: 'array', items: { type: 'string' }, maxItems: 10 },
    scenes: {
      type: 'array', minItems: 2, maxItems: 16,
      items: {
        type: 'object', additionalProperties: false,
        properties: {
          title: { type: 'string' },
          narrativeRole: { type: 'string', enum: ['开场钩子', '冲突建立', '冲突升级', '反转', '高潮', '收束'] },
          script: { type: 'string' },
          estimatedDurationSec: { type: 'integer', minimum: 20, maximum: 120 },
          retainedHighlights: { type: 'array', items: { type: 'string' }, maxItems: 4 },
        },
        required: ['title', 'narrativeRole', 'script', 'estimatedDurationSec', 'retainedHighlights'],
      },
    },
  },
  required: ['theme', 'logline', 'characters', 'retainedPlotPoints', 'omittedContent', 'scenes'],
} as const;

const instructions = `你是“小说转AI短剧”的改编编辑。输入可能是小说章节、故事梗概或未经整理的长文本。你的任务不是逐句分割，而是先压缩叙事，再输出少量、完整、可拍摄的短剧场景。

必须遵守：
1. 先识别主题、主角、主要对手、核心人物关系和一条主线；支线只在服务主线时保留。
2. 删除重复说明、同义反复、长篇心理独白、过度世界观解释、重复升级、说教和不影响因果的过场。
3. 必须保留：开场钩子、关键诱因、主要冲突、至少一次升级或反转、最精彩的高潮和有兑现感的收束。
4. 把保留的小说叙述转换为人物可见动作、短台词和即时反应；禁止只写概述或一句旁白。
5. 每个 scenes 项必须是一场完整戏剧事件，至少包含“触发—对抗/选择—状态变化或结果”，不能把单独一句话当成一个场景。
6. 通常输出 4–10 场；内容很短时可 2–3 场，内容复杂时最多 16 场。每场建议 20–120 秒、约 100–450 个中文字符，后续分镜系统会再拆成多个镜头。
7. 不新增与原文无关的人物、设定或支线；允许合并功能重复的事件和次要人物，但要在 omittedContent 中说明。
8. script 是可以继续交给“交互节拍编译器”的改编场景正文，不是创作建议，也不是摘要。
9. 仅输出 JSON 对象，不要 Markdown、解释文字或代码块。

JSON Schema：
${JSON.stringify(schema)}`;

function outputText(payload: Record<string, unknown>) {
  const choices = Array.isArray(payload.choices) ? payload.choices : [];
  const first = choices[0];
  if (first && typeof first === 'object') {
    const message = (first as { message?: unknown }).message;
    if (message && typeof message === 'object') {
      const content = (message as { content?: unknown }).content;
      if (typeof content === 'string') return content;
    }
  }
  return typeof payload.output_text === 'string' ? payload.output_text : '';
}

function parseOutput(text: string) {
  const clean = text.replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '').trim();
  const start = clean.indexOf('{');
  const end = clean.lastIndexOf('}');
  const json = start >= 0 && end > start ? clean.slice(start, end + 1) : clean;
  try {
    return JSON.parse(json) as RawNovelAdaptation;
  } catch {
    return JSON.parse(json.replace(/,\s*([}\]])/g, '$1')) as RawNovelAdaptation;
  }
}

export async function POST(request: Request) {
  try {
    const body = await request.json() as { text?: string; episodeNumber?: number };
    const text = body.text?.trim() ?? '';
    if (!text) return Response.json({ error: '请先粘贴小说或长剧本。' }, { status: 400 });
    if (text.length > 30000) return Response.json({ error: '单次改编请控制在 30000 字以内；更长内容请按章节分批处理。' }, { status: 400 });

    const apiKey = process.env.DEEPSEEK_API_KEY;
    if (!apiKey) return Response.json({ error: '模型服务尚未配置。' }, { status: 503 });

    let response: Response;
    try {
      response = await fetch(API_URL, {
        method: 'POST',
        headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: MODEL,
          messages: [
            { role: 'system', content: instructions },
            { role: 'user', content: `把下面内容压缩改编成少量完整短剧场景。原文：\n\n${text}` },
          ],
          thinking: { type: 'disabled' },
          response_format: { type: 'json_object' },
          temperature: 0.25,
          max_tokens: 5200,
          stream: false,
        }),
        signal: AbortSignal.timeout(MODEL_TIMEOUT_MS),
      });
    } catch (error) {
      console.warn('DeepSeek adaptation unavailable', error instanceof Error ? error.message : 'unknown error');
      return Response.json({ error: 'AI精简改编响应超时或暂时不可用，请稍后再试。' }, { status: 504 });
    }

    let payload: Record<string, unknown>;
    try {
      payload = await response.json() as Record<string, unknown>;
    } catch {
      return Response.json({ error: 'AI精简改编暂时不可用，请稍后再试。' }, { status: 502 });
    }
    if (!response.ok) {
      console.error('DeepSeek adaptation failed', response.status);
      return Response.json({ error: 'AI精简改编暂时不可用，请稍后再试。' }, { status: 502 });
    }
    const resultText = outputText(payload);
    if (!resultText) return Response.json({ error: '模型没有返回可用的改编结果。' }, { status: 502 });
    const result = normalizeNovelAdaptation(parseOutput(resultText), body.episodeNumber);
    return Response.json({ result, meta: { provider: 'deepseek', model: MODEL } });
  } catch (error) {
    console.error('Novel adaptation failed', error instanceof Error ? error.message : 'unknown error');
    return Response.json({ error: error instanceof Error ? error.message : 'AI精简改编失败。' }, { status: 500 });
  }
}
