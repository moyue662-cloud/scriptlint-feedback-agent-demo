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

export interface AdaptationCompileContext {
  theme: string;
  logline: string;
  globalCharacters: string[];
  currentScene: {
    title: string;
    narrativeRole?: string;
    retainedHighlights: string[];
    appearingCharacters: string[];
    factsToEstablish: string[];
    timeMarker?: string;
  };
  priorScenes: Array<{
    title: string;
    retainedHighlights: string[];
    establishedFacts: string[];
    timeMarker?: string;
  }>;
}

export function buildAdaptationCompileContext(
  adaptation: NovelAdaptationResult | null,
  draft: ImportedSceneDraft,
): AdaptationCompileContext | null {
  if (!adaptation) return null;
  const sceneIndex = adaptation.scenes.findIndex((scene) => scene === draft || (scene.title === draft.title && scene.script === draft.script));
  if (sceneIndex < 0) return null;
  return {
    theme: adaptation.theme,
    logline: adaptation.logline,
    globalCharacters: adaptation.characters,
    currentScene: {
      title: draft.title,
      narrativeRole: draft.narrativeRole,
      retainedHighlights: draft.retainedHighlights ?? [],
      appearingCharacters: draft.appearingCharacters ?? [],
      factsToEstablish: draft.establishedFacts ?? [],
      timeMarker: draft.timeMarker,
    },
    priorScenes: adaptation.scenes.slice(Math.max(0, sceneIndex - 5), sceneIndex).map((scene) => ({
      title: scene.title,
      retainedHighlights: scene.retainedHighlights ?? [],
      establishedFacts: scene.establishedFacts ?? [],
      timeMarker: scene.timeMarker,
    })),
  };
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
    appearingCharacters: string[];
    establishedFacts: string[];
    timeMarker: string;
  }>;
}

const cleanText = (value: unknown, fallback = '') => typeof value === 'string' ? value.trim() : fallback;
const cleanList = (value: unknown, limit: number) => Array.isArray(value)
  ? value.map((item) => cleanText(item)).filter(Boolean).slice(0, limit)
  : [];

const MIN_ADAPTED_SCENE_CHARS = 60;

function mergeUnique(left: string[] = [], right: string[] = [], limit: number) {
  return [...new Set([...left, ...right])].slice(0, limit);
}

function mergeAdaptedScenes(left: ImportedSceneDraft, right: ImportedSceneDraft): ImportedSceneDraft {
  const title = left.title === right.title ? left.title : `${left.title} / ${right.title}`.slice(0, 80);
  return {
    ...left,
    title,
    script: `${left.script}\n${right.script}`.trim(),
    estimatedDurationSec: Math.min(120, (left.estimatedDurationSec ?? 20) + (right.estimatedDurationSec ?? 20)),
    narrativeRole: right.narrativeRole === '高潮' || right.narrativeRole === '反转'
      ? right.narrativeRole
      : left.narrativeRole || right.narrativeRole,
    retainedHighlights: mergeUnique(left.retainedHighlights, right.retainedHighlights, 4),
    appearingCharacters: mergeUnique(left.appearingCharacters, right.appearingCharacters, 8),
    establishedFacts: mergeUnique(left.establishedFacts, right.establishedFacts, 6),
    timeMarker: left.timeMarker || right.timeMarker,
  };
}

/**
 * Models sometimes return outline fragments as scenes. Merge those fragments
 * deterministically so one draft remains a complete multi-shot event instead
 * of becoming a three-to-five-second video clip.
 */
function mergeShortAdaptedScenes(input: ImportedSceneDraft[]) {
  const scenes: ImportedSceneDraft[] = [];
  let pending: ImportedSceneDraft | null = null;

  for (const original of input) {
    let scene = original;
    if (pending) {
      scene = mergeAdaptedScenes(pending, scene);
      pending = null;
    }
    if (scene.script.replace(/\s/g, '').length < MIN_ADAPTED_SCENE_CHARS) {
      if (scenes.length > 0) scenes[scenes.length - 1] = mergeAdaptedScenes(scenes.at(-1)!, scene);
      else pending = scene;
      continue;
    }
    scenes.push(scene);
  }

  if (pending) {
    if (scenes.length > 0) scenes[scenes.length - 1] = mergeAdaptedScenes(scenes.at(-1)!, pending);
    else scenes.push(pending);
  }
  return scenes;
}

export function normalizeNovelAdaptation(raw: RawNovelAdaptation, episodeNumber = 1): NovelAdaptationResult {
  const normalizedEpisode = Math.max(1, Math.min(999, Math.round(Number(episodeNumber) || 1)));
  const rawScenes = Array.isArray(raw?.scenes) ? raw.scenes : [];
  const normalizedScenes = rawScenes
    .map((scene, index): ImportedSceneDraft | null => {
      const rawScript = cleanText(scene?.script);
      if (!rawScript) return null;
      const timeMarker = cleanText(scene?.timeMarker).slice(0, 40);
      const script = timeMarker && !rawScript.slice(0, 50).includes(timeMarker)
        ? `${timeMarker}。\n${rawScript}`
        : rawScript;
      return {
        episodeNumber: normalizedEpisode,
        title: cleanText(scene?.title, `改编场景 ${index + 1}`).slice(0, 80),
        script,
        splitReason: 'adapted',
        estimatedDurationSec: Math.max(20, Math.min(120, Math.round(Number(scene?.estimatedDurationSec) || 45))),
        narrativeRole: cleanText(scene?.narrativeRole, '情节推进').slice(0, 24),
        retainedHighlights: cleanList(scene?.retainedHighlights, 4),
        appearingCharacters: cleanList(scene?.appearingCharacters, 8),
        establishedFacts: cleanList(scene?.establishedFacts, 6),
        timeMarker: timeMarker || undefined,
      };
    })
    .filter((scene): scene is ImportedSceneDraft => Boolean(scene))
    .slice(0, 16);

  const scenes = mergeShortAdaptedScenes(normalizedScenes);

  if (scenes.length < 2) throw new Error('模型返回的完整场景不足，请重新运行改编。');
  if (scenes.some((scene) => scene.script.replace(/\s/g, '').length < MIN_ADAPTED_SCENE_CHARS)) {
    throw new Error('模型返回了过短的场景片段，请重新运行改编。');
  }

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
