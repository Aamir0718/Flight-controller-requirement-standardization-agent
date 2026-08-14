"use client";

import { useQuery } from "@tanstack/react-query";
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
} from "lucide-react";
import { ConsistencyResponse, RequirementRelationship } from "@/types";

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
        label: "Contradiction",
        color: "bg-[#FF4D4F]/15 text-[#FF4D4F] border-[#FF4D4F]/30",
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

  const handleReanalyze = async () => {
    if (!activeRunId) return;
    try {
      await apiService.reanalyzeConsistency(activeRunId);
      refetch();
    } catch (error: any) {
      console.error("Failed to reanalyze consistency:", error);
      alert(error.message || "Failed to reanalyze consistency. Please try again.");
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
            <div className="p-2 rounded-lg bg-[#00C853]/10 text-[#00C853]">
              <CheckCircle2 className="w-5 h-5" />
            </div>
          </div>
          <div className="text-3xl font-bold text-[#00C853]">{consistencyScore}%</div>
        </div>
      </motion.div>

      {/* Consistency Matrix */}
      <motion.div
        initial={{ opacity: 0, y: 15 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
        className="drdo-card p-6"
      >
        <div className="pb-4 border-b border-[#243244] mb-4">
          <h2 className="text-base font-bold text-[#F5F7FA] flex items-center gap-2">
            <GitBranch className="w-4 h-4 text-[#1EA7FF]" />
            Consistency Matrix
          </h2>
        </div>

        {relationships.length === 0 ? (
          <div className="py-12 text-center text-[#8FA3BF] text-sm">
            No relationships detected. All requirements appear independent.
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
