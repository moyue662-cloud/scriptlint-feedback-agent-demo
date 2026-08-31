export interface ImportedSceneDraft {
  episodeNumber: number;
  title: string;
  script: string;
}

const headingPattern = /^(?:(?:第\s*)?(\d{1,3})\s*[场镜幕](?:\s+.*)?|场景\s*(\d{1,3})(?:\s+.*)?|场次\s*(\d{1,3})(?:\s+.*)?|(?:INT\.?|EXT\.?)(?:[ .：:].*)|(?:内景|外景)[：:].*)$/i;

function cleanTitle(line: string, index: number) {
  const text = line.trim().replace(/^[#*\-\s]+/, '').replace(/[：:]\s*$/, '').trim();
  return text.slice(0, 80) || `场次 ${index + 1}`;
}

function pushDraft(drafts: ImportedSceneDraft[], lines: string[], title: string | null, episodeNumber: number) {
  const script = lines.join('\n').trim();
  if (!script) return;
  drafts.push({ episodeNumber, title: title || `场次 ${drafts.length + 1}`, script });
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
      pushDraft(drafts, currentLines, currentTitle, currentEpisode);
      currentLines = [];
      currentTitle = cleanTitle(line, drafts.length);
      continue;
    }
    currentLines.push(rawLine);
  }
  pushDraft(drafts, currentLines, currentTitle, currentEpisode);

  if (drafts.length > 1) return drafts.slice(0, 80);
  const blocks = normalized.split(/\n\s*\n\s*\n+/).map((block) => block.trim()).filter(Boolean);
  if (blocks.length > 1) {
    return blocks.slice(0, 80).map((script, index) => ({ episodeNumber, title: `场次 ${index + 1}`, script }));
  }
  return drafts;
}
