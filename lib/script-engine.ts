export type Severity = 'hard' | 'soft';

export type IssueType =
  | 'missing_character'
  | 'abstract_emotion'
  | 'missing_response'
  | 'weak_action'
  | 'knowledge_risk'
  | 'emotion_jump'
  | 'continuity'
  | 'dialogue_logic'
  | 'character_consistency';

export interface InteractionBeat {
  id: string;
  source: string;
  actor: string;
  receiver: string;
  trigger: string;
  goal: string;
  action: string;
  dialogue: string;
  reaction: string;
  response: string;
  stateBefore: string;
  stateAfter: string;
}

export interface ScriptIssue {
  id: string;
  severity: Severity;
  type: IssueType;
  targetId: string;
  title: string;
  detail: string;
  suggestion: string;
  resolved: boolean;
}

export interface AnalysisResult {
  characters: string[];
  beats: InteractionBeat[];
  issues: ScriptIssue[];
  score: number;
  executionPrompt: string;
  analyzedAt: string;
}

export type AnalysisSource = 'ai' | 'local' | 'saved';

const emotionActions: Record<string, string> = {
  生气: '攥紧手中的物品，呼吸变重，直视对方后再开口',
  愤怒: '下颌收紧，向前一步，压低声音逼问对方',
  尴尬: '手上的动作停顿，短暂抬眼后避开对方目光',
  紧张: '手指反复摩挲物品边缘，说话前出现短暂停顿',
  难过: '肩膀缓慢垂下，视线停在地面，声音变轻',
  害怕: '身体向后缩了一点，先观察出口再看向对方',
  怀疑: '盯住对方的细微反应，停顿后换一种方式追问',
  惊讶: '动作突然停住，目光在关键物品与对方之间移动',
  高兴: '眉眼放松，身体主动靠近，语速比之前稍快',
  沉默: '保持原有动作两秒，以回避目光作为明确回应',
};

const actionWords = [
  '发现', '看见', '拿起', '放下', '拍', '推', '走', '站', '坐', '停',
  '抬头', '低头', '转身', '质问', '追问', '解释', '回答', '避开', '看向',
  '盯', '攥', '握', '抓', '松开', '靠近', '后退', '迈', '点头', '摇头',
  '吸气', '呼吸', '停顿', '开口', '说', '喊', '哭', '笑', '沉默', '摩挲',
  '贴', '递', '指', '按', '敲', '翻', '撕', '摔', '端', '举', '收回', '伸出',
];

const genericActionPattern = /保持当前站位，把注意力转向对方，等待其反应|等待(?:其|对方)?(?:反应|回应)/;

const characterStopWords = new Set([
  '原始剧本', '客厅', '晚上', '夜晚', '随后', '突然', '因为', '但是',
  '然后', '此时', '很生气地', '很尴尬地', '很紧张地', '很难过地',
  '很害怕地', '很高兴地', '试图隐瞒', '继续追问', '质问父亲',
]);

const characterNoisePattern = /很|非常|试图|继续|突然|然后|此时|正在|不相信|的$|地$/;

