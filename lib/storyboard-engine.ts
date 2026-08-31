import type { AnalysisResult, Severity } from '@/lib/script-engine';

export type ContinuityIssueType =
  | 'beat_coverage'
  | 'character_position'
  | 'gaze_direction'
  | 'prop_state'
  | 'space_state'
  | 'time_state'
  | 'shot_density'
  | 'shot_identity';

export interface ShotState {
  characterPositions: string;
  gazeDirection: string;
  propState: string;
  spaceState: string;
  timeState: string;
}

export interface StoryboardShot {
  id: string;
  beatId: string;
  durationSec: number;
  shotSize: string;
  cameraAngle: string;
  cameraMovement: string;
  focus: string;
  action: string;
  dialogue: string;
  sound: string;
  transition: string;
  startState: ShotState;
  endState: ShotState;
  continuityReason: string;
  videoPrompt: string;
}

export interface ContinuityIssue {
  id: string;
  severity: Severity;
  type: ContinuityIssueType;
  fromShotId: string;
  toShotId: string;
  detail: string;
  suggestion: string;
  resolved: boolean;
}

export interface StoryboardResult {
  shots: StoryboardShot[];
  issues: ContinuityIssue[];
  continuityScore: number;
  totalDurationSec: number;
  modelPrompt: string;
  generatedAt: string;
}

export interface StoryboardRepairScope {
  editableShotIds: string[];
  lockedShotIds: string[];
  editableBeatIds: string[];
}

export function getStoryboardBudget(analysis: AnalysisResult) {
  const beatCount = Math.max(1, analysis.beats.length);
  return {
    maxShots: Math.max(beatCount, Math.min(12, beatCount * 2)),
    maxDurationSec: Math.max(18, Math.min(90, beatCount * 10)),
  };
}

const stateChecks: Array<{
  key: keyof ShotState;
  type: ContinuityIssueType;
  label: string;
  severity: Severity;
}> = [
  { key: 'characterPositions', type: 'character_position', label: '人物站位', severity: 'hard' },
  { key: 'gazeDirection', type: 'gaze_direction', label: '视线方向', severity: 'soft' },
  { key: 'propState', type: 'prop_state', label: '道具状态', severity: 'hard' },
  { key: 'spaceState', type: 'space_state', label: '空间关系', severity: 'hard' },
  { key: 'timeState', type: 'time_state', label: '时间状态', severity: 'hard' },
];

export function getStoryboardRepairScope(current: StoryboardResult): StoryboardRepairScope {
  const activeIssues = current.issues.filter((issue) => !issue.resolved);
  const shotIndex = new Map(current.shots.map((shot, index) => [shot.id, index]));
  const editableIndexes = new Set<number>();
  const editableBeatIds = new Set<string>();

  activeIssues.forEach((issue) => {
    [issue.fromShotId, issue.toShotId].forEach((id) => {
      const index = shotIndex.get(id);
      if (index === undefined) {
        if (issue.type === 'beat_coverage') editableBeatIds.add(id);
        return;
      }
      for (let neighbor = Math.max(0, index - 1); neighbor <= Math.min(current.shots.length - 1, index + 1); neighbor += 1) {
        editableIndexes.add(neighbor);
        editableBeatIds.add(current.shots[neighbor].beatId);
      }
    });
  });

  return {
    editableShotIds: current.shots.filter((_, index) => editableIndexes.has(index)).map((shot) => shot.id),
    lockedShotIds: current.shots.filter((_, index) => !editableIndexes.has(index)).map((shot) => shot.id),
    editableBeatIds: [...editableBeatIds],
  };
}

export function enforceStoryboardRepairScope(
  current: StoryboardResult,
  candidate: Omit<StoryboardResult, 'generatedAt' | 'totalDurationSec' | 'continuityScore'>,
  scope: StoryboardRepairScope,
) {
  const editableIds = new Set(scope.editableShotIds);
  const editableBeatIds = new Set(scope.editableBeatIds);
  const currentIds = new Set(current.shots.map((shot) => shot.id));
  const candidateById = new Map(candidate.shots.map((shot) => [shot.id, shot]));
  const extraByBeat = new Map<string, StoryboardShot[]>();

  candidate.shots.forEach((shot) => {
    if (currentIds.has(shot.id) || !editableBeatIds.has(shot.beatId)) return;
    const extras = extraByBeat.get(shot.beatId) ?? [];
    extras.push(shot);
    extraByBeat.set(shot.beatId, extras);
  });

  let shots: StoryboardShot[] = [];
  current.shots.forEach((shot, index) => {
    const replacement = editableIds.has(shot.id) ? candidateById.get(shot.id) : shot;
    if (replacement) shots.push(replacement);
    const isLastShotForBeat = current.shots[index + 1]?.beatId !== shot.beatId;
    if (isLastShotForBeat && editableBeatIds.has(shot.beatId)) {
      shots.push(...(extraByBeat.get(shot.beatId) ?? []));
      extraByBeat.delete(shot.beatId);
    }
  });
  extraByBeat.forEach((extras) => shots.push(...extras));

  if (shots.length > current.shots.length) {
    const removableExtras = new Set(shots.filter((shot) => !currentIds.has(shot.id)).map((shot) => shot.id));
    let overflow = shots.length - current.shots.length;
    shots = shots.filter((shot) => {
      if (overflow <= 0 || !removableExtras.has(shot.id)) return true;
      overflow -= 1;
      removableExtras.delete(shot.id);
      return false;
    });
  }

  return { ...candidate, shots };
}

