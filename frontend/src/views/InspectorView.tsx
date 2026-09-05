import React, { useEffect, useState } from "react";
import { Search, Terminal, AlertTriangle, CheckCircle, Clock, Wrench, Shield, ChevronRight } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

export const InspectorView: React.FC = () => {
  const [runs, setRuns] = useState<any[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [runDetails, setRunDetails] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetchRuns();
  }, []);

  const fetchRuns = async () => {
    try {
      const res = await fetch("/api/runs?limit=50");
      if (res.ok) {
        const data = await res.json();
        setRuns(data);
        if (data.length > 0 && !selectedRunId) {
          setSelectedRunId(data[0].run_id);
          fetchRunDetails(data[0].run_id);
        }
      }
    } catch (e) {
      console.error("Failed to fetch runs", e);
    }
  };

  const fetchRunDetails = async (runId: string) => {
    try {
      setLoading(true);
      const res = await fetch(`/api/runs/${runId}`);
      if (res.ok) {
        const data = await res.json();
        setRunDetails(data);
      }
    } catch (e) {
      console.error("Failed to load run details", e);
    } finally {
      setLoading(false);
    }
  };

  const handleSelectRun = (runId: string) => {
    setSelectedRunId(runId);
    fetchRunDetails(runId);
  };

  const summary = runDetails?.summary || {};
  const steps = runDetails?.steps || [];
  const repairs = runDetails?.repairs || [];

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8 space-y-6">
      <div>
        <h2 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
          <Search className="h-6 w-6 text-emerald-400" />
          <span>Execution Trace & Repair Inspector</span>
        </h2>
        <p className="text-sm text-zinc-400 mt-1">
          Deep-dive into step-by-step action sequences, verification checks, and prompt repair amendments.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: Run History Selector */}
        <div className="lg:col-span-4 space-y-3">
          <div className="flex items-center justify-between pb-1">
            <span className="text-xs font-semibold uppercase tracking-wider text-zinc-400">
              Recorded Runs ({runs.length})
            </span>
            <Button variant="ghost" size="sm" onClick={fetchRuns} className="text-xs text-emerald-400">
              Refresh
            </Button>
          </div>

          <div className="space-y-2 max-h-[640px] overflow-y-auto pr-1">
            {runs.length > 0 ? (
              runs.map((r) => {
                const isSelected = r.run_id === selectedRunId;
                const isSuccess = r.status === "success";
                return (
                  <div
                    key={r.run_id}
                    onClick={() => handleSelectRun(r.run_id)}
                    className={`cursor-pointer rounded-xl border p-3 text-xs transition-all ${
                      isSelected
                        ? "border-emerald-500/50 bg-emerald-500/10 shadow"
                        : "border-white/5 bg-zinc-900/50 hover:bg-zinc-800/40"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-mono font-bold text-white">{r.run_id}</span>
                      <Badge
                        variant={isSuccess ? "emerald" : r.status === "failed" ? "destructive" : "secondary"}
                        className="text-[10px]"
                      >
                        {r.status}
                      </Badge>
                    </div>
                    <p className="mt-1 font-medium text-zinc-300 line-clamp-1">{r.task_goal}</p>
                    <div className="mt-2 flex items-center justify-between text-[10px] text-zinc-500 font-mono">
                      <span>{r.strategy}</span>
                      <span>{r.completion_time_sec ? `${r.completion_time_sec.toFixed(1)}s` : "—"}</span>
                    </div>
                  </div>
                );
              })
            ) : (
              <p className="text-xs text-zinc-500 italic">No past runs found in experiments.db.</p>
            )}
          </div>
        </div>

        {/* Right Column: Detailed Trace */}
        <div className="lg:col-span-8 space-y-6">
          {loading ? (
            <div className="flex h-64 items-center justify-center text-zinc-500">
              Loading trace details...
            </div>
          ) : selectedRunId && runDetails ? (
            <>
              {/* Run Summary Card */}
              <Card className="glass-card">
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between">
                    <div>
                      <span className="text-[10px] font-mono uppercase tracking-wider text-emerald-400">
                        RUN INSPECTOR: {selectedRunId}
                      </span>
                      <CardTitle className="text-base text-white mt-1">
                        {summary.task_goal || runs.find((r) => r.run_id === selectedRunId)?.task_goal || "Run Summary"}
                      </CardTitle>
                    </div>
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs font-mono">
                    <div className="rounded-lg bg-zinc-950 p-2.5 border border-white/5">
                      <span className="text-zinc-500 block text-[10px]">Strategy</span>
                      <span className="font-semibold text-white">{summary.strategy || "—"}</span>
                    </div>
                    <div className="rounded-lg bg-zinc-950 p-2.5 border border-white/5">
                      <span className="text-zinc-500 block text-[10px]">Action Accuracy</span>
                      <span className="font-semibold text-emerald-400">
                        {summary.action_accuracy !== undefined ? `${summary.action_accuracy}%` : "100%"}
                      </span>
                    </div>
                    <div className="rounded-lg bg-zinc-950 p-2.5 border border-white/5">
                      <span className="text-zinc-500 block text-[10px]">Total Retries</span>
                      <span className="font-semibold text-amber-400">{summary.avg_retries || 0}</span>
                    </div>
                    <div className="rounded-lg bg-zinc-950 p-2.5 border border-white/5">
                      <span className="text-zinc-500 block text-[10px]">Tokens Used</span>
                      <span className="font-semibold text-white">{summary.avg_token_usage || 0}</span>
                    </div>
                  </div>
                </CardContent>
              </Card>

              {/* Prompt Repairs (if any) */}
              {repairs.length > 0 && (
                <Card className="glass-card border-amber-500/30">
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm text-amber-400 flex items-center gap-2">
                      <Wrench className="h-4 w-4" />
                      <span>Prompt Repair Engine Events ({repairs.length})</span>
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3 text-xs">
                    {repairs.map((rp: any, i: number) => (
                      <div key={i} className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-3 space-y-2">
                        <div className="flex items-center justify-between">
                          <span className="font-mono font-bold text-amber-300">
                            Step #{rp.step_index + 1} Recovery Escalation
                          </span>
                          <Badge variant="amber" className="text-[10px]">
                            {rp.repair_strategy}
                          </Badge>
                        </div>
                        <p className="text-zinc-300 font-mono text-[11px]">
                          <strong>Failure:</strong> {rp.failure_reason}
                        </p>
                      </div>
                    ))}
                  </CardContent>
                </Card>
              )}

              {/* Action Steps Sequence */}
              <Card className="glass-card">
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm text-white flex items-center gap-2">
                    <Terminal className="h-4 w-4 text-emerald-400" />
                    <span>Action Execution Sequence ({steps.length} Steps)</span>
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="space-y-2.5 max-h-96 overflow-y-auto pr-1">
                    {steps.length > 0 ? (
                      steps.map((st: any, i: number) => {
                        const isSuccess = st.verification_status === "success";
                        return (
                          <div
                            key={i}
                            className="rounded-xl border border-white/5 bg-zinc-950/60 p-3 text-xs space-y-1"
                          >
                            <div className="flex items-center justify-between font-mono">
                              <span className="font-bold text-zinc-300">
                                Step #{st.step_index + 1}: {st.sub_task_type}
                              </span>
                              <Badge variant={isSuccess ? "emerald" : "destructive"} className="text-[10px]">
                                {st.verification_status}
                              </Badge>
                            </div>
                            <div className="text-[11px] font-mono text-zinc-400">
                              <span>Action: </span>
                              <code className="text-emerald-300">{st.action_taken}</code>
                            </div>
                            {st.verification_reason && (
                              <p className="text-[10px] text-zinc-500">
                                Verification Note: {st.verification_reason}
                              </p>
                            )}
                          </div>
                        );
                      })
                    ) : (
                      <p className="text-xs text-zinc-500 italic">No action steps recorded for this run.</p>
                    )}
                  </div>
                </CardContent>
              </Card>
            </>
          ) : (
            <div className="flex h-64 items-center justify-center text-zinc-500 text-xs">
              Select a run from the left panel to inspect its full trace.
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
