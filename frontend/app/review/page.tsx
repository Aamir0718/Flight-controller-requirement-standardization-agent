"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiService } from "@/services/api";
import { useState } from "react";
import { Requirement } from "@/types";
import {
  Columns3,
  Search,
  Sparkles,
  AlertTriangle,
  Award,
  Pencil,
  Loader2,
  XCircle,
  Save,
  X,
} from "lucide-react";
import { motion } from "framer-motion";
import Link from "next/link";
import { useActiveRun } from "@/context/ActiveRunContext";
import { ReviewEmptyState } from "@/components/empty-states/ReviewEmptyState";

// Badge color/label per requirement status (src/storage/db.py's
// REQUIREMENT_STATUSES) -- "analyzed" is deliberately NOT green or red on
// its own; it just hasn't been resolved by a human yet, so it renders
// neutral/blue like "generating" does, not alarming red.
const STATUS_BADGE: Record<string, { label: string; className: string }> = {
  analyzed: {
    label: "Not Generated",
    className: "bg-[#1EA7FF]/15 text-[#1EA7FF] border-[#1EA7FF]/30",
  },
  generating: {
    label: "Generating…",
    className: "bg-[#1EA7FF]/15 text-[#1EA7FF] border-[#1EA7FF]/30",
  },
  generated: {
    label: "AI Generated",
    className: "bg-[#00C853]/15 text-[#00C853] border-[#00C853]/30",
  },
  edited: {
    label: "Manually Edited",
    className: "bg-[#8B5CF6]/15 text-[#8B5CF6] border-[#8B5CF6]/30",
  },
  failed: {
    label: "Generation Failed",
    className: "bg-[#FF4D4F]/15 text-[#FF4D4F] border-[#FF4D4F]/30",
  },
};

