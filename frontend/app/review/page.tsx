"use client";

import { useQuery } from "@tanstack/react-query";
import { apiService } from "@/services/api";
import { useState } from "react";
import { Requirement, Candidate } from "@/types";
import {
  Columns3,
  Search,
  Filter,
  Sparkles,
  AlertTriangle,
  Award,
  ChevronDown,
  ChevronUp,
  FileText
} from "lucide-react";
import { motion } from "framer-motion";
import Link from "next/link";
import { useActiveRun } from "@/context/ActiveRunContext";
import { ReviewEmptyState } from "@/components/empty-states/ReviewEmptyState";

function ReviewContent() {
  const { activeRunId } = useActiveRun();

  const [searchQuery, setSearchQuery] = useState("");
  const [filterStatus, setFilterStatus] = useState<"all" | "review" | "ready">("all");

  const { data: requirements, isLoading } = useQuery({
    queryKey: ["requirements", activeRunId],
    queryFn: () => apiService.getRunRequirements(activeRunId!),
    enabled: !!activeRunId,
  });

  if (!activeRunId) {
    return <ReviewEmptyState />;
  }

  const filteredRequirements = requirements?.filter((req) => {
    const matchesSearch =
      req.original_text.toLowerCase().includes(searchQuery.toLowerCase()) ||
      req.sequence_in_run.toString().includes(searchQuery);

    if (filterStatus === "review") return matchesSearch && req.needs_human_review;
    if (filterStatus === "ready") return matchesSearch && !req.needs_human_review;
    return matchesSearch;
  });

  const totalReqs = requirements?.length || 0;
  const needReviewCount = requirements?.filter((r) => r.needs_human_review).length || 0;
  const readyCount = totalReqs - needReviewCount;

  return (
    <div className="space-y-6 select-none py-2">
      {/* Header Toolbar */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-[#243244]">
        <div>
          <div className="flex items-center gap-2 text-xs text-[#8FA3BF]">
            <span>Review Workspace</span>
            <span>/</span>
            <span className="text-[#1EA7FF] font-semibold">Run #{activeRunId}</span>
          </div>
          <h1 className="text-2xl font-bold text-[#F5F7FA]">Requirement Review Queue</h1>
        </div>

        <div className="flex items-center gap-3">
          <Link
            href="/compare"
            className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-[#0F172A] border border-[#243244] text-xs font-semibold text-[#1EA7FF] hover:border-[#1EA7FF]/40 transition"
          >
            <Columns3 className="w-4 h-4" />
            <span>Open Side-by-Side Matrix</span>
          </Link>
          <Link
            href="/export"
            className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-[#1EA7FF] hover:bg-[#008ee6] text-xs font-semibold text-white transition shadow-lg shadow-[#1EA7FF]/20"
          >
            <span>Export Report</span>
          </Link>
        </div>
      </div>

      {/* Filter & Search Bar */}
      <div className="drdo-card p-4 flex flex-col md:flex-row items-center justify-between gap-4">
        {/* Search Input */}
        <div className="relative w-full md:w-96">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-[#8FA3BF]" />
          <input
            type="text"
            placeholder="Search requirement text or #ID..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full bg-[#142036] border border-[#243244] rounded-lg pl-9 pr-4 py-2 text-xs text-[#F5F7FA] placeholder-[#8FA3BF] focus:outline-none focus:border-[#1EA7FF]"
          />
        </div>

        {/* Filter Segmented Buttons */}
        <div className="flex items-center gap-2 text-xs">
          <button
            onClick={() => setFilterStatus("all")}
            className={`px-3 py-1.5 rounded-lg border font-semibold transition ${
              filterStatus === "all"
                ? "bg-[#1EA7FF]/15 border-[#1EA7FF] text-[#1EA7FF]"
                : "bg-[#142036] border-[#243244] text-[#8FA3BF] hover:text-[#F5F7FA]"
            }`}
          >
            All ({totalReqs})
          </button>
          <button
            onClick={() => setFilterStatus("review")}
            className={`px-3 py-1.5 rounded-lg border font-semibold transition ${
              filterStatus === "review"
                ? "bg-[#FFB300]/15 border-[#FFB300] text-[#FFB300]"
                : "bg-[#142036] border-[#243244] text-[#8FA3BF] hover:text-[#F5F7FA]"
            }`}
          >
            Needs Review ({needReviewCount})
          </button>
          <button
            onClick={() => setFilterStatus("ready")}
            className={`px-3 py-1.5 rounded-lg border font-semibold transition ${
              filterStatus === "ready"
                ? "bg-[#00C853]/15 border-[#00C853] text-[#00C853]"
                : "bg-[#142036] border-[#243244] text-[#8FA3BF] hover:text-[#F5F7FA]"
            }`}
          >
            Ready ({readyCount})
          </button>
        </div>
      </div>

      {/* Requirement Cards List */}
      {isLoading ? (
        <div className="py-12 text-center text-[#8FA3BF] text-sm">Loading requirement records...</div>
      ) : !filteredRequirements || filteredRequirements.length === 0 ? (
        <div className="drdo-card p-12 text-center text-[#8FA3BF] text-sm">
          No requirements match the selected search or filter criteria.
        </div>
      ) : (
        <div className="space-y-6">
          {filteredRequirements.map((req) => {
            const seq = req.sequence_in_run + 1;
            // Rejected by src/pipeline/graph.py's ComplianceCheck gate before
            // ever reaching the LLM -- signaled by no candidates and no
            // recommended candidate index (see RejectNonEars in graph.py).
            const isRejected = req.candidates.length === 0 && req.recommended_index === -1;

            return (
              <motion.div
                key={seq}
                initial={{ opacity: 0, y: 15 }}
                animate={{ opacity: 1, y: 0 }}
                className="drdo-card p-6 space-y-5"
              >
                {/* Requirement Card Top Bar */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-4 border-b border-[#243244]">
                  <div className="flex items-center gap-3">
                    <span className="font-mono text-xs font-bold px-2.5 py-1 rounded bg-[#1EA7FF]/10 text-[#1EA7FF] border border-[#1EA7FF]/30">
                      REQ #{seq}
                    </span>
                    <span className="text-xs text-[#8FA3BF]">
                      Pattern: <strong className="text-[#F5F7FA]">{req.ears_pattern?.pattern || "Unknown"}</strong>
                    </span>
                  </div>

                  <div className="flex items-center gap-2">
                    {isRejected ? (
                      <span className="px-2.5 py-1 rounded-full bg-[#FF4D4F]/15 text-[#FF4D4F] border border-[#FF4D4F]/30 text-xs font-semibold">
                        Rejected — Not EARS Compliant
                      </span>
                    ) : req.needs_human_review ? (
                      <span className="px-2.5 py-1 rounded-full bg-[#FFB300]/15 text-[#FFB300] border border-[#FFB300]/30 text-xs font-semibold">
                        Needs Manual Review
                      </span>
                    ) : (
                      <span className="px-2.5 py-1 rounded-full bg-[#00C853]/15 text-[#00C853] border border-[#00C853]/30 text-xs font-semibold">
                        Ready for Export
                      </span>
                    )}

                    <span className="px-2.5 py-1 rounded-full bg-[#142036] text-[#F5F7FA] border border-[#243244] text-xs font-mono font-bold">
                      INCOSE: {req.recommended_score.toFixed(1)}
                    </span>
                  </div>
                </div>

                {/* Original Requirement Statement */}
                <div className="space-y-1.5">
                  <span className="text-[11px] font-bold uppercase tracking-wider text-[#8FA3BF]">
                    Original Requirement Statement
                  </span>
                  <div className="p-3.5 rounded-xl bg-[#07111F] border border-[#243244] font-mono text-xs text-[#F5F7FA] leading-relaxed">
                    {req.original_text}
                  </div>
                </div>

                {/* Detected Rule Violation Chips */}
                <div className="space-y-1.5">
                  <span className="text-[11px] font-bold uppercase tracking-wider text-[#8FA3BF]">
                    Detected Quality Defect Chips
                  </span>
                  <div className="flex flex-wrap gap-2">
                    {req.rule_flags && req.rule_flags.length > 0 ? (
                      req.rule_flags.map((flag, i) => {
                        const type = flag.violation_type.toLowerCase();
                        let colorClass = "bg-[#FFB300]/15 text-[#FFB300] border-[#FFB300]/30";
                        let prefix = "🟡";

                        if (type.includes("ambigu") || type.includes("vague")) {
                          colorClass = "bg-[#FF4D4F]/15 text-[#FF4D4F] border-[#FF4D4F]/30";
                          prefix = "🔴";
                        } else if (type.includes("trigger") || type.includes("missing")) {
                          colorClass = "bg-[#1EA7FF]/15 text-[#1EA7FF] border-[#1EA7FF]/30";
                          prefix = "🔵";
                        } else if (type.includes("compound")) {
                          colorClass = "bg-[#8B5CF6]/15 text-[#8B5CF6] border-[#8B5CF6]/30";
                          prefix = "🟣";
                        }

                        return (
                          <span
                            key={i}
                            className={`px-2.5 py-1 rounded-lg border text-xs font-semibold flex items-center gap-1.5 ${colorClass}`}
                          >
                            <span>{prefix}</span>
                            <span>{flag.violation_type.replace("_", " ")}: {flag.reason}</span>
                          </span>
                        );
                      })
                    ) : (
                      <span className="px-2.5 py-1 rounded-lg border bg-[#00C853]/15 text-[#00C853] border-[#00C853]/30 text-xs font-semibold flex items-center gap-1.5">
                        <span>🟢</span>
                        <span>Good Requirement: No Quality Defects Detected</span>
                      </span>
                    )}
                  </div>
                </div>

                {/* 3 AI Candidate Cards, or a rejection notice if the
                    EARS compliance gate never let this one reach the LLM */}
                {isRejected ? (
                  <div className="p-4 rounded-xl bg-[#FF4D4F]/5 border border-[#FF4D4F]/30 flex items-start gap-3">
                    <AlertTriangle className="w-4 h-4 text-[#FF4D4F] flex-shrink-0 mt-0.5" />
                    <p className="text-xs text-[#8FA3BF] leading-relaxed">
                      This requirement does not follow a recognized EARS pattern, so it was
                      rejected before any LLM rewrite was attempted. No candidates were
                      generated — restructure the original text into an EARS template
                      (Ubiquitous, Event-driven, State-driven, Unwanted Behavior, Optional
                      Feature, or Complex) and re-run the pipeline.
                    </p>
                  </div>
                ) : (
                <div className="space-y-2">
                  <span className="text-[11px] font-bold uppercase tracking-wider text-[#8FA3BF]">
                    AI Generated Candidate Rewrites
                  </span>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    {req.candidates.map((cand) => {
                      const isRecommended = cand.index === req.recommended_index;
                      return (
                        <div
                          key={cand.index}
                          className={`p-4 rounded-xl border space-y-3 transition ${
                            isRecommended
                              ? "bg-[#1EA7FF]/10 border-[#1EA7FF]/50 shadow-lg shadow-[#1EA7FF]/10"
                              : "bg-[#142036]/50 border-[#243244]"
                          }`}
                        >
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-bold text-[#F5F7FA]">
                              Candidate #{cand.index + 1}
                            </span>
                            {isRecommended && (
                              <span className="px-2 py-0.5 rounded bg-[#1EA7FF] text-white text-[10px] font-bold uppercase tracking-wider flex items-center gap-1">
                                <Award className="w-3 h-3" /> Recommended
                              </span>
                            )}
                          </div>

                          <div className="text-xs text-[#F5F7FA] leading-relaxed min-h-[4.5rem]">
                            {cand.rewritten_text}
                          </div>

                          <div className="flex items-center justify-between text-xs pt-2 border-t border-[#243244]/60">
                            <span className="text-[#8FA3BF]">INCOSE Score:</span>
                            <span className="font-mono font-bold text-[#1EA7FF]">
                              {cand.score.toFixed(1)} / 100
                            </span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
                )}

                {/* Footer */}
                {!isRejected && (
                  <div className="flex flex-wrap items-center justify-end gap-3 pt-3 border-t border-[#243244]">
                    <Link
                      href={`/compare?req_seq=${seq}`}
                      className="text-xs font-semibold text-[#1EA7FF] hover:underline flex items-center gap-1"
                    >
                      <span>View Word Diff Comparison Matrix</span>
                      <span>→</span>
                    </Link>
                  </div>
                )}
              </motion.div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function ReviewPage() {
  return <ReviewContent />;
}
