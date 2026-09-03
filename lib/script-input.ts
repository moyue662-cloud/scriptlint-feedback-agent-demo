export interface ScriptInputAssessment {
  kind: 'scene' | 'narrative';
  shouldAdaptFirst: boolean;
  reasons: string[];
}

const metaPitchPattern = /(?:完整版|全篇|爽点|逻辑闭环|层层|结局.*封神|四合一|故事梗概|小说设定|人物设定|世界观)/;
const expositionPattern = /(?:我叫|他是典型|她是典型|上古|残魂|入世|封印修为|主角|反派|人物弧光|背景设定)/;
const compressedTimelinePattern = /(?:多年后|三年后|数月后|毕业后|后来|最终|从那以后|与此同时)/g;
const sceneHeadingPattern = /^(?:(?:第\s*)?\d{1,3}\s*[场镜幕]|场景\s*\d+|(?:INT\.?|EXT\.?|内景|外景)[ .：:])/gim;
const dialogueLinePattern = /^\s*[\u4e00-\u9fa5A-Za-z0-9·]{1,8}\s*[：:]\s*[^\n]+/gm;

export function assessScriptInput(input: string): ScriptInputAssessment {
  const text = input.trim();
  if (!text) return { kind: 'scene', shouldAdaptFirst: false, reasons: [] };

  const sentenceCount = text.split(/[。！？!?\n]+/).filter((part) => part.trim()).length;
  const sceneHeadingCount = [...text.matchAll(sceneHeadingPattern)].length;
  const dialogueLineCount = [...text.matchAll(dialogueLinePattern)].length;
  const quotedDialogueCount = [...text.matchAll(/[“"]([^”"]{2,80})[”"]/g)].length;
  const timelineJumpCount = [...text.matchAll(compressedTimelinePattern)].length;
  const plusListCount = (text.match(/\s[+＋]\s/g) ?? []).length;
  const reasons: string[] = [];
  let narrativeScore = 0;

  if (metaPitchPattern.test(text)) {
    narrativeScore += 4;
    reasons.push('包含创作说明或梗概式宣传语');
  }
  if (expositionPattern.test(text)) {
    narrativeScore += 2;
    reasons.push('包含人物背景或世界观说明');
  }
  if (plusListCount >= 2) {
    narrativeScore += 2;
    reasons.push('使用多个情节标签串联内容');
  }
  if (timelineJumpCount >= 1) {
    narrativeScore += timelineJumpCount >= 2 ? 2 : 1;
    reasons.push('正文压缩了跨时间事件');
  }
  if (sentenceCount >= 7 && dialogueLineCount === 0 && quotedDialogueCount <= 1) {
    narrativeScore += 2;
    reasons.push('以叙述说明为主，缺少场景化对话');
  }
  if (sceneHeadingCount > 0 || dialogueLineCount >= 2 || quotedDialogueCount >= 3) narrativeScore -= 2;

  const shouldAdaptFirst = narrativeScore >= 3;
  return {
    kind: shouldAdaptFirst ? 'narrative' : 'scene',
    shouldAdaptFirst,
    reasons: shouldAdaptFirst ? reasons.slice(0, 3) : [],
  };
}
