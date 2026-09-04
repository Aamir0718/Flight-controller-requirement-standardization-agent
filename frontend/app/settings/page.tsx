"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Settings, Server, Cpu, Database, ShieldCheck } from "lucide-react";
import { apiService } from "@/services/api";

export default function SettingsPage() {
  const { data: healthData } = useQuery({
    queryKey: ["health"],
    queryFn: () => apiService.getHealth(),
    refetchInterval: 30000,
  });
  
  const [apiUrl, setApiUrl] = useState(
    process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000"
  );

  const modelName = healthData?.model || "Loading...";

  return (
    <div className="max-w-4xl mx-auto space-y-6 select-none py-4">
      {/* Header */}
      <div className="pb-4 border-b border-[#243244]">
        <div className="flex items-center gap-2 text-xs text-[#1EA7FF] font-semibold mb-1">
          <Settings className="w-4 h-4" /> System Configuration
        </div>
        <h1 className="text-2xl font-bold text-[#F5F7FA]">Platform Settings & Environment</h1>
        <p className="text-xs text-[#8FA3BF]">
          Manage local loopback API connections, LLM endpoint parameters, and offline security rules.
        </p>
      </div>

      <div className="space-y-6">
        {/* API Settings */}
        <div className="drdo-card p-6 space-y-4">
          <h2 className="text-sm font-bold text-[#F5F7FA] flex items-center gap-2 border-b border-[#243244] pb-3">
            <Server className="w-4 h-4 text-[#1EA7FF]" />
            FastAPI Backend Endpoint
          </h2>

          <div className="space-y-2">
            <label className="text-xs font-semibold text-[#8FA3BF]">
              NEXT_PUBLIC_API_URL (FastAPI Loopback URL)
            </label>
            <input
              type="text"
              value={apiUrl}
              onChange={(e) => setApiUrl(e.target.value)}
              className="w-full bg-[#142036] border border-[#243244] rounded-xl px-4 py-2.5 text-xs font-mono text-[#F5F7FA] focus:outline-none focus:border-[#1EA7FF]"
            />
            <p className="text-[11px] text-[#8FA3BF]">
              Default is <code className="text-[#1EA7FF]">http://127.0.0.1:8000</code> to satisfy air-gapped offline guarantees.
            </p>
          </div>
        </div>

        {/* Model Settings */}
        <div className="drdo-card p-6 space-y-4">
          <h2 className="text-sm font-bold text-[#F5F7FA] flex items-center gap-2 border-b border-[#243244] pb-3">
            <Cpu className="w-4 h-4 text-[#FFB300]" />
            LLM Endpoint Configuration
          </h2>

          <div className="space-y-2">
            <label className="text-xs font-semibold text-[#8FA3BF]">
              Configured Model Name
            </label>
            <div className="w-full bg-[#142036] border border-[#243244] rounded-xl px-4 py-2.5 text-xs font-mono text-[#F5F7FA]">
              {modelName}
            </div>
            <p className="text-[11px] text-[#8FA3BF]">
              Configured model in <code className="text-[#1EA7FF]">config/settings.yaml</code>. To change, edit the configuration file and restart the backend.
            </p>
          </div>
        </div>

        {/* Security Info Card */}
        <div className="p-4 rounded-xl bg-[#00C853]/10 border border-[#00C853]/30 flex items-center gap-3 text-xs text-[#00C853]">
          <ShieldCheck className="w-5 h-5 flex-shrink-0" />
          <span>
            Analysis, editing, and export run entirely on this machine. Generate and contradiction
            detection are the only actions that reach the DRDO-internal LLM endpoint over the network.
          </span>
        </div>

        {/* Info Note */}
        <div className="p-4 rounded-xl bg-[#FFB300]/10 border border-[#FFB300]/30 flex items-center gap-3 text-xs text-[#FFB300]">
          <ShieldCheck className="w-5 h-5 flex-shrink-0" />
          <span>
            Model configuration is read-only from the backend. To change the model, edit <code className="text-[#1EA7FF]">config/settings.yaml</code> and restart the backend.
          </span>
        </div>
      </div>
    </div>
  );
}
