import type { AnalysisResult } from '@/lib/script-engine';
import type { StoryboardResult } from '@/lib/storyboard-engine';

export interface CharacterSceneState {
  name: string;
  emotionalState: string;
  lastAction: string;
  lastDialogue: string;
  knownFacts: string[];
}

export interface SceneSnapshot {
  characters: CharacterSceneState[];
  characterPositions: string;
  gazeDirection: string;
  propState: string;
  spaceState: string;
  timeState: string;
}

export type DeliveryShotStatus = 'pending' | 'submitted' | 'accepted';

export interface DeliveryTrackingState {
  statuses: Record<string, DeliveryShotStatus>;
  updatedAt: string | null;
}

export type SceneProductionStatus = 'ready' | 'needs-review' | 'in-production' | 'completed';

export interface SceneProductionSummary {
  shotCount: number;
  durationSec: number;
  continuityIssueCount: number;
  submittedShotCount: number;
  acceptedShotCount: number;
  productionProgress: number;
  status: SceneProductionStatus;
}

export const DEFAULT_PROJECT_ID = 'default';

export interface SceneProject {
  id: string;
  name: string;
  approvedAt: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface EpisodeSummary {
  projectId: string;
  episodeNumber: number;
  title: string;
  objective: string;
  conflict: string;
  notes: string;
  updatedAt: string;
}

export interface StoredScene {
  id: string;
  projectId: string;
  sceneNumber: number;
  episodeNumber: number;
  sceneOrder: number;
  title: string;
  script: string;
  snapshot: SceneSnapshot;
  deliveryTracking: DeliveryTrackingState;
  summary: SceneProductionSummary;
  createdAt: string;
}

export interface StoredSceneDetail extends StoredScene {
  analysis: AnalysisResult;
  storyboard: StoryboardResult;
}

export function buildSceneProductionSummary(
  storyboard: StoryboardResult | null,
  deliveryTracking: DeliveryTrackingState,
): SceneProductionSummary {
  const shots = storyboard?.shots ?? [];
  const shotCount = shots.length;
  const submittedShotCount = shots.filter((shot) => {
    const status = deliveryTracking.statuses[shot.id];
    return status === 'submitted' || status === 'accepted';
  }).length;
  const acceptedShotCount = shots.filter((shot) => deliveryTracking.statuses[shot.id] === 'accepted').length;
  const continuityIssueCount = storyboard?.issues.filter((issue) => !issue.resolved).length ?? 0;
  const productionProgress = shotCount > 0 ? Math.round((acceptedShotCount / shotCount) * 100) : 0;
  const status: SceneProductionStatus = continuityIssueCount > 0
    ? 'needs-review'
    : shotCount > 0 && acceptedShotCount === shotCount
      ? 'completed'
      : submittedShotCount > 0
        ? 'in-production'
        : 'ready';

  return {
    shotCount,
    durationSec: shots.reduce((total, shot) => total + Math.max(0, Number(shot.durationSec) || 0), 0),
    continuityIssueCount,
    submittedShotCount,
    acceptedShotCount,
    productionProgress,
    status,
  };
}

export function buildSceneSnapshot(analysis: AnalysisResult, storyboard: StoryboardResult): SceneSnapshot {
  const finalShot = storyboard.shots.at(-1);
  const characters = analysis.characters.map((name) => {
    const involved = analysis.beats.filter((beat) => beat.actor === name || beat.receiver === name);
    const lastActingBeat = [...involved].reverse().find((beat) => beat.actor === name);
    const lastReceivingBeat = [...involved].reverse().find((beat) => beat.receiver === name);
    const knownFacts = involved
      .flatMap((beat) => [beat.trigger, beat.source])
      .map((fact) => fact.trim())
      .filter(Boolean)
      .filter((fact, index, all) => all.indexOf(fact) === index)
      .slice(-8);

    return {
      name,
      emotionalState: lastActingBeat?.stateAfter ?? lastReceivingBeat?.stateAfter ?? '未明确',
      lastAction: lastActingBeat?.action ?? lastReceivingBeat?.reaction ?? '保持上一状态',
      lastDialogue: lastActingBeat?.dialogue || lastReceivingBeat?.response || '无台词',
      knownFacts,
    };
  });

  return {
    characters,
    characterPositions: finalShot?.endState.characterPositions ?? '未建立',
    gazeDirection: finalShot?.endState.gazeDirection ?? '未建立',
    propState: finalShot?.endState.propState ?? '未建立',
    spaceState: finalShot?.endState.spaceState ?? '未建立',
    timeState: finalShot?.endState.timeState ?? '未建立',
  };
}

export function sceneContinuityContext(scene: StoredScene) {
  return {
    previousEpisodeNumber: scene.episodeNumber,
    previousSceneNumber: scene.sceneOrder,
    previousSceneTitle: scene.title,
    rule: '以下是上一场结束时的确定状态。新场景必须默认继承；只有剧本明确描述时间流逝、移动、交接或状态变化时才能改变。',
    snapshot: scene.snapshot,
  };
}
