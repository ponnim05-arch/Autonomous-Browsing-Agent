import React, { useState, useEffect, useRef } from "react";
import { apiUrl, wsUrl } from "@/lib/api";
import { Navbar } from "@/components/Navbar";
import { HomeView } from "@/views/HomeView";
import { AgentView } from "@/views/AgentView";
import { DashboardView } from "@/views/DashboardView";
import { InspectorView } from "@/views/InspectorView";

export function App() {
  const [activeTab, setActiveTab] = useState("home");
  const [backendConnected, setBackendConnected] = useState(false);
  const [config, setConfig] = useState<any>(null);

  // Active run state
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [activeGoal, setActiveGoal] = useState<string>("");
  const [activeStrategy, setActiveStrategy] = useState<string>("plan_then_execute");
  const [agentStatus, setAgentStatus] = useState<"idle" | "running" | "completed" | "error">("idle");
  const [currentUrl, setCurrentUrl] = useState<string | null>(null);
  const [pageTitle, setPageTitle] = useState<string | null>(null);
  const [currentScreenshot, setCurrentScreenshot] = useState<string | null>(null);
  const [logs, setLogs] = useState<Array<{ type: string; message: string; timestamp?: string }>>([]);
  const [steps, setSteps] = useState<any[]>([]);
  const [currentStepIndex, setCurrentStepIndex] = useState<number>(0);
  const [totalSteps, setTotalSteps] = useState<number>(0);
  const [extractedItems, setExtractedItems] = useState<any[]>([]);

  const wsRef = useRef<WebSocket | null>(null);

  // When the app window closes/reloads, tell the backend to stop all agents,
  // cancel active tasks and close browser sessions. sendBeacon survives page
  // unload; fetch keepalive is the fallback (e.g. Firefox tab close).
  useEffect(() => {
    const shutdownBeacon = () => {
      try {
        const url = apiUrl("/api/shutdown");
        if (navigator.sendBeacon) {
          navigator.sendBeacon(url, new Blob(["{}"], { type: "application/json" }));
        } else {
          fetch(url, { method: "POST", keepalive: true }).catch(() => {});
        }
      } catch {
        /* best-effort */
      }
    };
    window.addEventListener("pagehide", shutdownBeacon);
    return () => {
      window.removeEventListener("pagehide", shutdownBeacon);
      shutdownBeacon();
    };
  }, []);

  // Check backend health & fetch config. The app ALWAYS opens as a fresh
  // session: no previous run is restored, no task auto-executes. Stale runs
  // are cancelled by the backend's startup cleanup.
  useEffect(() => {
    checkHealth();
    try {
      sessionStorage.clear();
    } catch {
      /* storage unavailable */
    }
    const interval = setInterval(checkHealth, 10000);
    return () => clearInterval(interval);
  }, []);

  const checkHealth = async () => {
    try {
      const res = await fetch(apiUrl("/api/health"));
      if (res.ok) {
        setBackendConnected(true);
        if (!config) {
          const cfgRes = await fetch(apiUrl("/api/config"));
          if (cfgRes.ok) {
            const data = await cfgRes.json();
            setConfig(data);
          }
        }
      } else {
        setBackendConnected(false);
      }
    } catch {
      setBackendConnected(false);
    }
  };

  const handleStartRun = async (params: {
    goal: string;
    strategy: string;
    model: string;
    browser_mode: string;
    plan?: any;
  }) => {
    setActiveGoal(params.goal);
    setActiveStrategy(params.strategy);
    setAgentStatus("running");
    setLogs([{ type: "info", message: `Task submitted: "${params.goal}"` }]);
    setSteps(params.plan?.steps || []);
    setCurrentStepIndex(0);
    setTotalSteps(params.plan?.steps?.length || 0);
    setCurrentScreenshot(null);
    setCurrentUrl(null);
    setPageTitle(null);
    setExtractedItems([]);
    setActiveTab("agent");

    try {
      const res = await fetch(apiUrl("/api/run"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(params),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Failed to start agent run");
      }

      const { run_id } = await res.json();
      setActiveRunId(run_id);
      connectWebSocket(run_id);
    } catch (err: any) {
      setAgentStatus("error");
      setLogs((prev) => [...prev, { type: "error", message: `Error starting run: ${err.message}` }]);
    }
  };

  const connectWebSocket = (runId: string) => {
    if (wsRef.current) {
      wsRef.current.close();
    }

    const ws = new WebSocket(wsUrl(`/ws/agent/${runId}`));
    wsRef.current = ws;

    ws.onopen = () => {
      setLogs((prev) => [...prev, { type: "info", message: "Connected to real-time agent stream." }]);
    };

    ws.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);
        const { type, data } = message;

        if (type === "status") {
          setLogs((prev) => [...prev, { type: "info", message: data.message }]);
        } else if (type === "plan_ready") {
          const recSteps = data.steps || [];
          const total = data.total_steps || recSteps.length || 0;
          setSteps(recSteps);
          setTotalSteps(total);
          setLogs((prev) => [
            ...prev,
            { type: "info", message: `Execution plan prepared with ${total} actions.` },
          ]);
        } else if (type === "step_start") {
          const idx = data.step_index ?? 0;
          setCurrentStepIndex(idx);
          if (data.total_steps) {
            setTotalSteps((prev) => (prev > 0 ? prev : data.total_steps));
          }
          setSteps((prev) => {
            if (prev.length === 0 && data.total_steps) {
              return Array.from({ length: data.total_steps }, (_, sIdx) => ({
                action: sIdx === idx ? data.action : "action",
                description: sIdx === idx ? (data.description || `${data.action} ${data.selector || data.value || ""}`) : `Step ${sIdx + 1}`,
                selector: sIdx === idx ? data.selector : undefined,
                value: sIdx === idx ? data.value : undefined,
              }));
            }
            return prev;
          });
          const desc = data.description || `${data.action || ""} ${data.selector || data.value || ""}`.trim();
          setLogs((prev) => [
            ...prev,
            { type: "step", message: `Step ${idx + 1}/${data.total_steps || "?"}: ${desc}` },
          ]);
        } else if (type === "step_completed") {
          if (data.url) setCurrentUrl(data.url);
          if (data.title) setPageTitle(data.title);
          if (data.screenshot_base64) {
            setCurrentScreenshot(data.screenshot_base64);
          } else if (data.screenshot) {
            // Add cache buster
            setCurrentScreenshot(`${data.screenshot}?t=${Date.now()}`);
          }
          if (data.extracted_items && data.extracted_items.length > 0) {
            setExtractedItems((prev) => [...prev, ...data.extracted_items]);
          }
          if (data.error) {
            setLogs((prev) => [
              ...prev,
              { type: "error", message: `Step ${data.step_index + 1} issue: ${data.error}` },
            ]);
          }
        } else if (type === "browser_event") {
          setLogs((prev) => [...prev, { type: "info", message: data.message }]);
          if (data.url) setCurrentUrl(data.url);
        } else if (type === "viewport_frame" || type === "viewport_update" || type === "screenshot_stream") {
          if (data.url) setCurrentUrl(data.url);
          if (data.title) setPageTitle(data.title);
          if (data.data) {
            setCurrentScreenshot(data.data);
          } else if (data.screenshot_base64) {
            setCurrentScreenshot(data.screenshot_base64);
          } else if (data.screenshot) {
            setCurrentScreenshot(`${data.screenshot}?t=${Date.now()}`);
          }
        } else if (type === "run_cleared") {
          resetRunState();
          if (wsRef.current) {
            wsRef.current.close();
            wsRef.current = null;
          }
        } else if (type === "run_finished") {
          if (data.total_steps) {
            setTotalSteps(data.total_steps);
            setCurrentStepIndex(data.total_steps);
          }
          if (data.steps && data.steps.length > 0) {
            setSteps(data.steps);
          }
          if (data.final_url) setCurrentUrl(data.final_url);
          if (data.final_title) setPageTitle(data.final_title);
          if (data.final_screenshot_base64) {
            setCurrentScreenshot(data.final_screenshot_base64);
          } else if (data.final_screenshot) {
            setCurrentScreenshot(`${data.final_screenshot}?t=${Date.now()}`);
          }

          const msg = data.message || (data.status === "success" ? "Goal completed successfully!" : "Execution failed.");
          if (data.status === "success") {
            setAgentStatus("completed");
            setLogs((prev) => [
              ...prev,
              { type: "info", message: msg.startsWith("🎉") || msg.startsWith("⚠️") ? msg : `🎉 ${msg}` },
            ]);
          } else {
            setAgentStatus("error");
            setLogs((prev) => [
              ...prev,
              { type: "error", message: msg.startsWith("❌") ? msg : `❌ ${msg}` },
            ]);
          }
        }
      } catch (err) {
        console.error("Error parsing WS message:", err);
      }
    };

    ws.onclose = () => {
      // Stream finished or closed
    };
  };

  const handleStopRun = async () => {
    if (!activeRunId) return;
    try {
      await fetch(apiUrl(`/api/stop/${activeRunId}`), { method: "POST" });
      setAgentStatus("idle");
      setLogs((prev) => [...prev, { type: "info", message: "Agent stopped by user." }]);
    } catch (e) {
      console.error(e);
    }
  };

  const handleSendInteraction = (interaction: any) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: "interact", ...interaction }));
    }
  };

  const resetRunState = () => {
    setActiveRunId(null);
    setActiveGoal("");
    setActiveStrategy("plan_then_execute");
    setAgentStatus("idle");
    setCurrentUrl(null);
    setPageTitle(null);
    setCurrentScreenshot(null);
    setLogs([]);
    setSteps([]);
    setCurrentStepIndex(0);
    setTotalSteps(0);
    setExtractedItems([]);
  };

  const handleClearRun = async () => {
    const runId = activeRunId;
    resetRunState();
    setLogs([{ type: "info", message: "Task cleared. Ready for a new task." }]);
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    if (runId) {
      try {
        await fetch(apiUrl(`/api/runs/${runId}/clear`), { method: "POST" });
      } catch (e) {
        console.debug("Could not notify backend of run clear:", e);
      }
    }
    // Stay in the Agent View showing its fresh empty state
    setActiveTab("agent");
  };

  return (
    <div className="app-container min-h-screen bg-[#09090b] text-zinc-100 selection:bg-emerald-500/20 selection:text-emerald-300 transition-colors duration-200">
      <Navbar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        agentStatus={agentStatus}
        backendConnected={backendConnected}
        config={config}
      />

      <main className="pb-16">
        {activeTab === "home" && (
          <HomeView onStartRun={handleStartRun} config={config} />
        )}
        {activeTab === "agent" && (
          <AgentView
            runId={activeRunId}
            goal={activeGoal}
            strategy={activeStrategy}
            status={agentStatus}
            currentUrl={currentUrl}
            pageTitle={pageTitle}
            currentScreenshot={currentScreenshot}
            logs={logs}
            steps={steps}
            currentStepIndex={currentStepIndex}
            totalSteps={totalSteps}
            extractedItems={extractedItems}
            onStopRun={handleStopRun}
            onClearRun={handleClearRun}
            onNavigateHome={() => setActiveTab("home")}
            onSendInteraction={handleSendInteraction}
          />
        )}
        {activeTab === "dashboard" && <DashboardView />}
        {activeTab === "inspector" && <InspectorView />}
      </main>
    </div>
  );
}

export default App;