function ReviewContent() {
  const { activeRunId } = useActiveRun();
  const queryClient = useQueryClient();

  const [searchQuery, setSearchQuery] = useState("");
  const [filterStatus, setFilterStatus] = useState<"all" | "review" | "ready">("all");
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState("");

  const { data: requirements, isLoading } = useQuery({
    queryKey: ["requirements", activeRunId],
    queryFn: () => apiService.getRunRequirements(activeRunId!),
    enabled: !!activeRunId,
    // Live per-row progress: while anything is mid-generation, the status
    // column itself IS the progress indicator -- no separate console.
    refetchInterval: (query) => {
      const rows = query.state.data as Requirement[] | undefined;
      return rows?.some((r) => r.status === "generating") ? 1200 : false;
    },
  });

  const generateMutation = useMutation({
    mutationFn: (ids: number[]) => apiService.generateRequirements(activeRunId!, ids),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["requirements", activeRunId] });
      setSelectedIds(new Set());
    },
  });

  const editMutation = useMutation({
    mutationFn: ({ id, text }: { id: number; text: string }) =>
      apiService.editRequirement(activeRunId!, id, text),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["requirements", activeRunId] });
      setEditingId(null);
    },
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

  const selectableIds = (filteredRequirements || [])
    .filter((r) => r.status !== "generating")
    .map((r) => Number(r.id));
  const allSelected = selectableIds.length > 0 && selectableIds.every((id) => selectedIds.has(id));

  const toggleSelectAll = () => {
    setSelectedIds(allSelected ? new Set() : new Set(selectableIds));
  };

  const toggleOne = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const startEdit = (req: Requirement) => {
    setEditingId(Number(req.id));
    setEditDraft(req.recommended_text || req.original_text);
  };

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
            href="/consistency"
            className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-[#0F172A] border border-[#243244] text-xs font-semibold text-[#1EA7FF] hover:border-[#1EA7FF]/40 transition"
          >
            <span>Run Consistency Check</span>
          </Link>
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
        <div className="flex items-center gap-3 w-full md:w-auto">
          <label className="flex items-center gap-2 text-xs text-[#8FA3BF] cursor-pointer select-none">
            <input
              type="checkbox"
              checked={allSelected}
              onChange={toggleSelectAll}
              disabled={selectableIds.length === 0}
              className="w-4 h-4 accent-[#1EA7FF]"
            />
            Select All
          </label>
          <div className="relative w-full md:w-80">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-[#8FA3BF]" />
            <input
              type="text"
              placeholder="Search requirement text or #ID..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-[#142036] border border-[#243244] rounded-lg pl-9 pr-4 py-2 text-xs text-[#F5F7FA] placeholder-[#8FA3BF] focus:outline-none focus:border-[#1EA7FF]"
            />
          </div>
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

      {/* Bulk action bar -- appears only once something is selected */}
      {selectedIds.size > 0 && (
        <div className="drdo-card p-4 flex items-center justify-between gap-4 border-[#1EA7FF]/40 bg-[#1EA7FF]/5">
          <span className="text-xs text-[#F5F7FA]">
            <strong>{selectedIds.size}</strong> requirement{selectedIds.size === 1 ? "" : "s"} selected
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setSelectedIds(new Set())}
              className="px-3 py-1.5 rounded-lg text-xs font-semibold text-[#8FA3BF] hover:text-[#F5F7FA] transition"
            >
              Clear
            </button>
            <button
              onClick={() => generateMutation.mutate(Array.from(selectedIds))}
              disabled={generateMutation.isPending}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-[#1EA7FF] hover:bg-[#008ee6] disabled:opacity-50 text-white text-xs font-semibold transition"
            >
              <Sparkles className="w-3.5 h-3.5" />
              Generate Selected ({selectedIds.size})
            </button>
          </div>
        </div>
      )}

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
            const reqId = Number(req.id);
            const status = req.status || "generated"; // old-style rows default to "generated"
            const badge = STATUS_BADGE[status] || STATUS_BADGE.generated;
            const isGenerating = status === "generating";
            const isEditingThis = editingId === reqId;
            const isSaving = editMutation.isPending && editMutation.variables?.id === reqId;

            return (
              <motion.div
                key={reqId}
                initial={{ opacity: 0, y: 15 }}
                animate={{ opacity: 1, y: 0 }}
                className="drdo-card p-6 space-y-5"
              >
                {/* Requirement Card Top Bar */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-4 border-b border-[#243244]">
                  <div className="flex items-center gap-3">
                    <input
                      type="checkbox"
                      checked={selectedIds.has(reqId)}
                      onChange={() => toggleOne(reqId)}
                      disabled={isGenerating}
                      className="w-4 h-4 accent-[#1EA7FF]"
                    />
                    <span className="font-mono text-xs font-bold px-2.5 py-1 rounded bg-[#1EA7FF]/10 text-[#1EA7FF] border border-[#1EA7FF]/30">
                      REQ #{seq}
                    </span>
                    <span className="text-xs text-[#8FA3BF]">
                      Pattern: <strong className="text-[#F5F7FA]">{req.ears_pattern?.pattern || "Unknown"}</strong>
                    </span>
                  </div>

                  <div className="flex items-center gap-2">
                    <span
                      className={`px-2.5 py-1 rounded-full border text-xs font-semibold flex items-center gap-1.5 ${badge.className}`}
                    >
                      {isGenerating && <Loader2 className="w-3 h-3 animate-spin" />}
                      {badge.label}
                    </span>
                    <span className="px-2.5 py-1 rounded-full bg-[#142036] text-[#F5F7FA] border border-[#243244] text-xs font-mono font-bold">
                      INCOSE: {req.recommended_score.toFixed(1)}
                    </span>
                  </div>
                </div>

                {/* Original Requirement Statement (from the Excel cell,
                    never modified by Generate or Edit) */}
                <div className="space-y-1.5">
                  <span className="text-[11px] font-bold uppercase tracking-wider text-[#8FA3BF]">
                    Original Requirement Statement
                  </span>
                  <div className="p-3.5 rounded-xl bg-[#07111F] border border-[#243244] font-mono text-xs text-[#F5F7FA] leading-relaxed">
                    {req.original_text}
                  </div>
                </div>

                {/* INCOSE violations from the deterministic analysis --
                    always shown (also true for a generated/edited row, so
                    a human can see what the original text was flagged
                    for), sourced from src/rules/incose_scorer.py's full
                    rulebook scoring. */}
                <div className="space-y-1.5">
                  <span className="text-[11px] font-bold uppercase tracking-wider text-[#8FA3BF]">
                    INCOSE Violations (Original Text)
                  </span>
                  <div className="flex flex-wrap gap-2">
                    {req.violations && req.violations.length > 0 ? (
                      req.violations.map((v, i) => (
                        <span
                          key={i}
                          className="px-2.5 py-1 rounded-lg border text-xs font-semibold flex items-center gap-1.5 bg-[#FFB300]/15 text-[#FFB300] border-[#FFB300]/30"
                          title={v.reasons?.join(" ")}
                        >
                          <span>🟡</span>
                          <span>
                            {v.id} ({v.title})
                          </span>
                        </span>
                      ))
                    ) : (
                      <span className="px-2.5 py-1 rounded-lg border bg-[#00C853]/15 text-[#00C853] border-[#00C853]/30 text-xs font-semibold flex items-center gap-1.5">
                        <span>🟢</span>
                        <span>No INCOSE violations detected</span>
                      </span>
                    )}
                  </div>
                </div>

                {/* A rejection/failure/recheck reason, whenever
                    ears_pattern.reason carries one -- EARS/INCOSE gate
                    rejection at analysis time, a generation failure, or
                    the LLM's own output failing its post-generation
                    recheck (src/pipeline/graph.py's generate_requirement()). */}
                {req.needs_human_review && req.ears_pattern?.reason && (
                  <div className="p-3.5 rounded-xl bg-[#FF4D4F]/10 border border-[#FF4D4F]/30 flex items-start gap-2.5">
                    <AlertTriangle className="w-4 h-4 flex-shrink-0 text-[#FF4D4F] mt-0.5" />
                    <p className="text-xs text-[#FF4D4F] leading-relaxed font-mono">{req.ears_pattern.reason}</p>
                  </div>
                )}
                {status === "failed" && req.error_message && (
                  <div className="p-3.5 rounded-xl bg-[#FF4D4F]/10 border border-[#FF4D4F]/30 flex items-start gap-2.5">
                    <XCircle className="w-4 h-4 flex-shrink-0 text-[#FF4D4F] mt-0.5" />
                    <p className="text-xs text-[#FF4D4F] leading-relaxed">
                      Generation failed: {req.error_message}. Try Generate again, or Edit this requirement yourself.
                    </p>
                  </div>
                )}

                {/* Edit mode: a plain textarea, no LLM involved */}
                {isEditingThis ? (
                  <div className="space-y-2">
                    <span className="text-[11px] font-bold uppercase tracking-wider text-[#8FA3BF]">
                      Edit Requirement (Manual — No AI)
                    </span>
                    <textarea
                      value={editDraft}
                      onChange={(e) => setEditDraft(e.target.value)}
                      rows={3}
                      className="w-full p-3.5 rounded-xl bg-[#07111F] border border-[#1EA7FF]/40 font-mono text-xs text-[#F5F7FA] leading-relaxed focus:outline-none focus:border-[#1EA7FF]"
                    />
                    <div className="flex items-center justify-end gap-2">
                      <button
                        onClick={() => setEditingId(null)}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-[#8FA3BF] hover:text-[#F5F7FA] transition"
                      >
                        <X className="w-3.5 h-3.5" />
                        Cancel
                      </button>
                      <button
                        onClick={() => editMutation.mutate({ id: reqId, text: editDraft })}
                        disabled={isSaving || !editDraft.trim()}
                        className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-[#00C853] hover:bg-[#00a844] disabled:opacity-50 text-white text-xs font-semibold transition"
                      >
                        {isSaving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                        Save
                      </button>
                    </div>
                  </div>
                ) : status === "generated" || status === "edited" ? (
                  status === "edited" ? (
                    <div className="space-y-1.5">
                      <span className="text-[11px] font-bold uppercase tracking-wider text-[#8FA3BF]">
                        Manually Edited Requirement
                      </span>
                      <div className="p-3.5 rounded-xl bg-[#8B5CF6]/5 border border-[#8B5CF6]/30 font-mono text-xs text-[#F5F7FA] leading-relaxed">
                        {req.recommended_text}
                      </div>
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
                  )
                ) : isGenerating ? (
                  <div className="p-4 rounded-xl bg-[#1EA7FF]/5 border border-[#1EA7FF]/30 flex items-center gap-3">
                    <Loader2 className="w-4 h-4 text-[#1EA7FF] flex-shrink-0 animate-spin" />
                    <p className="text-xs text-[#8FA3BF]">
                      Generating candidate rewrites via Ollama — this can take seconds to several minutes on CPU.
                    </p>
                  </div>
                ) : (
                  <div className="p-4 rounded-xl bg-[#142036]/50 border border-[#243244] flex items-center gap-3">
                    <Sparkles className="w-4 h-4 text-[#8FA3BF] flex-shrink-0" />
                    <p className="text-xs text-[#8FA3BF]">
                      Not generated yet. Click Generate to send this requirement to the LLM, or Edit to write the
                      fix yourself.
                    </p>
                  </div>
                )}

                {/* Footer: per-row actions */}
                {!isEditingThis && (
                  <div className="flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-[#243244]">
                    <div>
                      {(status === "generated" || status === "edited") && (
                        <Link
                          href={`/compare?req_seq=${seq}`}
                          className="text-xs font-semibold text-[#1EA7FF] hover:underline flex items-center gap-1"
                        >
                          <span>View Word Diff Comparison Matrix</span>
                          <span>→</span>
                        </Link>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => startEdit(req)}
                        disabled={isGenerating}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#0F172A] border border-[#243244] hover:border-[#8B5CF6]/40 disabled:opacity-50 text-xs font-semibold text-[#8B5CF6] transition"
                      >
                        <Pencil className="w-3.5 h-3.5" />
                        Edit
                      </button>
                      <button
                        onClick={() => generateMutation.mutate([reqId])}
                        disabled={isGenerating || (generateMutation.isPending && generateMutation.variables?.includes(reqId))}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#1EA7FF] hover:bg-[#008ee6] disabled:opacity-50 text-xs font-semibold text-white transition"
                      >
                        <Sparkles className="w-3.5 h-3.5" />
                        {status === "generated" || status === "failed" ? "Regenerate" : "Generate"}
                      </button>
                    </div>
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
