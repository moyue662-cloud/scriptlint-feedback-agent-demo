import { hasExplicitSceneTransition, type EpisodeSummary, type StoredScene } from '@/lib/scene-state';

export type EpisodeReviewSeverity = 'hard' | 'soft';
export type EpisodeReviewStatus = 'ready' | 'attention' | 'blocked';

export interface EpisodeReviewIssue {
  id: string;
  severity: EpisodeReviewSeverity;
  title: string;
  detail: string;
  suggestion: string;
}

export interface EpisodeReviewCheck {
  id: 'objective' | 'conflict' | 'execution' | 'continuity';
  label: string;
  passed: boolean;
  detail: string;
}

export interface EpisodeReviewResult {
  episodeNumber: number;
  score: number;
  status: EpisodeReviewStatus;
  issues: EpisodeReviewIssue[];
  checks: EpisodeReviewCheck[];
  sceneCount: number;
  shotCount: number;
  reviewedShotCount: number;
  acceptedShotCount: number;
  continuityIssueCount: number;
}

function isMissingState(value: string) {
  const normalized = value.trim();
  return !normalized || normalized.includes('未建立') || normalized.includes('未明确');
}

function progressionSignature(scene: StoredScene) {
  return JSON.stringify({
    characters: scene.snapshot.characters.map((character) => [
      character.name, character.emotionalState, character.lastAction, [...character.knownFacts].sort(),
    ]),
    positions: scene.snapshot.characterPositions,
    gaze: scene.snapshot.gazeDirection,
    props: scene.snapshot.propState,
    space: scene.snapshot.spaceState,
    time: scene.snapshot.timeState,
  });
}

function hasExplainedTransition(scene: StoredScene) {
  return hasExplicitSceneTransition(scene.script, scene.transitionReason);
}

function describeCrossSceneMismatch(previous: StoredScene, current: StoredScene) {
  if (!current.openingState) return ['缺少下一场第一镜头的开始状态'];
  const fields = [
    ['人物站位', previous.snapshot.characterPositions, current.openingState.characterPositions],
    ['视线', previous.snapshot.gazeDirection, current.openingState.gazeDirection],
    ['道具', previous.snapshot.propState, current.openingState.propState],
    ['空间', previous.snapshot.spaceState, current.openingState.spaceState],
    ['时间', previous.snapshot.timeState, current.openingState.timeState],
  ] as const;
  return fields.filter(([, from, to]) => from.trim() !== to.trim()).map(([label, from, to]) => `${label}“${from}”→“${to}”`);
}

