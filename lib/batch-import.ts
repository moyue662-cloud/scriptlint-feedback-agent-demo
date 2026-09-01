export interface ImportedSceneDraft {
  episodeNumber: number;
  title: string;
  script: string;
  splitReason?: 'heading' | 'paragraph' | 'length';
}

const headingPattern = /^(?:(?:第\s*)?(\d{1,3})\s*[场镜幕](?:\s+.*)?|场景\s*(\d{1,3})(?:\s+.*)?|场次\s*(\d{1,3})(?:\s+.*)?|(?:INT\.?|EXT\.?)(?:[ .：:].*)|(?:内景|外景)[：:].*)$/i;

function cleanTitle(line: string, index: number) {
  const text = line.trim().replace(/^[#*\-\s]+/, '').replace(/[：:]\s*$/, '').trim();
  return text.slice(0, 80) || `场次 ${index + 1}`;
}

function pushDraft(drafts: ImportedSceneDraft[], lines: string[], title: string | null, episodeNumber: number, splitReason: ImportedSceneDraft['splitReason'] = 'heading') {
  const script = lines.join('\n').trim();
  if (!script) return;
  drafts.push({ episodeNumber, title: title || `场次 ${drafts.length + 1}`, script, splitReason });
}

function splitLongBlock(input: string, episodeNumber: number) {
  const units = input.match(/[^。！？!?\n]+(?:[。！？!?][”"'’』】）]?|(?=\n)|$)/g)
    ?.map((unit) => unit.trim()).filter(Boolean) ?? [input];
  const chunks: string[] = [];
  let current: string[] = [];
  let currentLength = 0;
  const targetLength = 1800;
  const targetUnits = 18;
  units.forEach((unit) => {
    if (current.length > 0 && (currentLength >= targetLength || current.length >= targetUnits)) {
      chunks.push(current.join(''));
      current = [];
      currentLength = 0;
    }
    const nextLength = currentLength + unit.length + (current.length ? 1 : 0);
    current.push(unit);
    currentLength = nextLength;
  });
  if (current.length > 0) chunks.push(current.join(''));
  return chunks.slice(0, 80).map((script, index) => ({
    episodeNumber,
    title: `分段建议 ${index + 1}`,
    script,
    splitReason: 'length' as const,
  }));
}

export function splitScriptIntoScenes(input: string, episodeNumber = 1): ImportedSceneDraft[] {
  const normalized = input.replace(/\r\n?/g, '\n').trim();
  if (!normalized) return [];
  const lines = normalized.split('\n');
  const drafts: ImportedSceneDraft[] = [];
  let currentLines: string[] = [];
  let currentTitle: string | null = null;
  const currentEpisode = Math.max(1, Math.min(999, Math.round(Number(episodeNumber) || 1)));

  for (const rawLine of lines) {
    const line = rawLine.trim();
    const heading = headingPattern.exec(line.replace(/^#+\s*/, ''));
    if (heading) {
      pushDraft(drafts, currentLines, currentTitle, currentEpisode, 'heading');
      currentLines = [];
      currentTitle = cleanTitle(line, drafts.length);
      continue;
    }
    currentLines.push(rawLine);
  }
  pushDraft(drafts, currentLines, currentTitle, currentEpisode, 'heading');

  if (drafts.length > 1) return drafts.slice(0, 80);
  const blocks = normalized.split(/\n\s*\n\s*\n+/).map((block) => block.trim()).filter(Boolean);
  if (blocks.length > 1) {
    return blocks.slice(0, 80).map((script, index) => ({ episodeNumber, title: `分段建议 ${index + 1}`, script, splitReason: 'paragraph' as const }));
  }
  if (normalized.length > 6000 || normalized.split(/[。！？!?]/).filter(Boolean).length > 30) {
    return splitLongBlock(normalized, currentEpisode);
  }
  return drafts;
}
