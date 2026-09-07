"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { apiService } from "@/services/api";
import { useActiveRun } from "@/context/ActiveRunContext";
import { motion } from "framer-motion";
import {
  GitBranch,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Layers,
  RefreshCw,
  AlertCircle,
  Copy,
  FileText,
  Grid3x3,
  ListChecks,
} from "lucide-react";
import { ConsistencyResponse, RequirementRelationship, ConsistencyMatrixCell } from "@/types";

// Cell coloring: duplicate in red, contradiction in purple (kept
// distinct from duplicate's red -- both used to share red, which made it
// impossible to tell "identical wording" apart from "actively
// conflicting" just by looking at the grid, even though the underlying
// classification already knows the difference), similar in amber,
// independent in green.
const MATRIX_CELL_STYLE: Record<string, string> = {
  duplicate: "bg-[#FF4D4F]",
  contradiction: "bg-[#8B5CF6]",
  similar: "bg-[#FFB300]",
  independent: "bg-[#00C853]/40",
};

// Text color per cell background, for legibility -- amber is bright
// enough to need dark text; the rest sit on dark-enough backgrounds for
// white to read clearly.
const MATRIX_TEXT_STYLE: Record<string, string> = {
  duplicate: "text-white",
  contradiction: "text-white",
  similar: "text-[#1A1400]",
  independent: "text-white/90",
};

function pairKey(a: number, b: number): string {
  return a < b ? `${a}-${b}` : `${b}-${a}`;
}

const getRelationshipBadge = (type: string) => {
  switch (type) {
    case "duplicate":
      return {
        label: "Duplicate",
        color: "bg-[#FF4D4F]/15 text-[#FF4D4F] border-[#FF4D4F]/30",
        icon: Copy,
        action: "Merge Recommended",
      };
    case "similar":
      return {
        label: "Highly Similar",
        color: "bg-[#FFB300]/15 text-[#FFB300] border-[#FFB300]/30",
        icon: Layers,
        action: "Review Required",
      };
    case "contradiction":
      return {
        // Distinct from Duplicate's red -- same reasoning as the matrix's
        // MATRIX_CELL_STYLE above: sharing a color made "identical
        // wording" indistinguishable from "actively conflicting" at a
        // glance.
        label: "Contradiction",
        color: "bg-[#8B5CF6]/15 text-[#8B5CF6] border-[#8B5CF6]/30",
        icon: XCircle,
        action: "Manual Review Required",
      };
    default:
      return {
        label: "Independent",
        color: "bg-[#00C853]/15 text-[#00C853] border-[#00C853]/30",
        icon: CheckCircle2,
        action: null,
      };
  }
};