export function addStoryboardRepairHistory(current: StoryboardResult, repaired: StoryboardResult): StoryboardResult {
  const activeKeys = new Set(
    repaired.issues.filter((issue) => !issue.resolved)
      .map((issue) => `${issue.type}|${issue.fromShotId}|${issue.toShotId}`),
  );
  const resolvedHistory = current.issues
    .filter((issue) => !issue.resolved)
    .filter((issue) => !activeKeys.has(`${issue.type}|${issue.fromShotId}|${issue.toShotId}`))
    .map((issue) => ({ ...issue, resolved: true }));

  return { ...repaired, issues: [...resolvedHistory, ...repaired.issues] };
}

export function buildFallbackStoryboard(analysis: AnalysisResult): Omit<StoryboardResult, 'generatedAt' | 'totalDurationSec' | 'continuityScore'> {
  const baseState: ShotState = {
    characterPositions: '沿用剧本中的站位',
    gazeDirection: '跟随当前交互对象',
    propState: '沿用剧本中的道具状态',
    spaceState: '沿用剧本中的场景空间',
    timeState: '沿用剧本中的时间',
  };
  const shots: StoryboardShot[] = [];
  analysis.beats.forEach((beat, index) => {
    const previous = index > 0 ? shots[index - 1] : undefined;
    const startState = previous ? { ...previous.endState } : { ...baseState };
    const endState = { ...startState };
    shots.push({
      id: `S${String(index + 1).padStart(2, '0')}`,
      beatId: beat.id,
      durationSec: 4,
      shotSize: index === 0 ? '中景' : '近景',
      cameraAngle: '平视',
      cameraMovement: '固定',
      focus: `${beat.actor}与${beat.receiver}的交互`,
      action: beat.action || '保持站位并对向当前交互对象',
      dialogue: beat.dialogue || beat.response || '',
      sound: '保留现场环境声，台词清晰可辨',
      transition: index === 0 ? '建立镜头' : '连续承接',
      startState,
      endState,
      continuityReason: index === 0 ? '建立场景' : '连续承接',
      videoPrompt: `短剧写实镜头，${beat.actor}对${beat.receiver}执行一个清晰动作并完成回应；${beat.dialogue || beat.response || '无台词'}；保持人物身份、服装、道具、空间和时间连续。`,
    });
  });

  return {
    shots,
    issues: [],
    modelPrompt: '按镜头编号顺序执行；每镜头只完成一个主要动作，严格继承上一镜头结束状态，保持人物、道具、空间和时间连续。',
  };
}

