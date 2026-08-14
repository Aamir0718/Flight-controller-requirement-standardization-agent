"use client";

import { useEffect, useState } from "react";
import { apiService } from "@/services/api";
import { Activity, Bell, Server, Database, Sparkles, RefreshCw } from "lucide-react";

export function TopNav() {
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [modelName, setModelName] = useState<string>("");

  const checkHealth = async () => {
    setIsRefreshing(true);
    try {
      const res = await apiService.getHealth();
      setApiOnline(res.status === "ok");
      setModelName(res.model || "");
    } catch {
      setApiOnline(false);
    } finally {
      setIsRefreshing(false);
    }
  };

  useEffect(() => {
    checkHealth();
    const interval = setInterval(checkHealth, 30000);
    return () => clearInterval(interval);
  }, []);

  return (
    <header className="h-16 bg-[#07111F]/80 backdrop-blur-md border-b border-[#243244] px-6 flex items-center justify-between sticky top-0 z-20">
      {/* Search / Breadcrumbs */}
      <div className="flex items-center gap-3">
        <span className="text-xs font-bold uppercase tracking-widest text-[#1EA7FF] bg-[#1EA7FF]/10 px-2.5 py-1 rounded border border-[#1EA7FF]/20">
          DRDO Flight Control Engine
        </span>
        <span className="text-xs text-[#8FA3BF]">v2.4 Aerospace Edition</span>
      </div>

      {/* Status Bar Indicators */}
      <div className="flex items-center gap-4">
        {/* Ollama Model Indicator */}
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[#0F172A] border border-[#243244] text-xs">
          <Sparkles className="w-3.5 h-3.5 text-[#FFB300]" />
          <span className="text-[#8FA3BF]">Model:</span>
          <span className="font-mono font-semibold text-[#F5F7FA]">{modelName || "Loading..."}</span>
        </div>

        {/* SQLite Database Status */}
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[#0F172A] border border-[#243244] text-xs">
          <Database className="w-3.5 h-3.5 text-[#1EA7FF]" />
          <span className="text-[#8FA3BF]">SQLite:</span>
          <span className="font-semibold text-[#00C853]">Persisted</span>
        </div>

        {/* API Backend Health Status */}
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[#0F172A] border border-[#243244] text-xs">
          <Server className="w-3.5 h-3.5 text-[#8FA3BF]" />
          <span className="text-[#8FA3BF]">FastAPI:</span>
          {apiOnline === null ? (
            <span className="text-[#FFB300] font-medium">Checking...</span>
          ) : apiOnline ? (
            <span className="flex items-center gap-1.5 text-[#00C853] font-semibold">
              <span className="w-2 h-2 rounded-full bg-[#00C853] animate-pulse"></span>
              Online (8000)
            </span>
          ) : (
            <span className="flex items-center gap-1.5 text-[#FF4D4F] font-semibold">
              <span className="w-2 h-2 rounded-full bg-[#FF4D4F]"></span>
              Offline
            </span>
          )}
        </div>

        {/* Refresh Health Button */}
        <button
          onClick={checkHealth}
          disabled={isRefreshing}
          className="p-2 rounded-lg bg-[#0F172A] border border-[#243244] text-[#8FA3BF] hover:text-[#F5F7FA] hover:border-[#1EA7FF]/40 transition"
          title="Refresh Health Status"
        >
          <RefreshCw className={`w-4 h-4 ${isRefreshing ? "animate-spin" : ""}`} />
        </button>

        {/* Notifications Icon */}
        <div className="relative p-2 rounded-lg bg-[#0F172A] border border-[#243244] text-[#8FA3BF]">
          <Bell className="w-4 h-4" />
          <span className="absolute top-1 right-1 w-2 h-2 bg-[#1EA7FF] rounded-full"></span>
        </div>
      </div>
    </header>
  );
}