function splitSentences(script: string) {
  return (
    script
      .replace(/\r/g, '')
      .match(/[^。！？!?\n]+(?:[。！？!?][”"'’』】）]?|(?=\n)|$)/g)
      ?.map((sentence) => sentence.trim())
      .filter(Boolean) ?? []
  );
}

function detectCharacters(script: string) {
  const names: string[] = [];
  const add = (name: string) => {
    const cleaned = name.replace(/[“”"'，。！？、\s]/g, '');
    if (
      cleaned.length >= 2 && cleaned.length <= 4 &&
      !characterStopWords.has(cleaned) && !characterNoisePattern.test(cleaned) && !names.includes(cleaned)
    ) names.push(cleaned);
  };

  for (const match of script.matchAll(/(?:^|[。！？!?\n])\s*([\u4e00-\u9fa5]{2,4})\s*[：:]/g)) add(match[1]);
  for (const match of script.matchAll(
    /([\u4e00-\u9fa5]{2,4})(?=发现|看见|质问|询问|回答|解释|说道|说|问|喊|哭|笑|感到|试图|沉默|拿起|放下|转身|怀疑|不相信|尴尬|生气|愤怒|紧张|难过|害怕|高兴|追问)/g,
  )) add(match[1]);

  ['父亲', '母亲', '女儿', '儿子', '老师', '医生', '老板'].forEach((name) => {
    if (script.includes(name)) add(name);
  });
  return names.slice(0, 8);
}

function findEmotion(sentence: string) {
  return Object.keys(emotionActions).find((emotion) => sentence.includes(emotion));
}

function inferGoal(sentence: string, actor: string) {
  if (/质问|追问|真相|为什么|什么时候/.test(sentence)) return '迫使对方给出明确解释';
  if (/隐瞒|回避|不重要|没事/.test(sentence)) return '回避核心事实并维持当前局面';
  if (/道歉|原谅/.test(sentence)) return '修复关系并降低对方的抵抗';
  if (/离开|转身|走/.test(sentence)) return '终止当前冲突并保护自己';
  return `${actor}试图让对方理解自己的立场`;
}

function extractDialogue(sentence: string) {
  const quote = sentence.match(/[“"]([^”"]+)[”"]/);
  if (quote) return quote[1];
  const colon = sentence.match(/[：:]\s*(.+)$/);
  return colon ? colon[1].replace(/[。！？!?]$/, '') : '';
}

function inferAction(sentence: string, emotion?: string, dialogue = '') {
  if (actionWords.some((word) => sentence.includes(word))) {
    return sentence
      .replace(/[“"]([^”"]+)[”"]/g, '')
      .replace(/很(?:生气|尴尬|紧张|难过|害怕|高兴)(?:地)?/g, '')
      .replace(/[，,:：。！？!?]+$/g, '')
      .trim();
  }
  if (dialogue) {
    const combined = `${sentence}${dialogue}`;
    if (/？|\?|为什么|怎么|什么时候|吗|哪/.test(combined)) {
      return '保持与对方目光接触，停顿半秒后追问';
    }
    if (/！|!|喊|吼|怒/.test(combined)) {
      return '身体向前一步，抬高音量说出这句话';
    }
    if (/回答|解释|说明|承认|不是|是的|我知道/.test(combined)) {
      return '先吸气稳定语速，直视对方并解释';
    }
    return '保持当前站位，直视对方并清晰说出这句话';
  }
  if (emotion) return emotionActions[emotion];
  if (/怀疑|担心|意识到|想到|觉得|认为|感到|不相信|犹豫/.test(sentence)) {
    return '短暂停顿，视线落在关键对象上，再抬眼观察对方';
  }
  if (/决定|准备|想要|试图|打算/.test(sentence)) {
    return '收回视线，调整站姿，朝目标迈出一步';
  }
  if (/拒绝|否认|不愿|不肯/.test(sentence)) {
    return '摇头并收回伸出的手，和对方保持距离';
  }
  if (/结果|成功|完成|结束/.test(sentence)) {
    return '确认结果后停住手上动作，抬眼观察对方';
  }
  return '保持当前站位，把注意力转向对方，等待其反应';
}

function hasConcreteAction(action: string) {
  const normalized = action.trim();
  if (!normalized || genericActionPattern.test(normalized)) return false;
  return actionWords.some((word) => normalized.includes(word))
    || /目光|视线|距离|语速|音量|声音|姿势|站位|身体|肩膀|下颌|手指|呼吸|停顿|开口|说出|观察/.test(normalized);
}

function weakActionIssue(beat: InteractionBeat, issueId: string, resolved = hasConcreteAction(beat.action)): ScriptIssue {
  return {
    id: issueId, severity: 'soft', type: 'weak_action', targetId: beat.id,
    title: '缺少明确的可执行动作',
    detail: resolved
      ? '已根据该节拍的台词、情绪或上下文补全为单一、可拍摄动作。'
      : '当前内容主要描述心理或结果，没有给出单一、可拍摄的动作。',
    suggestion: `${resolved ? '已补充动作' : '补充动作'}：${beat.action}`,
    resolved,
  };
}

function inferState(emotion: string | undefined, direction: 'before' | 'after') {
  if (!emotion) return direction === 'before' ? '观望' : '立场更明确';
  const transitions: Record<string, [string, string]> = {
    生气: ['怀疑', '愤怒'], 愤怒: ['压抑', '对抗'], 尴尬: ['隐瞒', '防御'],
    紧张: ['平静表象', '戒备'], 难过: ['克制', '受伤'], 害怕: ['不安', '退缩'],
    怀疑: ['观望', '警觉'], 惊讶: ['正常预期', '意外'], 高兴: ['期待', '放松'],
    沉默: ['抵抗', '回避'],
  };
  return transitions[emotion]?.[direction === 'before' ? 0 : 1] ?? emotion;
}

function buildExecutionPrompt(beats: InteractionBeat[]) {
  const body = beats.map((beat) =>
    `[${beat.id}]\n触发：${beat.trigger}\n人物目标：${beat.actor}—${beat.goal}\n可见动作：${beat.action}\n台词：${beat.dialogue || '无台词'}\n对方反应：${beat.receiver}—${beat.reaction}\n回应：${beat.response}\n状态变化：${beat.stateBefore} → ${beat.stateAfter}`,
  ).join('\n\n');
  return `请将以下交互节拍扩写为现实主义短剧。严格保持人物目标、事件顺序和状态变化；每个镜头只表现一个主要动作；不得加入人物尚未知晓的信息；不得改变已定义道具的位置。\n\n${body}`;
}

export function analyzeScript(script: string): AnalysisResult {
  const sentences = splitSentences(script);
  const characters = detectCharacters(script);
  const usableCharacters = characters.length >= 2 ? characters : [...characters, '对方'].slice(0, 2);
  const beats: InteractionBeat[] = sentences.map((sentence, index) => {
    const actor = characters.find((character) => sentence.includes(character)) ?? usableCharacters[index % usableCharacters.length] ?? '角色A';
    const receiver = usableCharacters.find((character) => character !== actor) ?? '对方';
    const emotion = findEmotion(sentence);
    const dialogue = extractDialogue(sentence);
    const nextSentence = sentences[index + 1] ?? '';
    const nextDialogue = extractDialogue(nextSentence);
    return {
      id: `B${String(index + 1).padStart(2, '0')}`,
      source: sentence,
      actor,
      receiver,
      trigger: index === 0
        ? sentence.includes('发现') ? sentence.split(/后|，/)[0] : '场景开始，人物注意到当前变化'
        : `承接B${String(index).padStart(2, '0')}的行动或台词`,
      goal: inferGoal(sentence, actor),
      action: inferAction(sentence, emotion, dialogue),
      dialogue: dialogue || (sentence.includes('质问') ? '请把这件事解释清楚。' : ''),
      reaction: emotionActions[findEmotion(nextSentence) ?? ''] ?? '动作短暂停顿，并将注意力转向对方',
      response: nextDialogue || (index < sentences.length - 1 ? '以接下来的行动回应' : '沉默两秒，以目光回避作为回应'),
      stateBefore: inferState(emotion, 'before'),
      stateAfter: inferState(emotion, 'after'),
    };
  });

  const issues: ScriptIssue[] = [];
  let issueIndex = 1;
  if (characters.length < 2) {
    issues.push({
      id: `E${String(issueIndex++).padStart(2, '0')}`, severity: 'hard',
      type: 'missing_character', targetId: 'SCRIPT', title: '交互对象不明确',
      detail: '系统未能稳定识别至少两名人物，无法验证动作与回应关系。',
      suggestion: '使用“人物名：台词”格式，或在人物卡中补充出场角色。', resolved: false,
    });
  }

  beats.forEach((beat) => {
    const emotion = findEmotion(beat.source);
    if (emotion) issues.push({
      id: `E${String(issueIndex++).padStart(2, '0')}`, severity: 'soft',
      type: 'abstract_emotion', targetId: beat.id, title: `“${emotion}”缺少可见表演`,
      detail: `原文使用抽象情绪“${emotion}”，视频模型可能产生随机或过度表演。`,
      suggestion: `改为：${emotionActions[emotion]}`, resolved: false,
    });

    // Dialogue already has a deterministic speaking action. Only flag beats
    // whose source is still purely psychological/result-oriented, and point
    // the writer to the inferred, beat-specific action instead of repeating a
    // one-size-fits-all suggestion.
    if (!actionWords.some((word) => beat.source.includes(word)) && !beat.dialogue) {
      issues.push(weakActionIssue(beat, `E${String(issueIndex++).padStart(2, '0')}`));
    }
  });

  const hardCount = issues.filter((issue) => issue.severity === 'hard' && !issue.resolved).length;
  const softCount = issues.filter((issue) => issue.severity === 'soft' && !issue.resolved).length;
  return {
    characters, beats, issues,
    score: Math.max(35, Math.min(98, 96 - hardCount * 18 - softCount * 5)),
    executionPrompt: buildExecutionPrompt(beats), analyzedAt: new Date().toISOString(),
  };
}

/**
 * Stabilise a model response before it reaches the UI. Models occasionally
 * return empty/generic actions or copy the same weak-action warning onto every
 * beat. We preserve the model's editorial fields while deterministically
 * filling the execution-critical fields and rebuilding weak-action checks.
 */
export function normalizeAnalysisResult(
  result: Omit<AnalysisResult, 'analyzedAt'>,
  script: string,
  rebuildWeakIssues = true,
): Omit<AnalysisResult, 'analyzedAt'> {
  const local = analyzeScript(script);
  const beats = (Array.isArray(result.beats) ? result.beats : []).slice(0, 30).map((raw, index) => {
    const fallback = local.beats[index];
    const source = typeof raw.source === 'string' && raw.source.trim() ? raw.source.trim() : fallback?.source ?? '';
    const dialogue = typeof raw.dialogue === 'string' && raw.dialogue.trim()
      ? raw.dialogue.trim()
      : extractDialogue(source);
    const emotion = findEmotion(source);
    const modelAction = typeof raw.action === 'string' ? raw.action.trim() : '';
    const inferredAction = inferAction(source, emotion, dialogue);
    const action = hasConcreteAction(modelAction) ? modelAction : inferredAction;
    return {
      ...raw,
      id: typeof raw.id === 'string' && raw.id.trim() ? raw.id : `B${String(index + 1).padStart(2, '0')}`,
      source,
      actor: typeof raw.actor === 'string' && raw.actor.trim() ? raw.actor : fallback?.actor ?? '角色A',
      receiver: typeof raw.receiver === 'string' && raw.receiver.trim() ? raw.receiver : fallback?.receiver ?? '对方',
      trigger: typeof raw.trigger === 'string' && raw.trigger.trim() ? raw.trigger : fallback?.trigger ?? '场景开始，人物注意到当前变化',
      goal: typeof raw.goal === 'string' && raw.goal.trim() ? raw.goal : fallback?.goal ?? '让对方理解自己的立场',
      action,
      dialogue,
      reaction: typeof raw.reaction === 'string' && raw.reaction.trim() ? raw.reaction : fallback?.reaction ?? '动作短暂停顿，并将注意力转向对方',
      response: typeof raw.response === 'string' && raw.response.trim() ? raw.response : fallback?.response ?? '以接下来的行动回应',
      stateBefore: typeof raw.stateBefore === 'string' && raw.stateBefore.trim() ? raw.stateBefore : fallback?.stateBefore ?? '观望',
      stateAfter: typeof raw.stateAfter === 'string' && raw.stateAfter.trim() ? raw.stateAfter : fallback?.stateAfter ?? '立场更明确',
    } satisfies InteractionBeat;
  });

  const modelIssues = Array.isArray(result.issues) ? result.issues : [];
  const beatById = new Map(beats.map((beat) => [beat.id, beat]));
  const placeholderCharacters = /^(?:对方|角色A|角色B|未知人物|众人|群体|旁白)$/;
  const characters = [...new Set([
    ...(Array.isArray(result.characters) ? result.characters : []),
    ...beats.flatMap((beat) => [beat.actor, beat.receiver]),
  ].map((name) => typeof name === 'string' ? name.trim() : '').filter((name) => name && !placeholderCharacters.test(name)))].slice(0, 12);
  const adjustedWeakIssues = modelIssues
    .filter((issue) => issue.type === 'weak_action')
    .map((issue) => {
      const numericTarget = issue.targetId.match(/(\d+)$/)?.[1];
      const beat = beatById.get(issue.targetId)
        ?? (numericTarget ? beats[Number(numericTarget) - 1] : undefined);
      return beat ? { ...issue, suggestion: `补充动作：${beat.action}` } : issue;
    });
  const preservedIssues = modelIssues.filter((issue) => issue.type !== 'weak_action').map((issue) => {
    const numericTarget = issue.targetId.match(/(\d+)$/)?.[1];
    const beat = beatById.get(issue.targetId)
      ?? (numericTarget ? beats[Number(numericTarget) - 1] : undefined);
    const rosterOnly = issue.type === 'missing_character'
      && /characters|角色.*(?:未|不在|缺少)|未在.*列出|数组.*不包含/i.test(`${issue.title}${issue.detail}`);
    if (rosterOnly && characters.length >= 2) return {
      ...issue,
      detail: '系统已根据节拍中的行动者和承接者自动同步人物表。',
      suggestion: '已自动补入人物表，无需人工处理。',
      resolved: true,
    };
    if (issue.type === 'abstract_emotion' && beat && hasConcreteAction(beat.action)) return {
      ...issue,
      detail: `抽象情绪已落实为可拍摄动作：${beat.action}`,
      suggestion: `已使用动作表达：${beat.action}`,
      resolved: true,
    };
    if (issue.type === 'missing_response' && beat && beat.reaction.trim() && beat.response.trim()) return {
      ...issue,
      detail: `已补全承接反应与回应：${beat.reaction}；${beat.response}`,
      suggestion: '已补全，无需人工处理。',
      resolved: true,
    };
    return issue;
  });
  const weakIssues = beats
    .filter((beat) => !hasConcreteAction(beat.action) && !beat.dialogue)
    .map((beat, index) => weakActionIssue(beat, `LOCAL-W${String(index + 1).padStart(2, '0')}`));
  const issues = [...preservedIssues, ...(rebuildWeakIssues ? weakIssues : adjustedWeakIssues)];
  const hardCount = issues.filter((issue) => issue.severity === 'hard' && !issue.resolved).length;
  const softCount = issues.filter((issue) => issue.severity === 'soft' && !issue.resolved).length;
  return {
    ...result,
    characters,
    beats,
    issues,
    score: Math.max(35, Math.min(98, 96 - hardCount * 18 - softCount * 5)),
    executionPrompt: buildExecutionPrompt(beats),
  };
}

export function repairAnalysis(result: AnalysisResult): AnalysisResult {
  const issues = result.issues.map((issue) => ({ ...issue, resolved: issue.type !== 'missing_character' }));
  const unresolvedHard = issues.filter((issue) => !issue.resolved && issue.severity === 'hard').length;
  const unresolvedSoft = issues.filter((issue) => !issue.resolved && issue.severity === 'soft').length;
  return {
    ...result, issues,
    score: Math.max(result.score, Math.min(99, 96 - unresolvedHard * 18 - unresolvedSoft * 5)),
    executionPrompt: buildExecutionPrompt(result.beats), analyzedAt: new Date().toISOString(),
  };
}
