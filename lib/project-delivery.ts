import type { SceneProject, StoredSceneDetail } from '@/lib/scene-state';

export type ProjectDeliveryAspectRatio = '9:16' | '16:9';

export interface ProjectProductionPackage {
  schemaVersion: 'scene-flow-production/v1';
  packageType: 'final' | 'review-draft';
  project: { id: string; name: string };
  output: {
    aspectRatio: ProjectDeliveryAspectRatio;
    resolution: '1080×1920' | '1920×1080';
    style: string;
  };
  instructions: string[];
  episodes: Array<{
    episodeNumber: number;
    scenes: Array<{
      sceneNumber: number;
      title: string;
      sourceScript: string;
      shots: Array<{
        sequenceId: string;
        shotId: string;
        durationSec: number;
        focus: string;
        action: string;
        dialogue: string;
        videoPrompt: string;
        continuityReason: string;
        startState: StoredSceneDetail['storyboard']['shots'][number]['startState'];
        endState: StoredSceneDetail['storyboard']['shots'][number]['endState'];
        humanReviewed: boolean;
        productionStatus: 'pending' | 'submitted' | 'accepted';
      }>;
    }>;
  }>;
  totals: { episodes: number; scenes: number; shots: number; durationSec: number; reviewedShots: number };
  generatedAt: string;
}

function pad(value: number) {
  return String(value).padStart(2, '0');
}

export function buildProjectProductionPackage(input: {
  project: SceneProject;
  scenes: StoredSceneDetail[];
  ready: boolean;
  aspectRatio: ProjectDeliveryAspectRatio;
}): ProjectProductionPackage {
  const ordered = [...input.scenes].sort((a, b) => (
    a.episodeNumber - b.episodeNumber || a.sceneOrder - b.sceneOrder || a.sceneNumber - b.sceneNumber
  ));
  const episodeNumbers = Array.from(new Set(ordered.map((scene) => scene.episodeNumber)));
  const episodes = episodeNumbers.map((episodeNumber) => {
    const episodeScenes = ordered.filter((scene) => scene.episodeNumber === episodeNumber);
    return {
      episodeNumber,
      scenes: episodeScenes.map((scene, sceneIndex) => {
        const reviewed = new Set(scene.deliveryTracking.reviewedShotIds);
        return {
          sceneNumber: sceneIndex + 1,
          title: scene.title,
          sourceScript: scene.script,
          shots: scene.storyboard.shots.map((shot, shotIndex) => ({
            sequenceId: `EP${pad(episodeNumber)}-SC${pad(sceneIndex + 1)}-SH${pad(shotIndex + 1)}`,
            shotId: shot.id,
            durationSec: shot.durationSec,
            focus: shot.focus,
            action: shot.action,
            dialogue: shot.dialogue,
            videoPrompt: shot.videoPrompt,
            continuityReason: shot.continuityReason,
            startState: shot.startState,
            endState: shot.endState,
            humanReviewed: reviewed.has(shot.id),
            productionStatus: scene.deliveryTracking.statuses[shot.id] ?? 'pending',
          })),
        };
      }),
    };
  });
  const allShots = episodes.flatMap((episode) => episode.scenes.flatMap((scene) => scene.shots));
  return {
    schemaVersion: 'scene-flow-production/v1',
    packageType: input.project.approvedAt && input.ready ? 'final' : 'review-draft',
    project: { id: input.project.id, name: input.project.name },
    output: {
      aspectRatio: input.aspectRatio,
      resolution: input.aspectRatio === '9:16' ? '1080×1920' : '1920×1080',
      style: '写实短剧，电影级自然光，表演克制，台词清晰，严格保持人物身份与跨镜连续性',
    },
    instructions: [
      '必须严格按照 sequenceId 顺序逐镜生成，不得合并、跳过或改写剧情事实。',
      '每个镜头只执行 videoPrompt 中的单一主要动作，并使用给定时长。',
      '下一个镜头必须继承上一个镜头的 endState；明确转场时按 continuityReason 执行。',
      '不得改变人物身份、服装、站位、视线、道具归属、空间和时间状态。',
    ],
    episodes,
    totals: {
      episodes: episodes.length,
      scenes: ordered.length,
      shots: allShots.length,
      durationSec: allShots.reduce((total, shot) => total + shot.durationSec, 0),
      reviewedShots: allShots.filter((shot) => shot.humanReviewed).length,
    },
    generatedAt: new Date().toISOString(),
  };
}

function stateLines(label: string, state: ProjectProductionPackage['episodes'][number]['scenes'][number]['shots'][number]['startState']) {
  return [
    `- ${label}人物站位：${state.characterPositions}`,
    `- ${label}视线：${state.gazeDirection}`,
    `- ${label}道具：${state.propState}`,
    `- ${label}空间：${state.spaceState}`,
    `- ${label}时间：${state.timeState}`,
  ];
}

export function projectProductionPackageToMarkdown(value: ProjectProductionPackage) {
  const lines = [
    `# ${value.project.name} · 视频制作执行包`,
    '',
    `- 状态：${value.packageType === 'final' ? '最终版' : '审查草稿'}`,
    `- 画幅：${value.output.aspectRatio}（${value.output.resolution}）`,
    `- 总计：${value.totals.episodes} 集 / ${value.totals.scenes} 场 / ${value.totals.shots} 镜 / ${value.totals.durationSec} 秒`,
    `- 人工确认：${value.totals.reviewedShots}/${value.totals.shots} 镜`,
    '',
    '## 全局执行规则',
    '',
    ...value.instructions.map((instruction, index) => `${index + 1}. ${instruction}`),
  ];
  value.episodes.forEach((episode) => {
    lines.push('', `## 第 ${episode.episodeNumber} 集`);
    episode.scenes.forEach((scene) => {
      lines.push('', `### 第 ${scene.sceneNumber} 场 · ${scene.title}`);
      scene.shots.forEach((shot) => {
        lines.push(
          '', `#### ${shot.sequenceId} · ${shot.durationSec} 秒`,
          '', `- 主体：${shot.focus}`, `- 动作：${shot.action}`,
          `- 台词：${shot.dialogue || '无'}`, `- 连续性理由：${shot.continuityReason}`,
          `- 人工确认：${shot.humanReviewed ? '已确认' : '未确认'}`,
          `- 制作状态：${shot.productionStatus}`,
          '', '**视频 Prompt**', '', shot.videoPrompt, '', '**状态锁定**',
          ...stateLines('开始', shot.startState), ...stateLines('结束', shot.endState),
        );
      });
    });
  });
  return `${lines.join('\n')}\n`;
}
