import { buildEpisodeSourceHash, type EpisodeAIReview, type EpisodeAIReviewCategory, type EpisodeAIReviewIssue } from '@/lib/episode-ai-review';
import { getEpisodeSummary, listEpisodeAIReviews, listSceneDetails, upsertEpisodeAIReview } from '@/lib/scene-db';
import { DEFAULT_PROJECT_ID } from '@/lib/scene-state';

export const runtime = 'edge';

const MODEL = 'deepseek-v4-flash';
const API_URL = 'https://api.deepseek.com/chat/completions';
const MODEL_TIMEOUT_MS = 36000;
const categories = new Set<EpisodeAIReviewCategory>(['causality', 'motivation', 'conflict', 'pacing', 'knowledge', 'hook']);

const reviewSchema = {
  type: 'object', additionalProperties: false,
  properties: {
    overview: { type: 'string' }, hookAssessment: { type: 'string' },
    strengths: { type: 'array', maxItems: 6, items: { type: 'string' } },
    issues: {
      type: 'array', maxItems: 20, items: {
        type: 'object', additionalProperties: false,
        properties: {
          id: { type: 'string' }, severity: { type: 'string', enum: ['hard', 'soft'] },
          category: { type: 'string', enum: ['causality', 'motivation', 'conflict', 'pacing', 'knowledge', 'hook'] },
          sceneIds: { type: 'array', maxItems: 8, items: { type: 'string' } },
          title: { type: 'string' }, detail: { type: 'string' }, suggestion: { type: 'string' },
        },
        required: ['id', 'severity', 'category', 'sceneIds', 'title', 'detail', 'suggestion'],
      },
    },
  },
  required: ['overview', 'hookAssessment', 'strengths', 'issues'],
} as const;

const instructions = `你是短剧整集结构审查员。只依据输入中的本集目标、核心冲突和已保存场次做审查，不得补写不存在的事实。只输出合法 JSON 对象。

审查六项：
1. causality：每场是否由上一场结果触发，下一场是否回应前一场未解决问题。
2. motivation：人物行为是否符合其目标、已知信息和前一场状态。
3. conflict：阻力是否逐场升级，是否存在只有对话但冲突不推进的场次。
4. pacing：是否有重复功能、信息顺序混乱或可以合并的场次。
5. knowledge：人物是否突然知道未获得的信息，或忘记已经确认的信息。
6. hook：本集结尾是否产生明确的新问题、选择、危险或信息反转。

hard 仅用于会破坏因果、人物动机或信息逻辑的结构问题；审美增强、节奏优化和钩子强化使用 soft。每个问题必须引用真实 sceneIds，并给出限制范围明确的修改建议。没有问题时 issues 返回空数组。

JSON Schema：
${JSON.stringify(reviewSchema)}`;

function outputText(payload: Record<string, unknown>) {
  const choices = Array.isArray(payload.choices) ? payload.choices : [];
  const message = choices[0] && typeof choices[0] === 'object' ? (choices[0] as { message?: unknown }).message : null;
  return message && typeof message === 'object' && typeof (message as { content?: unknown }).content === 'string'
    ? (message as { content: string }).content : '';
}

function parseReview(text: string, validSceneIds: Set<string>) {
  const clean = text.replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '').trim();
  const first = clean.indexOf('{');
  const last = clean.lastIndexOf('}');
  const parsed = JSON.parse(first >= 0 && last > first ? clean.slice(first, last + 1) : clean) as Record<string, unknown>;
  const rawIssues = Array.isArray(parsed.issues) ? parsed.issues : [];
  const issues: EpisodeAIReviewIssue[] = rawIssues.slice(0, 20).flatMap((value, index) => {
    if (!value || typeof value !== 'object') return [];
    const issue = value as Record<string, unknown>;
    if ((issue.severity !== 'hard' && issue.severity !== 'soft') || typeof issue.category !== 'string' || !categories.has(issue.category as EpisodeAIReviewCategory)) return [];
    if (typeof issue.title !== 'string' || typeof issue.detail !== 'string' || typeof issue.suggestion !== 'string') return [];
    const sceneIds = Array.isArray(issue.sceneIds)
      ? issue.sceneIds.filter((id): id is string => typeof id === 'string' && validSceneIds.has(id)).slice(0, 8)
      : [];
    if (sceneIds.length === 0) return [];
    return [{
      id: typeof issue.id === 'string' && issue.id.trim() ? issue.id.trim() : `AI${index + 1}`,
      severity: issue.severity, category: issue.category as EpisodeAIReviewCategory, sceneIds,
      title: issue.title.trim(), detail: issue.detail.trim(), suggestion: issue.suggestion.trim(),
    }];
  });
  return {
    overview: typeof parsed.overview === 'string' ? parsed.overview.trim() : '',
    hookAssessment: typeof parsed.hookAssessment === 'string' ? parsed.hookAssessment.trim() : '',
    strengths: Array.isArray(parsed.strengths)
      ? parsed.strengths.filter((item): item is string => typeof item === 'string' && Boolean(item.trim())).slice(0, 6)
      : [],
    issues,
  };
}

