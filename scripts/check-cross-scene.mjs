import assert from 'node:assert/strict';
import path from 'node:path';
import { runnerImport } from 'vite';

const loadOptions = { resolve: { alias: { '@': process.cwd() } } };
const { module: episodeModule } = await runnerImport(path.resolve('lib/episode-review.ts'), loadOptions);
const { module: stateModule } = await runnerImport(path.resolve('lib/scene-state.ts'), loadOptions);
const { module: aiReviewModule } = await runnerImport(path.resolve('lib/episode-ai-review.ts'), loadOptions);
const { module: batchImportModule } = await runnerImport(path.resolve('lib/batch-import.ts'), loadOptions);
const { module: scriptEngineModule } = await runnerImport(path.resolve('lib/script-engine.ts'), loadOptions);
const { module: adaptationModule } = await runnerImport(path.resolve('lib/novel-adaptation.ts'), loadOptions);
const { module: scriptInputModule } = await runnerImport(path.resolve('lib/script-input.ts'), loadOptions);

const { buildEpisodeReview } = episodeModule;
const { buildSceneSnapshot, inheritStoryboardOpeningState } = stateModule;
const { buildEpisodeSourceHash, passesEpisodeAIReviewGate } = aiReviewModule;
const { splitScriptIntoScenes } = batchImportModule;
const { analyzeScript, normalizeAnalysisResult } = scriptEngineModule;
const { buildAdaptationCompileContext, normalizeNovelAdaptation } = adaptationModule;
const { assessScriptInput } = scriptInputModule;

  const endState = {
    characterPositions: '林晓站在茶几旁，父亲坐在沙发上',
    gazeDirection: '林晓看父亲，父亲低头',
    propState: '辞职通知书在茶几上',
    spaceState: '客厅，夜晚',
    timeState: '夜晚，连续时间',
  };
  const changedOpening = {
    ...endState,
    characterPositions: '林晓坐在沙发上，父亲站在门口',
  };
  const character = {
    name: '林晓', emotionalState: '愤怒', lastAction: '放下通知书', lastDialogue: '告诉我真相', knownFacts: ['父亲已经辞职'],
  };
  const scene = (id, title, snapshot, openingState, script = '') => ({
    id, projectId: 'default', sceneNumber: Number(id.slice(1)), episodeNumber: 1,
    sceneOrder: Number(id.slice(1)), title, script, snapshot, openingState,
    transitionReason: '建立场景', deliveryTracking: { statuses: { s1: 'accepted' }, updatedAt: null },
    summary: {
      shotCount: 1, durationSec: 4, continuityIssueCount: 0, submittedShotCount: 1,
      acceptedShotCount: 1, productionProgress: 100, status: 'completed',
    },
    createdAt: '2026-01-01T00:00:00.000Z',
  });
  const summary = {
    projectId: 'default', episodeNumber: 1, title: '辞职真相',
    objective: '林晓逼父亲正面回应辞职原因', conflict: '父亲继续隐瞒，林晓不断追问',
    notes: '', updatedAt: '2026-01-01T00:00:00.000Z',
  };
  const first = scene('s1', '发现通知书', { ...endState, characters: [character] }, endState);
  const broken = scene('s2', '继续对峙', { ...changedOpening, characters: [character] }, changedOpening);
  const brokenReview = buildEpisodeReview(1, [first, broken], summary);
  assert.equal(brokenReview.status, 'blocked');
  assert.ok(brokenReview.issues.some((issue) => issue.id.startsWith('cross-scene-')));

  const explained = scene('s2', '十分钟后继续对峙', { ...changedOpening, characters: [character] }, changedOpening, '十分钟后，父亲站到门口。');
  const explainedReview = buildEpisodeReview(1, [first, explained], summary);
  assert.ok(!explainedReview.issues.some((issue) => issue.id.startsWith('cross-scene-')));

  const inheritedSnapshot = {
    ...endState,
    characters: [
      character,
      { name: '父亲', emotionalState: '防御', lastAction: '低头', lastDialogue: '这不重要', knownFacts: ['林晓发现了通知书'] },
    ],
  };
  const analysis = {
    characters: ['林晓'], score: 100, executionPrompt: '', analyzedAt: '', issues: [],
    beats: [{
      id: 'b1', source: '林晓继续追问', actor: '林晓', receiver: '父亲', trigger: '父亲仍然沉默',
      goal: '得到真相', action: '看着父亲', dialogue: '你现在能说了吗？', reaction: '父亲抬头', response: '',
      stateBefore: '克制', stateAfter: '坚定',
    }],
  };
  const storyboard = {
    shots: [{
      id: 's1', beatId: 'b1', durationSec: 4, shotSize: '中景', cameraAngle: '平视', cameraMovement: '固定',
      focus: '林晓', action: '林晓看着父亲', dialogue: '你现在能说了吗？', sound: '环境声', transition: '连续承接',
      startState: endState, endState, continuityReason: '连续承接', videoPrompt: '保持连续。',
    }],
    issues: [], continuityScore: 100, totalDurationSec: 4, modelPrompt: '', generatedAt: '',
  };
  const merged = buildSceneSnapshot(analysis, storyboard, inheritedSnapshot);
  const lin = merged.characters.find((item) => item.name === '林晓');
  assert.ok(lin.knownFacts.includes('父亲已经辞职'));
  assert.ok(lin.knownFacts.includes('父亲仍然沉默'));
  assert.ok(merged.characters.some((item) => item.name === '父亲'));

  const detailScenes = [
    { ...first, analysis, storyboard },
    { ...explained, analysis: { ...analysis, analyzedAt: 'later' }, storyboard },
  ];
  const originalHash = await buildEpisodeSourceHash(1, detailScenes, summary);
  const changedSummaryHash = await buildEpisodeSourceHash(1, detailScenes, { ...summary, conflict: '冲突升级为父亲准备离家' });
  const reorderedHash = await buildEpisodeSourceHash(1, [
    { ...detailScenes[0], sceneOrder: 2 }, { ...detailScenes[1], sceneOrder: 1 },
  ], summary);
  assert.notEqual(originalHash, changedSummaryHash);
  assert.notEqual(originalHash, reorderedHash);

  const deliveryOnlyHash = await buildEpisodeSourceHash(1, [
    { ...detailScenes[0], deliveryTracking: { statuses: { s1: 'submitted' }, updatedAt: 'later' } },
    detailScenes[1],
  ], summary);
  assert.equal(originalHash, deliveryOnlyHash);

  const inheritedStoryboard = inheritStoryboardOpeningState(
    { ...storyboard, shots: [{ ...storyboard.shots[0], startState: changedOpening }] },
    first,
    '林晓继续追问父亲。',
  );
  assert.deepEqual(inheritedStoryboard.shots[0].startState, endState);
  const transitionedStoryboard = inheritStoryboardOpeningState(
    { ...storyboard, shots: [{ ...storyboard.shots[0], startState: changedOpening }] },
    first,
    '第二天，林晓来到公司。',
  );
  assert.deepEqual(transitionedStoryboard.shots[0].startState, changedOpening);

  assert.equal(passesEpisodeAIReviewGate({ status: 'attention' }), true);
  assert.equal(passesEpisodeAIReviewGate({ status: 'blocked' }), false);
  assert.equal(passesEpisodeAIReviewGate(null), false);

  const imported = splitScriptIntoScenes(`第1场 客厅\n林晓：你什么时候辞职的？\n\n第2场 公司门口\n父亲：这件事我会解释。`);
  assert.equal(imported.length, 2);
  assert.equal(imported[0].title, '第1场 客厅');
  assert.match(imported[1].script, /父亲/);
  const colonHeadings = splitScriptIntoScenes(`第1场：客厅\n林晓：你什么时候辞职的？\n\n第2场：公司门口\n父亲：这件事我会解释。`);
  assert.equal(colonHeadings.length, 2);
  assert.equal(colonHeadings[0].title, '第1场：客厅');
  const paragraphSuggestions = splitScriptIntoScenes('第一段交互。\n\n第二段交互。');
  assert.equal(paragraphSuggestions.length, 1);
  assert.equal(splitScriptIntoScenes('只有一场戏').length, 1);
  const longScript = Array.from({ length: 90 }, (_, index) => `林晓在桌边观察父亲的动作${index + 1}。`).join('');
  const suggestedChunks = splitScriptIntoScenes(longScript);
  assert.ok(suggestedChunks.length > 1);
  assert.equal(suggestedChunks[0].splitReason, 'grouped');
  assert.ok(suggestedChunks.every((draft) => draft.script.length >= 260));
  assert.ok(suggestedChunks.every((draft) => draft.estimatedDurationSec >= 20));
  const unpunctuated = splitScriptIntoScenes('超长无标点文本'.repeat(1300));
  assert.ok(unpunctuated.length > 1);
  assert.ok(unpunctuated.length <= 24);
  assert.ok(unpunctuated.every((draft) => draft.script.length <= 980));

  const narrativeAssessment = assessScriptInput('我给你终极四合一完整版：都市修仙 + 酒精屏幕因果 + 舍友偷卷翻车 + 保研碾压！全篇逻辑闭环，结局彻底封神。我叫林玄，上古仙尊残魂入世，封印修为蛰伏凡尘。他的室友张宸是典型的伪天才，后来两人的命运彻底逆转。');
  assert.equal(narrativeAssessment.shouldAdaptFirst, true);
  assert.equal(narrativeAssessment.kind, 'narrative');
  const sceneAssessment = assessScriptInput('客厅，夜晚。\n林晓：你什么时候辞职的？\n父亲：这不重要。\n林晓把通知书拍在桌上，父亲停下收拾茶杯的动作。');
  assert.equal(sceneAssessment.shouldAdaptFirst, false);
  assert.equal(sceneAssessment.kind, 'scene');

  const adapted = normalizeNovelAdaptation({
    theme: '敬畏细节', logline: '林玄守住细节，张宸因狂妄失去机会。',
    characters: ['林玄', '张宸'],
    retainedPlotPoints: ['酒精擦屏', '保研反转'], omittedContent: ['重复说教'],
    scenes: [
      { title: '擦屏冲突', narrativeRole: '开场钩子', estimatedDurationSec: 45, retainedHighlights: ['酒精擦屏'], appearingCharacters: ['林玄', '张宸'], establishedFacts: ['林玄警告酒精会损伤镀膜'], timeMarker: '大一开学夜', script: '大一开学夜，宿舍。张宸举起酒精瓶嘲笑林玄。林玄按住电脑：“镀膜会坏。”张宸甩开他的手，当众擦满屏幕。林玄停手，不再劝阻。' },
      { title: '结果兑现', narrativeRole: '高潮', estimatedDurationSec: 60, retainedHighlights: ['保研公布'], appearingCharacters: ['林玄', '张宸', '辅导员'], establishedFacts: ['林玄保研第一', '张宸落选'], timeMarker: '三年后', script: '三年后，保研名单公布。辅导员贴出名单，林玄位列第一，张宸落选。张宸盯着斑驳屏幕质问原因，林玄把当年的警告重新说给他听。张宸沉默。' },
    ],
  }, 2);
  assert.equal(adapted.scenes.length, 2);
  assert.equal(adapted.scenes[0].episodeNumber, 2);
  assert.equal(adapted.scenes[0].splitReason, 'adapted');
  assert.equal(adapted.estimatedTotalDurationSec, 105);
  assert.deepEqual(adapted.scenes[1].appearingCharacters, ['林玄', '张宸', '辅导员']);
  assert.equal(adapted.scenes[1].timeMarker, '三年后');
  const secondContext = buildAdaptationCompileContext(adapted, adapted.scenes[1]);
  assert.deepEqual(secondContext.priorScenes.flatMap((scene) => scene.establishedFacts), ['林玄警告酒精会损伤镀膜']);
  assert.deepEqual(secondContext.currentScene.factsToEstablish, ['林玄保研第一', '张宸落选']);
  assert.equal(secondContext.priorScenes.some((scene) => scene.establishedFacts.includes('林玄保研第一')), false);

  const prefixedTime = normalizeNovelAdaptation({
    theme: '时间测试', logline: '时间标记必须进入正文。', characters: ['甲', '乙'], retainedPlotPoints: [], omittedContent: [],
    scenes: [
      { title: '前场', narrativeRole: '开场钩子', estimatedDurationSec: 30, retainedHighlights: [], appearingCharacters: ['甲', '乙'], establishedFacts: [], timeMarker: '', script: '甲把信封递给乙，乙接过信封后拆开，抬眼询问信件来源。甲避开目光，只让乙继续读完再说。' },
      { title: '后场', narrativeRole: '收束', estimatedDurationSec: 30, retainedHighlights: [], appearingCharacters: ['甲', '乙'], establishedFacts: [], timeMarker: '两个月后', script: '甲在车站拦住乙，把已经磨损的信封重新递过去。乙没有接，转身望向进站列车。甲收回信封，站在原地目送乙登上列车。' },
    ],
  });
  assert.ok(prefixedTime.scenes[1].script.startsWith('两个月后。'));

  const dialogueOnly = analyzeScript('林晓：“你为什么不告诉我？”父亲：“这不重要。”');
  assert.equal(dialogueOnly.issues.filter((issue) => issue.type === 'weak_action').length, 0);
  assert.ok(dialogueOnly.beats.every((beat) => beat.action.includes('说出这句话') || beat.action.includes('追问') || beat.action.includes('解释')));

  const emotionOnly = analyzeScript('林晓怀疑父亲。父亲尴尬。林晓继续追问。');
  const emotionWeakIssues = emotionOnly.issues.filter((issue) => issue.type === 'weak_action');
  assert.equal(emotionWeakIssues.length, 2);
  assert.ok(emotionWeakIssues.every((issue) => issue.resolved));
  assert.ok(emotionWeakIssues.every((issue) => !issue.suggestion.includes('等待其反应')));

  const modelLike = normalizeAnalysisResult({
    characters: ['林晓', '父亲'], score: 90, executionPrompt: '',
    beats: dialogueOnly.beats.map((beat) => ({ ...beat, action: '保持当前站位，把注意力转向对方，等待其反应' })),
    issues: dialogueOnly.beats.map((beat, index) => ({
      id: `M${index + 1}`, severity: 'soft', type: 'weak_action', targetId: beat.id,
      title: '缺少明确的可执行动作', detail: '模型重复提示', suggestion: '补充动作：等待其反应', resolved: false,
    })),
  }, '林晓：“你为什么不告诉我？”父亲：“这不重要。”');
  assert.equal(modelLike.issues.filter((issue) => issue.type === 'weak_action').length, 0);
  assert.ok(modelLike.beats.every((beat) => !beat.action.includes('等待其反应')));

  const rosterAndPerformance = normalizeAnalysisResult({
    characters: ['林玄, 张宸'], score: 60, executionPrompt: '',
    beats: [{
      id: 'B01', source: '辅导员贴出名单。', actor: '辅导员', receiver: '林玄',
      trigger: '名单公布', goal: '公布结果', action: '抬手把名单贴在公告栏上', dialogue: '',
      reaction: '林玄抬眼确认自己的名字', response: '林玄点头并退到一旁', stateBefore: '等待', stateAfter: '确认',
    }],
    issues: [
      { id: 'R1', severity: 'soft', type: 'missing_character', targetId: 'B01', title: '辅导员角色未在characters中列出', detail: '辅导员在b1中出现，但characters数组未包含该角色。', suggestion: '补入人物表', resolved: false },
      { id: 'R2', severity: 'soft', type: 'abstract_emotion', targetId: 'B01', title: '内心独白中的抽象情绪', detail: '需要转为动作', suggestion: '补动作', resolved: false },
      { id: 'R3', severity: 'soft', type: 'missing_response', targetId: 'B01', title: '回应缺失', detail: '需要回应', suggestion: '补回应', resolved: false },
    ],
  }, '辅导员贴出名单。林玄抬眼确认名字后点头。');
  assert.ok(rosterAndPerformance.characters.includes('辅导员'));
  assert.deepEqual(rosterAndPerformance.characters, ['林玄', '张宸', '辅导员']);
  assert.ok(rosterAndPerformance.issues.every((issue) => issue.resolved));

  const placeholderResponse = normalizeAnalysisResult({
    characters: ['甲', '乙'], score: 70, executionPrompt: '',
    beats: [{
      id: 'B01', source: '甲把信封递给乙。', actor: '甲', receiver: '乙', trigger: '甲取出信封', goal: '让乙查看内容',
      action: '甲伸手把信封递到乙面前', dialogue: '', reaction: '乙低头看向信封', response: '以接下来的行动回应', stateBefore: '戒备', stateAfter: '迟疑',
    }],
    issues: [{ id: 'P1', severity: 'soft', type: 'missing_response', targetId: 'B01', title: '回应缺失', detail: '占位回应不可拍', suggestion: '补充回应', resolved: false }],
  }, '甲把信封递给乙。');
  assert.equal(placeholderResponse.beats[0].response.includes('以接下来的行动回应'), false);
  assert.equal(placeholderResponse.issues[0].resolved, true);

console.log('cross-scene regression checks passed');
