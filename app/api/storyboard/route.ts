import type { AnalysisResult } from '@/lib/script-engine';
import { requireAuth } from '@/lib/auth';
import { getLatestScene, getPreviousScene } from '@/lib/scene-db';
import { DEFAULT_PROJECT_ID, inheritStoryboardOpeningState, sceneContinuityContext } from '@/lib/scene-state';
import {
  addStoryboardRepairHistory,
  buildFallbackStoryboard,
  enforceStoryboardRepairScope,
  finalizeStoryboard,
  getStoryboardBudget,
  getStoryboardRepairScope,
  type StoryboardResult,
} from '@/lib/storyboard-engine';

export const runtime = 'edge';

const MODEL = 'deepseek-v4-flash';
const API_URL = 'https://api.deepseek.com/chat/completions';
const MODEL_TIMEOUT_MS = 36000;
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

const instructions = `你是短剧分镜编译器。输入包含原始剧本和已经验证的交互节拍。你要生成能直接交给视频模型执行的镜头表，并建立可被程序比较的连续性状态，只输出 JSON 对象。

规则：
1. 每个交互节拍至少对应一个镜头；重要的“行动—反应”可以拆为两个镜头。
2. 每个镜头只保留一个主要动作，时长 1—15 秒；台词必须与当前人物动作同步。
3. 第一镜头先建立空间和人物轴线，后续景别和机位必须服务冲突推进，禁止无意义炫技。
4. 每个镜头都填写 startState 与 endState。除非镜头中实际发生变化，下一个镜头 startState 必须逐字复制上一个镜头 endState。
5. 连续检查必须覆盖人物站位、视线、道具、空间和时间。确有跳切时，在 continuityReason 中说明；普通连续镜头写“连续承接”。
6. videoPrompt 要描述主体、单一动作、构图、光线和连续性约束，不得改变人物身份、服装、道具或剧情事实。
7. issues 只记录仍存在的具体问题；没有问题可以返回空数组。
8. modelPrompt 是将全部镜头发送给后续视频生成模型的总指令，强调镜头顺序和状态锁定。
9. 仅输出符合下方 JSON Schema 的合法 JSON；禁止 Markdown、注释、未加双引号的键和尾随逗号。

JSON Schema：
${JSON.stringify(storyboardSchema)}`;

const repairInstructions = `${instructions}

当前任务是“受控分镜修复”，不是重新创作：
1. 只修改 editableShotIds 中的镜头及 editableBeatIds 对应的必要新增镜头。
2. lockedShotIds 中的镜头必须原样返回，所有字段、顺序和编号都不得改变或删除。
3. 逐项解决 activeIssues，并保证修改后镜头与前后锁定镜头的状态能够衔接。
4. 不得改变已经确定的剧情事实、人物关系、台词信息和节拍顺序。
5. 修复后的镜头总数不得超过当前分镜；优先删减、合并或简化，不得通过持续拆镜制造镜头膨胀。
6. 若一个问题无法在授权范围内安全解决，保留原镜头并继续在 issues 中说明，不得扩大修改范围。`;

