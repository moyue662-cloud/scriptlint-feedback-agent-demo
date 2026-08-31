import type { EpisodeSummary, StoredSceneDetail } from '@/lib/scene-state';

export type EpisodeAIReviewStatus = 'ready' | 'attention' | 'blocked';
export type EpisodeAIReviewCategory = 'causality' | 'motivation' | 'conflict' | 'pacing' | 'knowledge' | 'hook';

export interface EpisodeAIReviewIssue {
  id: string;
  severity: 'hard' | 'soft';
  category: EpisodeAIReviewCategory;
  sceneIds: string[];
  title: string;
  detail: string;
  suggestion: string;
}

export interface EpisodeAIReview {
  projectId: string;
  episodeNumber: number;
  sourceHash: string;
  score: number;
  status: EpisodeAIReviewStatus;
  overview: string;
  hookAssessment: string;
  strengths: string[];
  issues: EpisodeAIReviewIssue[];
  reviewedAt: string;
}

export function passesEpisodeAIReviewGate(review: EpisodeAIReview | null | undefined) {
  return Boolean(review && review.status !== 'blocked');
}

export async function buildEpisodeSourceHash(
  episodeNumber: number,
  scenes: StoredSceneDetail[],
  summary: EpisodeSummary | null,
) {
  const source = JSON.stringify({
    episodeNumber,
    summary: summary ? {
      title: summary.title, objective: summary.objective, conflict: summary.conflict,
      notes: summary.notes, updatedAt: summary.updatedAt,
    } : null,
    scenes: scenes
      .filter((scene) => scene.episodeNumber === episodeNumber)
      .sort((a, b) => a.sceneOrder - b.sceneOrder || a.sceneNumber - b.sceneNumber)
      .map((scene) => ({
        id: scene.id, order: scene.sceneOrder, title: scene.title, script: scene.script,
        analyzedAt: scene.analysis.analyzedAt, storyboardAt: scene.storyboard.generatedAt,
      })),
  });
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(source));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
}
