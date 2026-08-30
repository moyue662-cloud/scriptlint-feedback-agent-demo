'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle, ArrowDown, ArrowRight, ArrowUp, Check, ChevronRight, Clipboard, Download,
  Camera, Clock, Database, FileText, Film, GitBranch, GripVertical, Loader2, Play,
  PackageCheck, RefreshCcw, Save, ScanSearch, Sparkles, Users,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Progress } from '@/components/ui/progress';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import {
  analyzeScript, repairAnalysis, type AnalysisResult, type AnalysisSource,
} from '@/lib/script-engine';
import { DEFAULT_PROJECT_ID } from '@/lib/scene-state';
import type { DeliveryShotStatus, SceneProductionStatus, SceneProject, StoredScene, StoredSceneDetail } from '@/lib/scene-state';
import {
  buildFallbackStoryboard, finalizeStoryboard, type ShotState, type StoryboardResult,
} from '@/lib/storyboard-engine';
import {
  buildVideoDeliveryPackage, validateVideoDeliveryPackage, videoDeliveryToMarkdown,
  type DeliveryAspectRatio, type VideoDeliveryPackage,
} from '@/lib/video-delivery';

const deliveryStatusLabels: Record<DeliveryShotStatus, string> = {
  pending: '待提交', submitted: '已提交', accepted: '已验收',
};

const sceneStatusLabels: Record<SceneProductionStatus, string> = {
  ready: '待制作', 'needs-review': '需复核', 'in-production': '制作中', completed: '已完成',
};

const sceneStatusClasses: Record<SceneProductionStatus, string> = {
  ready: 'border-slate-200 bg-slate-50 text-slate-700',
  'needs-review': 'border-amber-200 bg-amber-50 text-amber-800',
  'in-production': 'border-sky-200 bg-sky-50 text-sky-800',
  completed: 'border-emerald-200 bg-emerald-50 text-emerald-800',
};

const sampleScript = `客厅，夜晚。
林晓发现桌上父亲的辞职通知书，很生气地质问父亲：“你什么时候辞职的？”
父亲很尴尬，试图隐瞒：“这不重要。”
林晓不相信父亲的解释，继续追问。父亲沉默。`;

const AI_REQUEST_TIMEOUT_MS = 30000;
const PIPELINE_LOOP_LIMIT = 3;

type PipelinePhase = 'idle' | 'analyzing' | 'repairing_script' | 'generating_storyboard' | 'repairing_storyboard' | 'complete' | 'blocked' | 'error';
const pipelinePhaseLabels: Record<PipelinePhase, string> = {
  idle: '未运行', analyzing: '分析剧本', repairing_script: '修复剧本结构',
  generating_storyboard: '生成分镜', repairing_storyboard: '修复分镜连续性',
  complete: '已完成', blocked: '等待处理', error: '运行失败',
};
const pipelinePhaseProgress: Record<PipelinePhase, number> = {
  idle: 0, analyzing: 12, repairing_script: 34, generating_storyboard: 58,
  repairing_storyboard: 78, complete: 100, blocked: 100, error: 100,
};

const pipeline = [
  { id: '01', label: '剧本理解', icon: FileText },
  { id: '02', label: '交互节拍', icon: GitBranch },
  { id: '03', label: '状态建模', icon: Users },
  { id: '04', label: '规则检查', icon: ScanSearch },
  { id: '05', label: '分镜生成', icon: Camera },
  { id: '06', label: '连续性验证', icon: Film },
  { id: '07', label: '跨场继承', icon: Database },
];