function getOutputText(payload: Record<string, unknown>) {
  const choices = Array.isArray(payload.choices) ? payload.choices : [];
  const firstChoice = choices[0];
  if (firstChoice && typeof firstChoice === 'object') {
    const message = (firstChoice as { message?: unknown }).message;
    if (message && typeof message === 'object') {
      const content = (message as { content?: unknown }).content;
      if (typeof content === 'string') return content;
    }
  }
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
  const unauthorized = await requireAuth(request);
  if (unauthorized) return unauthorized;
  try {
    const body = await request.json() as {
      script?: string;
      analysis?: AnalysisResult;
      mode?: 'generate' | 'repair';
      current?: StoryboardResult;
      loopCount?: number;
      projectId?: string;
      sceneId?: string;
    };
    if (!body.script?.trim() || !body.analysis?.beats?.length) {
      return Response.json({ error: '请先完成剧本交互分析。' }, { status: 400 });
    }
    const apiKey = process.env.DEEPSEEK_API_KEY;
    if (!apiKey) return Response.json({ error: '模型服务尚未配置。' }, { status: 503 });

    const repairMode = body.mode === 'repair';
    if (repairMode && (!body.current?.shots?.length || !body.current.issues.some((issue) => !issue.resolved))) {
      return Response.json({ error: '当前没有需要修复的分镜问题。' }, { status: 400 });
    }
    if (repairMode && (body.loopCount ?? 0) > 3) {
      return Response.json({ error: '分镜修复最多运行3轮。' }, { status: 400 });
    }
    const scope = repairMode && body.current ? getStoryboardRepairScope(body.current) : null;
    const budget = getStoryboardBudget(body.analysis);
    const projectId = body.projectId?.trim() || DEFAULT_PROJECT_ID;
    let previousScene = null;
    try {
      previousScene = body.sceneId?.trim()
        ? await getPreviousScene(body.sceneId.trim(), projectId)
        : await getLatestScene(projectId);
    } catch (error) {
      console.warn('Storyboard previous scene context unavailable', error instanceof Error ? error.message : 'unknown error');
    }
    const previousSceneContext = previousScene
      ? `\n\n上一场结束状态（权威约束）：\n${JSON.stringify(sceneContinuityContext(previousScene))}\n若当前剧本没有明确写出时间、地点或人物移动变化，第一镜头 startState 必须逐字段继承这份状态。若剧本明确转场，必须在第一镜头 continuityReason 中写清变化依据。`
      : '';
    const budgetContext = `\n\n本场硬预算：最多 ${budget.maxShots} 个镜头、预计总时长最多 ${budget.maxDurationSec} 秒。每个节拍通常使用 1 个镜头，确有必要的行动—反应最多拆为 2 个。不得用重复表情、重复停顿或无信息增量反应填充镜头。`;
    const input = repairMode && body.current && scope
      ? `原始剧本：\n${body.script}\n\n交互分析：\n${JSON.stringify(body.analysis)}\n\n当前分镜：\n${JSON.stringify(body.current)}\n\nactiveIssues：\n${JSON.stringify(body.current.issues.filter((issue) => !issue.resolved))}\n\n修复范围：\n${JSON.stringify(scope)}${previousSceneContext}${budgetContext}`
      : `原始剧本：\n${body.script}\n\n交互分析：\n${JSON.stringify(body.analysis)}${previousSceneContext}${budgetContext}`;

    let parsed: Omit<StoryboardResult, 'generatedAt' | 'totalDurationSec' | 'continuityScore'>;
    let usedFallback = false;
    try {
      const modelResponse = await fetch(API_URL, {
        method: 'POST',
        headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: MODEL,
          messages: [
            { role: 'system', content: repairMode ? repairInstructions : instructions },
            { role: 'user', content: input },
          ],
          thinking: { type: 'disabled' },
          response_format: { type: 'json_object' },
          temperature: 0.2,
          max_tokens: 7000,
          stream: false,
        }),
        signal: AbortSignal.timeout(MODEL_TIMEOUT_MS),
      });
      const payload = await modelResponse.json() as Record<string, unknown>;
      if (!modelResponse.ok) throw new Error(`DeepSeek storyboard status ${modelResponse.status}`);
      const outputText = getOutputText(payload);
      if (!outputText) throw new Error('DeepSeek storyboard returned no output');
      parsed = parseOutput(outputText);
    } catch (error) {
      usedFallback = true;
      console.warn('Storyboard AI unavailable, using rule fallback', error instanceof Error ? error.message : 'unknown error');
      parsed = repairMode && body.current
        ? {
            shots: body.current.shots,
            issues: body.current.issues.filter((issue) => !issue.resolved),
            modelPrompt: body.current.modelPrompt,
          }
        : buildFallbackStoryboard(body.analysis);
    }
    const scoped = repairMode && body.current && scope
      ? enforceStoryboardRepairScope(body.current, parsed, scope)
      : parsed;
    const continuityScoped = inheritStoryboardOpeningState(scoped, previousScene, body.script);
    const finalized = finalizeStoryboard(continuityScoped, body.analysis, scope?.lockedShotIds);
    const result = repairMode && body.current
      ? addStoryboardRepairHistory(body.current, finalized)
      : finalized;
    return Response.json({
      result,
      meta: {
        source: usedFallback ? 'local' : 'ai', provider: usedFallback ? 'rules' : 'deepseek', model: MODEL,
        mode: repairMode ? 'repair' : 'generate',
        fallback: usedFallback,
        editableShotIds: scope?.editableShotIds ?? [],
        lockedShotCount: scope?.lockedShotIds.length ?? 0,
      },
    });
  } catch (error) {
    console.error('Storyboard generation failed', error instanceof Error ? error.message : 'unknown error');
    return Response.json({ error: '分镜生成失败，请稍后重试。' }, { status: 500 });
  }
}
