export type VisualIssueType = 'identity' | 'wardrobe' | 'prop' | 'position' | 'gaze' | 'space' | 'time' | 'shot';

export interface VisualReviewIssue {
  id: string;
  severity: 'hard' | 'soft';
  type: VisualIssueType;
  frameIndex: number;
  shotId: string | null;
  title: string;
  detail: string;
  suggestion: string;
}

export interface VisualReview {
  overview: string;
  score: number;
  framesAnalyzed: number;
  issues: VisualReviewIssue[];
}

export const visualIssueTypeLabels: Record<VisualIssueType, string> = {
  identity: '人物身份', wardrobe: '服装外观', prop: '道具', position: '站位',
  gaze: '视线', space: '空间', time: '时间', shot: '镜头表达',
};

export function isVisualDataUrl(value: unknown): value is string {
  return typeof value === 'string'
    && /^data:image\/(?:png|jpe?g|webp);base64,[A-Za-z0-9+/=]+$/i.test(value);
}

