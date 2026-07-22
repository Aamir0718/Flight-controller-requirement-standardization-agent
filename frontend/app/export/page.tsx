"use client";

import { useQuery } from "@tanstack/react-query";
import { apiService } from "@/services/api";
import { Download, FileSpreadsheet, FileCode, FileText, CheckCircle2 } from "lucide-react";
import { useActiveRun } from "@/context/ActiveRunContext";
import { ExportEmptyState } from "@/components/empty-states/ExportEmptyState";

function ExportContent() {
  const { activeRunId } = useActiveRun();

  const { data: run } = useQuery({
    queryKey: ["run_status", activeRunId],
    queryFn: () => apiService.getRunStatus(activeRunId!),
    enabled: !!activeRunId,
  });

  if (!activeRunId) {
    return <ExportEmptyState />;
  }

  const downloadUrl = apiService.getDownloadUrl(activeRunId);

  return (
    <div className="max-w-4xl mx-auto space-y-6 select-none py-4">
      {/* Header */}
      <div className="pb-4 border-b border-[#243244]">
        <div className="flex items-center gap-2 text-xs text-[#1EA7FF] font-semibold mb-1">
          <Download className="w-4 h-4" /> DRDO Specification Export Center
        </div>
        <h1 className="text-2xl font-bold text-[#F5F7FA]">Export Reviewed Specification Package</h1>
        <p className="text-xs text-[#8FA3BF]">
          Download standardized flight controller requirement specifications in production-ready formats.
        </p>
      </div>

      {/* Main Download CTA Card */}
      <div className="drdo-card p-8 border-[#1EA7FF]/40 bg-gradient-to-br from-[#0F172A] via-[#142036] to-[#0F172A] space-y-6">
        <div className="flex items-center gap-4">
          <div className="p-4 rounded-2xl bg-[#1EA7FF]/10 text-[#1EA7FF] border border-[#1EA7FF]/30">
            <FileSpreadsheet className="w-8 h-8" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-[#F5F7FA]">
              {run?.file_name ? `run_${activeRunId}_review.xlsx` : `Run #${activeRunId} Reviewed Export`}
            </h2>
            <p className="text-xs text-[#8FA3BF]">
              Contains original requirements, EARS pattern tags, INCOSE score metrics, and accepted candidate rewrites.
            </p>
          </div>
        </div>

        <div className="p-4 rounded-xl bg-[#07111F] border border-[#243244] grid grid-cols-2 sm:grid-cols-4 gap-4 text-xs">
          <div>
            <span className="text-[#8FA3BF]">Run ID:</span>
            <div className="font-mono font-bold text-[#1EA7FF]">#{activeRunId}</div>
          </div>
          <div>
            <span className="text-[#8FA3BF]">Status:</span>
            <div className="font-semibold text-[#00C853] capitalize">{run?.status || "Completed"}</div>
          </div>
          <div>
            <span className="text-[#8FA3BF]">Requirements:</span>
            <div className="font-bold text-[#F5F7FA]">{run?.requirement_count || 0} items</div>
          </div>
          <div>
            <span className="text-[#8FA3BF]">Format:</span>
            <div className="font-bold text-[#F5F7FA]">OpenXML (.xlsx)</div>
          </div>
        </div>

        <div className="flex flex-wrap gap-4 pt-2">
          <a
            href={downloadUrl}
            download={`run_${activeRunId}_review.xlsx`}
            className="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-[#1EA7FF] hover:bg-[#008ee6] text-white font-semibold text-sm shadow-lg shadow-[#1EA7FF]/25 transition"
          >
            <Download className="w-4 h-4" />
            <span>Download Excel Specification</span>
          </a>
        </div>
      </div>

      {/* Additional Export Formats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
        <div className="drdo-card p-5 space-y-3 opacity-60">
          <div className="flex items-center gap-2 text-xs font-bold text-[#8FA3BF]">
            <FileCode className="w-4 h-4 text-[#8B5CF6]" />
            JSON Trace Package
          </div>
          <p className="text-xs text-[#8FA3BF]">Structured JSON payload containing raw LangGraph state transitions.</p>
          <span className="inline-block text-[10px] uppercase font-bold text-[#8FA3BF] bg-[#243244] px-2 py-0.5 rounded">
            Coming Soon
          </span>
        </div>

        <div className="drdo-card p-5 space-y-3 opacity-60">
          <div className="flex items-center gap-2 text-xs font-bold text-[#8FA3BF]">
            <FileText className="w-4 h-4 text-[#FFB300]" />
            Audit PDF Report
          </div>
          <p className="text-xs text-[#8FA3BF]">Executive compliance report with INCOSE rule failure breakdowns.</p>
          <span className="inline-block text-[10px] uppercase font-bold text-[#8FA3BF] bg-[#243244] px-2 py-0.5 rounded">
            Coming Soon
          </span>
        </div>

        <div className="drdo-card p-5 space-y-3">
          <div className="flex items-center gap-2 text-xs font-bold text-[#00C853]">
            <CheckCircle2 className="w-4 h-4" />
            SQLite Local Backup
          </div>
          <p className="text-xs text-[#8FA3BF]">Database file <code className="text-[#1EA7FF]">data/app.db</code> retains complete run history.</p>
          <span className="inline-block text-[10px] uppercase font-bold text-[#00C853] bg-[#00C853]/10 border border-[#00C853]/30 px-2 py-0.5 rounded">
            Persisted
          </span>
        </div>
      </div>
    </div>
  );
}

export default function ExportPage() {
  return <ExportContent />;
}
