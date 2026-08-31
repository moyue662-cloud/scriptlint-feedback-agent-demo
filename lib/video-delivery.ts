import type { StoryboardResult } from '@/lib/storyboard-engine';

export type DeliveryAspectRatio = '9:16' | '16:9';

export interface VideoDeliveryOptions {
  aspectRatio: DeliveryAspectRatio;
  resolution: string;
  style: string;
}

export interface VideoDeliveryPackage {
  formatVersion: 'video-delivery/v1';
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

export interface VideoDeliveryValidationIssue {
  code: string;
  message: string;
  shotId?: string;
}

export interface VideoDeliveryValidation {
  valid: boolean;
  issues: VideoDeliveryValidationIssue[];
}

export function buildVideoDeliveryPackage(
  storyboard: StoryboardResult,
  options: VideoDeliveryOptions,
): VideoDeliveryPackage {
  return {
    formatVersion: 'video-delivery/v1',
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
      continuityLock: `开始状态：站位 ${shot.startState.characterPositions}；视线 ${shot.startState.gazeDirection}；道具 ${shot.startState.propState}；空间 ${shot.startState.spaceState}；时间 ${shot.startState.timeState}。结束状态：站位 ${shot.endState.characterPositions}；视线 ${shot.endState.gazeDirection}；道具 ${shot.endState.propState}；空间 ${shot.endState.spaceState}；时间 ${shot.endState.timeState}。`,
    })),
  };
}

export function validateVideoDeliveryPackage(delivery: VideoDeliveryPackage): VideoDeliveryValidation {
  const issues: VideoDeliveryValidationIssue[] = [];
  if (delivery.formatVersion !== 'video-delivery/v1') {
    issues.push({ code: 'format_version', message: '交付包格式版本不受支持。' });
  }
  if (!delivery.globalPrompt.trim()) {
    issues.push({ code: 'global_prompt', message: '缺少整体生成指令。' });
  }
  if (!delivery.shots.length) {
    issues.push({ code: 'empty_shots', message: '交付包至少需要一个镜头。' });
  }

  const seenIds = new Set<string>();
  delivery.shots.forEach((shot, index) => {
    const expectedOrder = index + 1;
    if (shot.order !== expectedOrder) {
      issues.push({ code: 'shot_order', shotId: shot.id, message: `镜头顺序应为 ${expectedOrder}，当前为 ${shot.order}。` });
    }
    if (seenIds.has(shot.id)) {
      issues.push({ code: 'duplicate_shot', shotId: shot.id, message: '镜头编号重复。' });
    }
    seenIds.add(shot.id);
    if (!Number.isFinite(shot.durationSec) || shot.durationSec < 1 || shot.durationSec > 15) {
      issues.push({ code: 'duration', shotId: shot.id, message: '镜头时长必须在 1—15 秒之间。' });
    }
    if (!shot.prompt.trim()) {
      issues.push({ code: 'shot_prompt', shotId: shot.id, message: '缺少镜头视频 Prompt。' });
    }
    if (!shot.dialogue.trim()) {
      issues.push({ code: 'dialogue', shotId: shot.id, message: '缺少台词字段；无台词镜头应填写“无台词”。' });
    }
    if (!shot.continuityLock.includes('开始状态：') || !shot.continuityLock.includes('结束状态：')) {
      issues.push({ code: 'continuity_lock', shotId: shot.id, message: '连续性锁定必须同时包含开始状态和结束状态。' });
    }
  });

  return { valid: issues.length === 0, issues };
}

export function videoDeliveryToMarkdown(delivery: VideoDeliveryPackage) {
  const shots = delivery.shots.map((shot) =>
    `## ${shot.order}. ${shot.id}（${shot.durationSec}秒）\n\n视频Prompt：${shot.prompt}\n\n台词：${shot.dialogue}\n\n连续性锁定：${shot.continuityLock}`,
  ).join('\n\n');
  return `# ${delivery.title}\n\n画面比例：${delivery.aspectRatio}\n分辨率：${delivery.resolution}\n整体风格：${delivery.style}\n\n## 总指令\n\n${delivery.globalPrompt}\n\n${shots}\n`;
}
