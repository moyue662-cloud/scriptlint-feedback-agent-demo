import type { ImportedSceneDraft } from '@/lib/batch-import';
import type { NovelAdaptationResult } from '@/lib/novel-adaptation';

export type BatchCompilePhase = 'pending' | 'analyzing' | 'repairing_script' | 'storyboarding' | 'repairing_storyboard' | 'saving' | 'complete' | 'failed';
export type BatchCompileStatus = 'active' | 'failed' | 'completed' | 'cancelled';

export interface BatchCompileItem {
  phase: BatchCompilePhase;
  detail: string;
  error?: string;
  sceneId?: string;
}

export interface BatchCompileRun {
  id: string;
  projectId: string;
  status: BatchCompileStatus;
  drafts: ImportedSceneDraft[];
  items: BatchCompileItem[];
  adaptation: NovelAdaptationResult | null;
  nextIndex: number;
  lastError?: string;
  createdAt: string;
  updatedAt: string;
}

export const pendingBatchItem = (): BatchCompileItem => ({ phase: 'pending', detail: '等待整集队列' });

export function isBatchCompilePhase(value: unknown): value is BatchCompilePhase {
  return typeof value === 'string' && ['pending', 'analyzing', 'repairing_script', 'storyboarding', 'repairing_storyboard', 'saving', 'complete', 'failed'].includes(value);
}
