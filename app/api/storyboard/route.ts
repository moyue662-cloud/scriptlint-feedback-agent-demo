import type { AnalysisResult } from '@/lib/script-engine';
import {
  finalizeStoryboard,
  type StoryboardResult,
} from '@/lib/storyboard-engine';

export const runtime = 'edge';

const MODEL = 'deepseek-v4-flash';
const API_URL = 'https://api.deepseek.com/responses';
const stateProperties = {
  characterPositions: { type: 'string' },
  gazeDirection: { type: 'string' },
  propState: { type: 'string' },
  spaceState: { type: 'string' },
  timeState: { type: 'string' },
};

const storyboardSchema = {
  type: 'object',
  additionalProperties: false,
  properties: {
    shots: {
      type: 'array', minItems: 1, maxItems: 60,
      items: {
        type: 'object', additionalProperties: false,
        properties: {
          id: { type: 'string' }, beatId: { type: 'string' },
          durationSec: { type: 'number', minimum: 1, maximum: 15 },
          shotSize: { type: 'string' }, cameraAngle: { type: 'string' },
          cameraMovement: { type: 'string' }, focus: { type: 'string' },
          action: { type: 'string' }, dialogue: { type: 'string' },
          sound: { type: 'string' }, transition: { type: 'string' },
          startState: {
            type: 'object', additionalProperties: false, properties: stateProperties,
            required: ['characterPositions', 'gazeDirection', 'propState', 'spaceState', 'timeState'],
          },
          endState: {
            type: 'object', additionalProperties: false, properties: stateProperties,
            required: ['characterPositions', 'gazeDirection', 'propState', 'spaceState', 'timeState'],
          },
          continuityReason: { type: 'string' }, videoPrompt: { type: 'string' },
        },
        required: [
          'id', 'beatId', 'durationSec', 'shotSize', 'cameraAngle', 'cameraMovement',
          'focus', 'action', 'dialogue', 'sound', 'transition', 'startState',
          'endState', 'continuityReason', 'videoPrompt',
        ],
      },
    },
    issues: {
      type: 'array', maxItems: 40,
      items: {
        type: 'object', additionalProperties: false,
        properties: {
          id: { type: 'string' }, severity: { type: 'string', enum: ['hard', 'soft'] },
          type: { type: 'string', enum: [
            'beat_coverage', 'character_position', 'gaze_direction', 'prop_state',
            'space_state', 'time_state', 'shot_density', 'shot_identity',
          ] },
          fromShotId: { type: 'string' }, toShotId: { type: 'string' },
          detail: { type: 'string' }, suggestion: { type: 'string' },
          resolved: { type: 'boolean' },
        },
        required: ['id', 'severity', 'type', 'fromShotId', 'toShotId', 'detail', 'suggestion', 'resolved'],
      },
    },
    modelPrompt: { type: 'string' },
  },
  required: ['shots', 'issues', 'modelPrompt'],
} as const;

const instructions = `你是短剧分镜编译器。输入包含原始剧本和已经验证的交互节拍。你要生成能直接交给视频模型执行的镜头表，并建立可被程序比较的连续性状态。

规则：
1. 每个交互节拍至少对应一个镜头；重要的“行动—反应”可以拆为两个镜头。
2. 每个镜头只保留一个主要动作，时长 1—15 秒；台词必须与当前人物动作同步。
3. 第一镜头先建立空间和人物轴线，后续景别和机位必须服务冲突推进，禁止无意义炫技。
4. 每个镜头都填写 startState 与 endState。除非镜头中实际发生变化，下一个镜头 startState 必须逐字复制上一个镜头 endState。
5. 连续检查必须覆盖人物站位、视线、道具、空间和时间。确有跳切时，在 continuityReason 中说明；普通连续镜头写“连续承接”。
6. videoPrompt 要描述主体、单一动作、构图、光线和连续性约束，不得改变人物身份、服装、道具或剧情事实。
7. issues 只记录仍存在的具体问题；没有问题可以返回空数组。
8. modelPrompt 是将全部镜头发送给后续视频生成模型的总指令，强调镜头顺序和状态锁定。
9. 仅输出合法 JSON；禁止 Markdown、注释、未加双引号的键和尾随逗号。`;

function getOutputText(payload: Record<string, unknown>) {
  const output = Array.isArray(payload.output) ? payload.output : [];
  for (const item of output) {
    if (!item || typeof item !== 'object') continue;
    const content = Array.isArray((item as { content?: unknown[] }).content)
      ? (item as { content: unknown[] }).content : [];
    for (const part of content) {
      if (part && typeof part === 'object' && (part as { type?: string }).type === 'output_text') {
        const text = (part as { text?: unknown }).text;
        if (typeof text === 'string') return text;
      }
    }
  }
  return '';
}

function parseOutput(text: string) {
  const clean = text.replace(/^\uFEFF/, '').replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '').trim();
  const first = clean.indexOf('{');
  const last = clean.lastIndexOf('}');
  const objectText = first >= 0 && last > first ? clean.slice(first, last + 1) : clean;
  try {
    return JSON.parse(objectText) as Omit<StoryboardResult, 'generatedAt' | 'totalDurationSec' | 'continuityScore'>;
  } catch {
    return JSON.parse(
      objectText
        .replace(/^\s*\/\/.*$/gm, '')
        .replace(/\/\*[\s\S]*?\*\//g, '')
        .replace(/,\s*([}\]])/g, '$1')
        .replace(/([{,]\s*)([A-Za-z_$][\w$]*)\s*:/g, '$1"$2":'),
    ) as Omit<StoryboardResult, 'generatedAt' | 'totalDurationSec' | 'continuityScore'>;
  }
}

export async function POST(request: Request) {
  try {
    const body = await request.json() as { script?: string; analysis?: AnalysisResult };
    if (!body.script?.trim() || !body.analysis?.beats?.length) {
      return Response.json({ error: '请先完成剧本交互分析。' }, { status: 400 });
    }
    const apiKey = process.env.DEEPSEEK_API_KEY;
    if (!apiKey) return Response.json({ error: '模型服务尚未配置。' }, { status: 503 });

    const modelResponse = await fetch(API_URL, {
      method: 'POST',
      headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: MODEL,
        instructions,
        input: `原始剧本：\n${body.script}\n\n交互分析：\n${JSON.stringify(body.analysis)}`,
        reasoning: { effort: 'none' },
        text: { format: { type: 'json_schema', name: 'short_drama_storyboard', schema: storyboardSchema } },
        max_output_tokens: 12000,
      }),
    });
    const payload = await modelResponse.json() as Record<string, unknown>;
    if (!modelResponse.ok) {
      console.error('DeepSeek storyboard failed', modelResponse.status);
      return Response.json({ error: '分镜生成暂时不可用，请稍后再试。' }, { status: 502 });
    }
    const outputText = getOutputText(payload);
    if (!outputText) return Response.json({ error: '模型没有返回可用分镜。' }, { status: 502 });
    const result = finalizeStoryboard(parseOutput(outputText), body.analysis);
    return Response.json({ result, meta: { source: 'ai', provider: 'deepseek', model: MODEL } });
  } catch (error) {
    console.error('Storyboard generation failed', error instanceof Error ? error.message : 'unknown error');
    return Response.json({ error: '分镜生成失败，请稍后重试。' }, { status: 500 });
  }
}
