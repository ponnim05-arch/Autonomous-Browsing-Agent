import React, { useEffect, useState, useCallback } from "react";
import { apiUrl } from "@/lib/api";
import {
  Key,
  ExternalLink,
  Save,
  CheckCircle2,
  AlertCircle,
  Eye,
  EyeOff,
  RefreshCw,
  Shield,
  Search,
  Cpu,
  Loader2,
  Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface Provider {
  id: string;
  name: string;
  description: string;
  link: string;
  link_label: string;
  env_var: string;
  category: "llm" | "search";
}

interface SettingsData {
  keys: Record<string, string>;
  providers: Provider[];
}

export const SettingsView: React.FC = () => {
  const [data, setData] = useState<SettingsData | null>(null);
  const [formValues, setFormValues] = useState<Record<string, string>>({});
  const [visibleFields, setVisibleFields] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState<"idle" | "success" | "error">("idle");
  const [errorMessage, setErrorMessage] = useState("");

  const fetchKeys = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(apiUrl("/api/settings/keys"));
      if (!res.ok) throw new Error("Failed to fetch settings");
      const json: SettingsData = await res.json();
      setData(json);
      setFormValues(json.keys);
    } catch (err: any) {
      setErrorMessage(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchKeys();
  }, [fetchKeys]);

  const handleChange = (id: string, value: string) => {
    setFormValues((prev) => ({ ...prev, [id]: value }));
    setSaveStatus("idle");
  };

  const toggleVisibility = (id: string) => {
    setVisibleFields((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const handleSave = async () => {
    setSaving(true);
    setSaveStatus("idle");
    try {
      const res = await fetch(apiUrl("/api/settings/keys"), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(formValues),
      });
      if (!res.ok) throw new Error("Failed to save keys");
      setSaveStatus("success");
      // Refresh to show updated masked keys
      setTimeout(() => fetchKeys(), 1200);
    } catch (err: any) {
      setSaveStatus("error");
      setErrorMessage(err.message);
    } finally {
      setSaving(false);
    }
  };

  const hasChanges = data
    ? Object.entries(formValues).some(([key, val]) => val !== data.keys[key])
    : false;

  const llmProviders = data?.providers.filter((p) => p.category === "llm") || [];
  const searchProviders = data?.providers.filter((p) => p.category === "search") || [];

  const getCategoryIcon = (category: string) => {
    switch (category) {
      case "llm":
        return Cpu;
      case "search":
        return Search;
      default:
        return Key;
    }
  };

  const getProviderIcon = (name: string) => {
    if (name.includes("NVIDIA")) return "🟢";
    if (name.includes("Gemini") || name.includes("Google")) return "🔵";
    if (name.includes("OpenAI")) return "⚫";
    if (name.includes("Anthropic") || name.includes("Claude")) return "🟠";
    if (name.includes("Serp")) return "🔍";
    if (name.includes("Bing")) return "🟦";
    return "🔑";
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="flex flex-col items-center gap-4">
          <div className="relative">
            <div className="h-16 w-16 rounded-2xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center">
              <Loader2 className="h-8 w-8 text-emerald-400 animate-spin" />
            </div>
          </div>
          <p className="text-sm text-zinc-400 animate-pulse">Loading settings…</p>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl px-4 sm:px-6 lg:px-8 py-8 space-y-8">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="space-y-1">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center">
              <Key className="h-5 w-5 text-emerald-400" />
            </div>
            <div>
              <h1 className="text-2xl font-bold tracking-tight text-white">API Configuration</h1>
              <p className="text-sm text-zinc-400 mt-0.5">
                Manage your AI model and search API keys
              </p>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="secondary"
            onClick={fetchKeys}
            className="gap-1.5"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </Button>
          <Button
            size="sm"
            variant="default"
            onClick={handleSave}
            disabled={saving || !hasChanges}
            className="gap-1.5 bg-emerald-600 hover:bg-emerald-500 text-white disabled:opacity-40"
          >
            {saving ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Save className="h-3.5 w-3.5" />
            )}
            {saving ? "Saving…" : "Save Changes"}
          </Button>
        </div>
      </div>

      {/* Status Toast */}
      {saveStatus === "success" && (
        <div className="flex items-center gap-2 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-300 animate-in slide-in-from-top-2 duration-200">
          <CheckCircle2 className="h-4 w-4 text-emerald-400" />
          API keys saved successfully! Changes are active immediately.
        </div>
      )}
      {saveStatus === "error" && (
        <div className="flex items-center gap-2 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300 animate-in slide-in-from-top-2 duration-200">
          <AlertCircle className="h-4 w-4 text-red-400" />
          Failed to save: {errorMessage}
        </div>
      )}

      {/* Info Banner */}
      <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 px-5 py-4">
        <div className="flex items-start gap-3">
          <Shield className="h-5 w-5 text-amber-400 mt-0.5 flex-shrink-0" />
          <div className="space-y-1">
            <p className="text-sm font-medium text-amber-200">Security Note</p>
            <p className="text-xs text-zinc-400 leading-relaxed">
              API keys are stored locally in your <code className="text-zinc-300 bg-zinc-800 px-1.5 py-0.5 rounded">.env</code> file and are never transmitted to external servers.
              Keys are masked for display — only the first 8 and last 4 characters are shown.
              You need <strong className="text-zinc-300">at least one LLM provider key</strong> for the agent to work.
            </p>
          </div>
        </div>
      </div>

      {/* LLM Providers Section */}
      <section className="space-y-4">
        <div className="flex items-center gap-2">
          <Cpu className="h-4 w-4 text-emerald-400" />
          <h2 className="text-lg font-semibold text-white">AI Model Providers</h2>
          <Badge variant="emerald" className="text-[10px] uppercase font-mono tracking-wider px-1.5 py-0">
            Required
          </Badge>
        </div>
        <p className="text-xs text-zinc-400 -mt-2">
          Configure at least one LLM provider to enable planning and browser automation.
        </p>
        <div className="grid gap-4 md:grid-cols-2">
          {llmProviders.map((provider) => (
            <ApiKeyCard
              key={provider.id}
              provider={provider}
              value={formValues[provider.id] || ""}
              originalValue={data?.keys[provider.id] || ""}
              visible={visibleFields[provider.id] || false}
              onChange={(val) => handleChange(provider.id, val)}
              onToggleVisibility={() => toggleVisibility(provider.id)}
              icon={getProviderIcon(provider.name)}
            />
          ))}
        </div>
      </section>

      {/* Search Providers Section */}
      <section className="space-y-4">
        <div className="flex items-center gap-2">
          <Search className="h-4 w-4 text-blue-400" />
          <h2 className="text-lg font-semibold text-white">Search API Keys</h2>
          <Badge variant="secondary" className="text-[10px] uppercase font-mono tracking-wider px-1.5 py-0">
            Optional
          </Badge>
        </div>
        <p className="text-xs text-zinc-400 -mt-2">
          If no search key is set, the agent falls back to <strong className="text-zinc-300">free DuckDuckGo search</strong> — no key needed.
        </p>
        <div className="grid gap-4 md:grid-cols-2">
          {searchProviders.map((provider) => (
            <ApiKeyCard
              key={provider.id}
              provider={provider}
              value={formValues[provider.id] || ""}
              originalValue={data?.keys[provider.id] || ""}
              visible={visibleFields[provider.id] || false}
              onChange={(val) => handleChange(provider.id, val)}
              onToggleVisibility={() => toggleVisibility(provider.id)}
              icon={getProviderIcon(provider.name)}
            />
          ))}
        </div>
      </section>

      {/* Floating Save Bar */}
      {hasChanges && (
        <div className="fixed bottom-0 left-0 right-0 z-40 border-t border-white/10 bg-zinc-950/95 backdrop-blur-xl px-6 py-3 animate-in slide-in-from-bottom-4 duration-200">
          <div className="mx-auto max-w-5xl flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-amber-400" />
              <span className="text-sm text-zinc-300">You have unsaved changes</span>
            </div>
            <Button
              size="sm"
              onClick={handleSave}
              disabled={saving}
              className="gap-1.5 bg-emerald-600 hover:bg-emerald-500 text-white"
            >
              {saving ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Save className="h-3.5 w-3.5" />
              )}
              {saving ? "Saving…" : "Save All Changes"}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
};

/* ────────────────────── Individual API Key Card ────────────────────── */

interface ApiKeyCardProps {
  provider: Provider;
  value: string;
  originalValue: string;
  visible: boolean;
  onChange: (val: string) => void;
  onToggleVisibility: () => void;
  icon: string;
}

const ApiKeyCard: React.FC<ApiKeyCardProps> = ({
  provider,
  value,
  originalValue,
  visible,
  onChange,
  onToggleVisibility,
  icon,
}) => {
  const isConfigured = originalValue.length > 0;
  const isModified = value !== originalValue;

  return (
    <Card className="group relative overflow-hidden border-white/5 bg-zinc-900/60 hover:bg-zinc-900/80 hover:border-white/10 transition-all duration-300">
      {/* Subtle gradient accent */}
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-emerald-500/30 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />

      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <span className="text-lg">{icon}</span>
            <div>
              <CardTitle className="text-sm font-semibold text-white flex items-center gap-2">
                {provider.name}
                {isConfigured && (
                  <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
                )}
                {isModified && (
                  <Badge variant="emerald" className="text-[9px] px-1 py-0 uppercase">
                    Modified
                  </Badge>
                )}
              </CardTitle>
              <CardDescription className="text-[11px] text-zinc-500 mt-0.5">
                {provider.description}
              </CardDescription>
            </div>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-3">
        {/* Input Row */}
        <div className="relative">
          <input
            id={`key-${provider.id}`}
            type={visible ? "text" : "password"}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder={`Paste your ${provider.name} key here…`}
            spellCheck={false}
            autoComplete="off"
            className="w-full rounded-lg border border-white/10 bg-zinc-950/80 px-3 py-2.5 pr-10 text-xs font-mono text-zinc-200 placeholder:text-zinc-600 focus:border-emerald-500/50 focus:ring-1 focus:ring-emerald-500/20 focus:outline-none transition-all"
          />
          <button
            type="button"
            onClick={onToggleVisibility}
            className="absolute right-2.5 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300 transition-colors"
            title={visible ? "Hide key" : "Show key"}
          >
            {visible ? (
              <EyeOff className="h-3.5 w-3.5" />
            ) : (
              <Eye className="h-3.5 w-3.5" />
            )}
          </button>
        </div>

        {/* Env var + Get Key link */}
        <div className="flex items-center justify-between">
          <code className="text-[10px] text-zinc-600 bg-zinc-950/60 px-1.5 py-0.5 rounded">
            {provider.env_var}
          </code>
          <a
            href={provider.link}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-[11px] font-medium text-emerald-400 hover:text-emerald-300 transition-colors group/link"
          >
            <ExternalLink className="h-3 w-3 group-hover/link:translate-x-0.5 transition-transform" />
            {provider.link_label}
          </a>
        </div>
      </CardContent>
    </Card>
  );
};
