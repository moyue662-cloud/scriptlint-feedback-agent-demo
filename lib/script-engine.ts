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

export type AnalysisSource = 'ai' | 'local';

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
  '抬头', '低头', '转身', '质问', '解释', '回答', '避开', '看向',
];

const characterStopWords = new Set([
  '原始剧本', '客厅', '晚上', '夜晚', '随后', '突然', '因为', '但是',
  '然后', '此时',
]);

function splitSentences(script: string) {
  return (
    script
      .replace(/\r/g, '')
      .match(/[^。！？!?\n]+[。！？!?]?/g)
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
      !characterStopWords.has(cleaned) && !names.includes(cleaned)
    ) names.push(cleaned);
  };

  for (const match of script.matchAll(/([\u4e00-\u9fa5]{2,4})[：:]/g)) add(match[1]);
  for (const match of script.matchAll(
    /([\u4e00-\u9fa5]{2,4})(?=发现|看见|质问|询问|回答|解释|说道|说|问|喊|哭|笑|很生气|很尴尬|感到|试图|沉默|拿起|放下|转身)/g,
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

function inferAction(sentence: string, emotion?: string) {
  if (actionWords.some((word) => sentence.includes(word))) {
    return sentence
      .replace(/[“"]([^”"]+)[”"]/g, '')
      .replace(/很(?:生气|尴尬|紧张|难过|害怕|高兴)/g, '')
      .replace(/[，。！？!?]+$/g, '')
      .trim();
  }
  if (emotion) return emotionActions[emotion];
  return '保持当前站位，把注意力转向对方，等待其反应';
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
      action: inferAction(sentence, emotion),
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

    if (!actionWords.some((word) => beat.source.includes(word))) issues.push({
      id: `E${String(issueIndex++).padStart(2, '0')}`, severity: 'soft',
      type: 'weak_action', targetId: beat.id, title: '缺少明确的可执行动作',
      detail: '当前内容主要描述心理或结果，没有给出单一、可拍摄的动作。',
      suggestion: `补充动作：${beat.action}`, resolved: false,
    });
  });

  const hardCount = issues.filter((issue) => issue.severity === 'hard').length;
  const softCount = issues.filter((issue) => issue.severity === 'soft').length;
  return {
    characters, beats, issues,
    score: Math.max(35, Math.min(98, 96 - hardCount * 18 - softCount * 5)),
    executionPrompt: buildExecutionPrompt(beats), analyzedAt: new Date().toISOString(),
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
