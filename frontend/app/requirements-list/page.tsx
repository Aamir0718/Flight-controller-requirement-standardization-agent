"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiService } from "@/services/api";
import { useActiveRun } from "@/context/ActiveRunContext";
import { motion } from "framer-motion";
import { ListChecks, AlertCircle, Search, RefreshCw } from "lucide-react";

// A plain requirement-number -> full-text reference list. This exists
// specifically as a companion to the Consistency Analysis page's matrix:
// that grid can only fit requirement NUMBERS on its axes (no room for
// text with 50+ requirements), so this page is where a human looks up
// what requirement #30 vs #31 actually say while reading the matrix.
export default function RequirementsListPage() {
  const { activeRunId } = useActiveRun();
  const [search, setSearch] = useState("");

  const {
    data: requirements,
    isLoading,
    isError,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ["requirements", activeRunId],
    queryFn: () => apiService.getRunRequirements(activeRunId!),
    enabled: !!activeRunId,
  });

  const filtered = useMemo(() => {
    const rows = requirements || [];
    const query = search.trim().toLowerCase();
    if (!query) return rows;
    return rows.filter(
      (r) =>
        (r.recommended_text || r.original_text || "").toLowerCase().includes(query) ||
        String(r.sequence_in_run + 1).includes(query)
    );
  }, [requirements, search]);

  if (!activeRunId) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-center">
          <AlertCircle className="w-16 h-16 text-[#8FA3BF] mx-auto mb-4" />
          <h2 className="text-xl font-bold text-[#F5F7FA] mb-2">No Active Run Selected</h2>
          <p className="text-[#8FA3BF] text-sm">
            Select a run from the history to see its requirements list.
          </p>
        </div>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-center">
          <RefreshCw className="w-8 h-8 text-[#1EA7FF] animate-spin mx-auto mb-4" />
          <p className="text-[#8FA3BF] text-sm">Loading requirements...</p>
        </div>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-center">
          <AlertCircle className="w-16 h-16 text-[#FF4D4F] mx-auto mb-4" />
          <h2 className="text-xl font-bold text-[#F5F7FA] mb-2">Failed to Load</h2>
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-[#1EA7FF] hover:bg-[#008ee6] disabled:opacity-50 text-white text-sm font-semibold transition"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isFetching ? "animate-spin" : ""}`} />
            <span>Retry</span>
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 select-none">
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex items-center justify-between flex-wrap gap-3"
      >
        <div>
          <div className="flex items-center gap-2 text-xs text-[#1EA7FF] font-semibold mb-1">
            <ListChecks className="w-4 h-4" />
            Reference List
          </div>
          <h1 className="text-2xl font-bold text-[#F5F7FA]">Requirements List</h1>
          <p className="text-xs text-[#8FA3BF] mt-1">
            Every requirement number next to its full text -- use this alongside the Consistency
            Matrix, which only shows numbers.
          </p>
        </div>
        <div className="relative w-full sm:w-72">
          <Search className="w-4 h-4 text-[#8FA3BF] absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by number or text..."
            className="w-full pl-9 pr-3 py-2 rounded-lg bg-[#0F172A] border border-[#243244] text-sm text-[#F5F7FA] placeholder:text-[#8FA3BF] focus:outline-none focus:border-[#1EA7FF]/40"
          />
        </div>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 15 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="drdo-card p-6"
      >
        {filtered.length === 0 ? (
          <div className="py-12 text-center text-[#8FA3BF] text-sm">
            {search ? "No requirements match your search." : "No requirements in this run."}
          </div>
        ) : (
          <div className="divide-y divide-[#243244]/60">
            {filtered.map((req) => (
              <div key={req.id} className="py-3 flex items-start gap-4">
                <span className="font-mono text-xs font-bold px-2.5 py-1 rounded bg-[#1EA7FF]/10 text-[#1EA7FF] border border-[#1EA7FF]/30 flex-shrink-0">
                  #{req.sequence_in_run + 1}
                </span>
                <p className="text-sm text-[#F5F7FA] leading-relaxed">
                  {req.recommended_text || req.original_text}
                </p>
              </div>
            ))}
          </div>
        )}
      </motion.div>
    </div>
  );
}