export default function ConsistencyPage() {
  const { activeRunId } = useActiveRun();
  // Duplicate/similarity detection is pure embeddings and never needs the
  // LLM; contradiction detection does. If the LLM endpoint isn't
  // reachable, the backend still returns valid duplicate/similar results
  // and just skips contradiction checking -- this banner is how that gets
  // surfaced, instead of it silently under-reporting contradictions.
  const [lastMessage, setLastMessage] = useState<{ text: string; isWarning: boolean } | null>(null);

  const {
    data: consistencyData,
    isLoading,
    isError,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ["consistency", activeRunId],
    queryFn: () => apiService.getRunConsistency(activeRunId!),
    enabled: !!activeRunId,
  });

  const { data: matrixData, refetch: refetchMatrix } = useQuery({
    queryKey: ["consistency_matrix", activeRunId],
    queryFn: () => apiService.getConsistencyMatrix(activeRunId!),
    enabled: !!activeRunId,
  });

  // O(1) cell lookup by display id pair, instead of scanning cells[] once
  // per grid square (n^2 lookups over an n(n-1)/2 array otherwise).
  const cellByPair = useMemo(() => {
    const map = new Map<string, ConsistencyMatrixCell>();
    for (const cell of matrixData?.cells || []) {
      map.set(pairKey(cell.display_id_1, cell.display_id_2), cell);
    }
    return map;
  }, [matrixData]);

  const handleReanalyze = async () => {
    if (!activeRunId) return;
    try {
      const result = await apiService.reanalyzeConsistency(activeRunId);
      setLastMessage({ text: result.message, isWarning: result.status !== "completed" });
      refetch();
      refetchMatrix();
    } catch (error: any) {
      console.error("Failed to reanalyze consistency:", error);
      setLastMessage({
        text: error.message || "Failed to reanalyze consistency. Please try again.",
        isWarning: true,
      });
    }
  };

  if (!activeRunId) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-center">
          <AlertCircle className="w-16 h-16 text-[#8FA3BF] mx-auto mb-4" />
          <h2 className="text-xl font-bold text-[#F5F7FA] mb-2">No Active Run Selected</h2>
          <p className="text-[#8FA3BF] text-sm">
            Select a run from the history to view consistency analysis.
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
          <p className="text-[#8FA3BF] text-sm">Loading consistency analysis...</p>
        </div>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-center">
          <AlertTriangle className="w-16 h-16 text-[#FF4D4F] mx-auto mb-4" />
          <h2 className="text-xl font-bold text-[#F5F7FA] mb-2">Analysis Failed</h2>
          <p className="text-[#8FA3BF] text-sm mb-4">
            Failed to load consistency analysis data.
          </p>
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-[#1EA7FF] hover:bg-[#008ee6] disabled:opacity-50 text-white text-sm font-semibold transition"
          >
            {isFetching ? (
              <RefreshCw className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <RefreshCw className="w-3.5 h-3.5" />
            )}
            <span>Retry</span>
          </button>
        </div>
      </div>
    );
  }

  const summary = consistencyData?.summary || {
    duplicate: 0,
    similar: 0,
    contradiction: 0,
    independent: 0,
  };
  const relationships = consistencyData?.relationships || [];

  // Calculate overall consistency score
  const totalPairs = consistencyData?.total_requirements 
    ? (consistencyData.total_requirements * (consistencyData.total_requirements - 1)) / 2
    : 1;
  const independentRatio = summary.independent / totalPairs;
  const consistencyScore = Math.round(independentRatio * 100);

  // An empty relationships list alone can't tell "never analyzed" apart
  // from "analyzed and genuinely found nothing" from "the last analysis
  // crashed" -- consistency_analyzed_at/consistency_last_error (backend's
  // src/storage/db.py) disambiguate. The score/summary cards below are
  // only a real result in the "ok" case.
  const analysisState: "never_run" | "failed" | "ok" = !consistencyData?.consistency_analyzed_at
    ? "never_run"
    : consistencyData.consistency_last_error
    ? "failed"
    : "ok";

  return (
    <div className="space-y-6 select-none">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex items-center justify-between"
      >
        <div>
          <div className="flex items-center gap-2 text-xs text-[#1EA7FF] font-semibold mb-1">
            <GitBranch className="w-4 h-4" />
            Cross Requirement Validation
          </div>
          <h1 className="text-2xl font-bold text-[#F5F7FA]">
            Requirement Consistency Analysis
          </h1>
          <p className="text-xs text-[#8FA3BF] mt-1">
            Detects duplicates, similarities, and contradictions across all requirements
          </p>
        </div>
        <button
          onClick={handleReanalyze}
          disabled={isFetching}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-[#0F172A] border border-[#243244] hover:border-[#1EA7FF]/40 text-[#F5F7FA] text-sm font-semibold transition disabled:opacity-50"
        >
          {isFetching ? (
            <RefreshCw className="w-4 h-4 animate-spin" />
          ) : (
            <RefreshCw className="w-4 h-4" />
          )}
          <span>Re-analyze</span>
        </button>
      </motion.div>

      {lastMessage && (
        <div
          className={`p-3.5 rounded-xl border flex items-start gap-2.5 text-xs ${
            lastMessage.isWarning
              ? "bg-[#FFB300]/10 border-[#FFB300]/30 text-[#FFB300]"
              : "bg-[#00C853]/10 border-[#00C853]/30 text-[#00C853]"
          }`}
        >
          {lastMessage.isWarning ? (
            <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          ) : (
            <CheckCircle2 className="w-4 h-4 flex-shrink-0 mt-0.5" />
          )}
          <p className="leading-relaxed">{lastMessage.text}</p>
        </div>
      )}

      {/* Persistent state banner -- unlike lastMessage above (only shown
          right after clicking Re-analyze this session), this reflects
          what's actually persisted for this run, so it still shows up on
          a fresh page load/reload. */}
      {analysisState === "never_run" && (
        <div className="p-3.5 rounded-xl border flex items-start gap-2.5 text-xs bg-[#1EA7FF]/10 border-[#1EA7FF]/30 text-[#1EA7FF]">
          <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <p className="leading-relaxed">
            Not analyzed yet. The numbers below are placeholders, not a real result -- click
            &quot;Re-analyze&quot; to check for duplicates, similar, and contradicting requirements.
          </p>
        </div>
      )}
      {analysisState === "failed" && (
        <div className="p-3.5 rounded-xl border flex items-start gap-2.5 text-xs bg-[#FF4D4F]/10 border-[#FF4D4F]/30 text-[#FF4D4F]">
          <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
          <p className="leading-relaxed">
            The last consistency analysis failed: {consistencyData?.consistency_last_error}. The
            numbers below do NOT reflect a real result -- do not read this as &quot;no
            relationships found&quot;. Click &quot;Re-analyze&quot; to try again.
          </p>
        </div>
      )}

      {/* Summary Cards */}
      <motion.div
        initial={{ opacity: 0, y: 15 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4"
      >
        <div className="drdo-card p-5 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-wider text-[#8FA3BF]">
              Total Requirements
            </span>
            <div className="p-2 rounded-lg bg-[#1EA7FF]/10 text-[#1EA7FF]">
              <FileText className="w-5 h-5" />
            </div>
          </div>
          <div className="text-3xl font-bold text-[#F5F7FA]">
            {consistencyData?.total_requirements || 0}
          </div>
        </div>

        <div className="drdo-card p-5 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-wider text-[#8FA3BF]">
              Duplicates
            </span>
            <div className="p-2 rounded-lg bg-[#FF4D4F]/10 text-[#FF4D4F]">
              <Copy className="w-5 h-5" />
            </div>
          </div>
          <div className="text-3xl font-bold text-[#FF4D4F]">{summary.duplicate}</div>
        </div>

        <div className="drdo-card p-5 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-wider text-[#8FA3BF]">
              Highly Similar
            </span>
            <div className="p-2 rounded-lg bg-[#FFB300]/10 text-[#FFB300]">
              <Layers className="w-5 h-5" />
            </div>
          </div>
          <div className="text-3xl font-bold text-[#FFB300]">{summary.similar}</div>
        </div>

        <div className="drdo-card p-5 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-wider text-[#8FA3BF]">
              Contradictions
            </span>
            <div className="p-2 rounded-lg bg-[#FF4D4F]/10 text-[#FF4D4F]">
              <XCircle className="w-5 h-5" />
            </div>
          </div>
          <div className="text-3xl font-bold text-[#FF4D4F]">{summary.contradiction}</div>
        </div>

        <div className="drdo-card p-5 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-wider text-[#8FA3BF]">
              Consistency Score
            </span>
            <div
              className={`p-2 rounded-lg ${
                analysisState === "ok" ? "bg-[#00C853]/10 text-[#00C853]" : "bg-[#8FA3BF]/10 text-[#8FA3BF]"
              }`}
            >
              <CheckCircle2 className="w-5 h-5" />
            </div>
          </div>
          {analysisState === "ok" ? (
            <div className="text-3xl font-bold text-[#00C853]">{consistencyScore}%</div>
          ) : (
            <div className="text-lg font-bold text-[#8FA3BF]">Not available</div>
          )}
        </div>
      </motion.div>

      {/* Consistency Matrix -- the real N x N grid: every requirement
          number on both axes, every cell colored by relationship (red =
          duplicate/contradiction, amber = similar, green = independent).
          Reuses the same analysis the Re-analyze button above already
          computed -- doesn't call the LLM or recompute anything itself. */}
      <motion.div
        initial={{ opacity: 0, y: 15 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.15 }}
        className="drdo-card p-6"
      >
        <div className="pb-4 border-b border-[#243244] mb-4 flex items-center justify-between flex-wrap gap-3">
          <div>
            <h2 className="text-base font-bold text-[#F5F7FA] flex items-center gap-2">
              <Grid3x3 className="w-4 h-4 text-[#1EA7FF]" />
              Consistency Matrix
            </h2>
            <p className="text-[10px] text-[#8FA3BF] mt-1">
              Each cell shows the similarity % between that pair of requirements.
            </p>
          </div>
          <div className="flex items-center gap-3 text-[10px] text-[#8FA3BF] flex-wrap">
            <span className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-sm bg-[#FF4D4F] inline-block" /> Duplicate
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-sm bg-[#8B5CF6] inline-block" /> Contradiction
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-sm bg-[#FFB300] inline-block" /> Similar
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-sm bg-[#00C853]/40 inline-block" /> Independent
            </span>
          </div>
        </div>

        {analysisState !== "ok" ? (
          <div className="py-12 text-center text-[#8FA3BF] text-sm">
            {analysisState === "never_run"
              ? 'Not analyzed yet -- click "Re-analyze" above to build the matrix.'
              : "The last analysis attempt failed -- see the banner above. The matrix cannot be trusted until you re-analyze."}
          </div>
        ) : matrixData && matrixData.requirements.length >= 2 ? (
          <div className="overflow-auto max-h-[560px] rounded-lg border border-[#243244]">
            <table className="border-collapse text-[10px]">
              <thead>
                <tr>
                  <th className="sticky top-0 left-0 z-20 bg-[#0F172A] border border-[#243244] w-11 h-9" />
                  {matrixData.requirements.map((colReq) => (
                    <th
                      key={colReq.id}
                      title={`#${colReq.display_id}: ${colReq.text}`}
                      className="sticky top-0 z-10 bg-[#0F172A] border border-[#243244] w-11 h-9 font-mono font-bold text-[#8FA3BF] text-center"
                    >
                      {colReq.display_id}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {matrixData.requirements.map((rowReq) => (
                  <tr key={rowReq.id}>
                    <th
                      title={`#${rowReq.display_id}: ${rowReq.text}`}
                      className="sticky left-0 z-10 bg-[#0F172A] border border-[#243244] w-11 h-9 font-mono font-bold text-[#8FA3BF] text-center"
                    >
                      {rowReq.display_id}
                    </th>
                    {matrixData.requirements.map((colReq) => {
                      if (rowReq.id === colReq.id) {
                        return (
                          <td
                            key={colReq.id}
                            title={`#${rowReq.display_id}: ${rowReq.text}`}
                            className="border border-[#243244] w-11 h-9 bg-[#243244]"
                          />
                        );
                      }
                      const cell = cellByPair.get(pairKey(rowReq.display_id, colReq.display_id));
                      const type = cell?.relationship_type || "independent";
                      const pct = cell?.similarity_score != null ? Math.round(cell.similarity_score * 100) : null;
                      const tooltip = cell
                        ? `#${rowReq.display_id} vs #${colReq.display_id}: ${type}${
                            pct != null ? ` (${pct}%)` : ""
                          }${cell.reason ? ` -- ${cell.reason}` : ""}`
                        : `#${rowReq.display_id} vs #${colReq.display_id}: independent`;
                      return (
                        <td
                          key={colReq.id}
                          title={tooltip}
                          className={`border border-[#243244] w-11 h-9 font-mono font-semibold text-center ${MATRIX_CELL_STYLE[type]} ${MATRIX_TEXT_STYLE[type]} hover:opacity-70 transition cursor-default`}
                        >
                          {pct != null ? pct : ""}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="py-12 text-center text-[#8FA3BF] text-sm">
            Need at least 2 requirements to build a matrix.
          </div>
        )}
      </motion.div>

      {/* Flagged Relationships -- the pairs the analysis actually flagged
          (duplicate/similar/contradiction), as a readable list. The grid
          above shows the whole set at a glance; this is the detail view
          for exactly the cells that aren't green. */}
      <motion.div
        initial={{ opacity: 0, y: 15 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
        className="drdo-card p-6"
      >
        <div className="pb-4 border-b border-[#243244] mb-4">
          <h2 className="text-base font-bold text-[#F5F7FA] flex items-center gap-2">
            <GitBranch className="w-4 h-4 text-[#1EA7FF]" />
            Flagged Relationships
          </h2>
        </div>

        {relationships.length === 0 ? (
          <div className="py-12 text-center text-[#8FA3BF] text-sm">
            {analysisState === "never_run"
              ? 'Not analyzed yet -- click "Re-analyze" above to check for duplicates, similar, and contradicting requirements.'
              : analysisState === "failed"
              ? "The last analysis attempt failed -- see the banner above. This is not a real result."
              : "No relationships detected. All requirements appear independent."}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-[#243244] text-[#8FA3BF] uppercase text-[10px] tracking-wider">
                  <th className="py-3 px-3">Req #1</th>
                  <th className="py-3 px-3">Req #2</th>
                  <th className="py-3 px-3">Relationship</th>
                  <th className="py-3 px-3">Similarity</th>
                  <th className="py-3 px-3">Confidence</th>
                  <th className="py-3 px-3">Reason</th>
                  <th className="py-3 px-3 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#243244]/50">
                {relationships.map((rel) => {
                  const badge = getRelationshipBadge(rel.relationship_type);
                  const Icon = badge.icon;
                  
                  return (
                    <tr key={rel.id} className="hover:bg-[#142036]/50 transition">
                      <td className="py-3 px-3 font-mono font-bold text-[#1EA7FF]">
                        #{rel.req_1?.display_id || rel.req_1?.sequence_in_run || rel.req_id_1}
                      </td>
                      <td className="py-3 px-3 font-mono font-bold text-[#1EA7FF]">
                        #{rel.req_2?.display_id || rel.req_2?.sequence_in_run || rel.req_id_2}
                      </td>
                      <td className="py-3 px-3">
                        <span
                          className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-bold border ${badge.color}`}
                        >
                          <Icon className="w-3 h-3" />
                          {badge.label}
                        </span>
                      </td>
                      <td className="py-3 px-3 text-[#8FA3BF]">
                        {(rel.similarity_score * 100).toFixed(1)}%
                      </td>
                      <td className="py-3 px-3 text-[#8FA3BF]">
                        {(rel.confidence * 100).toFixed(1)}%
                      </td>
                      <td className="py-3 px-3 text-[#8FA3BF] max-w-xs truncate">
                        {rel.reason || "-"}
                      </td>
                      <td className="py-3 px-3 text-right">
                        {badge.action && (
                          <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-[#1EA7FF]">
                            {badge.action}
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </motion.div>

      {/* Requirement Details */}
      {relationships.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 15 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3 }}
          className="drdo-card p-6"
        >
          <div className="pb-4 border-b border-[#243244] mb-4">
            <h2 className="text-base font-bold text-[#F5F7FA] flex items-center gap-2">
              <FileText className="w-4 h-4 text-[#1EA7FF]" />
              Related Requirements
            </h2>
          </div>

          <div className="space-y-4">
            {relationships.slice(0, 5).map((rel) => {
              const badge = getRelationshipBadge(rel.relationship_type);
              const Icon = badge.icon;
              
              return (
                <div
                  key={rel.id}
                  className="p-4 rounded-lg bg-[#142036]/60 border border-[#243244]/80 space-y-3"
                >
                  <div className="flex items-center justify-between">
                    <span
                      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-bold border ${badge.color}`}
                    >
                      <Icon className="w-3 h-3" />
                      {badge.label}
                    </span>
                    <span className="text-[10px] text-[#8FA3BF]">
                      {(rel.similarity_score * 100).toFixed(1)}% similar
                    </span>
                  </div>
                  
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="space-y-1">
                      <div className="text-[10px] font-bold text-[#8FA3BF]">
                        Requirement #{rel.req_1?.display_id || rel.req_1?.sequence_in_run || rel.req_id_1}
                      </div>
                      <div className="text-xs text-[#F5F7FA] line-clamp-2">
                        {rel.req_1?.recommended_text || rel.req_1?.original_text}
                      </div>
                    </div>
                    <div className="space-y-1">
                      <div className="text-[10px] font-bold text-[#8FA3BF]">
                        Requirement #{rel.req_2?.display_id || rel.req_2?.sequence_in_run || rel.req_id_2}
                      </div>
                      <div className="text-xs text-[#F5F7FA] line-clamp-2">
                        {rel.req_2?.recommended_text || rel.req_2?.original_text}
                      </div>
                    </div>
                  </div>
                  
                  {rel.reason && (
                    <div className="text-[10px] text-[#8FA3BF] italic">
                      {rel.reason}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          
          {relationships.length > 5 && (
            <div className="pt-4 text-center text-xs text-[#8FA3BF]">
              Showing 5 of {relationships.length} relationships
            </div>
          )}
        </motion.div>
      )}
    </div>
  );
}
