import { env } from 'cloudflare:workers';

import { createSceneStatesTableSql } from '@/db/schema';
import type { SceneSnapshot, StoredScene } from '@/lib/scene-state';
import type { AnalysisResult } from '@/lib/script-engine';
import type { StoryboardResult } from '@/lib/storyboard-engine';

interface SceneRow {
  id: string;
  scene_number: number;
  title: string;
  script: string;
  snapshot_json: string;
  created_at: string;
}

function database() {
  return (env as unknown as { DB: D1Database }).DB;
}

let schemaPromise: Promise<void> | null = null;

async function ensureSchema() {
  schemaPromise ??= database().prepare(createSceneStatesTableSql).run().then(() => undefined);
  return schemaPromise;
}

function toStoredScene(row: SceneRow): StoredScene {
  return {
    id: row.id,
    sceneNumber: row.scene_number,
    title: row.title,
    script: row.script,
    snapshot: JSON.parse(row.snapshot_json) as SceneSnapshot,
    createdAt: row.created_at,
  };
}

export async function listScenes(limit = 30) {
  await ensureSchema();
  const result = await database().prepare(
    `SELECT id, scene_number, title, script, snapshot_json, created_at
     FROM scene_states ORDER BY scene_number DESC LIMIT ?`,
  ).bind(Math.max(1, Math.min(100, limit))).all<SceneRow>();
  return result.results.map(toStoredScene);
}

export async function getLatestScene() {
  await ensureSchema();
  const row = await database().prepare(
    `SELECT id, scene_number, title, script, snapshot_json, created_at
     FROM scene_states ORDER BY scene_number DESC LIMIT 1`,
  ).first<SceneRow>();
  return row ? toStoredScene(row) : null;
}

export async function saveScene(input: {
  title: string;
  sourceHash: string;
  script: string;
  analysis: AnalysisResult;
  storyboard: StoryboardResult;
  snapshot: SceneSnapshot;
}) {
  await ensureSchema();
  const existing = await database().prepare(
    'SELECT id, scene_number FROM scene_states WHERE source_hash = ?',
  ).bind(input.sourceHash).first<{ id: string; scene_number: number }>();
  const createdAt = new Date().toISOString();

  if (existing) {
    await database().prepare(
      `UPDATE scene_states SET title = ?, script = ?, analysis_json = ?, storyboard_json = ?,
       snapshot_json = ?, created_at = ? WHERE id = ?`,
    ).bind(
      input.title, input.script, JSON.stringify(input.analysis), JSON.stringify(input.storyboard),
      JSON.stringify(input.snapshot), createdAt, existing.id,
    ).run();
    return { id: existing.id, sceneNumber: existing.scene_number, updated: true };
  }

  const latest = await database().prepare(
    'SELECT COALESCE(MAX(scene_number), 0) AS latest FROM scene_states',
  ).first<{ latest: number }>();
  const sceneNumber = Number(latest?.latest ?? 0) + 1;
  const id = crypto.randomUUID();
  await database().prepare(
    `INSERT INTO scene_states
     (id, scene_number, title, source_hash, script, analysis_json, storyboard_json, snapshot_json, created_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
  ).bind(
    id, sceneNumber, input.title, input.sourceHash, input.script,
    JSON.stringify(input.analysis), JSON.stringify(input.storyboard),
    JSON.stringify(input.snapshot), createdAt,
  ).run();
  return { id, sceneNumber, updated: false };
}
