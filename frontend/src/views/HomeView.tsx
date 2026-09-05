import React, { useState } from "react";
import { Play, ListTree, Sparkles, Shield, Compass, Cpu, Layers, CheckCircle2, ArrowRight, Eye, EyeOff, Radio } from "lucide-react";
import { HandwritingText } from "@/components/ui/handwriting-text";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface HomeViewProps {
  onStartRun: (params: {
    goal: string;
    strategy: string;
    model: string;
    browser_mode: string;
    plan?: any;
  }) => void;
  config: any;
}

export const HomeView: React.FC<HomeViewProps> = ({ onStartRun, config }) => {
  const [goal, setGoal] = useState("");
  const [strategy, setStrategy] = useState("plan_then_execute");
  const [model, setModel] = useState("meta/llama-3.2-11b-vision-instruct");
  const [browserMode, setBrowserMode] = useState("visible");
  const [isPlanning, setIsPlanning] = useState(false);
  const [generatedPlan, setGeneratedPlan] = useState<any>(null);
  const [planError, setPlanError] = useState<string | null>(null);

  const sampleGoals = [
    "Find the cheapest laptop under Rs.60,000 with 16GB RAM on Flipkart",
    "Search Wikipedia for Quantum Computing and extract summary",
    "Find the top trending repositories on GitHub today",
    "Search Hacker News for latest AI agent research discussions",
  ];

  const strategies = [
    {
      id: "plan_then_execute",
      name: "Plan-then-Execute",
      badge: "⚡ Ultra Fast",
      desc: "One fast LLM call creates a verified sequence. Direct Playwright execution.",
      color: "emerald",
    },
    {
      id: "dynamic",
      name: "Dynamic",
      badge: "🟢 Adaptive",
      desc: "Classic Observe-Think-Act loop after every single action.",
      color: "emerald",
    },
    {
      id: "static",
      name: "Static",
      badge: "🔵 Baseline",
      desc: "Fixed prompt pipeline with no dynamic state injection.",
      color: "cyan",
    },
    {
      id: "self_reflective",
      name: "Self-Reflective",
      badge: "🟡 CoT",
      desc: "Performs chain-of-thought analysis on DOM changes before taking actions.",
      color: "amber",
    },
    {
      id: "failure_recovery",
      name: "Failure-Recovery",
      badge: "🔴 Self-Healing",
      desc: "Aggressive error diagnostic and automatic prompt repairs on failure.",
      color: "destructive",
    },
  ];

  const handleGeneratePlan = async () => {
    if (!goal.trim()) return;
    setIsPlanning(true);
    setPlanError(null);
    try {
      const res = await fetch("/api/plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: jsonBody({ goal, model, strategy }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to generate plan");
      }
      const data = await res.json();
      setGeneratedPlan(data);
    } catch (err: any) {
      setPlanError(err.message);
    } finally {
      setIsPlanning(false);
    }
  };

  const jsonBody = (obj: any) => JSON.stringify(obj);

  const handleExecute = () => {
    if (!goal.trim()) return;
    onStartRun({
      goal,
      strategy,
      model,
      browser_mode: browserMode,
      plan: generatedPlan,
    });
  };

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8 space-y-10">
      {/* ── Hero Section with 21st.dev HandwritingText ── */}
      <div className="relative overflow-hidden rounded-3xl border border-white/10 bg-gradient-to-b from-zinc-900/90 via-zinc-900/50 to-zinc-950/80 p-8 sm:p-12 shadow-2xl backdrop-blur-xl">
        <div className="absolute top-0 right-0 -mt-8 -mr-8 h-96 w-96 rounded-full bg-emerald-500/10 blur-3xl pointer-events-none" />
        <div className="absolute bottom-0 left-0 -mb-8 -ml-8 h-80 w-80 rounded-full bg-cyan-500/10 blur-3xl pointer-events-none" />

        <div className="relative max-w-3xl space-y-4">
          <div className="inline-flex items-center gap-2 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1 text-xs font-semibold text-emerald-400">
            <Sparkles className="h-3.5 w-3.5" />
            <span>Empirical Adaptive Prompt Engineering Framework</span>
          </div>

          <h1 className="text-3xl sm:text-5xl font-extrabold tracking-tight text-white leading-tight">
            Autonomous Web Agents that are{" "}
            <br className="hidden sm:inline" />
            <HandwritingText
              words={["live.", "self-healing.", "adaptive.", "verifiable."]}
              className="text-emerald-400 font-bold"
              height="1.2em"
              interval={3000}
            />
          </h1>

          <p className="text-base sm:text-lg text-zinc-400 max-w-2xl leading-relaxed">
            Plan-then-execute architecture featuring intelligent multi-tier model routing, real-time Playwright browser execution, and autonomous prompt repair diagnostics.
          </p>
        </div>
      </div>

      {/* ── Main Configuration Form ── */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
        {/* Left Column: Goal Input & Quick Chips */}
        <div className="lg:col-span-8 space-y-6">
          <Card className="glass-card">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-white">
                <Compass className="h-5 w-5 text-emerald-400" />
                <span>Specify Your Task Goal</span>
              </CardTitle>
              <CardDescription>
                Describe what you want the autonomous browser agent to achieve in plain English.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="relative">
                <textarea
                  value={goal}
                  onChange={(e) => setGoal(e.target.value)}
                  placeholder="e.g. Find the cheapest laptop under Rs.60,000 with 16GB RAM on Flipkart"
                  rows={4}
                  className="w-full rounded-xl border border-white/10 bg-zinc-950/80 p-4 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500 transition-all font-sans"
                />
              </div>

              {/* Sample Goals */}
              <div className="space-y-2">
                <span className="text-xs font-medium text-zinc-400">Example Prompts:</span>
                <div className="flex flex-wrap gap-2">
                  {sampleGoals.map((sample, idx) => (
                    <button
                      key={idx}
                      onClick={() => setGoal(sample)}
                      className="rounded-lg border border-white/5 bg-zinc-900/60 px-2.5 py-1.5 text-xs text-zinc-300 hover:border-emerald-500/40 hover:text-emerald-400 hover:bg-zinc-800/60 transition-all text-left"
                    >
                      {sample}
                    </button>
                  ))}
                </div>
              </div>

              {/* Action Buttons */}
              <div className="flex flex-wrap gap-3 pt-2">
                <Button
                  onClick={handleExecute}
                  disabled={!goal.trim() || isPlanning}
                  size="lg"
                  className="flex-1 sm:flex-initial flex items-center gap-2"
                >
                  <Play className="h-4 w-4 fill-current" />
                  <span>Execute in Browser Now</span>
                </Button>
                <Button
                  onClick={handleGeneratePlan}
                  disabled={!goal.trim() || isPlanning}
                  variant="outline"
                  size="lg"
                  className="flex items-center gap-2"
                >
                  <ListTree className="h-4 w-4 text-emerald-400" />
                  <span>{isPlanning ? "Planning..." : "Plan Only (Preview)"}</span>
                </Button>
              </div>

              {planError && (
                <div className="rounded-xl border border-red-500/20 bg-red-500/10 p-3 text-xs text-red-400">
                  {planError}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Generated Plan Preview (if available) */}
          {generatedPlan && (
            <Card className="glass-card border-emerald-500/30 animate-in fade-in-50 duration-300">
              <CardHeader className="flex flex-row items-center justify-between">
                <div>
                  <CardTitle className="text-white flex items-center gap-2">
                    <CheckCircle2 className="h-5 w-5 text-emerald-400" />
                    <span>Plan Generated ({generatedPlan.steps?.length || 0} Steps)</span>
                  </CardTitle>
                  <CardDescription>
                    Domain: <span className="text-zinc-200">{generatedPlan.domain}</span> | Type: <span className="text-zinc-200">{generatedPlan.task_type}</span> | Tokens: <span className="text-zinc-200">{generatedPlan.tokens}</span>
                  </CardDescription>
                </div>
                <Button size="sm" onClick={handleExecute} className="gap-2">
                  <span>Start Plan</span>
                  <ArrowRight className="h-3.5 w-3.5" />
                </Button>
              </CardHeader>
              <CardContent>
                <div className="space-y-2 max-h-72 overflow-y-auto pr-2">
                  {generatedPlan.steps?.map((st: any, i: number) => (
                    <div
                      key={i}
                      className="flex items-start gap-3 rounded-xl border border-white/5 bg-zinc-950/60 p-3 text-xs"
                    >
                      <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-zinc-800 text-zinc-300 font-mono font-bold">
                        {i + 1}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="font-semibold text-white uppercase">{st.action}</span>
                          {st.checkpoint && (
                            <Badge variant="amber" className="text-[10px] px-1.5 py-0">
                              Checkpoint
                            </Badge>
                          )}
                        </div>
                        <p className="text-zinc-400 truncate mt-0.5">{st.description || st.value || st.selector}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </div>

        {/* Right Column: Execution Configuration */}
        <div className="lg:col-span-4 space-y-6">
          {/* Strategy Selection */}
          <Card className="glass-card">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-semibold text-white flex items-center gap-2">
                <Layers className="h-4 w-4 text-emerald-400" />
                <span>Prompting Strategy</span>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {strategies.map((s) => (
                <div
                  key={s.id}
                  onClick={() => setStrategy(s.id)}
                  className={`cursor-pointer rounded-xl border p-3 transition-all ${
                    strategy === s.id
                      ? "border-emerald-500/50 bg-emerald-500/10 shadow-lg shadow-emerald-500/5"
                      : "border-white/5 bg-zinc-950/40 hover:border-white/10 hover:bg-zinc-900/60"
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold text-white">{s.name}</span>
                    <Badge variant={s.color as any} className="text-[10px] px-1.5 py-0">
                      {s.badge}
                    </Badge>
                  </div>
                  <p className="mt-1 text-[11px] text-zinc-400 leading-relaxed">{s.desc}</p>
                </div>
              ))}
            </CardContent>
          </Card>

          {/* Model & Browser Mode Options */}
          <Card className="glass-card">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-semibold text-white flex items-center gap-2">
                <Cpu className="h-4 w-4 text-emerald-400" />
                <span>Runtime Settings</span>
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 text-xs">
              {/* Model Choice */}
              <div className="space-y-1.5">
                <label className="text-zinc-400 font-medium">LLM Model Tier</label>
                <select
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  className="w-full rounded-xl border border-white/10 bg-zinc-950 p-2.5 text-xs text-zinc-100 focus:border-emerald-500 focus:outline-none"
                >
                  {config?.available_models?.map((m: any) => (
                    <option key={m.id} value={m.id}>
                      {m.name} ({m.tier})
                    </option>
                  )) || (
                    <option value="meta/llama-3.2-11b-vision-instruct">
                      Llama 3.2 11B Vision (Fast Vision)
                    </option>
                  )}
                </select>
              </div>

              {/* Browser Mode */}
              <div className="space-y-1.5">
                <label className="text-zinc-400 font-medium">Browser Mode</label>
                <div className="grid grid-cols-3 gap-2">
                  <button
                    type="button"
                    onClick={() => setBrowserMode("visible")}
                    className={`flex flex-col items-center justify-center rounded-xl border p-2 text-center transition-all ${
                      browserMode === "visible"
                        ? "border-emerald-500 bg-emerald-500/10 text-emerald-400 font-semibold"
                        : "border-white/5 bg-zinc-950 text-zinc-400 hover:bg-zinc-900"
                    }`}
                  >
                    <Eye className="h-4 w-4 mb-1" />
                    <span className="text-[10px]">Visible</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setBrowserMode("headless")}
                    className={`flex flex-col items-center justify-center rounded-xl border p-2 text-center transition-all ${
                      browserMode === "headless"
                        ? "border-emerald-500 bg-emerald-500/10 text-emerald-400 font-semibold"
                        : "border-white/5 bg-zinc-950 text-zinc-400 hover:bg-zinc-900"
                    }`}
                  >
                    <EyeOff className="h-4 w-4 mb-1" />
                    <span className="text-[10px]">Headless</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setBrowserMode("cdp")}
                    className={`flex flex-col items-center justify-center rounded-xl border p-2 text-center transition-all ${
                      browserMode === "cdp"
                        ? "border-emerald-500 bg-emerald-500/10 text-emerald-400 font-semibold"
                        : "border-white/5 bg-zinc-950 text-zinc-400 hover:bg-zinc-900"
                    }`}
                  >
                    <Radio className="h-4 w-4 mb-1" />
                    <span className="text-[10px]">CDP Attach</span>
                  </button>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
};
