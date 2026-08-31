import assert from 'node:assert/strict';
import path from 'node:path';
import { runnerImport } from 'vite';

const loadOptions = { resolve: { alias: { '@': process.cwd() } } };
const { module: episodeModule } = await runnerImport(path.resolve('lib/episode-review.ts'), loadOptions);
const { module: stateModule } = await runnerImport(path.resolve('lib/scene-state.ts'), loadOptions);
const { module: aiReviewModule } = await runnerImport(path.resolve('lib/episode-ai-review.ts'), loadOptions);

const { buildEpisodeReview } = episodeModule;
const { buildSceneSnapshot } = stateModule;
const { buildEpisodeSourceHash } = aiReviewModule;

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

console.log('cross-scene regression checks passed');
