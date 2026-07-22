"use client";

import { useQuery } from "@tanstack/react-query";
import { apiService } from "@/services/api";
import { useState } from "react";
import { History, Search, FileSpreadsheet, CheckCircle2, AlertCircle, Clock, ArrowRight } from "lucide-react";
import { formatDate } from "@/lib/utils";
import { motion } from "framer-motion";
import { useSelectRun } from "@/hooks/useSelectRun";
import { HistoryEmptyState } from "@/components/empty-states/HistoryEmptyState";

export default function HistoryPage() {
  const [search, setSearch] = useState("");
  const selectRun = useSelectRun();

  const { data: runs, isLoading } = useQuery({
    queryKey: ["runs"],
    queryFn: () => apiService.listRuns(),
    refetchInterval: 5000,
  });

  const filteredRuns = runs?.filter((r) =>
    r.file_name.toLowerCase().includes(search.toLowerCase()) || r.id.toString().includes(search)
  );

  return (
    <div className="space-y-6 select-none py-2">
      {/* Header */}
      <div className="pb-4 border-b border-[#243244]">
        <div className="flex items-center gap-2 text-xs text-[#1EA7FF] font-semibold mb-1">
          <History className="w-4 h-4" /> Run Trace History
        </div>
        <h1 className="text-2xl font-bold text-[#F5F7FA]">Historical Analysis Runs</h1>
        <p className="text-xs text-[#8FA3BF]">
          All previously parsed and reviewed requirement workbooks persisted in local SQLite database.
        </p>
      </div>

      {/* Search Input */}
      <div className="drdo-card p-4 flex items-center justify-between">
        <div className="relative w-full md:w-96">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-[#8FA3BF]" />
          <input
            type="text"
            placeholder="Search run ID or workbook filename..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full bg-[#142036] border border-[#243244] rounded-lg pl-9 pr-4 py-2 text-xs text-[#F5F7FA] placeholder-[#8FA3BF] focus:outline-none focus:border-[#1EA7FF]"
          />
        </div>
        <div className="text-xs text-[#8FA3BF]">
          Showing {filteredRuns?.length || 0} run records
        </div>
      </div>

      {/* Runs Timeline List */}
      {isLoading ? (
        <div className="py-12 text-center text-[#8FA3BF] text-sm">Loading run history...</div>
      ) : !filteredRuns || filteredRuns.length === 0 ? (
        <HistoryEmptyState />
      ) : (
        <div className="space-y-3">
          {filteredRuns.slice().reverse().map((run) => (
            <motion.div
              key={run.id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="drdo-card p-5 flex flex-col md:flex-row md:items-center justify-between gap-4 hover:border-[#1EA7FF]/40 transition"
            >
              <div className="flex items-center gap-4">
                <div className={`p-3 rounded-xl border ${
                  run.status === "completed"
                    ? "bg-[#00C853]/10 border-[#00C853]/30 text-[#00C853]"
                    : run.status === "failed"
                    ? "bg-[#FF4D4F]/10 border-[#FF4D4F]/30 text-[#FF4D4F]"
                    : "bg-[#FFB300]/10 border-[#FFB300]/30 text-[#FFB300]"
                }`}>
                  <FileSpreadsheet className="w-6 h-6" />
                </div>

                <div className="space-y-1">
                  <div className="flex items-center gap-3">
                    <span className="font-mono text-xs font-bold text-[#1EA7FF] bg-[#1EA7FF]/10 px-2 py-0.5 rounded border border-[#1EA7FF]/20">
                      Run #{run.id}
                    </span>
                    <h3 className="text-sm font-semibold text-[#F5F7FA]">{run.file_name}</h3>
                  </div>

                  <div className="flex items-center gap-3 text-xs text-[#8FA3BF]">
                    <span>Uploaded: {formatDate(run.uploaded_at)}</span>
                    <span>•</span>
                    <span>Requirements: {run.requirement_count}/{run.total_requirements || "?"}</span>
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-3">
                <span className={`px-3 py-1 rounded-full text-xs font-bold ${
                  run.status === "completed"
                    ? "bg-[#00C853]/15 text-[#00C853] border border-[#00C853]/30"
                    : run.status === "failed"
                    ? "bg-[#FF4D4F]/15 text-[#FF4D4F] border border-[#FF4D4F]/30"
                    : "bg-[#FFB300]/15 text-[#FFB300] border border-[#FFB300]/30 animate-pulse"
                }`}>
                  {run.status.toUpperCase()}
                </span>

                {run.status === "completed" && (
                  <button
                    type="button"
                    onClick={() => selectRun(run.id)}
                    className="inline-flex items-center gap-1 px-4 py-2 rounded-xl bg-[#1EA7FF] hover:bg-[#008ee6] text-xs font-semibold text-white shadow-sm transition"
                  >
                    <span>View Review</span>
                    <ArrowRight className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
            </motion.div>
          ))}
        </div>
      )}
    </div>
  );
}
