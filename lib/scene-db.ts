import { env } from 'cloudflare:workers';

import { createProjectsTableSql, createSceneOrderIndexSql, createSceneStatesTableSql } from '@/db/schema';
import { buildSceneProductionSummary, DEFAULT_PROJECT_ID } from '@/lib/scene-state';
import type {
  DeliveryShotStatus, DeliveryTrackingState, SceneProject,
  SceneSnapshot, StoredScene, StoredSceneDetail,
} from '@/lib/scene-state';
import type { AnalysisResult } from '@/lib/script-engine';
import type { StoryboardResult } from '@/lib/storyboard-engine';

interface SceneRow {
  id: string;
  project_id: string;
  scene_number: number;
  episode_number?: number | null;
  scene_order?: number | null;
  title: string;
  script: string;
  analysis_json?: string;
  storyboard_json?: string;
  snapshot_json: string;
  delivery_tracking_json?: string | null;
  created_at: string;
}

interface ProjectRow {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
}

function database() {
  return (env as unknown as { DB: D1Database }).DB;
}

let schemaPromise: Promise<void> | null = null;

async function ensureSchema() {
  schemaPromise ??= (async () => {
    const db = database();
    await db.prepare(createProjectsTableSql).run();
    await db.prepare(createSceneStatesTableSql).run();
    await db.prepare(createSceneOrderIndexSql).run();
    const columns = await db.prepare('PRAGMA table_info(scene_states)').all<{ name: string }>();
    if (!columns.results.some((column) => column.name === 'delivery_tracking_json')) {
      try {
        await db.prepare("ALTER TABLE scene_states ADD COLUMN delivery_tracking_json TEXT NOT NULL DEFAULT '{}'").run();
      } catch (error) {
        // Another isolate may have applied the additive migration between the check and ALTER.
        if (!String(error).toLowerCase().includes('duplicate column')) throw error;
      }
    }
    if (!columns.results.some((column) => column.name === 'project_id')) {
      try {
        await db.prepare("ALTER TABLE scene_states ADD COLUMN project_id TEXT NOT NULL DEFAULT 'default'").run();
      } catch (error) {
        if (!String(error).toLowerCase().includes('duplicate column')) throw error;
      }
    }
    if (!columns.results.some((column) => column.name === 'episode_number')) {
      try {
        await db.prepare('ALTER TABLE scene_states ADD COLUMN episode_number INTEGER NOT NULL DEFAULT 1').run();
      } catch (error) {
        if (!String(error).toLowerCase().includes('duplicate column')) throw error;
      }
    }
    const addedSceneOrder = !columns.results.some((column) => column.name === 'scene_order');
    if (addedSceneOrder) {
      try {
        await db.prepare('ALTER TABLE scene_states ADD COLUMN scene_order INTEGER NOT NULL DEFAULT 0').run();
      } catch (error) {
        if (!String(error).toLowerCase().includes('duplicate column')) throw error;
      }
      await db.prepare('UPDATE scene_states SET scene_order = scene_number WHERE scene_order = 0').run();
    }
    await db.prepare(
      'INSERT OR IGNORE INTO projects (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)',
    ).bind(DEFAULT_PROJECT_ID, '未命名短剧项目', new Date().toISOString(), new Date().toISOString()).run();
  })();
  return schemaPromise;
}

function toSceneProject(row: ProjectRow): SceneProject {
  return {
    id: row.id,
    name: row.name,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
  };
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
  const deliveryTracking = normalizeDeliveryTracking(row.delivery_tracking_json ? JSON.parse(row.delivery_tracking_json) : null);
  const storyboard = row.storyboard_json ? JSON.parse(row.storyboard_json) as StoryboardResult : null;
  return {
    id: row.id,
    projectId: row.project_id || DEFAULT_PROJECT_ID,
    sceneNumber: row.scene_number,
    episodeNumber: Math.max(1, Number(row.episode_number) || 1),
    sceneOrder: Math.max(1, Number(row.scene_order) || row.scene_number),
    title: row.title,
    script: row.script,
    snapshot: JSON.parse(row.snapshot_json) as SceneSnapshot,
    deliveryTracking,
    summary: buildSceneProductionSummary(storyboard, deliveryTracking),
    createdAt: row.created_at,
  };
}

function toStoredSceneDetail(row: SceneRow): StoredSceneDetail {
  if (!row.analysis_json || !row.storyboard_json) throw new Error('场次详情数据不完整');
  return {
    ...toStoredScene(row),
    analysis: JSON.parse(row.analysis_json) as AnalysisResult,
    storyboard: JSON.parse(row.storyboard_json) as StoryboardResult,
  };
}

export async function getProject(id = DEFAULT_PROJECT_ID) {
  await ensureSchema();
  const row = await database().prepare(
    'SELECT id, name, created_at, updated_at FROM projects WHERE id = ?',
  ).bind(id).first<ProjectRow>();
  return row ? toSceneProject(row) : null;
}

export async function updateProjectName(name: string, id = DEFAULT_PROJECT_ID) {
  await ensureSchema();
  const trimmed = name.trim().slice(0, 80);
  if (!trimmed) return null;
  const updatedAt = new Date().toISOString();
  await database().prepare(
    'UPDATE projects SET name = ?, updated_at = ? WHERE id = ?',
  ).bind(trimmed, updatedAt, id).run();
  return getProject(id);
}

export async function listScenes(projectId = DEFAULT_PROJECT_ID, limit = 30) {
  await ensureSchema();
  const result = await database().prepare(
    `SELECT id, project_id, scene_number, episode_number, scene_order, title, script, storyboard_json, snapshot_json, delivery_tracking_json, created_at
     FROM scene_states WHERE project_id = ? ORDER BY scene_order DESC, scene_number DESC LIMIT ?`,
  ).bind(projectId, Math.max(1, Math.min(100, limit))).all<SceneRow>();
  return result.results.map(toStoredScene);
}