export function buildEpisodeReview(
  episodeNumber: number,
  scenes: StoredScene[],
  summary: EpisodeSummary | null,
): EpisodeReviewResult {
  const episodeScenes = scenes
    .filter((scene) => scene.episodeNumber === episodeNumber)
    .sort((a, b) => a.sceneOrder - b.sceneOrder || a.sceneNumber - b.sceneNumber);
  const issues: EpisodeReviewIssue[] = [];
  const shotCount = episodeScenes.reduce((total, scene) => total + scene.summary.shotCount, 0);
  const reviewedShotCount = episodeScenes.reduce((total, scene) => total + scene.summary.reviewedShotCount, 0);
  const acceptedShotCount = episodeScenes.reduce((total, scene) => total + scene.summary.acceptedShotCount, 0);
  const continuityIssueCount = episodeScenes.reduce((total, scene) => total + scene.summary.continuityIssueCount, 0);
  const crossSceneMismatches = episodeScenes.slice(1).flatMap((scene, index) => {
    const previous = episodeScenes[index];
    const mismatches = describeCrossSceneMismatch(previous, scene);
    return mismatches.length > 0 && !hasExplainedTransition(scene)
      ? [{ previous, scene, mismatches }]
      : [];
  });

  if (!summary?.title.trim()) {
    issues.push({
      id: 'missing-title', severity: 'soft', title: '缺少本集标题',
      detail: '本集还没有一个可识别的叙事标题。',
      suggestion: '补充一句能概括本集关键变化的标题。',
    });
  }
  if (!summary?.objective.trim()) {
    issues.push({
      id: 'missing-objective', severity: 'hard', title: '本集戏剧目标未定义',
      detail: '系统无法判断各场是否共同推进同一个结果。',
      suggestion: '明确本集结束时人物、关系或信息必须发生的变化。',
    });
  }
  if (!summary?.conflict.trim()) {
    issues.push({
      id: 'missing-conflict', severity: 'hard', title: '核心冲突未定义',
      detail: '缺少贯穿本集的阻力，容易出现有对话但没有推进。',
      suggestion: '写清谁想得到什么、谁或什么在阻止，以及本集必须升级到哪一步。',
    });
  }
  if (episodeScenes.length === 0) {
    issues.push({
      id: 'missing-scenes', severity: 'hard', title: '本集还没有场次',
      detail: '没有可用于验证目标、冲突和连续性的场次。',
      suggestion: '至少完成并保存一个场次后再进行整集审查。',
    });
  }

  const scenesWithoutShots = episodeScenes.filter((scene) => scene.summary.shotCount === 0);
  if (scenesWithoutShots.length > 0) {
    issues.push({
      id: 'missing-shots', severity: 'hard', title: `${scenesWithoutShots.length} 场缺少可执行分镜`,
      detail: `第 ${scenesWithoutShots.map((scene) => scene.sceneOrder).join('、')} 场无法进入视频制作。`,
      suggestion: '重新运行这些场次的分镜生成与连续性修复。',
    });
  }
  if (continuityIssueCount > 0) {
    issues.push({
      id: 'continuity-open', severity: 'hard', title: `仍有 ${continuityIssueCount} 项连续性问题`,
      detail: '人物、道具、空间或镜头状态尚未完全闭合。',
      suggestion: '逐场修复连续性问题后重新保存场次状态。',
    });
  }
  if (shotCount > reviewedShotCount) {
    issues.push({
      id: 'human-review-incomplete', severity: 'hard', title: `${shotCount - reviewedShotCount} 个镜头尚未完成人工审阅`,
      detail: `本集已人工确认 ${reviewedShotCount}/${shotCount} 个镜头，未确认镜头不能进入最终交付。`,
      suggestion: '逐场载入分镜，核对动作、台词、状态和视频Prompt后确认镜头。',
    });
  }
  crossSceneMismatches.forEach(({ previous, scene, mismatches }, index) => {
    issues.push({
      id: `cross-scene-${index + 1}`, severity: 'hard', title: `“${previous.title}”到“${scene.title}”衔接状态突变`,
      detail: `${mismatches.join('；')}，但下一场剧本或首镜头没有说明可见转场。`,
      suggestion: '让下一场第一镜头继承上一场结束状态；若确实经过时间或地点变化，请在剧本与首镜头转场理由中明确写出。',
    });
  });

  const incompleteStateScenes = episodeScenes.filter((scene) => [
    scene.snapshot.characterPositions,
    scene.snapshot.gazeDirection,
    scene.snapshot.propState,
    scene.snapshot.spaceState,
    scene.snapshot.timeState,
  ].some(isMissingState));
  if (incompleteStateScenes.length > 0) {
    issues.push({
      id: 'state-incomplete', severity: 'hard', title: `${incompleteStateScenes.length} 场结束状态不完整`,
      detail: `第 ${incompleteStateScenes.map((scene) => scene.sceneOrder).join('、')} 场缺少站位、视线、道具、空间或时间状态。`,
      suggestion: '补齐可见状态后再建立下一场继承关系。',
    });
  }

  const duplicateTitles = Array.from(new Set(episodeScenes
    .map((scene) => scene.title.trim())
    .filter((title, index, titles) => title && titles.indexOf(title) !== index)));
  if (duplicateTitles.length > 0) {
    issues.push({
      id: 'duplicate-titles', severity: 'soft', title: '存在重复场次标题',
      detail: `重复标题：${duplicateTitles.join('、')}。`,
      suggestion: '用“地点 + 核心动作或转折”区分场次，降低制作沟通歧义。',
    });
  }

  const unchangedTransitions = episodeScenes.slice(1).filter((scene, index) => (
    progressionSignature(scene) === progressionSignature(episodeScenes[index])
  ));
  if (unchangedTransitions.length > 0) {
    issues.push({
      id: 'weak-progression', severity: 'soft', title: `${unchangedTransitions.length} 处场间状态没有明显变化`,
      detail: `进入第 ${unchangedTransitions.map((scene) => scene.sceneOrder).join('、')} 场前后，人物、道具和空间状态完全相同。`,
      suggestion: '确认这些场是否真的推进了人物立场、信息差或冲突强度；必要时合并场次或补充可见变化。',
    });
  }

  if (shotCount > acceptedShotCount) {
    issues.push({
      id: 'production-incomplete', severity: 'soft', title: `${shotCount - acceptedShotCount} 个镜头尚未验收`,
      detail: `本集已验收 ${acceptedShotCount}/${shotCount} 个镜头。`,
      suggestion: '完成镜头提交与人工验收后再标记整集可交付。',
    });
  }

  const hardIssueCount = issues.filter((issue) => issue.severity === 'hard').length;
  const softIssueCount = issues.length - hardIssueCount;
  const score = Math.max(0, 100 - hardIssueCount * 18 - softIssueCount * 6);
  const checks: EpisodeReviewCheck[] = [
    {
      id: 'objective', label: '戏剧目标', passed: Boolean(summary?.objective.trim()),
      detail: summary?.objective.trim() || '尚未定义本集必须发生的变化',
    },
    {
      id: 'conflict', label: '冲突推进', passed: Boolean(summary?.conflict.trim()) && unchangedTransitions.length === 0,
      detail: !summary?.conflict.trim() ? '尚未定义主要阻力和升级方向' : unchangedTransitions.length > 0 ? `${unchangedTransitions.length} 处场间状态没有明显变化` : summary.conflict.trim(),
    },
    {
      id: 'execution', label: '场次可执行', passed: episodeScenes.length > 0 && scenesWithoutShots.length === 0 && reviewedShotCount === shotCount,
      detail: episodeScenes.length > 0 ? `${episodeScenes.length - scenesWithoutShots.length}/${episodeScenes.length} 场已有分镜，人工确认 ${reviewedShotCount}/${shotCount} 镜` : '尚无场次',
    },
    {
      id: 'continuity', label: '连续性闭合', passed: continuityIssueCount === 0 && incompleteStateScenes.length === 0 && crossSceneMismatches.length === 0 && episodeScenes.length > 0,
      detail: continuityIssueCount === 0 && incompleteStateScenes.length === 0 && crossSceneMismatches.length === 0
        ? '镜内与跨场状态均已闭合'
        : `${continuityIssueCount} 项镜内待修，${crossSceneMismatches.length} 处跨场突变，${incompleteStateScenes.length} 场状态不完整`,
    },
  ];

  return {
    episodeNumber,
    score,
    status: hardIssueCount > 0 ? 'blocked' : softIssueCount > 0 ? 'attention' : 'ready',
    issues,
    checks,
    sceneCount: episodeScenes.length,
    shotCount,
    reviewedShotCount,
    acceptedShotCount,
    continuityIssueCount,
  };
}
