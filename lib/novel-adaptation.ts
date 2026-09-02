import type { ImportedSceneDraft } from '@/lib/batch-import';

export interface NovelAdaptationResult {
  theme: string;
  logline: string;
  characters: string[];
  retainedPlotPoints: string[];
  omittedContent: string[];
  scenes: ImportedSceneDraft[];
  estimatedTotalDurationSec: number;
  source: 'ai';
}

export interface RawNovelAdaptation {
  theme: string;
  logline: string;
  characters: string[];
  retainedPlotPoints: string[];
  omittedContent: string[];
  scenes: Array<{
    title: string;
    narrativeRole: string;
    script: string;
    estimatedDurationSec: number;
    retainedHighlights: string[];
  }>;
}

const cleanText = (value: unknown, fallback = '') => typeof value === 'string' ? value.trim() : fallback;
const cleanList = (value: unknown, limit: number) => Array.isArray(value)
  ? value.map((item) => cleanText(item)).filter(Boolean).slice(0, limit)
  : [];

export function normalizeNovelAdaptation(raw: RawNovelAdaptation, episodeNumber = 1): NovelAdaptationResult {
  const normalizedEpisode = Math.max(1, Math.min(999, Math.round(Number(episodeNumber) || 1)));
  const rawScenes = Array.isArray(raw?.scenes) ? raw.scenes : [];
  const scenes = rawScenes
    .map((scene, index): ImportedSceneDraft | null => {
      const script = cleanText(scene?.script);
      if (script.length < 40) return null;
      return {
        episodeNumber: normalizedEpisode,
        title: cleanText(scene?.title, `改编场景 ${index + 1}`).slice(0, 80),
        script,
        splitReason: 'adapted',
        estimatedDurationSec: Math.max(20, Math.min(120, Math.round(Number(scene?.estimatedDurationSec) || 45))),
        narrativeRole: cleanText(scene?.narrativeRole, '情节推进').slice(0, 24),
        retainedHighlights: cleanList(scene?.retainedHighlights, 4),
      };
    })
    .filter((scene): scene is ImportedSceneDraft => Boolean(scene))
    .slice(0, 16);

  if (scenes.length < 2) throw new Error('模型返回的完整场景不足，请重新运行改编。');

  return {
    theme: cleanText(raw?.theme, '待人工确认主题'),
    logline: cleanText(raw?.logline, '待人工确认一句话主线'),
    characters: cleanList(raw?.characters, 12),
    retainedPlotPoints: cleanList(raw?.retainedPlotPoints, 10),
    omittedContent: cleanList(raw?.omittedContent, 10),
    scenes,
    estimatedTotalDurationSec: scenes.reduce((total, scene) => total + (scene.estimatedDurationSec ?? 0), 0),
    source: 'ai',
  };
}