export async function getLatestScene(projectId = DEFAULT_PROJECT_ID) {
  await ensureSchema();
  const row = await database().prepare(
    `SELECT id, project_id, scene_number, episode_number, scene_order, title, script, storyboard_json, snapshot_json, delivery_tracking_json, created_at
     FROM scene_states WHERE project_id = ? ORDER BY scene_order DESC, scene_number DESC LIMIT 1`,
  ).bind(projectId).first<SceneRow>();
  return row ? toStoredScene(row) : null;
}

export async function getSceneById(id: string) {
  await ensureSchema();
  const row = await database().prepare(
    `SELECT id, project_id, scene_number, episode_number, scene_order, title, script, analysis_json, storyboard_json,
       snapshot_json, delivery_tracking_json, created_at
     FROM scene_states WHERE id = ?`,
  ).bind(id).first<SceneRow>();
  return row ? toStoredSceneDetail(row) : null;
}

export async function saveScene(input: {
  projectId?: string;
  episodeNumber?: number;
  title: string;
  sourceHash: string;
  script: string;
  analysis: AnalysisResult;
  storyboard: StoryboardResult;
  snapshot: SceneSnapshot;
  deliveryTracking?: unknown;
}) {
  await ensureSchema();
  const projectId = input.projectId?.trim() || DEFAULT_PROJECT_ID;
  const episodeNumber = Math.max(1, Math.min(999, Math.round(Number(input.episodeNumber) || 1)));
  const project = await getProject(projectId);
  if (!project) throw new Error('项目不存在');
  const existing = await database().prepare(
    'SELECT id, scene_number, episode_number, scene_order FROM scene_states WHERE source_hash = ?',
  ).bind(input.sourceHash).first<{ id: string; scene_number: number; episode_number: number; scene_order: number }>();
  const createdAt = new Date().toISOString();
  const shotIds = new Set(input.storyboard.shots.map((shot) => shot.id));
  const deliveryTracking = normalizeDeliveryTracking(input.deliveryTracking, shotIds);
  deliveryTracking.updatedAt = deliveryTracking.updatedAt ?? createdAt;

  if (existing) {
    await database().prepare(
      `UPDATE scene_states SET episode_number = ?, title = ?, script = ?, analysis_json = ?, storyboard_json = ?,
       snapshot_json = ?, delivery_tracking_json = ?, created_at = ? WHERE id = ?`,
    ).bind(
      episodeNumber, input.title, input.script, JSON.stringify(input.analysis), JSON.stringify(input.storyboard),
      JSON.stringify(input.snapshot), JSON.stringify(deliveryTracking), createdAt, existing.id,
    ).run();
    return {
      id: existing.id,
      sceneNumber: existing.scene_number,
      episodeNumber,
      sceneOrder: existing.scene_order,
      updated: true,
    };
  }

  const latest = await database().prepare(
    'SELECT COALESCE(MAX(scene_number), 0) AS latest FROM scene_states',
  ).first<{ latest: number }>();
  const sceneNumber = Number(latest?.latest ?? 0) + 1;
  const latestOrder = await database().prepare(
    'SELECT COALESCE(MAX(scene_order), 0) AS latest FROM scene_states WHERE project_id = ?',
  ).bind(projectId).first<{ latest: number }>();
  const sceneOrder = Number(latestOrder?.latest ?? 0) + 1;
  const id = crypto.randomUUID();
  await database().prepare(
    `INSERT INTO scene_states
     (id, project_id, scene_number, episode_number, scene_order, title, source_hash, script, analysis_json, storyboard_json, snapshot_json, delivery_tracking_json, created_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
  ).bind(
    id, projectId, sceneNumber, episodeNumber, sceneOrder, input.title, input.sourceHash, input.script,
    JSON.stringify(input.analysis), JSON.stringify(input.storyboard),
    JSON.stringify(input.snapshot), JSON.stringify(deliveryTracking), createdAt,
  ).run();
  return { id, sceneNumber, episodeNumber, sceneOrder, updated: false };
}

export async function moveScene(input: { sceneId: string; direction: 'up' | 'down' }) {
  await ensureSchema();
  const db = database();
  const current = await db.prepare(
    'SELECT id, project_id, episode_number, scene_order FROM scene_states WHERE id = ?',
  ).bind(input.sceneId).first<{ id: string; project_id: string; episode_number: number; scene_order: number }>();
  if (!current) return null;
  const comparison = input.direction === 'up' ? '<' : '>';
  const order = input.direction === 'up' ? 'DESC' : 'ASC';
  const adjacent = await db.prepare(
    `SELECT id, scene_order FROM scene_states
     WHERE project_id = ? AND episode_number = ? AND scene_order ${comparison} ?
     ORDER BY scene_order ${order}, scene_number ${order} LIMIT 1`,
  ).bind(current.project_id, current.episode_number, current.scene_order).first<{ id: string; scene_order: number }>();
  if (!adjacent) return { moved: false };
  const temporaryOrder = Math.max(current.scene_order, adjacent.scene_order) + 1000000;
  await db.batch([
    db.prepare('UPDATE scene_states SET scene_order = ? WHERE id = ?').bind(temporaryOrder, current.id),
    db.prepare('UPDATE scene_states SET scene_order = ? WHERE id = ?').bind(current.scene_order, adjacent.id),
    db.prepare('UPDATE scene_states SET scene_order = ? WHERE id = ?').bind(adjacent.scene_order, current.id),
  ]);
  return { moved: true };
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
