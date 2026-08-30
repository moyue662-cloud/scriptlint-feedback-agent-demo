import type { StoryboardResult } from '@/lib/storyboard-engine';

export type DeliveryAspectRatio = '9:16' | '16:9';

export interface VideoDeliveryOptions {
  aspectRatio: DeliveryAspectRatio;
  resolution: string;
  style: string;
}

export interface VideoDeliveryPackage {
  title: string;
  aspectRatio: DeliveryAspectRatio;
  resolution: string;
  style: string;
  globalPrompt: string;
  shots: Array<{
    order: number;
    id: string;
    durationSec: number;
    prompt: string;
    dialogue: string;
    continuityLock: string;
  }>;
}

export function buildVideoDeliveryPackage(
  storyboard: StoryboardResult,
  options: VideoDeliveryOptions,
): VideoDeliveryPackage {
  return {
    title: '剧序 SceneFlow 视频生成交付包',
    aspectRatio: options.aspectRatio,
    resolution: options.resolution,
    style: options.style,
    globalPrompt: `${storyboard.modelPrompt} 输出比例 ${options.aspectRatio}，${options.resolution}，整体风格：${options.style}。严格按镜头顺序生成，不改变人物身份、服装、道具、空间和时间。`,
    shots: storyboard.shots.map((shot, index) => ({
      order: index + 1,
      id: shot.id,
      durationSec: shot.durationSec,
      prompt: `${shot.videoPrompt} 构图比例 ${options.aspectRatio}，${options.resolution}，风格：${options.style}。`,
      dialogue: shot.dialogue || '无台词',
      continuityLock: `开始状态：${shot.startState.characterPositions}；${shot.startState.propState}；${shot.startState.spaceState}；${shot.startState.timeState}。结束状态：${shot.endState.characterPositions}；${shot.endState.propState}；${shot.endState.spaceState}；${shot.endState.timeState}。`,
    })),
  };
}

export function videoDeliveryToMarkdown(delivery: VideoDeliveryPackage) {
  const shots = delivery.shots.map((shot) =>
    `## ${shot.order}. ${shot.id}（${shot.durationSec}秒）\n\n视频Prompt：${shot.prompt}\n\n台词：${shot.dialogue}\n\n连续性锁定：${shot.continuityLock}`,
  ).join('\n\n');
  return `# ${delivery.title}\n\n画面比例：${delivery.aspectRatio}\n分辨率：${delivery.resolution}\n整体风格：${delivery.style}\n\n## 总指令\n\n${delivery.globalPrompt}\n\n${shots}\n`;
}
