'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle, ArrowRight, Check, ChevronRight, Clipboard, Download,
  Camera, Clock, Database, FileText, Film, GitBranch, Loader2, Play,
  RefreshCcw, Save, ScanSearch, Sparkles, Users,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Progress } from '@/components/ui/progress';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import {
  analyzeScript, repairAnalysis, type AnalysisResult, type AnalysisSource,
} from '@/lib/script-engine';
import type { StoredScene } from '@/lib/scene-state';
import type { ShotState, StoryboardResult } from '@/lib/storyboard-engine';

const sampleScript = `客厅，夜晚。
林晓发现桌上父亲的辞职通知书，很生气地质问父亲：“你什么时候辞职的？”
父亲很尴尬，试图隐瞒：“这不重要。”
林晓不相信父亲的解释，继续追问。父亲沉默。`;

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
  const [isSceneSaving, setIsSceneSaving] = useState(false);
  const [previousSceneNumber, setPreviousSceneNumber] = useState<number | null>(null);
  const [reviewedShotIds, setReviewedShotIds] = useState<string[]>([]);

  async function loadScenes() {
    try {
      const response = await fetch('/api/scenes');
      const payload = await response.json() as { scenes?: StoredScene[] };
      if (response.ok && payload.scenes) setScenes(payload.scenes);
    } catch {
      // The current-scene workflow remains usable if persistent history is temporarily unavailable.
    }
  }

  useEffect(() => {
    const saved = window.localStorage.getItem('scene-flow-script');
    if (saved) {
      setScript(saved);
      setResult(analyzeScript(saved));
    }
    void loadScenes();
  }, []);

  const activeIssues = useMemo(() => result.issues.filter((issue) => !issue.resolved), [result]);
  const hardIssues = activeIssues.filter((issue) => issue.severity === 'hard');
  const activeContinuityIssues = storyboard?.issues.filter((issue) => !issue.resolved) ?? [];
  const busy = isRunning || isStoryboardRunning || isSceneSaving;
  const latestScene = scenes[0] ?? null;
  const hasHardStoryboardIssues = activeContinuityIssues.some((issue) => issue.severity === 'hard');
  const reviewedShotSet = useMemo(() => new Set(reviewedShotIds), [reviewedShotIds]);
  const reviewedShotCount = storyboard?.shots.filter((shot) => reviewedShotSet.has(shot.id)).length ?? 0;
  const allShotsReviewed = Boolean(storyboard?.shots.length) && reviewedShotCount === storyboard?.shots.length;
  const canSaveScene = Boolean(storyboard) && allShotsReviewed && hardIssues.length === 0 && !hasHardStoryboardIssues;

  async function requestAI(body: Record<string, unknown>) {
    const response = await fetch('/api/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
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
    } catch (error) {
      setResult(analyzeScript(script));
      setSource('local');
      setLoopCount(0);
      setStoryboard(null);
      setStoryboardLoopCount(0);
      setReviewedShotIds([]);
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
    } catch (error) {
      setResult((current) => repairAnalysis(current));
      setSource('local');
      setLoopCount((current) => current + 1);
      setStoryboard(null);
      setStoryboardLoopCount(0);
      setReviewedShotIds([]);
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
      setStoryboardLoopCount(0);
      setReviewedShotIds([]);
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
      setStoryboardLoopCount((current) => current + 1);
      setReviewedShotIds([]);
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
        body: JSON.stringify({ title: sceneTitle, script, analysis: result, storyboard }),
      });
      const payload = await response.json() as {
        saved?: { sceneNumber: number; updated: boolean };
        error?: string;
      };
      if (!response.ok || !payload.saved) throw new Error(payload.error || '场次状态保存失败');
      await loadScenes();
      setNotice(`第 ${payload.saved.sceneNumber} 场状态${payload.saved.updated ? '已更新' : '已保存'}，编译下一场时会自动继承。`);
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
    setSceneTitle('');
    setPreviousSceneNumber(latestScene?.sceneNumber ?? null);
    setNotice(latestScene ? `已载入第 ${latestScene.sceneNumber} 场结束状态，请输入下一场剧本。` : '请输入下一场剧本。');
    window.localStorage.setItem('scene-flow-script', '');
  }

  function exportResult() {
    const payload = {
      sourceScript: script, analysis: result, storyboard, sceneHistory: scenes,
      humanReview: { approved: allShotsReviewed, reviewedShotIds, reviewedAt: allShotsReviewed ? new Date().toISOString() : null },
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
            <Badge variant="outline" className={`hidden sm:inline-flex ${source === 'ai' ? 'border-violet-200 bg-violet-50 text-violet-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>
              <span className={`size-1.5 rounded-full ${source === 'ai' ? 'bg-violet-500' : 'bg-emerald-500'}`} />
              {source === 'ai' ? 'DeepSeek 智能编译' : '本地规则备用'}
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
                  <Button size="lg" onClick={runAnalysis} disabled={!script.trim() || busy} className="px-4">
                    {isRunning ? <Loader2 data-icon="inline-start" className="animate-spin" /> : <Play data-icon="inline-start" className="fill-current" />}
                    {isRunning ? '智能编译中…' : 'AI 编译这场戏'}
                  </Button>
                </div>
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
                  <div className="mb-4 rounded-xl border border-sky-200 bg-sky-50/60 p-4">
                    <div className="flex flex-col justify-between gap-3 lg:flex-row lg:items-end">
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-semibold text-sky-950">跨场景状态数据库</p>
                        <p className="mt-1 text-xs leading-5 text-sky-900">分镜确认后保存本场。下一场AI编译会自动继承最新人物、道具、空间和时间状态。</p>
                        <Input aria-label="场次标题" value={sceneTitle} onChange={(event) => setSceneTitle(event.target.value)} className="mt-3 max-w-md bg-white" placeholder={`场次标题，例如：${scenes.length + 1}. 客厅对峙`} />
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
                            <div className="flex items-center gap-2"><Badge className="bg-sky-700">第 {scene.sceneNumber} 场</Badge><span className="text-sm font-semibold">{scene.title}</span>{index === 0 && <Badge variant="outline">当前继承源</Badge>}</div>
                            <span className="text-[11px] text-muted-foreground">{new Date(scene.createdAt).toLocaleString('zh-CN')}</span>
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
            </Tabs>
          </Card>
        </section>

        <footer className="mt-6 flex flex-col justify-between gap-2 border-t border-border py-5 text-xs text-muted-foreground sm:flex-row">
          <span>交互分析、分镜修复与跨场景状态继承已串联。</span>
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
