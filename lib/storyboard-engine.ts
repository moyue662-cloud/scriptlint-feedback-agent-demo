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

export function finalizeStoryboard(
  raw: Omit<StoryboardResult, 'generatedAt' | 'totalDurationSec' | 'continuityScore'>,
  analysis: AnalysisResult,
): StoryboardResult {
  const ruleIssues: ContinuityIssue[] = [];
  let issueIndex = raw.issues.length + 1;
  const addIssue = (issue: Omit<ContinuityIssue, 'id' | 'resolved'>) => {
    ruleIssues.push({
      id: `C${String(issueIndex++).padStart(2, '0')}`,
      resolved: false,
      ...issue,
    });
  };

  const seenIds = new Set<string>();
  raw.shots.forEach((shot, index) => {
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
    const previous = raw.shots[index - 1];
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

  analysis.beats.forEach((beat) => {
    if (!raw.shots.some((shot) => shot.beatId === beat.id)) {
      addIssue({
        severity: 'hard', type: 'beat_coverage', fromShotId: beat.id, toShotId: beat.id,
        detail: `交互节拍 ${beat.id} 没有对应镜头，剧情因果链在分镜阶段中断。`,
        suggestion: `补充至少一个镜头表现 ${beat.actor} 的动作、台词及 ${beat.receiver} 的即时反应。`,
      });
    }
  });

  const issues = [...raw.issues, ...ruleIssues];
  const hardCount = issues.filter((issue) => !issue.resolved && issue.severity === 'hard').length;
  const softCount = issues.filter((issue) => !issue.resolved && issue.severity === 'soft').length;
  return {
    ...raw,
    issues,
    totalDurationSec: Math.round(raw.shots.reduce((sum, shot) => sum + shot.durationSec, 0) * 10) / 10,
    continuityScore: Math.max(0, Math.min(100, 100 - hardCount * 14 - softCount * 5)),
    generatedAt: new Date().toISOString(),
  };
}
