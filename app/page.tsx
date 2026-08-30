'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle, ArrowRight, Check, ChevronRight, Clipboard, Download,
  FileText, Film, GitBranch, Loader2, Play, RefreshCcw, ScanSearch, Sparkles, Users,
} from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import {
  analyzeScript, repairAnalysis, type AnalysisResult, type AnalysisSource,
} from '@/lib/script-engine';

const sampleScript = `客厅，夜晚。
林晓发现桌上父亲的辞职通知书，很生气地质问父亲：“你什么时候辞职的？”
父亲很尴尬，试图隐瞒：“这不重要。”
林晓不相信父亲的解释，继续追问。父亲沉默。`;

const pipeline = [
  { id: '01', label: '剧本理解', icon: FileText },
  { id: '02', label: '交互节拍', icon: GitBranch },
  { id: '03', label: '状态建模', icon: Users },
  { id: '04', label: '规则检查', icon: ScanSearch },
];

export default function Home() {
  const [script, setScript] = useState(sampleScript);
  const [result, setResult] = useState<AnalysisResult>(() => analyzeScript(sampleScript));
  const [loopCount, setLoopCount] = useState(0);
  const [copied, setCopied] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [source, setSource] = useState<AnalysisSource>('local');
  const [notice, setNotice] = useState('');

  useEffect(() => {
    const saved = window.localStorage.getItem('scene-flow-script');
    if (saved) {
      setScript(saved);
      setResult(analyzeScript(saved));
    }
  }, []);

  const activeIssues = useMemo(() => result.issues.filter((issue) => !issue.resolved), [result]);
  const hardIssues = activeIssues.filter((issue) => issue.severity === 'hard');

  async function requestAI(body: Record<string, unknown>) {
    const response = await fetch('/api/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const payload = await response.json() as { result?: AnalysisResult; error?: string };
    if (!response.ok || !payload.result) throw new Error(payload.error || '智能分析失败');
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
    } catch (error) {
      setResult(analyzeScript(script));
      setSource('local');
      setLoopCount(0);
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
    } catch (error) {
      setResult((current) => repairAnalysis(current));
      setSource('local');
      setLoopCount((current) => current + 1);
      setNotice(`${error instanceof Error ? error.message : '智能修复暂时不可用'}，本轮已由本地规则完成。`);
    } finally {
      setIsRunning(false);
    }
  }

  function exportResult() {
    const payload = { sourceScript: script, ...result, exportedAt: new Date().toISOString() };
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
                  <Button size="lg" onClick={runAnalysis} disabled={!script.trim() || isRunning} className="px-4">
                    {isRunning ? <Loader2 data-icon="inline-start" className="animate-spin" /> : <Play data-icon="inline-start" className="fill-current" />}
                    {isRunning ? '智能编译中…' : 'AI 编译这场戏'}
                  </Button>
                </div>
              </CardContent>
            </Card>

            <Card className="border-0 ring-border">
              <CardHeader>
                <CardTitle className="flex items-center gap-2"><GitBranch className="size-4 text-primary" />工作流状态</CardTitle>
                <CardDescription>第二阶段：大模型结构化编译，并由本地规则提供安全备用。</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid gap-2 sm:grid-cols-4">
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
                  <TabsList>
                    <TabsTrigger value="beats">交互节拍</TabsTrigger>
                    <TabsTrigger value="issues">问题 {activeIssues.length > 0 && <span className="rounded-full bg-primary px-1.5 text-[10px] text-primary-foreground">{activeIssues.length}</span>}</TabsTrigger>
                    <TabsTrigger value="prompt">执行Prompt</TabsTrigger>
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
                    <Button onClick={runRepairLoop} disabled={activeIssues.length === 0 || loopCount >= 3 || isRunning}>
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
                  <div className="mb-3 flex items-center justify-between">
                    <div><p className="text-sm font-semibold">模型执行指令</p><p className="text-xs text-muted-foreground">下一阶段可直接发送给大模型或视频分镜模块。</p></div>
                    <Button variant="outline" onClick={copyPrompt}>{copied ? <Check data-icon="inline-start" /> : <Clipboard data-icon="inline-start" />}{copied ? '已复制' : '复制'}</Button>
                  </div>
                  <pre className="max-h-[650px] overflow-auto whitespace-pre-wrap rounded-xl bg-[#201d1a] p-5 font-mono text-xs leading-6 text-[#f7f0e5]">{result.executionPrompt}</pre>
                </CardContent>
              </TabsContent>
            </Tabs>
          </Card>
        </section>

        <footer className="mt-6 flex flex-col justify-between gap-2 border-t border-border py-5 text-xs text-muted-foreground sm:flex-row">
          <span>智能模式使用结构化模型输出；异常时自动切换本地规则。</span>
          <span className="flex items-center gap-1.5"><Sparkles className="size-3.5" />DeepSeek Responses API · 受控修复 Loop</span>
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
