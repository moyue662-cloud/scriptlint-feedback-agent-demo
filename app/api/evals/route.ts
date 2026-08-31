import { EVAL_CASES, runLocalEvaluation } from '@/lib/eval-suite';

export const runtime = 'edge';

export async function GET() {
  return Response.json({
    suite: {
      id: 'sceneflow-regression-v1',
      title: 'SceneFlow 交互回归集',
      description: '用于检测抽象情绪、人物缺失、动作不足和干净交互的基础回归集。',
      cases: EVAL_CASES.map(({ script, ...testCase }) => ({ ...testCase, script })),
    },
    baseline: runLocalEvaluation(),
  });
}
