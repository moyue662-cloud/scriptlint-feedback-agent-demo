import { analyzeScript, type AnalysisResult, type IssueType } from '@/lib/script-engine';

export interface EvaluationCase {
  id: string;
  title: string;
  description: string;
  script: string;
  expectedIssueTypes: IssueType[];
  minimumBeatCount: number;
  clean?: boolean;
}

export interface EvaluationCaseResult {
  id: string;
  title: string;
  passed: boolean;
  score: number;
  beatCount: number;
  issueTypes: IssueType[];
  expectedIssueTypes: IssueType[];
  matchedIssueTypes: IssueType[];
  missingIssueTypes: IssueType[];
  unexpectedIssueTypes: IssueType[];
  hardIssueCount: number;
}

export interface EvaluationSummary {
  provider: string;
  model: string;
  ranAt: string;
  caseCount: number;
  passedCount: number;
  passRate: number;
  issueRecall: number;
  falsePositiveRate: number;
  averageScore: number;
  results: EvaluationCaseResult[];
}

/**
 * These fixtures are intentionally small and deterministic. They are not a
 * replacement for editorial review; they are a smoke suite that catches
 * regressions in the compiler's most important failure modes.
 */
export const EVAL_CASES: EvaluationCase[] = [
  {
    id: 'abstract-emotion',
    title: '抽象情绪没有落地',
    description: '人物只写“很生气/很尴尬”，需要转换为可见表演。',
    script: '林晓很生气地质问父亲：“你什么时候辞职的？”父亲很尴尬地说：“这不重要。”',
    expectedIssueTypes: ['abstract_emotion'],
    minimumBeatCount: 2,
  },
  {
    id: 'missing-character',
    title: '交互对象缺失',
    description: '只有环境和一个模糊人物，无法建立可靠的回应关系。',
    script: '客厅，夜晚。一个人发现桌上的通知书，很生气。',
    expectedIssueTypes: ['missing_character', 'abstract_emotion'],
    minimumBeatCount: 1,
  },
  {
    id: 'weak-action',
    title: '心理结果缺少动作',
    description: '人物状态有变化，但没有给出单一、可拍摄的动作。',
    script: '林晓怀疑父亲。父亲尴尬。林晓继续追问。',
    expectedIssueTypes: ['abstract_emotion', 'weak_action'],
    minimumBeatCount: 3,
  },
  {
    id: 'clean-interaction',
    title: '动作与回应完整',
    description: '每个节拍都有明确动作和承接，作为低误报基线。',
    script: '林晓拿起通知书，盯着父亲：“你什么时候辞职的？”父亲停下收拾茶杯，避开目光：“这不重要。”林晓攥紧通知书，拍在桌上。父亲站在桌边，保持沉默。',
    expectedIssueTypes: [],
    minimumBeatCount: 4,
    clean: true,
  },
];

function uniqueIssueTypes(analysis: AnalysisResult) {
  return Array.from(new Set(analysis.issues.map((issue) => issue.type)));
}

export function evaluateCase(testCase: EvaluationCase, analysis: AnalysisResult): EvaluationCaseResult {
  const issueTypes = uniqueIssueTypes(analysis);
  const expected = testCase.expectedIssueTypes;
  const matchedIssueTypes = expected.filter((type) => issueTypes.includes(type));
  const missingIssueTypes = expected.filter((type) => !issueTypes.includes(type));
  const unexpectedIssueTypes = issueTypes.filter((type) => !expected.includes(type));
  const hardIssueCount = analysis.issues.filter((issue) => issue.severity === 'hard' && !issue.resolved).length;
  const passed = analysis.beats.length >= testCase.minimumBeatCount
    && missingIssueTypes.length === 0
    && (!testCase.clean || hardIssueCount === 0);
  return {
    id: testCase.id,
    title: testCase.title,
    passed,
    score: Math.max(0, Math.min(100, Math.round(analysis.score))),
    beatCount: analysis.beats.length,
    issueTypes,
    expectedIssueTypes: expected,
    matchedIssueTypes,
    missingIssueTypes,
    unexpectedIssueTypes,
    hardIssueCount,
  };
}

export function summarizeEvaluation(
  results: EvaluationCaseResult[],
  provider: string,
  model: string,
  ranAt = new Date().toISOString(),
): EvaluationSummary {
  const expectedCount = results.reduce((total, result) => total + result.expectedIssueTypes.length, 0);
  const matchedCount = results.reduce((total, result) => total + result.matchedIssueTypes.length, 0);
  const cleanResults = EVAL_CASES.filter((testCase) => testCase.clean)
    .map((testCase) => results.find((result) => result.id === testCase.id))
    .filter((result): result is EvaluationCaseResult => Boolean(result));
  const falsePositiveCount = cleanResults.filter((result) => result.unexpectedIssueTypes.length > 0).length;
  return {
    provider,
    model,
    ranAt,
    caseCount: results.length,
    passedCount: results.filter((result) => result.passed).length,
    passRate: results.length ? Math.round((results.filter((result) => result.passed).length / results.length) * 100) : 0,
    issueRecall: expectedCount ? Math.round((matchedCount / expectedCount) * 100) : 100,
    falsePositiveRate: cleanResults.length ? Math.round((falsePositiveCount / cleanResults.length) * 100) : 0,
    averageScore: results.length ? Math.round(results.reduce((total, result) => total + result.score, 0) / results.length) : 0,
    results,
  };
}

export function runLocalEvaluation(): EvaluationSummary {
  const results = EVAL_CASES.map((testCase) => evaluateCase(testCase, analyzeScript(testCase.script)));
  return summarizeEvaluation(results, 'local', 'rule-engine');
}

