import { analyzeScript, type AnalysisResult } from '@/lib/script-engine';
import { getEpisodeSummary, getLatestScene, getPreviousScene } from '@/lib/scene-db';
import { sceneContinuityContext } from '@/lib/scene-state';

export const runtime = 'edge';

const MODEL = 'deepseek-v4-flash';
const API_URL = 'https://api.deepseek.com/chat/completions';
const MODEL_TIMEOUT_MS = 30000;
const issueTypes = [
  'missing_character', 'abstract_emotion', 'missing_response', 'weak_action',
  'knowledge_risk', 'emotion_jump', 'continuity', 'dialogue_logic',
  'character_consistency',
];

const analysisSchema = {
  type: 'object',
  additionalProperties: false,
  properties: {
    characters: { type: 'array', items: { type: 'string' }, maxItems: 12 },
    beats: {
      type: 'array',
      minItems: 1,
      maxItems: 30,
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          id: { type: 'string' },
          source: { type: 'string' },
          actor: { type: 'string' },
          receiver: { type: 'string' },
          trigger: { type: 'string' },
          goal: { type: 'string' },
          action: { type: 'string' },
          dialogue: { type: 'string' },
          reaction: { type: 'string' },
          response: { type: 'string' },
          stateBefore: { type: 'string' },
          stateAfter: { type: 'string' },
        },
        required: [
          'id', 'source', 'actor', 'receiver', 'trigger', 'goal', 'action',
          'dialogue', 'reaction', 'response', 'stateBefore', 'stateAfter',
        ],
      },
    },
    issues: {
      type: 'array',
      maxItems: 40,
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          id: { type: 'string' },
          severity: { type: 'string', enum: ['hard', 'soft'] },
          type: { type: 'string', enum: issueTypes },
          targetId: { type: 'string' },
          title: { type: 'string' },
          detail: { type: 'string' },
          suggestion: { type: 'string' },
          resolved: { type: 'boolean' },
        },
        required: ['id', 'severity', 'type', 'targetId', 'title', 'detail', 'suggestion', 'resolved'],
      },
    },
    score: { type: 'integer', minimum: 0, maximum: 100 },
    executionPrompt: { type: 'string' },
  },
  required: ['characters', 'beats', 'issues', 'score', 'executionPrompt'],
} as const;

const instructions = `你是短剧交互编译器，不是自由改写作者。你的任务是把中文原始剧本转换为可拍摄、可验证、可供视频模型执行的交互节拍，并只输出 JSON 对象。

必须遵守：
1. 不改变核心事实、人物关系、事件顺序和结局倾向。
2. 每个节拍都要有：触发、人物目标、一个可见动作、台词、对方即时反应、回应、前后状态。
3. 抽象情绪必须落到微动作、视线、停顿、距离或语气，禁止夸张堆砌动作。
4. 对方的反应必须明确承接上一句台词或动作；状态变化必须有可观察原因。
5. 人物不能使用自己尚未知晓的信息；道具、站位和时间线必须连续。
6. 台词保持口语化、简短、有潜台词，不重复已经明确的信息。
7. issues 只记录具体、可定位的问题；targetId 指向节拍编号或 SCRIPT。
8. executionPrompt 要完整列出修正后的节拍，并约束后续分镜模型保持人物、道具、空间和因果连续。
9. 如果提供“上一场状态”，必须默认继承人物情绪、知情信息、道具、空间与时间；若新剧本开场与其冲突且没有明确变化过程，添加 hard continuity 问题并给出补桥建议。
10. 仅输出符合下方 JSON Schema 的数据；禁止 Markdown 代码块、注释、未加双引号的键和尾随逗号。

JSON Schema：
${JSON.stringify(analysisSchema)}`;

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
  if (typeof payload.output_text === 'string') return payload.output_text;
  const output = Array.isArray(payload.output) ? payload.output : [];
  for (const item of output) {
    if (!item || typeof item !== 'object') continue;
    const content = Array.isArray((item as { content?: unknown[] }).content)
      ? (item as { content: unknown[] }).content
      : [];
    for (const part of content) {
      if (part && typeof part === 'object' && (part as { type?: string }).type === 'output_text') {
        const text = (part as { text?: unknown }).text;
        if (typeof text === 'string') return text;
      }
    }
  }
  return '';
}

function parseStructuredOutput(outputText: string) {
  const unfenced = outputText
    .replace(/^\uFEFF/, '')
    .replace(/^```(?:json)?\s*/i, '')
    .replace(/\s*```$/, '')
    .trim();
  const firstBrace = unfenced.indexOf('{');
  const lastBrace = unfenced.lastIndexOf('}');
  const objectText = firstBrace >= 0 && lastBrace > firstBrace
    ? unfenced.slice(firstBrace, lastBrace + 1)
    : unfenced;

  try {
    return JSON.parse(objectText) as Omit<AnalysisResult, 'analyzedAt'>;
  } catch {
    const repaired = objectText
      .replace(/^\s*\/\/.*$/gm, '')
      .replace(/\/\*[\s\S]*?\*\//g, '')
      .replace(/,\s*([}\]])/g, '$1')
      .replace(/([{,]\s*)([A-Za-z_$][\w$]*)\s*:/g, '$1"$2":');
    return JSON.parse(repaired) as Omit<AnalysisResult, 'analyzedAt'>;
  }
}

