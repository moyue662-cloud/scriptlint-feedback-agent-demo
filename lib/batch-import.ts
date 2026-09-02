export interface ImportedSceneDraft {
  episodeNumber: number;
  title: string;
  script: string;
  splitReason?: 'heading' | 'grouped' | 'length' | 'adapted';
  estimatedDurationSec?: number;
  narrativeRole?: string;
  retainedHighlights?: string[];
}

const headingPattern = /^(?:(?:第\s*)?(\d{1,3})\s*[场镜幕](?:(?:\s*[:：\-—]\s*|\s+).*)?|场景\s*(\d{1,3})(?:(?:\s*[:：\-—]\s*|\s+).*)?|场次\s*(\d{1,3})(?:(?:\s*[:：\-—]\s*|\s+).*)?|(?:INT\.?|EXT\.?)(?:[ .：:].*)|(?:内景|外景)[：:].*)$/i;
const narrativeBoundaryPattern = /^(?:第[一二三四五六七八九十百\d]+[章节幕]|[一二三四五六七八九十]+、|终章|尾声|序章|翌日|第二天|数日后|多年后|三年后|与此同时|就在这时|突然|最终|后来|从那天起|保研|考公)/;
const TARGET_GROUP_LENGTH = 620;
const MIN_GROUP_LENGTH = 260;
const MAX_GROUP_LENGTH = 980;
const MAX_DRAFTS = 24;

function cleanTitle(line: string, index: number) {
  const text = line.trim().replace(/^[#*\-\s]+/, '').replace(/[：:]\s*$/, '').trim();
  return text.slice(0, 80) || `场次 ${index + 1}`;
}

function estimateDuration(script: string) {
  const dialogueChars = [...script.matchAll(/[“"]([^”"]+)[”"]/g)]
    .reduce((total, match) => total + (match[1]?.length ?? 0), 0);
  const actionChars = Math.max(0, script.length - dialogueChars);
  return Math.max(20, Math.min(120, Math.round(dialogueChars / 3.6 + actionChars / 7.5)));
}

function pushDraft(drafts: ImportedSceneDraft[], lines: string[], title: string | null, episodeNumber: number, splitReason: ImportedSceneDraft['splitReason'] = 'heading') {
  const script = lines.join('\n').trim();
  if (!script) return;
  drafts.push({
    episodeNumber,
    title: title || `场次 ${drafts.length + 1}`,
    script,
    splitReason,
    estimatedDurationSec: estimateDuration(script),
  });
}

function sentenceUnits(input: string) {
  return input.match(/[^。！？!?\n]+(?:[。！？!?][”"'’』】）]?|(?=\n)|$)/g)
    ?.map((unit) => unit.trim()).filter(Boolean) ?? [input];
}

function narrativeUnits(input: string) {
  const blocks = input.split(/\n\s*\n+/).map((block) => block.trim()).filter(Boolean);
  if (blocks.length > 1) return blocks;
  return sentenceUnits(input);
}

function hardSliceUnit(unit: string) {
  const parts: string[] = [];
  let remaining = unit;
  while (remaining.length > MAX_GROUP_LENGTH) {
    const candidate = remaining.slice(0, MAX_GROUP_LENGTH);
    const punctuationIndex = Math.max(candidate.lastIndexOf('。'), candidate.lastIndexOf('！'), candidate.lastIndexOf('？'));
    const splitAt = punctuationIndex >= MIN_GROUP_LENGTH ? punctuationIndex + 1 : MAX_GROUP_LENGTH;
    parts.push(remaining.slice(0, splitAt).trim());
    remaining = remaining.slice(splitAt).trim();
  }
  if (remaining) parts.push(remaining);
  return parts;
}

function groupNarrativeInput(input: string, episodeNumber: number) {
  const units = narrativeUnits(input).flatMap(hardSliceUnit);
  const groups: string[][] = [];
  let current: string[] = [];
  let currentLength = 0;

  const flush = () => {
    if (!current.length) return;
    groups.push(current);
    current = [];
    currentLength = 0;
  };

  for (const unit of units) {
    const startsNewEvent = narrativeBoundaryPattern.test(unit);
    const wouldOverflow = currentLength + unit.length > MAX_GROUP_LENGTH;
    const reachedTarget = currentLength >= TARGET_GROUP_LENGTH;
    if (current.length > 0 && currentLength >= MIN_GROUP_LENGTH && (startsNewEvent || wouldOverflow || reachedTarget)) flush();
    current.push(unit);
    currentLength += unit.length + 1;
  }
  flush();

  if (groups.length > 1 && groups.at(-1)!.join('\n\n').length < MIN_GROUP_LENGTH) {
    const tail = groups.pop()!;
    groups.at(-1)!.push(...tail);
  }

  return groups.slice(0, MAX_DRAFTS).map((group, index) => {
    const script = group.join('\n\n').trim();
    return {
      episodeNumber,
      title: `场景建议 ${index + 1}`,
      script,
      splitReason: 'grouped' as const,
      estimatedDurationSec: estimateDuration(script),
    };
  });
}

export function splitScriptIntoScenes(input: string, episodeNumber = 1): ImportedSceneDraft[] {
  const normalized = input.replace(/\r\n?/g, '\n').trim();
  if (!normalized) return [];
  const lines = normalized.split('\n');
  const drafts: ImportedSceneDraft[] = [];
  let currentLines: string[] = [];
  let currentTitle: string | null = null;
  let headingCount = 0;
  const currentEpisode = Math.max(1, Math.min(999, Math.round(Number(episodeNumber) || 1)));

  for (const rawLine of lines) {
    const line = rawLine.trim();
    const heading = headingPattern.exec(line.replace(/^#+\s*/, ''));
    if (heading) {
      headingCount += 1;
      pushDraft(drafts, currentLines, currentTitle, currentEpisode, 'heading');
      currentLines = [];
      currentTitle = cleanTitle(line, drafts.length);
      continue;
    }
    currentLines.push(rawLine);
  }
  pushDraft(drafts, currentLines, currentTitle, currentEpisode, 'heading');

  if (headingCount > 0 && drafts.length > 1) return drafts.slice(0, MAX_DRAFTS);
  const structuralUnits = normalized.split(/\n\s*\n+/).filter((block) => block.trim()).length;
  const sentenceCount = normalized.split(/[。！？!?]/).filter(Boolean).length;
  if (normalized.length > 1200 || structuralUnits > 4 || sentenceCount > 12) {
    return groupNarrativeInput(normalized, currentEpisode);
  }
  return drafts;
}
