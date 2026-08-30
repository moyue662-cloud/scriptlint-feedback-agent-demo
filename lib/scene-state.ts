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

export interface StoredScene {
  id: string;
  sceneNumber: number;
  title: string;
  script: string;
  snapshot: SceneSnapshot;
  createdAt: string;
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
    previousSceneNumber: scene.sceneNumber,
    previousSceneTitle: scene.title,
    rule: '以下是上一场结束时的确定状态。新场景必须默认继承；只有剧本明确描述时间流逝、移动、交接或状态变化时才能改变。',
    snapshot: scene.snapshot,
  };
}