export default function Home() {
  const [script, setScript] = useState(sampleScript);
  const [result, setResult] = useState<AnalysisResult>(() => analyzeScript(sampleScript));
  const [loopCount, setLoopCount] = useState(0);
  const [copied, setCopied] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [source, setSource] = useState<AnalysisSource>('local');
  const [notice, setNotice] = useState('');
  const [storyboard, setStoryboard] = useState<StoryboardResult | null>(null);
  const [isStoryboardRunning, setIsStoryboardRunning] = useState(false);
  const [storyboardCopied, setStoryboardCopied] = useState(false);
  const [storyboardLoopCount, setStoryboardLoopCount] = useState(0);
  const [scenes, setScenes] = useState<StoredScene[]>([]);
  const [sceneTitle, setSceneTitle] = useState('');
  const [episodeNumber, setEpisodeNumber] = useState(1);
  const [selectedEpisode, setSelectedEpisode] = useState<number | 'all'>('all');
  const [isSceneSaving, setIsSceneSaving] = useState(false);
  const [isSceneLoading, setIsSceneLoading] = useState(false);
  const [isSceneReordering, setIsSceneReordering] = useState(false);
  const [draggingSceneId, setDraggingSceneId] = useState<string | null>(null);
  const [dragOverSceneId, setDragOverSceneId] = useState<string | null>(null);
  const [project, setProject] = useState<SceneProject | null>(null);
  const [projectName, setProjectName] = useState('');
  const [isProjectSaving, setIsProjectSaving] = useState(false);
  const [isPipelineRunning, setIsPipelineRunning] = useState(false);
  const [pipelinePhase, setPipelinePhase] = useState<PipelinePhase>('idle');
  const [pipelineStep, setPipelineStep] = useState('');
  const [previousSceneNumber, setPreviousSceneNumber] = useState<number | null>(null);
  const [reviewedShotIds, setReviewedShotIds] = useState<string[]>([]);
  const [deliveryAspectRatio, setDeliveryAspectRatio] = useState<DeliveryAspectRatio>('9:16');
  const [deliveryCopied, setDeliveryCopied] = useState(false);
  const [deliveryShotStatuses, setDeliveryShotStatuses] = useState<Record<string, DeliveryShotStatus>>({});
  const deliverySaveQueue = useRef<Promise<void>>(Promise.resolve());

  async function loadScenes() {
    try {
      const response = await fetch('/api/scenes');
      const payload = await response.json() as { scenes?: StoredScene[] };
      if (response.ok && payload.scenes) setScenes(payload.scenes);
    } catch {
      // The current-scene workflow remains usable if persistent history is temporarily unavailable.
    }
  }

  async function loadProject() {
    try {
      const response = await fetch('/api/project');
      const payload = await response.json() as { project?: SceneProject };
      if (response.ok && payload.project) {
        setProject(payload.project);
        setProjectName(payload.project.name);
      }
    } catch {
      // Project metadata is non-blocking; the scene workflow remains usable if it is unavailable.
    }
  }

  async function loadSavedScene(scene: StoredScene) {
    if (busy || isSceneLoading) return;
    setIsSceneLoading(true);
    setNotice('');
    try {
      const response = await fetch(`/api/scenes?id=${encodeURIComponent(scene.id)}`);
      const payload = await response.json() as { scene?: StoredSceneDetail; error?: string };
      if (!response.ok || !payload.scene) throw new Error(payload.error || '场次载入失败');
      const detail = payload.scene;
      setScript(detail.script);
      window.localStorage.setItem('scene-flow-script', detail.script);
      setResult(detail.analysis);
      setSource('saved');
      setLoopCount(0);
      setStoryboard(detail.storyboard);
      setStoryboardLoopCount(0);
      setReviewedShotIds(detail.storyboard.shots.map((shot) => shot.id));
      setDeliveryShotStatuses(detail.deliveryTracking.statuses);
      setDeliveryCopied(false);
      setSceneTitle(detail.title);
      setEpisodeNumber(detail.episodeNumber);
      setPreviousSceneNumber(scenes.find((item) => item.episodeNumber === detail.episodeNumber && item.sceneOrder < detail.sceneOrder)?.sceneOrder ?? null);
      setNotice(`已载入第 ${detail.episodeNumber} 集第 ${detail.sceneOrder} 场，可继续修改或查看制作进度。`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '场次载入失败，请稍后重试。');
    } finally {
      setIsSceneLoading(false);
    }
  }

  async function saveProjectName() {
    if (!projectName.trim() || isProjectSaving || busy) return;
    setIsProjectSaving(true);
    setNotice('');
    try {
      const response = await fetch('/api/project', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: projectName }),
      });
      const payload = await response.json() as { project?: SceneProject; error?: string };
      if (!response.ok || !payload.project) throw new Error(payload.error || '项目资料保存失败');
      setProject(payload.project);
      setProjectName(payload.project.name);
      setNotice('项目名称已保存。');
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '项目资料保存失败，请稍后重试。');
    } finally {
      setIsProjectSaving(false);
    }
  }

  useEffect(() => {
    const saved = window.localStorage.getItem('scene-flow-script');
    if (saved) {
      setScript(saved);
      setResult(analyzeScript(saved));
    }
    void loadScenes();
    void loadProject();
  }, []);

  const activeIssues = useMemo(() => result.issues.filter((issue) => !issue.resolved), [result]);
  const hardIssues = activeIssues.filter((issue) => issue.severity === 'hard');
  const activeContinuityIssues = storyboard?.issues.filter((issue) => !issue.resolved) ?? [];
  const busy = isRunning || isStoryboardRunning || isSceneSaving || isSceneLoading || isSceneReordering || isPipelineRunning || isProjectSaving;
  const latestScene = scenes[0] ?? null;
  const sceneTimeline = useMemo(() => {
    const ordered = [...scenes].sort((a, b) => a.sceneOrder - b.sceneOrder || a.sceneNumber - b.sceneNumber);
    const totalShots = ordered.reduce((total, scene) => total + scene.summary.shotCount, 0);
    const totalDurationSec = ordered.reduce((total, scene) => total + scene.summary.durationSec, 0);
    const acceptedShots = ordered.reduce((total, scene) => total + scene.summary.acceptedShotCount, 0);
    const statusCounts = ordered.reduce<Record<SceneProductionStatus, number>>((counts, scene) => {
      counts[scene.summary.status] += 1;
      return counts;
    }, { ready: 0, 'needs-review': 0, 'in-production': 0, completed: 0 });
    const episodes = Array.from(new Set(ordered.map((scene) => scene.episodeNumber))).map((episodeNumber) => ({
      episodeNumber,
      scenes: ordered.filter((scene) => scene.episodeNumber === episodeNumber),
    }));
    return {
      scenes: ordered,
      episodes,
      totalShots,
      totalDurationSec,
      acceptedShots,
      productionProgress: totalShots > 0 ? Math.round((acceptedShots / totalShots) * 100) : 0,
      statusCounts,
    };
  }, [scenes]);
  const visibleTimeline = useMemo(() => {
    const visibleScenes = selectedEpisode === 'all'
      ? sceneTimeline.scenes
      : sceneTimeline.scenes.filter((scene) => scene.episodeNumber === selectedEpisode);
    const totalShots = visibleScenes.reduce((total, scene) => total + scene.summary.shotCount, 0);
    const totalDurationSec = visibleScenes.reduce((total, scene) => total + scene.summary.durationSec, 0);
    const acceptedShots = visibleScenes.reduce((total, scene) => total + scene.summary.acceptedShotCount, 0);
    const episodes = Array.from(new Set(visibleScenes.map((scene) => scene.episodeNumber))).map((episodeNumber) => ({
      episodeNumber,
      scenes: visibleScenes.filter((scene) => scene.episodeNumber === episodeNumber),
    }));
    return {
      scenes: visibleScenes,
      episodes,
      totalShots,
      totalDurationSec,
      productionProgress: totalShots > 0 ? Math.round((acceptedShots / totalShots) * 100) : 0,
    };
  }, [sceneTimeline, selectedEpisode]);
  const episodeOptions = useMemo(
    () => Array.from(new Set(scenes.map((scene) => scene.episodeNumber))).sort((a, b) => a - b),
    [scenes],
  );
  const activeSavedScene = useMemo(
    () => script.trim() ? scenes.find((scene) => scene.script.trim() === script.trim()) ?? null : null,
    [scenes, script],
  );
  const hasHardStoryboardIssues = activeContinuityIssues.some((issue) => issue.severity === 'hard');
  const reviewedShotSet = useMemo(() => new Set(reviewedShotIds), [reviewedShotIds]);
  const reviewedShotCount = storyboard?.shots.filter((shot) => reviewedShotSet.has(shot.id)).length ?? 0;
  const allShotsReviewed = Boolean(storyboard?.shots.length) && reviewedShotCount === storyboard?.shots.length;
  const canSaveScene = Boolean(storyboard) && allShotsReviewed && hardIssues.length === 0 && !hasHardStoryboardIssues;
  const deliveryPackage = useMemo<VideoDeliveryPackage | null>(() => storyboard
    ? buildVideoDeliveryPackage(storyboard, {
        aspectRatio: deliveryAspectRatio,
        resolution: deliveryAspectRatio === '9:16' ? '1080×1920' : '1920×1080',
        style: '写实短剧，电影级自然光，表演克制，台词清晰',
    })
    : null, [storyboard, deliveryAspectRatio]);
  const deliveryValidation = useMemo(() => deliveryPackage ? validateVideoDeliveryPackage(deliveryPackage) : null, [deliveryPackage]);
  const deliveryHasHardIssues = hardIssues.length > 0 || hasHardStoryboardIssues;
  const canDeliver = allShotsReviewed && !deliveryHasHardIssues && deliveryValidation?.valid === true;
  const deliveryTracking = useMemo(() => {
    const shots = deliveryPackage?.shots ?? [];
    const submittedCount = shots.filter((shot) => deliveryShotStatuses[shot.id] === 'submitted' || deliveryShotStatuses[shot.id] === 'accepted').length;
    const acceptedCount = shots.filter((shot) => deliveryShotStatuses[shot.id] === 'accepted').length;
    return { total: shots.length, submittedCount, acceptedCount, complete: shots.length > 0 && acceptedCount === shots.length };
  }, [deliveryPackage, deliveryShotStatuses]);

  async function requestAI(body: Record<string, unknown>) {
    const response = await fetch('/api/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(AI_REQUEST_TIMEOUT_MS),
    });
    const payload = await response.json() as {
      result?: AnalysisResult;
      error?: string;
      meta?: { previousSceneNumber?: number | null };
    };
    if (!response.ok || !payload.result) throw new Error(payload.error || '智能分析失败');
    setPreviousSceneNumber(payload.meta?.previousSceneNumber ?? null);
    return payload.result;
  }

  async function runFullPipeline() {
    if (!script.trim() || busy) return;
    setIsPipelineRunning(true);
    setPipelinePhase('analyzing');
    setPipelineStep('正在读取原始剧本并建立交互节拍');
    setNotice('');
    window.localStorage.setItem('scene-flow-script', script);
    setLoopCount(0);
    setStoryboardLoopCount(0);
    setStoryboard(null);
    setReviewedShotIds([]);
    setDeliveryShotStatuses({});
    setDeliveryCopied(false);
    try {
      let analysis: AnalysisResult;
      let analysisSource: AnalysisSource = 'ai';
      try {
        analysis = await requestAI({ script, mode: 'analyze' });
      } catch {
        analysis = analyzeScript(script);
        analysisSource = 'local';
      }
      setResult(analysis);
      setSource(analysisSource);
      let scriptRepairCount = 0;
      while (analysis.issues.some((issue) => !issue.resolved) && scriptRepairCount < PIPELINE_LOOP_LIMIT) {
        setPipelinePhase('repairing_script');
        setPipelineStep(`正在运行剧本修复 Loop ${scriptRepairCount + 1}/${PIPELINE_LOOP_LIMIT}`);
        try {
          analysis = await requestAI({
            script, mode: 'repair', current: analysis, loopCount: scriptRepairCount + 1,
          });
          analysisSource = 'ai';
        } catch {
          analysis = repairAnalysis(analysis);
          analysisSource = 'local';
        }
        scriptRepairCount += 1;
        setResult(analysis);
        setSource(analysisSource);
        setLoopCount(scriptRepairCount);
      }
      if (analysis.issues.some((issue) => !issue.resolved && issue.severity === 'hard')) {
        setPipelinePhase('blocked');
        setPipelineStep('剧本仍有硬问题，已停止自动推进');
        setNotice('全流程已在剧本阶段暂停。请先补充人物或明确交互对象，再重新运行。');
        return;
      }

      setPipelinePhase('generating_storyboard');
      setPipelineStep('正在把交互节拍转换成连续性分镜');
      let nextStoryboard: StoryboardResult;
      try {
        const response = await fetch('/api/storyboard', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ script, analysis }),
        });
        const payload = await response.json() as { result?: StoryboardResult; error?: string };
        if (!response.ok || !payload.result) throw new Error(payload.error || '分镜生成失败');
        nextStoryboard = payload.result;
      } catch {
        nextStoryboard = finalizeStoryboard(buildFallbackStoryboard(analysis), analysis);
      }
      setStoryboard(nextStoryboard);
      setStoryboardLoopCount(0);
      setReviewedShotIds([]);
      setDeliveryShotStatuses({});

      let storyboardRepairCount = 0;
      while (nextStoryboard.issues.some((issue) => !issue.resolved) && storyboardRepairCount < PIPELINE_LOOP_LIMIT) {
        setPipelinePhase('repairing_storyboard');
        setPipelineStep(`正在运行分镜修复 Loop ${storyboardRepairCount + 1}/${PIPELINE_LOOP_LIMIT}`);
        try {
          const response = await fetch('/api/storyboard', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              script, analysis, mode: 'repair', current: nextStoryboard,
              loopCount: storyboardRepairCount + 1,
            }),
          });
          const payload = await response.json() as { result?: StoryboardResult; error?: string };
          if (!response.ok || !payload.result) throw new Error(payload.error || '分镜修复失败');
          nextStoryboard = payload.result;
        } catch {
          break;
        }
        storyboardRepairCount += 1;
        setStoryboard(nextStoryboard);
        setStoryboardLoopCount(storyboardRepairCount);
      }
      if (nextStoryboard.issues.some((issue) => !issue.resolved && issue.severity === 'hard')) {
        setPipelinePhase('blocked');
        setPipelineStep('分镜仍有硬问题，已停止自动推进');
        setNotice('全流程已在分镜阶段暂停。请检查连续性报告，修复后再进行人工确认。');
        return;
      }
      const remainingStoryboardIssues = nextStoryboard.issues.filter((issue) => !issue.resolved).length;
      setPipelinePhase('complete');
      setPipelineStep('剧本、交互节拍、分镜和连续性检查已完成');
      setNotice(remainingStoryboardIssues > 0
        ? `全流程完成，但仍有 ${remainingStoryboardIssues} 项软性分镜提示，请人工复核。`
        : '全流程完成，请进入分镜页逐镜确认后保存场次状态。');
    } catch (error) {
      setPipelinePhase('error');
      setPipelineStep('自动流程异常中止');
      setNotice(error instanceof Error ? error.message : '全流程运行失败，请稍后重试。');
    } finally {
      setIsPipelineRunning(false);
    }
  }

  async function runAnalysis() {
    setIsRunning(true);
    setNotice('');
    window.localStorage.setItem('scene-flow-script', script);
    try {
      const next = await requestAI({ script, mode: 'analyze' });
      setResult(next);
      setSource('ai');
      setLoopCount(0);
      setStoryboard(null);
      setStoryboardLoopCount(0);
      setReviewedShotIds([]);
      setDeliveryCopied(false);
      setDeliveryShotStatuses({});
    } catch (error) {
      setResult(analyzeScript(script));
      setSource('local');
      setLoopCount(0);
      setStoryboard(null);
      setStoryboardLoopCount(0);
      setReviewedShotIds([]);
      setDeliveryCopied(false);
      setDeliveryShotStatuses({});
      setNotice(`${error instanceof Error ? error.message : '智能分析暂时不可用'}，已切换到本地规则结果。`);
    } finally {
      setIsRunning(false);
    }
  }

  async function runRepairLoop() {
    if (loopCount >= 3 || activeIssues.length === 0 || isRunning) return;
    setIsRunning(true);
    setNotice('');
    try {
      const next = await requestAI({
        script, mode: 'repair', current: result, loopCount: loopCount + 1,
      });
      setResult(next);
      setSource('ai');
      setLoopCount((current) => current + 1);
      setStoryboard(null);
      setStoryboardLoopCount(0);
      setReviewedShotIds([]);
      setDeliveryCopied(false);
      setDeliveryShotStatuses({});
    } catch (error) {
      setResult((current) => repairAnalysis(current));
      setSource('local');
      setLoopCount((current) => current + 1);
      setStoryboard(null);
      setStoryboardLoopCount(0);
      setReviewedShotIds([]);
      setDeliveryCopied(false);
      setDeliveryShotStatuses({});
      setNotice(`${error instanceof Error ? error.message : '智能修复暂时不可用'}，本轮已由本地规则完成。`);
    } finally {
      setIsRunning(false);
    }
  }

  async function generateStoryboard() {
    if (isStoryboardRunning || !result.beats.length) return;
    setIsStoryboardRunning(true);
    setNotice('');
    try {
      const response = await fetch('/api/storyboard', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ script, analysis: result }),
      });
      const payload = await response.json() as { result?: StoryboardResult; error?: string };
      if (!response.ok || !payload.result) throw new Error(payload.error || '分镜生成失败');
      setStoryboard(payload.result);
      setDeliveryShotStatuses(activeSavedScene ? getPersistedDeliveryStatuses(payload.result) : {});
      setStoryboardLoopCount(0);
      setReviewedShotIds([]);
      setDeliveryCopied(false);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '分镜生成暂时不可用，请稍后重试。');
    } finally {
      setIsStoryboardRunning(false);
    }
  }

  async function repairStoryboardLoop() {
    if (!storyboard || isStoryboardRunning || activeContinuityIssues.length === 0 || storyboardLoopCount >= 3) return;
    setIsStoryboardRunning(true);
    setNotice('');
    try {
      const response = await fetch('/api/storyboard', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          script, analysis: result, mode: 'repair', current: storyboard,
          loopCount: storyboardLoopCount + 1,
        }),
      });
      const payload = await response.json() as { result?: StoryboardResult; error?: string };
      if (!response.ok || !payload.result) throw new Error(payload.error || '分镜修复失败');
      setStoryboard(payload.result);
      setDeliveryShotStatuses({});
      setStoryboardLoopCount((current) => current + 1);
      setReviewedShotIds([]);
      setDeliveryCopied(false);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '分镜修复暂时不可用，请稍后重试。');
    } finally {
      setIsStoryboardRunning(false);
    }
  }

  async function saveSceneState() {
    if (!storyboard || !canSaveScene || isSceneSaving) return;
    setIsSceneSaving(true);
    setNotice('');
    try {
      const response = await fetch('/api/scenes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          projectId: project?.id || DEFAULT_PROJECT_ID,
          episodeNumber,
          title: sceneTitle, script, analysis: result, storyboard,
          deliveryTracking: { statuses: deliveryShotStatuses },
        }),
      });
      const payload = await response.json() as {
        saved?: { sceneNumber: number; episodeNumber: number; sceneOrder: number; updated: boolean };
        error?: string;
      };
      if (!response.ok || !payload.saved) throw new Error(payload.error || '场次状态保存失败');
      await loadScenes();
      setNotice(`第 ${payload.saved.episodeNumber} 集第 ${payload.saved.sceneOrder} 场状态${payload.saved.updated ? '已更新' : '已保存'}，编译下一场时会自动继承。`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '场次状态保存失败，请稍后重试。');
    } finally {
      setIsSceneSaving(false);
    }
  }

  function startNextScene() {
    setScript('');
    setResult(analyzeScript(''));
    setSource('local');
    setLoopCount(0);
    setStoryboard(null);
    setStoryboardLoopCount(0);
    setReviewedShotIds([]);
    setDeliveryCopied(false);
    setDeliveryShotStatuses({});
    setSceneTitle('');
    setEpisodeNumber(latestScene?.episodeNumber ?? 1);
    setPreviousSceneNumber(latestScene?.sceneOrder ?? null);
    setNotice(latestScene ? `已载入第 ${latestScene.episodeNumber} 集第 ${latestScene.sceneOrder} 场结束状态，请输入下一场剧本。` : '请输入下一场剧本。');
    window.localStorage.setItem('scene-flow-script', '');
  }

  async function moveScene(sceneId: string, direction: 'move-up' | 'move-down') {
    if (busy) return;
    setIsSceneReordering(true);
    try {
      const response = await fetch('/api/scenes', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sceneId, action: direction }),
      });
      const payload = await response.json() as { moved?: boolean; error?: string };
      if (!response.ok) throw new Error(payload.error || '场次顺序调整失败');
      if (payload.moved) {
        await loadScenes();
        setNotice('场次顺序已调整，时间线和下一场继承关系已更新。');
      } else {
        setNotice(direction === 'move-up' ? '已经是本项目最前一场。' : '已经是本项目最后一场。');
      }
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '场次顺序调整失败，请稍后重试。');
    } finally {
      setIsSceneReordering(false);
    }
  }

  async function moveSceneBefore(sceneId: string, targetSceneId: string) {
    if (busy || sceneId === targetSceneId) return;
    setIsSceneReordering(true);
    try {
      const response = await fetch('/api/scenes', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sceneId, targetSceneId, action: 'move-before' }),
      });
      const payload = await response.json() as { moved?: boolean; error?: string };
      if (!response.ok) throw new Error(payload.error || '场次顺序调整失败');
      if (payload.moved) {
        await loadScenes();
        setNotice('场次顺序已调整，时间线和下一场继承关系已更新。');
      }
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '场次顺序调整失败，请稍后重试。');
    } finally {
      setIsSceneReordering(false);
      setDraggingSceneId(null);
      setDragOverSceneId(null);
    }
  }

  function getPersistedDeliveryStatuses(nextStoryboard: StoryboardResult) {
    if (!activeSavedScene) return {};
    const validShotIds = new Set(nextStoryboard.shots.map((shot) => shot.id));
    return Object.fromEntries(
      Object.entries(activeSavedScene.deliveryTracking.statuses)
        .filter(([shotId]) => validShotIds.has(shotId)),
    ) as Record<string, DeliveryShotStatus>;
  }

  function exportResult() {
    const payload = {
      sourceScript: script, analysis: result, storyboard, sceneHistory: scenes,
      humanReview: { approved: allShotsReviewed, reviewedShotIds, reviewedAt: allShotsReviewed ? new Date().toISOString() : null },
      videoDeliveryPackage: canDeliver ? deliveryPackage : null,
      videoDeliveryValidation: deliveryValidation,
      deliveryTracking: canDeliver ? { ...deliveryTracking, statuses: deliveryShotStatuses } : null,
      exportedAt: new Date().toISOString(),
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = '剧本交互执行包.json';
    anchor.click();
    URL.revokeObjectURL(url);
  }

  function queueDeliveryTrackingSave(sceneId: string, statuses: Record<string, DeliveryShotStatus>) {
    deliverySaveQueue.current = deliverySaveQueue.current.then(async () => {
      const response = await fetch('/api/scenes', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sceneId, deliveryTracking: { statuses } }),
      });
      const payload = await response.json() as { tracking?: StoredScene['deliveryTracking']; error?: string };
      if (!response.ok || !payload.tracking) throw new Error(payload.error || '制作进度保存失败');
      await loadScenes();
      setNotice('制作进度已保存，刷新页面后仍可继续。');
    }).catch((error) => {
      setNotice(error instanceof Error ? error.message : '制作进度保存失败，请稍后重试。');
    });
  }

  function setDeliveryShotStatus(shotId: string, status: DeliveryShotStatus) {
    const next = { ...deliveryShotStatuses };
    if (status === 'pending') delete next[shotId];
    else next[shotId] = status;
    setDeliveryShotStatuses(next);
    if (activeSavedScene) queueDeliveryTrackingSave(activeSavedScene.id, next);
    if (!activeSavedScene) setNotice('本页进度已更新；先保存场次状态，刷新后才能继续保留。');
  }

  async function copyPrompt() {
    await navigator.clipboard.writeText(result.executionPrompt);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }

  async function copyStoryboardPrompt() {
    if (!storyboard) return;
    await navigator.clipboard.writeText(storyboard.modelPrompt);
    setStoryboardCopied(true);
    window.setTimeout(() => setStoryboardCopied(false), 1600);
  }

  function toggleShotReview(shotId: string) {
    setReviewedShotIds((current) => current.includes(shotId)
      ? current.filter((id) => id !== shotId)
      : [...current, shotId]);
  }

  function approveAllShots() {
    if (!storyboard) return;
    setReviewedShotIds(storyboard.shots.map((shot) => shot.id));
  }

  async function copyDeliveryPackage() {
    if (!deliveryPackage || !canDeliver) return;
    await navigator.clipboard.writeText(videoDeliveryToMarkdown(deliveryPackage));
    setDeliveryCopied(true);
    window.setTimeout(() => setDeliveryCopied(false), 1600);
  }

  function downloadDeliveryPackage() {
    if (!deliveryPackage || !canDeliver) return;
    const blob = new Blob([JSON.stringify(deliveryPackage, null, 2)], { type: 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = '视频生成交付包.json';
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <main className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-30 border-b border-border/80 bg-background/92 backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-[1500px] items-center justify-between px-5 lg:px-8">
          <div className="flex items-center gap-3">
            <div className="grid size-9 place-items-center rounded-xl bg-primary text-primary-foreground shadow-[0_8px_24px_rgba(120,41,35,.24)]">
              <Film className="size-4" />
            </div>
            <div>
              <div className="font-semibold tracking-[-0.02em]">剧序 SceneFlow</div>
              <div className="text-[11px] text-muted-foreground">短剧交互编译工作台 · MVP</div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant="outline" className={`hidden sm:inline-flex ${source === 'ai' ? 'border-violet-200 bg-violet-50 text-violet-700' : source === 'saved' ? 'border-sky-200 bg-sky-50 text-sky-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>
              <span className={`size-1.5 rounded-full ${source === 'ai' ? 'bg-violet-500' : source === 'saved' ? 'bg-sky-500' : 'bg-emerald-500'}`} />
              {source === 'ai' ? 'DeepSeek 智能编译' : source === 'saved' ? '已保存场次' : '本地规则备用'}
            </Badge>
            {previousSceneNumber && <Badge variant="outline" className="hidden border-sky-200 bg-sky-50 text-sky-700 md:inline-flex">继承第 {previousSceneNumber} 场</Badge>}
            <Button variant="outline" onClick={exportResult}>
              <Download data-icon="inline-start" /> 导出执行包
            </Button>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-[1500px] px-5 py-7 lg:px-8">
        <section className="mb-6 flex flex-col justify-between gap-4 lg:flex-row lg:items-end">
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-primary">Interaction compiler</p>
            <h1 className="max-w-3xl text-2xl font-semibold tracking-[-0.035em] sm:text-3xl">把人类剧本，编译成 AI 能稳定执行的交互结构</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">识别模糊情绪、缺失回应与结构风险，生成可追溯的动作、台词和状态变化。</p>
          </div>
          <div className="grid grid-cols-3 gap-2 sm:min-w-[420px]">
            <Metric label="交互节拍" value={String(result.beats.length)} suffix="个" />
            <Metric label="未解决问题" value={String(activeIssues.length)} suffix="项" danger={hardIssues.length > 0} />
            <Metric label="执行清晰度" value={String(result.score)} suffix="分" />
          </div>
        </section>

        <section className="grid gap-5 xl:grid-cols-[minmax(0,0.93fr)_minmax(620px,1.35fr)]">
          <div className="space-y-5">
            <Card className="border-0 shadow-[0_14px_50px_rgba(56,41,35,.08)] ring-border">
              <CardHeader className="border-b border-border/70 pb-4">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <CardTitle>原始剧本</CardTitle>
                    <CardDescription>粘贴一场戏，建议使用“人物名：台词”的格式。</CardDescription>
                  </div>
                  <Badge variant="secondary">{script.length} 字</Badge>
                </div>
              </CardHeader>
              <CardContent className="pt-4">
                <Textarea
                  aria-label="原始剧本输入"
                  value={script}
                  onChange={(event) => setScript(event.target.value)}
                  className="min-h-[310px] resize-y border-0 bg-[#f8f4ed] p-4 font-[var(--font-script)] text-[15px] leading-8 shadow-inner focus-visible:ring-primary/20"
                  placeholder="在这里输入一场戏……"
                />
                {notice && (
                  <div role="status" className="mt-3 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 text-xs leading-5 text-amber-900">
                    <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />{notice}
                  </div>
                )}
                <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                  <button className="text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline" onClick={() => setScript(sampleScript)}>
                    恢复示例剧本
                  </button>
                  <div className="flex flex-wrap gap-2">
                    <Button size="lg" onClick={runAnalysis} disabled={!script.trim() || busy} className="px-4">
                      {isRunning ? <Loader2 data-icon="inline-start" className="animate-spin" /> : <Play data-icon="inline-start" className="fill-current" />}
                      {isRunning ? '智能编译中…' : 'AI 编译这场戏'}
                    </Button>
                    <Button size="lg" variant="outline" onClick={runFullPipeline} disabled={!script.trim() || busy} className="px-4">
                      {isPipelineRunning ? <Loader2 data-icon="inline-start" className="animate-spin" /> : <Sparkles data-icon="inline-start" />}
                      {isPipelineRunning ? '全流程运行中…' : '运行全流程'}
                    </Button>
                  </div>
                </div>
                {pipelinePhase !== 'idle' && (
                  <div className={`mt-3 rounded-lg border px-3 py-2.5 text-xs leading-5 ${pipelinePhase === 'complete' ? 'border-emerald-200 bg-emerald-50 text-emerald-900' : pipelinePhase === 'blocked' || pipelinePhase === 'error' ? 'border-amber-200 bg-amber-50 text-amber-900' : 'border-sky-200 bg-sky-50 text-sky-900'}`}>
                    <div className="flex flex-wrap items-center justify-between gap-2"><span className="font-semibold">全流程 · {pipelinePhaseLabels[pipelinePhase]}</span><span className="tabular-nums">{pipelinePhaseProgress[pipelinePhase]}%</span></div>
                    <p className="mt-1 text-[11px] opacity-85">{pipelineStep}</p>
                    <Progress value={pipelinePhaseProgress[pipelinePhase]} className="mt-2 h-1.5 [&_[data-slot=progress-indicator]]:bg-sky-600" />
                  </div>
                )}
              </CardContent>
            </Card>

            <Card className="border-0 ring-border">
              <CardHeader>
                <CardTitle className="flex items-center gap-2"><GitBranch className="size-4 text-primary" />工作流状态</CardTitle>
                <CardDescription>第五阶段：保存本场结束状态，并将人物、道具、空间与时间约束传递给下一场。</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid gap-2 sm:grid-cols-3 xl:grid-cols-7">
                  {pipeline.map((step, index) => {
                    const Icon = step.icon;
                    return (
                      <div key={step.id} className="relative rounded-xl border border-border bg-muted/35 p-3">
                        <div className="mb-4 flex items-center justify-between">
                          <span className="text-[11px] font-semibold text-muted-foreground">{step.id}</span>
                          <span className="grid size-6 place-items-center rounded-full bg-emerald-100 text-emerald-700"><Check className="size-3.5" /></span>
                        </div>
                        <Icon className="mb-2 size-4 text-primary" />
                        <p className="text-xs font-medium">{step.label}</p>
                        {index < pipeline.length - 1 && <ChevronRight className="absolute -right-3 top-1/2 z-10 hidden size-4 -translate-y-1/2 text-muted-foreground xl:block" />}
                      </div>
                    );
                  })}
                </div>
                <div className="mt-5 flex items-center gap-3">
                  <Progress value={result.score} className="flex-1 [&_[data-slot=progress-indicator]]:bg-primary" />
                  <span className="text-xs tabular-nums text-muted-foreground">Loop {loopCount}/3</span>
                </div>
              </CardContent>
            </Card>
          </div>

          <Card className="min-h-[700px] border-0 shadow-[0_14px_50px_rgba(56,41,35,.08)] ring-border">
            <Tabs defaultValue="beats" className="h-full">
              <CardHeader className="border-b border-border/70 pb-3">
                <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
                  <div><CardTitle>AI执行结构</CardTitle><CardDescription>每项输出均可追溯到原剧本句子。</CardDescription></div>
                  <TabsList className="h-auto flex-wrap">
                    <TabsTrigger value="beats">交互节拍</TabsTrigger>
                    <TabsTrigger value="issues">问题 {activeIssues.length > 0 && <span className="rounded-full bg-primary px-1.5 text-[10px] text-primary-foreground">{activeIssues.length}</span>}</TabsTrigger>
                    <TabsTrigger value="prompt">执行Prompt</TabsTrigger>
                    <TabsTrigger value="storyboard">分镜 {storyboard ? storyboard.shots.length : ''}</TabsTrigger>
                    <TabsTrigger value="states">状态库 {scenes.length || ''}</TabsTrigger>
                    <TabsTrigger value="delivery">交付包</TabsTrigger>
                  </TabsList>
                </div>
              </CardHeader>

              <TabsContent value="beats" className="m-0">
                <CardContent className="max-h-[760px] space-y-3 overflow-y-auto py-4">
                  {result.beats.map((beat) => (
                    <article key={beat.id} className="rounded-xl border border-border bg-card p-4 transition-shadow hover:shadow-sm">
                      <div className="mb-3 flex items-center justify-between gap-3">
                        <div className="flex items-center gap-2">
                          <Badge className="bg-primary/10 text-primary">{beat.id}</Badge>
                          <span className="text-sm font-semibold">{beat.actor}</span><ArrowRight className="size-3.5 text-muted-foreground" /><span className="text-sm font-medium text-muted-foreground">{beat.receiver}</span>
                        </div>
                        <span className="text-[11px] text-muted-foreground">{beat.stateBefore} → {beat.stateAfter}</span>
                      </div>
                      <div className="grid gap-x-5 gap-y-3 text-sm sm:grid-cols-2">
                        <BeatField label="触发" value={beat.trigger} /><BeatField label="人物目的" value={beat.goal} />
                        <BeatField label="可见动作" value={beat.action} /><BeatField label="对方反应" value={beat.reaction} />
                      </div>
                      {(beat.dialogue || beat.response) && (
                        <div className="mt-3 rounded-lg border-l-2 border-primary/60 bg-muted/40 px-3 py-2.5 text-sm leading-6">
                          {beat.dialogue && <p><span className="font-medium">{beat.actor}：</span>“{beat.dialogue}”</p>}
                          {beat.response && <p className="text-muted-foreground"><span className="font-medium text-foreground">{beat.receiver}：</span>{beat.response}</p>}
                        </div>
                      )}
                    </article>
                  ))}
                </CardContent>
              </TabsContent>

              <TabsContent value="issues" className="m-0">
                <CardContent className="py-4">
                  <div className="mb-4 flex items-center justify-between gap-4 rounded-xl bg-[#f8f4ed] p-4">
                    <div><p className="text-sm font-semibold">受控修复循环</p><p className="mt-1 text-xs text-muted-foreground">仅修改已定位的问题，最多运行3轮。</p></div>
                    <Button onClick={runRepairLoop} disabled={activeIssues.length === 0 || loopCount >= 3 || busy}>
                      {isRunning ? <Loader2 data-icon="inline-start" className="animate-spin" /> : <RefreshCcw data-icon="inline-start" />}
                      {isRunning ? '修复中…' : '运行修复 Loop'}
                    </Button>
                  </div>
                  <div className="space-y-3">
                    {result.issues.map((issue) => (
                      <div key={issue.id} className={`rounded-xl border p-4 ${issue.resolved ? 'border-emerald-200 bg-emerald-50/55' : issue.severity === 'hard' ? 'border-red-200 bg-red-50/55' : 'border-amber-200 bg-amber-50/55'}`}>
                        <div className="flex items-start gap-3">
                          <span className={`mt-0.5 grid size-7 shrink-0 place-items-center rounded-full ${issue.resolved ? 'bg-emerald-100 text-emerald-700' : issue.severity === 'hard' ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'}`}>
                            {issue.resolved ? <Check className="size-4" /> : <AlertTriangle className="size-4" />}
                          </span>
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2"><p className="text-sm font-semibold">{issue.title}</p><Badge variant="outline">{issue.targetId}</Badge>{issue.resolved && <Badge className="bg-emerald-600">已修复</Badge>}</div>
                            <p className="mt-1 text-xs leading-5 text-muted-foreground">{issue.detail}</p>
                            <p className="mt-2 text-xs leading-5"><span className="font-semibold">建议：</span>{issue.suggestion}</p>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </TabsContent>

              <TabsContent value="prompt" className="m-0">
                <CardContent className="py-4">
                  <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                    <div><p className="text-sm font-semibold">模型执行指令</p><p className="text-xs text-muted-foreground">可复制交互指令，或继续生成带连续性状态的分镜。</p></div>
                    <div className="flex gap-2">
                      <Button variant="outline" onClick={copyPrompt}>{copied ? <Check data-icon="inline-start" /> : <Clipboard data-icon="inline-start" />}{copied ? '已复制' : '复制'}</Button>
                      <Button onClick={generateStoryboard} disabled={busy}>
                        {isStoryboardRunning ? <Loader2 data-icon="inline-start" className="animate-spin" /> : <Camera data-icon="inline-start" />}
                        {isStoryboardRunning ? '生成中…' : storyboard ? '重新生成分镜' : '生成分镜'}
                      </Button>
                    </div>
                  </div>
                  <pre className="max-h-[650px] overflow-auto whitespace-pre-wrap rounded-xl bg-[#201d1a] p-5 font-mono text-xs leading-6 text-[#f7f0e5]">{result.executionPrompt}</pre>
                </CardContent>
              </TabsContent>

              <TabsContent value="storyboard" className="m-0">
                <CardContent className="py-4">
                  {!storyboard ? (
                    <div className="grid min-h-[520px] place-items-center rounded-xl border border-dashed border-border bg-muted/25 p-8 text-center">
                      <div className="max-w-md">
                        <span className="mx-auto mb-4 grid size-12 place-items-center rounded-2xl bg-primary/10 text-primary"><Camera className="size-5" /></span>
                        <h3 className="font-semibold">把交互节拍转换成可执行分镜</h3>
                        <p className="mt-2 text-sm leading-6 text-muted-foreground">系统会为每个镜头锁定人物站位、视线、道具、空间和时间状态，并自动比较相邻镜头。</p>
                        <Button className="mt-5" onClick={generateStoryboard} disabled={busy}>
                          {isStoryboardRunning ? <Loader2 data-icon="inline-start" className="animate-spin" /> : <Camera data-icon="inline-start" />}
                          {isStoryboardRunning ? '正在生成分镜…' : '生成分镜与连续性报告'}
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <div>
                      <div className="mb-4 grid gap-2 sm:grid-cols-5">
                        <Metric label="镜头数量" value={String(storyboard.shots.length)} suffix="个" />
                        <Metric label="预计时长" value={String(storyboard.totalDurationSec)} suffix="秒" />
                        <Metric label="连续性" value={String(storyboard.continuityScore)} suffix="分" danger={activeContinuityIssues.some((issue) => issue.severity === 'hard')} />
                        <Metric label="待修问题" value={String(activeContinuityIssues.length)} suffix="项" danger={activeContinuityIssues.length > 0} />
                        <Metric label="人工确认" value={String(reviewedShotCount)} suffix={`/${storyboard.shots.length}`} danger={!allShotsReviewed} />
                      </div>

                      {storyboard.issues.length > 0 && (
                        <div className="mb-4 rounded-xl border border-amber-200 bg-amber-50/60 p-4">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <p className="text-sm font-semibold text-amber-950">连续性报告 · 待修 {activeContinuityIssues.length} 项</p>
                            <span className="text-xs tabular-nums text-amber-900">分镜 Loop {storyboardLoopCount}/3</span>
                          </div>
                          <div className="mt-2 space-y-2">
                            {storyboard.issues.slice(0, 6).map((issue) => (
                              <p key={`${issue.id}-${issue.type}-${issue.fromShotId}-${issue.toShotId}`} className={`text-xs leading-5 ${issue.resolved ? 'text-emerald-800' : 'text-amber-900'}`}>
                                <span className="font-semibold">{issue.fromShotId} → {issue.toShotId}：</span>{issue.detail}
                                {issue.resolved && <Badge className="ml-2 bg-emerald-600">已修复</Badge>}
                              </p>
                            ))}
                          </div>
                        </div>
                      )}

                      <div className={`mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border p-4 ${allShotsReviewed ? 'border-emerald-200 bg-emerald-50/60' : 'border-violet-200 bg-violet-50/60'}`}>
                        <div>
                          <p className={`text-sm font-semibold ${allShotsReviewed ? 'text-emerald-950' : 'text-violet-950'}`}>人工审阅闸门 · {reviewedShotCount}/{storyboard.shots.length} 个镜头已确认</p>
                          <p className={`mt-1 text-xs leading-5 ${allShotsReviewed ? 'text-emerald-800' : 'text-violet-800'}`}>{allShotsReviewed ? '全部镜头已确认，可以保存本场状态或导出执行包。' : '请逐个检查动作、台词、状态和视频Prompt；确认后才能进入跨场景状态库。'}</p>
                        </div>
                        <Button variant={allShotsReviewed ? 'secondary' : 'outline'} size="sm" onClick={approveAllShots} disabled={allShotsReviewed || busy}>全部确认</Button>
                      </div>

                      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                        <p className="text-xs text-muted-foreground">开始状态必须承接上一镜头结束状态；有跳切时必须给出原因。</p>
                        <div className="flex gap-2">
                          <Button variant="outline" onClick={copyStoryboardPrompt}>{storyboardCopied ? <Check data-icon="inline-start" /> : <Clipboard data-icon="inline-start" />}{storyboardCopied ? '已复制' : '复制视频Prompt'}</Button>
                          <Button onClick={repairStoryboardLoop} disabled={busy || activeContinuityIssues.length === 0 || storyboardLoopCount >= 3}>
                            {isStoryboardRunning ? <Loader2 data-icon="inline-start" className="animate-spin" /> : <RefreshCcw data-icon="inline-start" />}
                            {isStoryboardRunning ? '修复中…' : activeContinuityIssues.length === 0 ? '无需修复' : '受控修复 Loop'}
                          </Button>
                          <Button variant="outline" onClick={generateStoryboard} disabled={busy}><RefreshCcw data-icon="inline-start" />重新生成</Button>
                        </div>
                      </div>

                      <div className="max-h-[650px] space-y-3 overflow-y-auto pr-1">
                        {storyboard.shots.map((shot) => {
                          const reviewed = reviewedShotSet.has(shot.id);
                          return (
                          <article key={shot.id} className={`rounded-xl border p-4 ${reviewed ? 'border-emerald-200 bg-emerald-50/20' : 'border-border bg-card'}`}>
                            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                              <div className="flex items-center gap-2"><Badge className="bg-primary/10 text-primary">{shot.id}</Badge><Badge variant="outline">{shot.beatId}</Badge><span className="text-sm font-semibold">{shot.focus}</span>{reviewed && <Badge className="bg-emerald-600">已确认</Badge>}</div>
                              <span className="flex items-center gap-1 text-xs text-muted-foreground"><Clock className="size-3.5" />{shot.durationSec}秒 · {shot.shotSize} · {shot.cameraAngle} · {shot.cameraMovement}</span>
                            </div>
                            <p className="text-sm leading-6"><span className="font-semibold">动作：</span>{shot.action}</p>
                            {shot.dialogue && <p className="mt-1 text-sm leading-6"><span className="font-semibold">台词：</span>{shot.dialogue}</p>}
                            <div className="mt-3 grid gap-2 lg:grid-cols-2">
                              <ShotStateView label="开始状态" state={shot.startState} />
                              <ShotStateView label="结束状态" state={shot.endState} />
                            </div>
                            <div className="mt-3 rounded-lg bg-muted/45 px-3 py-2.5 text-xs leading-5"><span className="font-semibold">视频Prompt：</span>{shot.videoPrompt}</div>
                            <div className="mt-3 flex justify-end">
                              <Button size="sm" variant={reviewed ? 'secondary' : 'outline'} onClick={() => toggleShotReview(shot.id)} aria-pressed={reviewed} disabled={busy}>
                                {reviewed ? <Check data-icon="inline-start" /> : null}{reviewed ? '取消确认' : '确认此镜头'}
                              </Button>
                            </div>
                          </article>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </CardContent>
              </TabsContent>

              <TabsContent value="states" className="m-0">
                <CardContent className="py-4">
                  <div className="mb-4 rounded-xl border border-border bg-card p-4">
                    <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-end">
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-semibold">项目资料</p>
                        <p className="mt-1 text-xs text-muted-foreground">项目内场次会按顺序保存，状态继承只在当前项目中生效。</p>
                        <Input aria-label="项目名称" value={projectName} onChange={(event) => setProjectName(event.target.value)} className="mt-3 max-w-md" placeholder="例如：林晓与父亲" disabled={busy} />
                      </div>
                      <Button variant="outline" onClick={saveProjectName} disabled={!projectName.trim() || busy}>{isProjectSaving ? <Loader2 data-icon="inline-start" className="animate-spin" /> : <Save data-icon="inline-start" />}{isProjectSaving ? '保存中…' : '保存项目名'}</Button>
                    </div>
                    {project && <p className="mt-2 text-[11px] text-muted-foreground">当前项目：{project.name} · 已保存 {scenes.length} 场</p>}
                  </div>
                  <div className="mb-4 rounded-xl border border-sky-200 bg-sky-50/60 p-4">
                    <div className="flex flex-col justify-between gap-3 lg:flex-row lg:items-end">
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-semibold text-sky-950">跨场景状态数据库</p>
                        <p className="mt-1 text-xs leading-5 text-sky-900">分镜确认后保存本场。下一场AI编译会自动继承最新人物、道具、空间和时间状态。</p>
                        <div className="mt-3 grid max-w-md gap-2 sm:grid-cols-[110px_1fr]">
                          <Input aria-label="集数" type="number" min={1} max={999} value={episodeNumber} onChange={(event) => setEpisodeNumber(Number(event.target.value))} className="bg-white" placeholder="集数" />
                          <Input aria-label="场次标题" value={sceneTitle} onChange={(event) => setSceneTitle(event.target.value)} className="bg-white" placeholder={`场次标题，例如：${scenes.length + 1}. 客厅对峙`} />
                        </div>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <Button onClick={saveSceneState} disabled={!canSaveScene || busy}>
                          {isSceneSaving ? <Loader2 data-icon="inline-start" className="animate-spin" /> : <Save data-icon="inline-start" />}
                          {isSceneSaving ? '保存中…' : '保存本场状态'}
                        </Button>
                        <Button variant="outline" onClick={startNextScene} disabled={!latestScene || busy}>开始下一场</Button>
                      </div>
                    </div>
                    {!storyboard && <p className="mt-3 text-xs text-sky-800">需要先生成分镜，系统才能取得准确的场景结束状态。</p>}
                    {storyboard && !allShotsReviewed && <p className="mt-3 text-xs text-violet-800">请先完成全部镜头的人工确认，再把本场写入状态库。</p>}
                    {storyboard && allShotsReviewed && !canSaveScene && <p className="mt-3 text-xs text-amber-800">请先解决剧本或分镜中的硬性问题，再把本场写入状态库。</p>}
                  </div>

                  {scenes.length > 0 && (
                    <div className="mb-4 rounded-xl border border-slate-200 bg-slate-50/70 p-4">
                      <div className="flex flex-col justify-between gap-3 lg:flex-row lg:items-end">
                        <div>
                          <p className="text-sm font-semibold text-slate-950">整部短剧制作总览</p>
                          <p className="mt-1 text-xs leading-5 text-slate-700">这里汇总全部集数；下方时间线可再按集数筛选。</p>
                        </div>
                        <div className="grid grid-cols-4 gap-2 text-center text-[11px] text-slate-700">
                          <div className="rounded-lg bg-white px-2.5 py-2"><p className="text-lg font-semibold tabular-nums text-slate-950">{sceneTimeline.scenes.length}</p><p>场次</p></div>
                          <div className="rounded-lg bg-white px-2.5 py-2"><p className="text-lg font-semibold tabular-nums text-slate-950">{sceneTimeline.totalShots}</p><p>镜头</p></div>
                          <div className="rounded-lg bg-white px-2.5 py-2"><p className="text-lg font-semibold tabular-nums text-slate-950">{sceneTimeline.totalDurationSec}秒</p><p>时长</p></div>
                          <div className="rounded-lg bg-white px-2.5 py-2"><p className="text-lg font-semibold tabular-nums text-slate-950">{sceneTimeline.productionProgress}%</p><p>完成度</p></div>
                        </div>
                      </div>
                      <div className="mt-4 flex items-center gap-3"><Progress value={sceneTimeline.productionProgress} className="h-2 flex-1 bg-slate-200" /><span className="min-w-12 text-right text-xs font-semibold tabular-nums text-slate-800">{sceneTimeline.productionProgress}%</span></div>
                      <div className="mt-3 flex flex-wrap gap-2">
                        {(Object.keys(sceneStatusLabels) as SceneProductionStatus[]).map((status) => <Badge key={status} variant="outline" className={sceneStatusClasses[status]}>{sceneStatusLabels[status]} {sceneTimeline.statusCounts[status]}</Badge>)}
                      </div>
                    </div>
                  )}

                  {scenes.length > 0 && (
                    <div className="mb-4 rounded-xl border border-indigo-200 bg-indigo-50/60 p-4">
                      <div className="flex flex-col justify-between gap-3 lg:flex-row lg:items-end">
                        <div className="min-w-0">
                          <p className="text-sm font-semibold text-indigo-950">场次时间线</p>
                          <p className="mt-1 text-xs leading-5 text-indigo-900">按场次顺序汇总时长、镜头和视频制作状态，帮助检查整部短剧的推进节奏。</p>
                          <p className="mt-1 flex items-center gap-1 text-[11px] text-indigo-700"><GripVertical className="size-3" />拖拽场次卡片可放到另一场之前，也可用右下角箭头调整。</p>
                        </div>
                        <NativeSelect value={String(selectedEpisode)} onChange={(event) => setSelectedEpisode(event.target.value === 'all' ? 'all' : Number(event.target.value))} aria-label="筛选集数" className="w-full lg:w-36">
                          <NativeSelectOption value="all">全部集数</NativeSelectOption>
                          {episodeOptions.map((episode) => <NativeSelectOption key={episode} value={String(episode)}>第 {episode} 集</NativeSelectOption>)}
                        </NativeSelect>
                        <div className="grid grid-cols-3 gap-2 text-center text-xs text-indigo-900">
                          <div className="rounded-lg bg-white/70 px-3 py-2"><p className="text-lg font-semibold tabular-nums">{visibleTimeline.scenes.length}</p><p>场次</p></div>
                          <div className="rounded-lg bg-white/70 px-3 py-2"><p className="text-lg font-semibold tabular-nums">{visibleTimeline.totalShots}</p><p>镜头</p></div>
                          <div className="rounded-lg bg-white/70 px-3 py-2"><p className="text-lg font-semibold tabular-nums">{visibleTimeline.totalDurationSec}秒</p><p>总时长</p></div>
                        </div>
                      </div>
                      <div className="mt-4 flex items-center gap-3">
                        <Progress value={visibleTimeline.productionProgress} className="h-2 flex-1 bg-indigo-100" />
                        <span className="min-w-12 text-right text-xs font-semibold tabular-nums text-indigo-900">{visibleTimeline.productionProgress}%</span>
                      </div>
                      <div className="mt-4 space-y-4">
                        {visibleTimeline.episodes.map((episode) => (
                          <section key={episode.episodeNumber} className="rounded-lg border border-indigo-100 bg-white/55 p-3">
                            <div className="mb-3 flex flex-wrap items-center justify-between gap-2"><div><p className="text-xs font-semibold uppercase tracking-[0.18em] text-indigo-800">第 {episode.episodeNumber} 集 · {episode.scenes.length} 场</p><p className="mt-1 text-[11px] text-indigo-700">{episode.scenes.reduce((total, scene) => total + scene.summary.durationSec, 0)}秒 · {episode.scenes.reduce((total, scene) => total + scene.summary.continuityIssueCount, 0)}项待修 · {episode.scenes.reduce((total, scene) => total + scene.summary.acceptedShotCount, 0)}/{episode.scenes.reduce((total, scene) => total + scene.summary.shotCount, 0)}镜头已验收</p></div><span className="text-[11px] text-indigo-700">顺序可调整</span></div>
                            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                              {episode.scenes.map((scene, index) => (
                                <div
                                  key={scene.id}
                                  draggable={!busy}
                                  onDragStart={(event) => {
                                    setDraggingSceneId(scene.id);
                                    event.dataTransfer.effectAllowed = 'move';
                                    event.dataTransfer.setData('text/plain', scene.id);
                                  }}
                                  onDragOver={(event) => {
                                    if (draggingSceneId && draggingSceneId !== scene.id) {
                                      event.preventDefault();
                                      event.dataTransfer.dropEffect = 'move';
                                      setDragOverSceneId(scene.id);
                                    }
                                  }}
                                  onDragLeave={() => {
                                    if (dragOverSceneId === scene.id) setDragOverSceneId(null);
                                  }}
                                  onDrop={(event) => {
                                    event.preventDefault();
                                    const sourceId = event.dataTransfer.getData('text/plain') || draggingSceneId;
                                    if (sourceId && sourceId !== scene.id) void moveSceneBefore(sourceId, scene.id);
                                  }}
                                  onDragEnd={() => {
                                    setDraggingSceneId(null);
                                    setDragOverSceneId(null);
                                  }}
                                  className={`relative rounded-lg border bg-white/85 p-3 transition ${dragOverSceneId === scene.id ? 'border-indigo-500 ring-2 ring-indigo-200' : 'border-indigo-100'} ${draggingSceneId === scene.id ? 'opacity-60' : ''}`}
                                >
                                  {index < episode.scenes.length - 1 && <span className="absolute -right-3 top-1/2 hidden h-px w-3 bg-indigo-200 xl:block" aria-hidden="true" />}
                                  <div className="flex items-start justify-between gap-2">
                                    <div className="flex min-w-0 items-center gap-2"><span className="grid size-6 shrink-0 place-items-center rounded-full bg-indigo-100 text-xs font-semibold text-indigo-800">{scene.sceneOrder}</span><p className="line-clamp-1 text-sm font-semibold text-indigo-950">{scene.title}</p></div>
                                    <Badge variant="outline" className={sceneStatusClasses[scene.summary.status]}>{sceneStatusLabels[scene.summary.status]}</Badge>
                                  </div>
                                  <div className="mt-3 grid grid-cols-3 gap-2 text-[11px] text-muted-foreground">
                                    <span><Clock className="mr-1 inline size-3" />{scene.summary.durationSec}秒</span>
                                    <span><Film className="mr-1 inline size-3" />{scene.summary.shotCount}镜头</span>
                                    <span className={scene.summary.continuityIssueCount > 0 ? 'text-amber-700' : 'text-emerald-700'}>{scene.summary.continuityIssueCount > 0 ? `待修 ${scene.summary.continuityIssueCount}` : '连续性通过'}</span>
                                  </div>
                                  <div className="mt-2 flex items-center gap-2"><Progress value={scene.summary.productionProgress} className="h-1.5 flex-1" /><span className="text-[11px] tabular-nums text-muted-foreground">{scene.summary.productionProgress}%</span></div>
                                  <div className="mt-3 flex justify-end gap-1">
                                    <Button size="sm" variant="ghost" aria-label={`第 ${scene.sceneOrder} 场上移`} onClick={() => void moveScene(scene.id, 'move-up')} disabled={busy || index === 0}><ArrowUp className="size-3.5" /></Button>
                                    <Button size="sm" variant="ghost" aria-label={`第 ${scene.sceneOrder} 场下移`} onClick={() => void moveScene(scene.id, 'move-down')} disabled={busy || index === episode.scenes.length - 1}><ArrowDown className="size-3.5" /></Button>
                                  </div>
                                </div>
                              ))}
                            </div>
                          </section>
                        ))}
                      </div>
                    </div>
                  )}

                  {!latestScene ? (
                    <div className="grid min-h-[430px] place-items-center rounded-xl border border-dashed border-border bg-muted/25 p-8 text-center">
                      <div className="max-w-md">
                        <span className="mx-auto mb-4 grid size-12 place-items-center rounded-2xl bg-sky-100 text-sky-700"><Database className="size-5" /></span>
                        <h3 className="font-semibold">还没有已保存场次</h3>
                        <p className="mt-2 text-sm leading-6 text-muted-foreground">完成第一场的分析、分镜和连续性检查后，把结束状态保存到这里。</p>
                      </div>
                    </div>
                  ) : (
                    <div className="max-h-[650px] space-y-3 overflow-y-auto pr-1">
                      {scenes.map((scene, index) => (
                        <article key={scene.id} className={`rounded-xl border p-4 ${index === 0 ? 'border-sky-200 bg-sky-50/35' : 'border-border bg-card'}`}>
                          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                            <div className="flex items-center gap-2"><Badge className="bg-sky-700">第 {scene.episodeNumber} 集 · 第 {scene.sceneOrder} 场</Badge><span className="text-sm font-semibold">{scene.title}</span>{index === 0 && <Badge variant="outline">当前继承源</Badge>}</div>
                            <div className="flex items-center gap-2"><span className="text-[11px] text-muted-foreground">{new Date(scene.createdAt).toLocaleString('zh-CN')}</span><Button size="sm" variant="outline" onClick={() => void loadSavedScene(scene)} disabled={busy}>{isSceneLoading ? <Loader2 data-icon="inline-start" className="animate-spin" /> : <FileText data-icon="inline-start" />}载入本场</Button></div>
                          </div>
                          <div className="grid gap-2 sm:grid-cols-3">
                            <StateField label="空间 / 时间" value={`${scene.snapshot.spaceState} · ${scene.snapshot.timeState}`} />
                            <StateField label="人物站位 / 视线" value={`${scene.snapshot.characterPositions} · ${scene.snapshot.gazeDirection}`} />
                            <StateField label="道具状态" value={scene.snapshot.propState} />
                          </div>
                          <div className="mt-3 grid gap-2 lg:grid-cols-2">
                            {scene.snapshot.characters.map((character) => (
                              <div key={character.name} className="rounded-lg border border-border/80 bg-white/70 p-3 text-xs leading-5">
                                <div className="flex items-center justify-between gap-2"><span className="font-semibold">{character.name}</span><Badge variant="outline">{character.emotionalState}</Badge></div>
                                <p className="mt-1"><span className="text-muted-foreground">最后动作：</span>{character.lastAction}</p>
                                <p><span className="text-muted-foreground">最后台词：</span>{character.lastDialogue}</p>
                                <p className="mt-1 line-clamp-2"><span className="text-muted-foreground">已知信息：</span>{character.knownFacts.join('；') || '未明确'}</p>
                              </div>
                            ))}
                          </div>
                        </article>
                      ))}
                    </div>
                  )}
                </CardContent>
              </TabsContent>

              <TabsContent value="delivery" className="m-0">
                <CardContent className="py-4">
                  {!storyboard ? (
                    <div className="grid min-h-[430px] place-items-center rounded-xl border border-dashed border-border bg-muted/25 p-8 text-center">
                      <div className="max-w-md">
                        <span className="mx-auto mb-4 grid size-12 place-items-center rounded-2xl bg-primary/10 text-primary"><PackageCheck className="size-5" /></span>
                        <h3 className="font-semibold">生成分镜后创建视频交付包</h3>
                        <p className="mt-2 text-sm leading-6 text-muted-foreground">交付包会按镜头顺序整理Prompt、时长、台词和连续性锁定条件。</p>
                      </div>
                    </div>
                  ) : !allShotsReviewed ? (
                    <div className="grid min-h-[430px] place-items-center rounded-xl border border-violet-200 bg-violet-50/50 p-8 text-center">
                      <div className="max-w-md">
                        <span className="mx-auto mb-4 grid size-12 place-items-center rounded-2xl bg-violet-100 text-violet-700"><PackageCheck className="size-5" /></span>
                        <h3 className="font-semibold">请先完成人工审阅</h3>
                        <p className="mt-2 text-sm leading-6 text-violet-800">当前已确认 {reviewedShotCount}/{storyboard.shots.length} 个镜头。全部确认后，系统才会开放视频交付包。</p>
                      </div>
                    </div>
                  ) : deliveryPackage ? (
                    <div>
                      <div className="mb-4 rounded-xl border border-emerald-200 bg-emerald-50/60 p-4">
                        <div className="flex flex-col justify-between gap-3 lg:flex-row lg:items-center">
                          <div><p className="text-sm font-semibold text-emerald-950">视频生成交付包已就绪</p><p className="mt-1 text-xs leading-5 text-emerald-800">可复制Markdown交给视频工具，或下载JSON作为逐镜输入。</p></div>
                          <div className="flex flex-wrap gap-2"><Button onClick={copyDeliveryPackage} disabled={!canDeliver}>{deliveryCopied ? <Check data-icon="inline-start" /> : <Clipboard data-icon="inline-start" />}{deliveryCopied ? '已复制' : '复制交付包'}</Button><Button variant="outline" onClick={downloadDeliveryPackage} disabled={!canDeliver}><Download data-icon="inline-start" />下载JSON</Button></div>
                        </div>
                      </div>
                      {deliveryValidation?.valid && !deliveryHasHardIssues ? (
                        <div className="mb-4 flex items-start gap-2 rounded-xl border border-emerald-200 bg-emerald-50/60 p-4 text-xs leading-5 text-emerald-900">
                          <Check className="mt-0.5 size-4 shrink-0 text-emerald-700" />
                          <div><p className="font-semibold">交付前校验通过 · video-delivery/v1</p><p className="mt-1">镜头顺序、时长、Prompt、台词和连续性锁定字段完整，可交给视频生成工具。</p></div>
                        </div>
                      ) : (
                        <div className="mb-4 rounded-xl border border-red-200 bg-red-50/70 p-4 text-xs leading-5 text-red-900">
                          <p className="font-semibold">交付前校验未通过</p>
                          {deliveryHasHardIssues && <p className="mt-1">存在未解决的剧本或分镜硬问题，请先回到对应页面处理。</p>}
                          <div className="mt-1 space-y-1">{deliveryValidation?.issues.slice(0, 5).map((issue) => <p key={`${issue.code}-${issue.shotId ?? 'global'}`}>· {issue.shotId ? `${issue.shotId}：` : ''}{issue.message}</p>)}</div>
                        </div>
                      )}
                      <div className="mb-4 rounded-xl border border-border bg-card p-4">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div><p className="text-sm font-semibold">制作跟踪</p><p className="mt-1 text-xs text-muted-foreground">已提交 {deliveryTracking.submittedCount}/{deliveryTracking.total} · 已验收 {deliveryTracking.acceptedCount}/{deliveryTracking.total}</p><p className="mt-1 text-[11px] text-muted-foreground">{activeSavedScene ? `已关联第 ${activeSavedScene.episodeNumber} 集第 ${activeSavedScene.sceneOrder} 场，进度自动保存` : '先保存场次状态，进度才能跨刷新保留'}</p></div>
                          <Badge variant="secondary" className={deliveryTracking.complete ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : ''}>{deliveryTracking.complete ? '本场已验收' : `已验收 ${deliveryTracking.acceptedCount}/${deliveryTracking.total}`}</Badge>
                        </div>
                        <Progress value={deliveryTracking.total ? (deliveryTracking.acceptedCount / deliveryTracking.total) * 100 : 0} className="mt-3 [&_[data-slot=progress-indicator]]:bg-emerald-600" />
                        <div className="mt-3 max-h-72 space-y-2 overflow-y-auto pr-1">
                          {deliveryPackage.shots.map((shot) => {
                            const status = deliveryShotStatuses[shot.id] ?? 'pending';
                            return (
                              <div key={shot.id} className="flex flex-col gap-2 rounded-lg border border-border/80 bg-muted/20 p-3 sm:flex-row sm:items-center sm:justify-between">
                                <div className="min-w-0"><p className="text-xs font-semibold">{shot.order}. {shot.id} · {shot.durationSec}秒</p><p className="mt-1 truncate text-xs text-muted-foreground">{shot.dialogue}</p></div>
                                <div className="flex shrink-0 gap-1">
                                  {(['pending', 'submitted', 'accepted'] as DeliveryShotStatus[]).map((option) => <Button key={option} size="sm" variant={status === option ? 'default' : 'outline'} onClick={() => setDeliveryShotStatus(shot.id, option)} aria-label={`${shot.id}标记为${deliveryStatusLabels[option]}`}>{deliveryStatusLabels[option]}</Button>)}
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                      <div className="mb-4 rounded-xl border border-border bg-card p-4">
                        <p className="mb-2 text-sm font-semibold">交付参数</p>
                        <div className="flex flex-wrap gap-2">
                          {(['9:16', '16:9'] as DeliveryAspectRatio[]).map((ratio) => <Button key={ratio} size="sm" variant={deliveryAspectRatio === ratio ? 'default' : 'outline'} onClick={() => setDeliveryAspectRatio(ratio)}>{ratio} {ratio === '9:16' ? '竖屏短剧' : '横屏短剧'}</Button>)}
                          <Badge variant="secondary">{deliveryAspectRatio === '9:16' ? '1080×1920' : '1920×1080'}</Badge>
                          <Badge variant="secondary">写实短剧 · 自然光 · 台词清晰</Badge>
                        </div>
                      </div>
                      <pre className="max-h-[650px] overflow-auto whitespace-pre-wrap rounded-xl bg-[#201d1a] p-5 font-mono text-xs leading-6 text-[#f7f0e5]">{videoDeliveryToMarkdown(deliveryPackage)}</pre>
                    </div>
                  ) : null}
                </CardContent>
              </TabsContent>
            </Tabs>
          </Card>
        </section>

        <footer className="mt-6 flex flex-col justify-between gap-2 border-t border-border py-5 text-xs text-muted-foreground sm:flex-row">
          <span>交互分析、分镜修复、人工确认与视频交付已串联。</span>
          <span className="flex items-center gap-1.5"><Sparkles className="size-3.5" />DeepSeek · 状态锁定 · 连续性规则</span>
        </footer>
      </div>
    </main>
  );
}

function Metric({ label, value, suffix, danger = false }: { label: string; value: string; suffix: string; danger?: boolean }) {
  return <div className="rounded-xl border border-border bg-card px-3 py-2.5"><p className="text-[11px] text-muted-foreground">{label}</p><p className={`mt-0.5 text-lg font-semibold tabular-nums ${danger ? 'text-red-700' : ''}`}>{value}<span className="ml-1 text-[11px] font-normal text-muted-foreground">{suffix}</span></p></div>;
}

function BeatField({ label, value }: { label: string; value: string }) {
  return <div><p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">{label}</p><p className="leading-6 text-foreground/90">{value}</p></div>;
}

function ShotStateView({ label, state }: { label: string; state: ShotState }) {
  return (
    <div className="rounded-lg border border-border/80 bg-[#faf7f1] p-3 text-xs leading-5">
      <p className="mb-1 font-semibold text-foreground">{label}</p>
      <p><span className="text-muted-foreground">站位：</span>{state.characterPositions}</p>
      <p><span className="text-muted-foreground">视线：</span>{state.gazeDirection}</p>
      <p><span className="text-muted-foreground">道具：</span>{state.propState}</p>
      <p><span className="text-muted-foreground">空间/时间：</span>{state.spaceState} · {state.timeState}</p>
    </div>
  );
}

function StateField({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-sky-100 bg-white/75 p-3 text-xs leading-5">
      <p className="mb-1 font-semibold text-sky-950">{label}</p>
      <p className="text-sky-900">{value}</p>
    </div>
  );
}
