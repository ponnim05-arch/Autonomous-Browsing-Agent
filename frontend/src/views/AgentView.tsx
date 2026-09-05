import React, { useState, useEffect, useRef } from "react";
import {
  Globe,
  RefreshCw,
  Square,
  CheckCircle,
  AlertTriangle,
  Play,
  Sparkles,
  ShoppingBag,
  ExternalLink,
  ShieldCheck,
  Terminal,
  Cpu,
  Tv,
  Image as ImageIcon,
  Maximize2,
  Flame,
  Copy,
  Check,
  Volume2,
  Layers,
  ArrowUpRight,
  X
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

interface AgentViewProps {
  runId: string | null;
  goal: string;
  strategy: string;
  status: "idle" | "running" | "completed" | "error";
  currentUrl: string | null;
  pageTitle: string | null;
  currentScreenshot: string | null;
  logs: Array<{ type: string; message: string; timestamp?: string }>;
  steps: any[];
  currentStepIndex: number;
  totalSteps: number;
  extractedItems: any[];
  onStopRun: () => void;
  onNavigateHome: () => void;
}

interface RelatedVideo {
  rank: number;
  videoId: string;
  title: string;
  author: string;
  url: string;
  thumbnail: string;
  duration?: string;
  views?: string;
  timeAgo?: string;
}

export const AgentView: React.FC<AgentViewProps> = ({
  runId,
  goal,
  strategy,
  status,
  currentUrl,
  pageTitle,
  currentScreenshot,
  logs,
  steps,
  currentStepIndex,
  totalSteps,
  extractedItems,
  onStopRun,
  onNavigateHome,
}) => {
  const [viewMode, setViewMode] = useState<"video" | "snapshot">("video");
  const [copiedUrl, setCopiedUrl] = useState(false);
  const [zoomImage, setZoomImage] = useState<string | null>(null);
  const [relatedVideos, setRelatedVideos] = useState<RelatedVideo[]>([]);
  const [activePreviewUrl, setActivePreviewUrl] = useState<string | null>(null);
  const [imgError, setImgError] = useState(false);

  const openedTabUrlRef = useRef<string | null>(null);

  // Helper to extract YouTube video ID
  const extractYouTubeId = (url: string | null): string | null => {
    if (!url) return null;
    const match = url.match(
      /(?:youtu\.be\/|youtube\.com\/(?:embed\/|v\/|watch\?v=|watch\?.+&v=))([a-zA-Z0-9_-]{11})/
    );
    return match ? match[1] : null;
  };

  const effectiveUrl = activePreviewUrl || currentUrl;
  const youtubeVideoId = extractYouTubeId(effectiveUrl);

  // Auto-switch to video mode when a YouTube URL is present
  useEffect(() => {
    if (youtubeVideoId) {
      setViewMode("video");
    }
  }, [youtubeVideoId]);

  // Reset image error state on new screenshot
  useEffect(() => {
    setImgError(false);
  }, [currentScreenshot]);

  // Fetch top 10 related videos from backend
  useEffect(() => {
    fetch("/api/related-videos")
      .then((res) => (res.ok ? res.json() : []))
      .then((data) => {
        if (Array.isArray(data) && data.length > 0) {
          setRelatedVideos(data);
        }
      })
      .catch((err) => console.error("Error fetching related videos:", err));
  }, []);

  // Make definitely sure the main task is opened in a new tab upon completion or target reach
  useEffect(() => {
    if (
      (status === "completed" || (totalSteps > 0 && currentStepIndex >= totalSteps - 1)) &&
      currentUrl &&
      openedTabUrlRef.current !== currentUrl
    ) {
      openedTabUrlRef.current = currentUrl;
      try {
        const newTab = window.open(currentUrl, "_blank");
        if (newTab) {
          console.log("Main task automatically launched in a new tab:", currentUrl);
        }
      } catch (err) {
        console.warn("Popup blocked, user can click manual button:", err);
      }
    }
  }, [status, currentUrl, currentStepIndex, totalSteps]);

  const progressPercent =
    totalSteps > 0
      ? Math.min(100, Math.round(((currentStepIndex + 1) / totalSteps) * 100))
      : 0;

  const handleCopyUrl = () => {
    if (!effectiveUrl) return;
    navigator.clipboard.writeText(effectiveUrl);
    setCopiedUrl(true);
    setTimeout(() => setCopiedUrl(false), 2000);
  };

  const handleOpenNewTab = (urlToOpen?: string) => {
    const target = urlToOpen || effectiveUrl;
    if (target) {
      window.open(target, "_blank");
    }
  };

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8 space-y-6">
      {/* Top Status Banner */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 rounded-2xl border border-white/5 bg-zinc-900/50 p-4 backdrop-blur-md">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono text-zinc-400">RUN ID:</span>
            <span className="text-xs font-mono font-bold text-emerald-400">
              {runId || "NO ACTIVE RUN"}
            </span>
            <Badge variant="emerald" className="text-[10px] uppercase font-mono">
              {strategy}
            </Badge>
            {status === "completed" && (
              <Badge variant="cyan" className="text-[10px] uppercase font-mono">
                ✓ Task Done
              </Badge>
            )}
          </div>
          <h2 className="text-sm sm:text-base font-semibold text-white line-clamp-1">
            {goal || "Waiting for task submission..."}
          </h2>
        </div>

        <div className="flex items-center gap-3">
          {effectiveUrl && (
            <Button
              variant="default"
              size="sm"
              onClick={() => handleOpenNewTab()}
              className="bg-emerald-500 hover:bg-emerald-400 text-zinc-950 font-bold gap-1.5 shadow-lg shadow-emerald-500/20"
            >
              <span>Open in New Tab</span>
              <ExternalLink className="h-3.5 w-3.5" />
            </Button>
          )}

          {status === "running" && (
            <Button variant="destructive" size="sm" onClick={onStopRun} className="gap-1.5">
              <Square className="h-3.5 w-3.5 fill-current" />
              <span>Stop Agent</span>
            </Button>
          )}

          {status !== "running" && (
            <Button variant="secondary" size="sm" onClick={onNavigateHome}>
              New Task
            </Button>
          )}
        </div>
      </div>

      {/* Prominent Completion Notice with New Tab confirmation */}
      {status === "completed" && effectiveUrl && (
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 rounded-2xl bg-gradient-to-r from-emerald-950/70 via-zinc-900 to-zinc-900 border border-emerald-500/40 p-4 shadow-xl">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-emerald-500 text-zinc-950 font-bold shadow-md shadow-emerald-500/30">
              <CheckCircle className="h-5 w-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-bold text-white">Main Task Running in New Tab</h3>
                <Badge variant="emerald" className="text-[10px]">
                  Ready
                </Badge>
              </div>
              <p className="text-xs text-zinc-300 line-clamp-1 mt-0.5">
                {pageTitle || effectiveUrl}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => handleOpenNewTab()}
              className="gap-1.5 text-xs text-emerald-300 border border-emerald-500/30 hover:bg-emerald-500/10"
            >
              <span>Switch / Re-open Tab</span>
              <ExternalLink className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      )}

      {/* Main Execution View: Split Screen */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: Subtask Checklist & Real-Time Event Log */}
        <div className="lg:col-span-5 space-y-6">
          {/* Progress Card */}
          <Card className="glass-card">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm font-semibold text-white flex items-center gap-2">
                  <Cpu className="h-4 w-4 text-emerald-400" />
                  <span>Execution Progress</span>
                </CardTitle>
                <span className="text-xs font-mono text-emerald-400 font-bold">
                  {totalSteps > 0 ? `${currentStepIndex + 1} / ${totalSteps}` : "Preparing..."}
                </span>
              </div>
              {/* Progress Bar */}
              <div className="w-full bg-zinc-950 rounded-full h-2 mt-2 overflow-hidden border border-white/5">
                <div
                  className="bg-emerald-500 h-2 transition-all duration-500 rounded-full shadow-sm shadow-emerald-500/50"
                  style={{ width: `${progressPercent}%` }}
                />
              </div>
            </CardHeader>
            <CardContent>
              {/* Planned Steps list */}
              <div className="space-y-2 max-h-56 overflow-y-auto pr-1">
                {steps.length > 0 ? (
                  steps.map((st, idx) => {
                    const isCompleted = idx < currentStepIndex || status === "completed";
                    const isCurrent = idx === currentStepIndex && status === "running";
                    return (
                      <div
                        key={idx}
                        className={`flex items-center gap-3 rounded-xl border p-2.5 text-xs transition-all ${
                          isCurrent
                            ? "border-emerald-500/50 bg-emerald-500/10 text-white"
                            : isCompleted
                            ? "border-white/5 bg-zinc-950/40 text-zinc-400"
                            : "border-white/5 bg-zinc-950/20 text-zinc-500"
                        }`}
                      >
                        <div
                          className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-md font-mono text-[10px] ${
                            isCompleted
                              ? "bg-emerald-500/20 text-emerald-400"
                              : isCurrent
                              ? "bg-emerald-500 text-zinc-950 font-bold"
                              : "bg-zinc-800 text-zinc-500"
                          }`}
                        >
                          {isCompleted ? "✓" : idx + 1}
                        </div>
                        <div className="flex-1 truncate">
                          <span className="font-semibold uppercase tracking-wider text-[10px] mr-2">
                            {st.action}
                          </span>
                          <span className="text-zinc-300">
                            {st.description || st.value || st.selector}
                          </span>
                        </div>
                        {st.checkpoint && (
                          <span className="text-[10px] text-amber-400 border border-amber-400/20 rounded px-1">
                            CP
                          </span>
                        )}
                      </div>
                    );
                  })
                ) : (
                  <p className="text-xs text-zinc-500 italic py-2">No step trace queued yet.</p>
                )}
              </div>
            </CardContent>
          </Card>

          {/* Real-Time Telemetry & Console Log */}
          <Card className="glass-card">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-semibold text-white flex items-center gap-2">
                <Terminal className="h-4 w-4 text-emerald-400" />
                <span>Live Action & Event Stream</span>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="h-72 overflow-y-auto rounded-xl bg-zinc-950/90 p-3 font-mono text-[11px] space-y-2 border border-white/5">
                {logs.length > 0 ? (
                  logs.map((log, idx) => (
                    <div key={idx} className="leading-relaxed flex gap-2">
                      <span className="text-zinc-600 shrink-0 select-none">&gt;</span>
                      <span
                        className={
                          log.type === "error"
                            ? "text-red-400"
                            : log.type === "step"
                            ? "text-emerald-400 font-semibold"
                            : log.type === "repair"
                            ? "text-amber-400"
                            : "text-zinc-300"
                        }
                      >
                        {log.message}
                      </span>
                    </div>
                  ))
                ) : (
                  <div className="flex h-full items-center justify-center text-zinc-600">
                    Listening for browser executor events...
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Right Column: Live Browser & Media Preview Container */}
        <div className="lg:col-span-7 space-y-6">
          <Card className="glass-card overflow-hidden border-white/10 shadow-2xl">
            {/* Browser Window Header & Address Bar */}
            <div className="border-b border-white/5 bg-zinc-950/95 px-4 py-3 space-y-2">
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-1.5">
                  <span className="h-3 w-3 rounded-full bg-red-500/80 inline-block" />
                  <span className="h-3 w-3 rounded-full bg-amber-500/80 inline-block" />
                  <span className="h-3 w-3 rounded-full bg-emerald-500/80 inline-block" />
                </div>

                {/* Mode Selector Tabs */}
                <div className="flex items-center bg-zinc-900 border border-white/5 rounded-lg p-0.5 text-xs">
                  {youtubeVideoId && (
                    <button
                      onClick={() => setViewMode("video")}
                      className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md transition-all font-medium ${
                        viewMode === "video"
                          ? "bg-emerald-500 text-zinc-950 font-bold shadow-sm"
                          : "text-zinc-400 hover:text-white"
                      }`}
                    >
                      <Tv className="h-3 w-3" />
                      <span>Video Player</span>
                    </button>
                  )}
                  <button
                    onClick={() => setViewMode("snapshot")}
                    className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md transition-all font-medium ${
                      viewMode === "snapshot" || !youtubeVideoId
                        ? "bg-emerald-500 text-zinc-950 font-bold shadow-sm"
                        : "text-zinc-400 hover:text-white"
                    }`}
                  >
                    <ImageIcon className="h-3 w-3" />
                    <span>Viewport Capture</span>
                  </button>
                </div>

                <div className="flex items-center gap-2">
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => {
                      if (currentScreenshot) setZoomImage(currentScreenshot);
                    }}
                    title="Zoom Snapshot"
                    className="h-7 w-7 text-zinc-400 hover:text-white hover:bg-zinc-800"
                  >
                    <Maximize2 className="h-3.5 w-3.5" />
                  </Button>
                  <RefreshCw
                    className={`h-3.5 w-3.5 text-zinc-400 ${
                      status === "running" ? "animate-spin text-emerald-400" : ""
                    }`}
                  />
                </div>
              </div>

              {/* URL Address Bar */}
              <div className="flex items-center gap-2 rounded-xl bg-zinc-900/90 px-3 py-1.5 text-xs border border-white/10 text-zinc-300">
                <ShieldCheck className="h-3.5 w-3.5 text-emerald-400 shrink-0" />
                <span className="flex-1 truncate font-mono text-[11px] text-zinc-300 select-all">
                  {effectiveUrl || "about:blank"}
                </span>

                <div className="flex items-center gap-1">
                  <button
                    onClick={handleCopyUrl}
                    className="p-1 text-zinc-400 hover:text-white rounded hover:bg-zinc-800 transition"
                    title="Copy URL"
                  >
                    {copiedUrl ? (
                      <Check className="h-3 w-3 text-emerald-400" />
                    ) : (
                      <Copy className="h-3 w-3" />
                    )}
                  </button>

                  {effectiveUrl && (
                    <button
                      onClick={() => handleOpenNewTab()}
                      className="flex items-center gap-1 px-2 py-0.5 rounded bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 text-[10px] font-semibold border border-emerald-500/30 transition-all hover:scale-105 active:scale-95"
                      title="Open page in a real browser tab"
                    >
                      <span>New Tab</span>
                      <ArrowUpRight className="h-3 w-3" />
                    </button>
                  )}
                </div>
              </div>
            </div>

            {/* Viewport Content Area */}
            <div className="relative min-h-[440px] bg-zinc-950 flex flex-col items-center justify-center overflow-hidden">
              {/* Video Player Mode (Interactive Embedded YouTube Player) */}
              {viewMode === "video" && youtubeVideoId ? (
                <div className="relative w-full h-[450px] bg-black">
                  <iframe
                    src={`https://www.youtube-nocookie.com/embed/${youtubeVideoId}?autoplay=1&enablejsapi=1&rel=0`}
                    title={pageTitle || "YouTube Video Preview"}
                    className="w-full h-full border-0"
                    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
                    allowFullScreen
                  />
                  <div className="absolute top-3 left-3 rounded-full bg-zinc-950/80 backdrop-blur-md px-2.5 py-1 text-[10px] font-semibold text-emerald-400 border border-white/10 flex items-center gap-1.5 pointer-events-none">
                    <Volume2 className="h-3 w-3 animate-pulse" />
                    <span>Live Media Playing</span>
                  </div>
                </div>
              ) : null}

              {/* Viewport Capture Mode (High-Res Browser Screenshot) */}
              {(viewMode === "snapshot" || (!youtubeVideoId && viewMode === "video")) && (
                <div className="relative w-full h-full min-h-[440px] flex items-center justify-center p-3">
                  {currentScreenshot && !imgError ? (
                    <div className="relative w-full h-full flex items-center justify-center">
                      <img
                        src={currentScreenshot}
                        alt="Live Browser Viewport"
                        className="w-full h-auto object-contain max-h-[520px] rounded-lg shadow-xl animate-in fade-in-50 duration-200 border border-white/5 cursor-zoom-in"
                        onClick={() => setZoomImage(currentScreenshot)}
                        onError={() => setImgError(true)}
                      />
                      {pageTitle && (
                        <div className="absolute bottom-3 left-3 right-3 rounded-xl bg-zinc-950/90 backdrop-blur-md p-2.5 text-xs text-white border border-white/10 flex items-center justify-between shadow-lg">
                          <span className="truncate font-medium">{pageTitle}</span>
                          <Badge variant="secondary" className="text-[10px] shrink-0 font-mono">
                            Page Loaded
                          </Badge>
                        </div>
                      )}
                    </div>
                  ) : imgError ? (
                    <div className="flex flex-col items-center justify-center p-8 text-center space-y-3 text-zinc-400">
                      <AlertTriangle className="h-10 w-10 text-amber-400" />
                      <p className="text-xs">Live screenshot is updating or temporarily unavailable.</p>
                      {effectiveUrl && (
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => handleOpenNewTab()}
                          className="gap-1.5 text-xs"
                        >
                          <span>Open in New Tab</span>
                          <ExternalLink className="h-3 w-3" />
                        </Button>
                      )}
                    </div>
                  ) : (
                    <div className="flex flex-col items-center justify-center p-12 text-center space-y-3 text-zinc-500">
                      <Globe className="h-12 w-12 text-zinc-700 animate-pulse" />
                      <p className="text-sm">
                        {status === "running"
                          ? "Capturing live browser viewport..."
                          : "Start a task to launch and observe the live browser viewport."}
                      </p>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Bottom Bar: Quick New Tab Action */}
            {effectiveUrl && (
              <div className="border-t border-white/5 bg-zinc-950/80 px-4 py-2.5 flex items-center justify-between text-xs text-zinc-400">
                <span className="flex items-center gap-1.5">
                  <span className="h-2 w-2 rounded-full bg-emerald-400 animate-ping" />
                  <span>Main task actively playing in browser</span>
                </span>
                <button
                  onClick={() => handleOpenNewTab()}
                  className="text-emerald-400 hover:text-emerald-300 font-semibold flex items-center gap-1 transition"
                >
                  <span>Open Full Video in New Tab</span>
                  <ExternalLink className="h-3 w-3" />
                </button>
              </div>
            )}
          </Card>

          {/* Extracted Products & Page Data (if available) */}
          {extractedItems && extractedItems.length > 0 && (
            <Card className="glass-card">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-semibold text-white flex items-center gap-2">
                  <ShoppingBag className="h-4 w-4 text-emerald-400" />
                  <span>Extracted Page Data & Items ({extractedItems.length})</span>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 max-h-56 overflow-y-auto pr-1">
                  {extractedItems.map((item, i) => (
                    <div
                      key={i}
                      className="rounded-xl border border-white/5 bg-zinc-950/60 p-3 text-xs space-y-1"
                    >
                      <h4 className="font-semibold text-white line-clamp-1">
                        {item.title || item.name || "Item"}
                      </h4>
                      {item.price && (
                        <p className="text-emerald-400 font-mono font-bold">{item.price}</p>
                      )}
                      {item.rating && (
                        <p className="text-amber-400 text-[10px]">★ {item.rating}</p>
                      )}
                      {item.url && (
                        <a
                          href={item.url}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-1 text-[10px] text-zinc-400 hover:text-emerald-400 mt-1"
                        >
                          <span>View Source</span>
                          <ExternalLink className="h-2.5 w-2.5" />
                        </a>
                      )}
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      {/* ── Top 10 Latest Videos & Updates Related to Task ── */}
      {relatedVideos.length > 0 && (
        <div className="space-y-4 pt-4">
          <div className="flex items-center justify-between">
            <div className="space-y-1">
              <div className="inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-emerald-400">
                <Flame className="h-4 w-4 text-amber-400" />
                <span>Top 10 Latest Videos & Tech Updates</span>
              </div>
              <h3 className="text-lg font-bold text-white">
                Prasad Tech in Telugu — Latest YouTube Releases
              </h3>
            </div>
            <Badge variant="emerald" className="text-xs font-mono">
              10 Latest Updates
            </Badge>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
            {relatedVideos.map((vid) => {
              const isCurrent = effectiveUrl?.includes(vid.videoId);
              return (
                <div
                  key={vid.videoId}
                  className={`group relative flex flex-col rounded-2xl border p-3 transition-all duration-300 ${
                    isCurrent
                      ? "border-emerald-500/60 bg-emerald-500/10 shadow-lg shadow-emerald-500/10"
                      : "border-white/5 bg-zinc-900/60 hover:border-white/20 hover:bg-zinc-900/90"
                  }`}
                >
                  {/* Thumbnail Container */}
                  <div className="relative aspect-video w-full overflow-hidden rounded-xl bg-zinc-950">
                    <img
                      src={vid.thumbnail}
                      alt={vid.title}
                      className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
                      loading="lazy"
                    />
                    <div className="absolute top-2 left-2 rounded-md bg-zinc-950/80 backdrop-blur-md px-1.5 py-0.5 text-[10px] font-bold font-mono text-emerald-400 border border-white/10">
                      #{vid.rank}
                    </div>
                    {vid.duration && (
                      <div className="absolute bottom-2 right-2 rounded-md bg-black/80 px-1.5 py-0.5 text-[10px] font-mono text-white">
                        {vid.duration}
                      </div>
                    )}
                  </div>

                  {/* Title & Metadata */}
                  <div className="mt-3 flex-1 flex flex-col justify-between space-y-2">
                    <div>
                      <h4
                        className="text-xs font-semibold text-zinc-100 line-clamp-2 group-hover:text-emerald-300 transition-colors"
                        title={vid.title}
                      >
                        {vid.title}
                      </h4>
                      <div className="mt-1 flex items-center gap-2 text-[10px] text-zinc-400 font-mono">
                        {vid.views && <span>{vid.views}</span>}
                        {vid.views && vid.timeAgo && <span>•</span>}
                        {vid.timeAgo && <span>{vid.timeAgo}</span>}
                      </div>
                    </div>

                    {/* Action Buttons */}
                    <div className="flex items-center gap-1.5 pt-1">
                      <button
                        onClick={() => {
                          setActivePreviewUrl(vid.url);
                          setViewMode("video");
                        }}
                        className="flex-1 flex items-center justify-center gap-1 rounded-lg bg-zinc-800 hover:bg-zinc-700 py-1.5 text-[11px] font-medium text-white transition-all"
                        title="Play in side container preview"
                      >
                        <Play className="h-3 w-3 fill-current text-emerald-400" />
                        <span>Preview</span>
                      </button>

                      <button
                        onClick={() => handleOpenNewTab(vid.url)}
                        className="flex items-center justify-center gap-1 rounded-lg bg-emerald-500/10 hover:bg-emerald-500/20 border border-emerald-500/30 px-2.5 py-1.5 text-[11px] font-semibold text-emerald-400 transition-all hover:scale-105 active:scale-95"
                        title="Open in new tab"
                      >
                        <ExternalLink className="h-3 w-3" />
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Screenshot Zoom Modal */}
      {zoomImage && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/90 backdrop-blur-md p-4 animate-in fade-in-50"
          onClick={() => setZoomImage(null)}
        >
          <div
            className="relative max-h-[90vh] max-w-[90vw] overflow-hidden rounded-2xl border border-white/20 bg-zinc-950 p-2 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between pb-2 px-2 border-b border-white/10 mb-2">
              <span className="text-xs font-mono text-zinc-400">High-Resolution Viewport Capture</span>
              <button
                onClick={() => setZoomImage(null)}
                className="rounded-lg p-1 text-zinc-400 hover:text-white hover:bg-zinc-800 transition"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <img
              src={zoomImage}
              alt="High Resolution Screenshot"
              className="max-h-[80vh] w-auto object-contain rounded-xl"
            />
          </div>
        </div>
      )}
    </div>
  );
};
