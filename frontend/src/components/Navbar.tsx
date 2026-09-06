import React, { useState } from "react";
import { Zap, Activity, BarChart3, Search, Terminal, Globe, Cpu, Server, CheckCircle2, AlertCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

interface NavbarProps {
  activeTab: string;
  setActiveTab: (tab: string) => void;
  agentStatus: "idle" | "running" | "completed" | "error";
  backendConnected: boolean;
  config: any;
}

export const Navbar: React.FC<NavbarProps> = ({
  activeTab,
  setActiveTab,
  agentStatus,
  backendConnected,
  config,
}) => {
  const [showDiag, setShowDiag] = useState(false);

  const tabs = [
    { id: "home", label: "Home", icon: Globe },
    { id: "agent", label: "Agent View", icon: Activity },
    { id: "dashboard", label: "Dashboard", icon: BarChart3 },
    { id: "inspector", label: "Run Inspector", icon: Search },
  ];

  return (
    <>
      <header className="sticky top-0 z-50 w-full border-b border-white/5 bg-zinc-950/80 backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
          {/* Logo & Branding */}
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 shadow-lg shadow-emerald-500/10">
              <Zap className="h-5 w-5 animate-pulse" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-base font-bold tracking-tight text-white">
                  Fast Browser Agent
                </span>
                <Badge variant="emerald" className="text-[10px] uppercase font-mono tracking-wider px-1.5 py-0">
                  v2.0
                </Badge>
              </div>
              <p className="text-xs text-zinc-400 hidden sm:block">
                Plan-then-Execute & Multi-Tier Model Router
              </p>
            </div>
          </div>

          {/* Navigation Links */}
          <nav className="flex items-center gap-1 rounded-xl bg-zinc-900/60 p-1 border border-white/5">
            {tabs.map((tab) => {
              const Icon = tab.icon;
              const isActive = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`flex items-center gap-2 rounded-lg px-3.5 py-1.5 text-xs font-medium transition-all ${
                    isActive
                      ? "bg-zinc-800 text-emerald-400 shadow font-semibold"
                      : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/40"
                  }`}
                >
                  <Icon className={`h-3.5 w-3.5 ${isActive ? "text-emerald-400" : "text-zinc-400"}`} />
                  <span>{tab.label}</span>
                </button>
              );
            })}
          </nav>

          {/* Status & Diagnostic Button */}
          <div className="flex items-center gap-3">
            {/* Agent Live Status */}
            <div className="hidden md:flex items-center gap-2">
              <span className="relative flex h-2 w-2">
                <span
                  className={`absolute inline-flex h-full w-full rounded-full opacity-75 ${
                    agentStatus === "running"
                      ? "animate-ping bg-emerald-400"
                      : agentStatus === "completed"
                      ? "bg-emerald-500"
                      : agentStatus === "error"
                      ? "bg-red-500"
                      : "bg-zinc-500"
                  }`}
                />
                <span
                  className={`relative inline-flex h-2 w-2 rounded-full ${
                    agentStatus === "running"
                      ? "bg-emerald-400"
                      : agentStatus === "completed"
                      ? "bg-emerald-500"
                      : agentStatus === "error"
                      ? "bg-red-500"
                      : "bg-zinc-600"
                  }`}
                />
              </span>
              <span className="text-xs font-mono uppercase tracking-wider text-zinc-400">
                {agentStatus}
              </span>
            </div>

            {/* Backend Connection Indicator */}
            <button
              onClick={() => setShowDiag(true)}
              className="flex items-center gap-2 rounded-xl border border-white/10 bg-zinc-900/50 px-3 py-1.5 text-xs text-zinc-300 hover:bg-zinc-800 hover:text-white transition-all"
              title="Click to view environment diagnostics"
            >
              <Server className="h-3.5 w-3.5 text-emerald-400" />
              <span className="hidden sm:inline">Backend</span>
              <span
                className={`h-1.5 w-1.5 rounded-full ${
                  backendConnected ? "bg-emerald-400 shadow-sm shadow-emerald-400" : "bg-red-500"
                }`}
              />
            </button>
          </div>
        </div>
      </header>

      {/* Diagnostics Modal */}
      {showDiag && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="w-full max-w-lg rounded-2xl border border-white/10 bg-zinc-900 p-6 shadow-2xl animate-in zoom-in-95 duration-150">
            <div className="flex items-center justify-between pb-4 border-b border-white/5">
              <div className="flex items-center gap-2">
                <Terminal className="h-5 w-5 text-emerald-400" />
                <h3 className="text-base font-semibold text-white">System Diagnostics & Environment</h3>
              </div>
              <button
                onClick={() => setShowDiag(false)}
                className="text-zinc-400 hover:text-white text-sm"
              >
                ✕
              </button>
            </div>

            <div className="mt-4 space-y-3 text-xs font-mono">
              <div className="flex justify-between py-1.5 border-b border-white/5">
                <span className="text-zinc-400">Backend Status</span>
                <span className={backendConnected ? "text-emerald-400" : "text-red-400"}>
                  {backendConnected ? "● Connected (FastAPI)" : "○ Offline"}
                </span>
              </div>
              <div className="flex justify-between py-1.5 border-b border-white/5">
                <span className="text-zinc-400">Fast Vision Model</span>
                <span className="text-zinc-200">{config?.fast_model || "meta/llama-3.2-11b-vision-instruct"}</span>
              </div>
              <div className="flex justify-between py-1.5 border-b border-white/5">
                <span className="text-zinc-400">Reasoning Model</span>
                <span className="text-zinc-200">{config?.reasoning_model || "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"}</span>
              </div>
              <div className="flex justify-between py-1.5 border-b border-white/5">
                <span className="text-zinc-400">Browser Automation</span>
                <span className="text-zinc-200">{config?.browser_type || "chromium"} ({config?.browser_mode || "visible"})</span>
              </div>
              <div className="flex justify-between py-1.5 border-b border-white/5">
                <span className="text-zinc-400">Telemetry Storage</span>
                <span className="text-zinc-200">{config?.storage_backend || "sqlite"} (data/experiments.db)</span>
              </div>

              <div className="pt-2">
                <p className="text-zinc-400 mb-2">API Keys Detected:</p>
                <div className="grid grid-cols-2 gap-2">
                  {Object.entries(config?.api_keys_present || {}).map(([provider, present]) => (
                    <div
                      key={provider}
                      className="flex items-center gap-2 rounded-lg bg-zinc-950/60 p-2 border border-white/5"
                    >
                      {present ? (
                        <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
                      ) : (
                        <AlertCircle className="h-3.5 w-3.5 text-amber-500" />
                      )}
                      <span className="uppercase text-zinc-300">{provider}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            <div className="mt-6 flex justify-end">
              <Button size="sm" variant="secondary" onClick={() => setShowDiag(false)}>
                Close
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};