export function finalizeStoryboard(
  raw: Omit<StoryboardResult, 'generatedAt' | 'totalDurationSec' | 'continuityScore'>,
  analysis: AnalysisResult,
  lockedShotIds: string[] = [],
): StoryboardResult {
  const shots: StoryboardShot[] = [];
  const lockedIds = new Set(lockedShotIds);
  raw.shots.forEach((shot, index) => {
    const continuous = index > 0 && !lockedIds.has(shot.id) &&
      /连续承接|直接承接|无变化/.test(shot.continuityReason);
    shots.push({
      ...shot,
      startState: continuous ? { ...shots[index - 1].endState } : shot.startState,
    });
  });

  const issueStateKeys: Partial<Record<ContinuityIssueType, keyof ShotState>> = {
    character_position: 'characterPositions',
    gaze_direction: 'gazeDirection',
    prop_state: 'propState',
    space_state: 'spaceState',
    time_state: 'timeState',
  };
  const reconciledModelIssues = raw.issues.filter((issue) => {
    const key = issueStateKeys[issue.type];
    if (!key) return true;
    const from = shots.find((shot) => shot.id === issue.fromShotId);
    const to = shots.find((shot) => shot.id === issue.toShotId);
    return !from || !to || from.endState[key].trim() !== to.startState[key].trim();
  });

  const ruleIssues: ContinuityIssue[] = [];
  let issueIndex = reconciledModelIssues.length + 1;
  const addIssue = (issue: Omit<ContinuityIssue, 'id' | 'resolved'>) => {
    ruleIssues.push({
      id: `C${String(issueIndex++).padStart(2, '0')}`,
      resolved: false,
      ...issue,
    });
  };

  const seenIds = new Set<string>();
  shots.forEach((shot, index) => {
    if (seenIds.has(shot.id)) {
      addIssue({
        severity: 'hard', type: 'shot_identity', fromShotId: shot.id, toShotId: shot.id,
        detail: `镜头编号 ${shot.id} 重复，后续状态无法唯一追踪。`,
        suggestion: `将第 ${index + 1} 个镜头改为唯一编号。`,
      });
    }
    seenIds.add(shot.id);

    if (shot.durationSec < 1 || shot.durationSec > 15) {
      addIssue({
        severity: 'soft', type: 'shot_density', fromShotId: shot.id, toShotId: shot.id,
        detail: `${shot.id} 时长为 ${shot.durationSec} 秒，不利于短剧节奏或单镜头稳定执行。`,
        suggestion: '将单镜头控制在 1—15 秒，并只保留一个主要动作。',
      });
    }

    const actionSteps = shot.action.split(/，|；|然后|随后|并且/).filter(Boolean).length;
    if (actionSteps > 3) {
      addIssue({
        severity: 'soft', type: 'shot_density', fromShotId: shot.id, toShotId: shot.id,
        detail: `${shot.id} 同时包含过多动作，视频模型容易漏执行或改变顺序。`,
        suggestion: '拆分为两个镜头，每个镜头只保留一个主要动作。',
      });
    }

    if (index === 0) return;
    const previous = shots[index - 1];
    const explainedCut = shot.continuityReason.trim().length >= 4 &&
      !/连续承接|直接承接|无变化/.test(shot.continuityReason);
    stateChecks.forEach(({ key, type, label, severity }) => {
      const from = previous.endState[key].trim();
      const to = shot.startState[key].trim();
      if (from && to && from !== to && !explainedCut) {
        addIssue({
          severity, type, fromShotId: previous.id, toShotId: shot.id,
          detail: `${label}没有连续承接：${previous.id}结束为“${from}”，${shot.id}开始为“${to}”。`,
          suggestion: `让${shot.id}的开始状态复制${previous.id}的结束状态，或明确写出可见变化原因。`,
        });
      }
    });
  });

  const budget = getStoryboardBudget(analysis);
  const totalDurationSec = Math.round(shots.reduce((sum, shot) => sum + shot.durationSec, 0) * 10) / 10;
  if (shots.length > budget.maxShots && shots.length > 0) {
    addIssue({
      severity: 'hard', type: 'shot_density', fromShotId: shots[0].id, toShotId: shots.at(-1)?.id ?? shots[0].id,
      detail: `本场共 ${shots.length} 个镜头，超过当前 ${analysis.beats.length} 个交互节拍的 ${budget.maxShots} 镜头预算。`,
      suggestion: '合并重复反应和无信息增量镜头，保留推动冲突或交代连续性所必需的镜头。',
    });
  }
  if (totalDurationSec > budget.maxDurationSec && shots.length > 0) {
    addIssue({
      severity: 'soft', type: 'shot_density', fromShotId: shots[0].id, toShotId: shots.at(-1)?.id ?? shots[0].id,
      detail: `本场预计 ${totalDurationSec} 秒，超过 ${budget.maxDurationSec} 秒的紧凑短剧预算。`,
      suggestion: '缩短停顿、合并重复动作，并删除没有新增剧情信息的镜头。',
    });
  }

  analysis.beats.forEach((beat) => {
    if (!shots.some((shot) => shot.beatId === beat.id)) {
      addIssue({
        severity: 'hard', type: 'beat_coverage', fromShotId: beat.id, toShotId: beat.id,
        detail: `交互节拍 ${beat.id} 没有对应镜头，剧情因果链在分镜阶段中断。`,
        suggestion: `补充至少一个镜头表现 ${beat.actor} 的动作、台词及 ${beat.receiver} 的即时反应。`,
      });
    }
  });

  const issues = [...reconciledModelIssues, ...ruleIssues];
  const hardCount = issues.filter((issue) => !issue.resolved && issue.severity === 'hard').length;
  const softCount = issues.filter((issue) => !issue.resolved && issue.severity === 'soft').length;
  return {
    ...raw,
    shots,
    issues,
    totalDurationSec,
    continuityScore: Math.max(0, Math.min(100, 100 - hardCount * 14 - softCount * 5)),
    generatedAt: new Date().toISOString(),
  };
}