export async function GET(request: Request) {
  try {
    const projectId = new URL(request.url).searchParams.get('projectId')?.trim() || DEFAULT_PROJECT_ID;
    const [reviews, scenes] = await Promise.all([listEpisodeAIReviews(projectId), listSceneDetails(projectId, 500)]);
    const current: EpisodeAIReview[] = [];
    const staleEpisodeNumbers: number[] = [];
    for (const review of reviews) {
      const summary = await getEpisodeSummary(review.episodeNumber, projectId);
      const sourceHash = await buildEpisodeSourceHash(review.episodeNumber, scenes, summary);
      if (sourceHash === review.sourceHash) current.push(review);
      else staleEpisodeNumbers.push(review.episodeNumber);
    }
    return Response.json({ reviews: current, staleEpisodeNumbers });
  } catch (error) {
    console.error('Episode AI review load failed', error instanceof Error ? error.message : 'unknown error');
    return Response.json({ error: 'AI整集审查记录暂时不可用。' }, { status: 500 });
  }
}

export async function POST(request: Request) {
  try {
    const body = await request.json() as { projectId?: string; episodeNumber?: number };
    const projectId = body.projectId?.trim() || DEFAULT_PROJECT_ID;
    const requestedEpisodeNumber = Number(body.episodeNumber);
    if (!Number.isFinite(requestedEpisodeNumber) || requestedEpisodeNumber < 1 || requestedEpisodeNumber > 999) {
      return Response.json({ error: '缺少有效的审查集数。' }, { status: 400 });
    }
    const episodeNumber = Math.round(requestedEpisodeNumber);
    const [allScenes, summary] = await Promise.all([
      listSceneDetails(projectId, 500), getEpisodeSummary(episodeNumber, projectId),
    ]);
    const scenes = allScenes.filter((scene) => scene.episodeNumber === episodeNumber)
      .sort((a, b) => a.sceneOrder - b.sceneOrder || a.sceneNumber - b.sceneNumber);
    if (scenes.length === 0) return Response.json({ error: '本集还没有已保存场次。' }, { status: 409 });
    if (!summary?.objective.trim() || !summary.conflict.trim()) {
      return Response.json({ error: '请先填写并保存本集戏剧目标和核心冲突。' }, { status: 409 });
    }
    const apiKey = process.env.DEEPSEEK_API_KEY;
    if (!apiKey) return Response.json({ error: '模型服务尚未配置。' }, { status: 503 });

    const input = JSON.stringify({
      episodeNumber,
      summary: { title: summary.title, objective: summary.objective, conflict: summary.conflict, notes: summary.notes },
      scenes: scenes.map((scene, index) => ({
        sceneId: scene.id, order: index + 1, title: scene.title, script: scene.script,
        characters: scene.analysis.characters,
        beats: scene.analysis.beats.map((beat) => ({
          actor: beat.actor, receiver: beat.receiver, trigger: beat.trigger, goal: beat.goal,
          action: beat.action, dialogue: beat.dialogue, reaction: beat.reaction,
          response: beat.response, stateBefore: beat.stateBefore, stateAfter: beat.stateAfter,
        })),
        openingState: scene.openingState, endingState: scene.snapshot,
      })),
    });
    const response = await fetch(API_URL, {
      method: 'POST',
      headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: MODEL,
        messages: [{ role: 'system', content: instructions }, { role: 'user', content: input }],
        thinking: { type: 'disabled' }, response_format: { type: 'json_object' },
        temperature: 0.1, max_tokens: 4500, stream: false,
      }),
      signal: AbortSignal.timeout(MODEL_TIMEOUT_MS),
    });
    const payload = await response.json() as Record<string, unknown>;
    if (!response.ok) return Response.json({ error: 'AI整集审查暂时不可用，请稍后重试。' }, { status: 502 });
    const text = outputText(payload);
    if (!text) return Response.json({ error: '模型没有返回可用的整集审查结果。' }, { status: 502 });
    const parsed = parseReview(text, new Set(scenes.map((scene) => scene.id)));
    const hardCount = parsed.issues.filter((issue) => issue.severity === 'hard').length;
    const softCount = parsed.issues.length - hardCount;
    const reviewedAt = new Date().toISOString();
    const review: EpisodeAIReview = {
      projectId, episodeNumber,
      sourceHash: await buildEpisodeSourceHash(episodeNumber, allScenes, summary),
      score: Math.max(0, 100 - hardCount * 15 - softCount * 6),
      status: hardCount > 0 ? 'blocked' : softCount > 0 ? 'attention' : 'ready',
      overview: parsed.overview, hookAssessment: parsed.hookAssessment,
      strengths: parsed.strengths, issues: parsed.issues, reviewedAt,
    };
    await upsertEpisodeAIReview(review);
    return Response.json({ review });
  } catch (error) {
    console.error('Episode AI review failed', error instanceof Error ? error.message : 'unknown error');
    return Response.json({ error: 'AI整集审查失败，请稍后重试。' }, { status: 500 });
  }
}
