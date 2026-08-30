import { env } from 'cloudflare:workers';

import { createSceneStatesTableSql } from '@/db/schema';
import type {
  DeliveryShotStatus, DeliveryTrackingState, SceneSnapshot, StoredScene,
} from '@/lib/scene-state';
import type { AnalysisResult } from '@/lib/script-engine';
import type { StoryboardResult } from '@/lib/storyboard-engine';

interface SceneRow {
  id: string;
  scene_number: number;
  title: string;
  script: string;
  snapshot_json: string;
  delivery_tracking_json?: string | null;
  created_at: string;
}

function database() {
  return (env as unknown as { DB: D1Database }).DB;
}

let schemaPromise: Promise<void> | null = null;

async function ensureSchema() {
  schemaPromise ??= (async () => {
    const db = database();
    await db.prepare(createSceneStatesTableSql).run();
    const columns = await db.prepare('PRAGMA table_info(scene_states)').all<{ name: string }>();
    if (!columns.results.some((column) => column.name === 'delivery_tracking_json')) {
      try {
        await db.prepare("ALTER TABLE scene_states ADD COLUMN delivery_tracking_json TEXT NOT NULL DEFAULT '{}'").run();
      } catch (error) {
        // Another isolate may have applied the additive migration between the check and ALTER.
        if (!String(error).toLowerCase().includes('duplicate column')) throw error;
      }
    }
  })();
  return schemaPromise;
}

const deliveryStatuses = new Set<DeliveryShotStatus>(['pending', 'submitted', 'accepted']);

function normalizeDeliveryTracking(value: unknown, shotIds?: Set<string>): DeliveryTrackingState {
  const raw = value && typeof value === 'object' ? value as { statuses?: unknown; updatedAt?: unknown } : {};
  const statuses: Record<string, DeliveryShotStatus> = {};
  if (raw.statuses && typeof raw.statuses === 'object') {
    for (const [shotId, status] of Object.entries(raw.statuses)) {
      if (shotIds && !shotIds.has(shotId)) continue;
      if (deliveryStatuses.has(status as DeliveryShotStatus) && status !== 'pending') {
        statuses[shotId] = status as DeliveryShotStatus;
      }
    }
  }
  const updatedAt = typeof raw.updatedAt === 'string' && raw.updatedAt ? raw.updatedAt : null;
  return { statuses, updatedAt };
}

function toStoredScene(row: SceneRow): StoredScene {
  return {
    id: row.id,
    sceneNumber: row.scene_number,
    title: row.title,
    script: row.script,
    snapshot: JSON.parse(row.snapshot_json) as SceneSnapshot,
    deliveryTracking: normalizeDeliveryTracking(row.delivery_tracking_json ? JSON.parse(row.delivery_tracking_json) : null),
    createdAt: row.created_at,
  };
}

export async function listScenes(limit = 30) {
  await ensureSchema();
  const result = await database().prepare(
    `SELECT id, scene_number, title, script, snapshot_json, delivery_tracking_json, created_at
     FROM scene_states ORDER BY scene_number DESC LIMIT ?`,
  ).bind(Math.max(1, Math.min(100, limit))).all<SceneRow>();
  return result.results.map(toStoredScene);
}

export async function getLatestScene() {
  await ensureSchema();
  const row = await database().prepare(
    `SELECT id, scene_number, title, script, snapshot_json, delivery_tracking_json, created_at
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
  deliveryTracking?: unknown;
}) {
  await ensureSchema();
  const existing = await database().prepare(
    'SELECT id, scene_number FROM scene_states WHERE source_hash = ?',
  ).bind(input.sourceHash).first<{ id: string; scene_number: number }>();
  const createdAt = new Date().toISOString();
  const shotIds = new Set(input.storyboard.shots.map((shot) => shot.id));
  const deliveryTracking = normalizeDeliveryTracking(input.deliveryTracking, shotIds);
  deliveryTracking.updatedAt = deliveryTracking.updatedAt ?? createdAt;

  if (existing) {
    await database().prepare(
      `UPDATE scene_states SET title = ?, script = ?, analysis_json = ?, storyboard_json = ?,
       snapshot_json = ?, delivery_tracking_json = ?, created_at = ? WHERE id = ?`,
    ).bind(
      input.title, input.script, JSON.stringify(input.analysis), JSON.stringify(input.storyboard),
      JSON.stringify(input.snapshot), JSON.stringify(deliveryTracking), createdAt, existing.id,
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
     (id, scene_number, title, source_hash, script, analysis_json, storyboard_json, snapshot_json, delivery_tracking_json, created_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
  ).bind(
    id, sceneNumber, input.title, input.sourceHash, input.script,
    JSON.stringify(input.analysis), JSON.stringify(input.storyboard),
    JSON.stringify(input.snapshot), JSON.stringify(deliveryTracking), createdAt,
  ).run();
  return { id, sceneNumber, updated: false };
}

export async function updateSceneDeliveryTracking(input: {
  sceneId: string;
  tracking: unknown;
}) {
  await ensureSchema();
  const row = await database().prepare(
    'SELECT storyboard_json FROM scene_states WHERE id = ?',
  ).bind(input.sceneId).first<{ storyboard_json: string }>();
  if (!row) return null;
  const storyboard = JSON.parse(row.storyboard_json) as StoryboardResult;
  const shotIds = new Set(storyboard.shots.map((shot) => shot.id));
  const tracking = normalizeDeliveryTracking(input.tracking, shotIds);
  tracking.updatedAt = new Date().toISOString();
  await database().prepare(
    'UPDATE scene_states SET delivery_tracking_json = ? WHERE id = ?',
  ).bind(JSON.stringify(tracking), input.sceneId).run();
  return tracking;
}