function enforceBeatCompleteness(result: Omit<AnalysisResult, 'analyzedAt'>, script: string) {
  const localBeatCount = analyzeScript(script).beats.length;
  const minimumBeatCount = Math.max(1, Math.ceil(localBeatCount * 0.75));
  if (result.beats.length >= minimumBeatCount) return { result, minimumBeatCount, blocked: false };
  const gateIssue = {
    id: 'MODEL-BEAT-GATE',
    severity: 'hard' as const,
    type: 'dialogue_logic' as const,
    targetId: 'SCRIPT',
    title: '模型节拍覆盖不足',
    detail: `模型只返回 ${result.beats.length} 个节拍，但原文结构至少需要 ${minimumBeatCount} 个节拍；前后动作或台词可能被合并，无法安全交给分镜模型。`,
    suggestion: '重新运行编译，或把每个“动作/台词/对方反应”拆成独立句子后再分析。',
    resolved: false,
  };
  return {
    result: {
      ...result,
      issues: [...result.issues.filter((issue) => issue.id !== gateIssue.id), gateIssue],
      score: Math.min(Number(result.score) || 0, 64),
    },
    minimumBeatCount,
    blocked: true,
  };
}

export async function POST(request: Request) {
  try {
    const body = await request.json() as {
      script?: string;
      mode?: 'analyze' | 'repair';
      current?: AnalysisResult;
      loopCount?: number;
      episodeNumber?: number;
      projectId?: string;
      sceneId?: string;
    };
    const script = body.script?.trim() ?? '';
    if (!script) return Response.json({ error: '请输入剧本后再分析。' }, { status: 400 });
    if (script.length > 12000) return Response.json({ error: '单次剧本请控制在 12000 字以内。' }, { status: 400 });

    const apiKey = process.env.DEEPSEEK_API_KEY;
    if (!apiKey) return Response.json({ error: '模型服务尚未配置。' }, { status: 503 });

    let previousScene = null;
    try {
      previousScene = body.sceneId?.trim()
        ? await getPreviousScene(body.sceneId.trim(), body.projectId?.trim() || undefined)
        : await getLatestScene(body.projectId?.trim() || undefined);
    } catch (error) {
      console.warn('Previous scene context unavailable', error instanceof Error ? error.message : 'unknown error');
    }
    const continuityContext = previousScene
      ? `\n\n上一场状态（权威连续性约束）：\n${JSON.stringify(sceneContinuityContext(previousScene))}`
      : '';
    let episodeSummary = null;
    if (body.episodeNumber) {
      try {
        episodeSummary = await getEpisodeSummary(body.episodeNumber, body.projectId?.trim() || undefined);
      } catch (error) {
        console.warn('Episode summary context unavailable', error instanceof Error ? error.message : 'unknown error');
      }
    }
    const episodeSummaryContext = episodeSummary
      ? `\n\n本集创作约束（辅助上下文，不能覆盖原始剧本事实）：\n${JSON.stringify({
          episodeNumber: episodeSummary.episodeNumber,
          title: episodeSummary.title,
          objective: episodeSummary.objective,
          conflict: episodeSummary.conflict,
          notes: episodeSummary.notes,
        })}`
      : '';

    const isRepair = body.mode === 'repair' && body.current;
    const input = isRepair
      ? `执行第 ${Math.max(1, body.loopCount ?? 1)} 轮受控修复。只修复 currentResult 中 resolved=false 的问题；不要重写无关节拍，不改变核心剧情。修复后将相应问题标为 resolved=true；如果无法安全修复则保留 false 并说明原因。\n\n原始剧本：\n${script}\n\ncurrentResult：\n${JSON.stringify(body.current)}${continuityContext}${episodeSummaryContext}`
      : `分析并编译下面这场短剧。保留原意，但把含糊的情绪和交互补成可拍摄的因果链。${continuityContext}${episodeSummaryContext}\n\n当前场原始剧本：\n${script}`;

    let modelResponse: Response;
    try {
      modelResponse = await fetch(API_URL, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${apiKey}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          model: MODEL,
          messages: [
            { role: 'system', content: instructions },
            { role: 'user', content: input },
          ],
          thinking: { type: 'disabled' },
          response_format: { type: 'json_object' },
          temperature: 0.2,
          max_tokens: 4500,
          stream: false,
        }),
        signal: AbortSignal.timeout(MODEL_TIMEOUT_MS),
      });
    } catch (error) {
      console.warn('DeepSeek analysis unavailable', error instanceof Error ? error.message : 'unknown error');
      return Response.json({ error: '智能分析响应超时或暂时不可用，请稍后再试。' }, { status: 504 });
    }

    const payload = await modelResponse.json() as Record<string, unknown>;
    if (!modelResponse.ok) {
      const apiError = payload.error && typeof payload.error === 'object'
        ? (payload.error as { message?: string }).message
        : undefined;
      console.error('DeepSeek response failed', modelResponse.status, apiError ?? 'unknown error');
      return Response.json({ error: '智能分析暂时不可用，请稍后再试。' }, { status: 502 });
    }

    const outputText = getOutputText(payload);
    if (!outputText) return Response.json({ error: '模型没有返回可用的结构化结果。' }, { status: 502 });
    const parsedResult = parseStructuredOutput(outputText);
    const beatCheck = enforceBeatCompleteness(parsedResult, script);
    const result = beatCheck.result;

    return Response.json({
      result: { ...result, analyzedAt: new Date().toISOString() },
      meta: {
        source: 'ai', provider: 'deepseek', model: MODEL,
        mode: isRepair ? 'repair' : 'analyze',
        beatGate: { minimum: beatCheck.minimumBeatCount, actual: result.beats.length, blocked: beatCheck.blocked },
        previousSceneNumber: previousScene?.sceneOrder ?? null,
        previousEpisodeNumber: previousScene?.episodeNumber ?? null,
      },
    });
  } catch (error) {
    console.error('Script analysis failed', error instanceof Error ? error.message : 'unknown error');
    return Response.json({ error: '剧本分析失败，请检查内容后重试。' }, { status: 500 });
  }
}
