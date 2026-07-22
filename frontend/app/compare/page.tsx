"use client";

import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { apiService } from "@/services/api";
import { useState, Suspense } from "react";
import { Award, Columns3, ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useActiveRun } from "@/context/ActiveRunContext";
import { CompareEmptyState } from "@/components/empty-states/CompareEmptyState";

function CompareContent() {
  const searchParams = useSearchParams();
  const reqSeqParam = searchParams.get("req_seq");
  const { activeRunId } = useActiveRun();

  const { data: requirements, isLoading } = useQuery({
    queryKey: ["requirements", activeRunId],
    queryFn: () => apiService.getRunRequirements(activeRunId!),
    enabled: !!activeRunId,
  });

  const [selectedSeq, setSelectedSeq] = useState<number>(
    reqSeqParam ? parseInt(reqSeqParam, 10) : 1
  );

  if (!activeRunId) {
    return <CompareEmptyState />;
  }

  const selectedReq = requirements?.find((r) => r.sequence_in_run + 1 === selectedSeq) || requirements?.[0];

  const highlightWords = (original: string, candidate: string) => {
    const origWords = original.split(" ");
    const candWords = candidate.split(" ");
    return candWords.map((word, idx) => {
      const isNew = !origWords.includes(word);
      return (
        <span
          key={idx}
          className={isNew ? "bg-[#1EA7FF]/20 text-[#1EA7FF] font-semibold px-1 rounded border-b border-[#1EA7FF]" : ""}
        >
          {word}{" "}
        </span>
      );
    });
  };

  return (
    <div className="space-y-6 select-none py-2">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-[#243244]">
        <div>
          <Link
            href="/review"
            className="inline-flex items-center gap-1.5 text-xs text-[#1EA7FF] hover:underline mb-1"
          >
            <ArrowLeft className="w-3.5 h-3.5" /> Back to Review Queue
          </Link>
          <h1 className="text-2xl font-bold text-[#F5F7FA]">Side-by-Side Comparison Matrix</h1>
        </div>

        {/* Select Requirement Dropdown */}
        {requirements && requirements.length > 0 && (
          <div className="flex items-center gap-3">
            <span className="text-xs text-[#8FA3BF] font-semibold">Select Requirement:</span>
            <select
              value={selectedReq?.sequence_in_run ? selectedReq.sequence_in_run + 1 : selectedSeq}
              onChange={(e) => setSelectedSeq(parseInt(e.target.value, 10))}
              className="bg-[#0F172A] border border-[#243244] rounded-xl px-4 py-2 text-xs font-semibold text-[#F5F7FA] focus:outline-none focus:border-[#1EA7FF]"
            >
              {requirements.map((r) => (
                <option key={r.sequence_in_run} value={r.sequence_in_run + 1}>
                  REQ #{r.sequence_in_run + 1}: {r.original_text.substring(0, 60)}...
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {isLoading || !selectedReq ? (
        <div className="py-12 text-center text-[#8FA3BF] text-sm">Loading comparison matrix...</div>
      ) : (
        <div className="space-y-4">
          {/* Active Requirement Header */}
          <div className="drdo-card p-4 flex flex-col md:flex-row md:items-center justify-between gap-3 bg-[#142036]">
            <div>
              <span className="text-[10px] font-bold uppercase tracking-wider text-[#1EA7FF]">
                Active Matrix View
              </span>
              <h2 className="text-sm font-bold text-[#F5F7FA]">
                Requirement #{selectedReq.sequence_in_run + 1}
              </h2>
            </div>

            <div className="flex items-center gap-2 text-xs">
              <span className="px-2.5 py-1 rounded-full bg-[#1EA7FF]/15 text-[#1EA7FF] border border-[#1EA7FF]/30 font-semibold">
                EARS: {selectedReq.ears_pattern?.pattern || "Unknown"}
              </span>
              <span className="px-2.5 py-1 rounded-full bg-[#00C853]/15 text-[#00C853] border border-[#00C853]/30 font-semibold">
                Highest Score: {selectedReq.recommended_score.toFixed(1)}
              </span>
            </div>
          </div>

          {/* 4-Column Side-by-Side Grid */}
          <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
            {/* Column 1: Original Requirement */}
            <div className="drdo-card p-5 space-y-3 bg-[#0F172A]">
              <div className="flex items-center justify-between pb-2 border-b border-[#243244]">
                <span className="text-xs font-bold uppercase text-[#8FA3BF]">Original Input</span>
                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-[#243244] text-[#8FA3BF]">Source</span>
              </div>
              <div className="font-mono text-xs text-[#F5F7FA] leading-relaxed min-h-[12rem] p-3 rounded-lg bg-[#07111F] border border-[#243244]">
                {selectedReq.original_text}
              </div>
            </div>

            {/* Candidate Columns 2, 3, 4 */}
            {[0, 1, 2].map((idx) => {
              const cand = selectedReq.candidates.find((c) => c.index === idx);
              const isRecommended = idx === selectedReq.recommended_index;

              return (
                <div
                  key={idx}
                  className={`drdo-card p-5 space-y-3 transition ${
                    isRecommended
                      ? "bg-[#1EA7FF]/10 border-[#1EA7FF]/50 shadow-xl shadow-[#1EA7FF]/10"
                      : "bg-[#0F172A]"
                  }`}
                >
                  <div className="flex items-center justify-between pb-2 border-b border-[#243244]">
                    <span className="text-xs font-bold text-[#F5F7FA]">Candidate #{idx + 1}</span>
                    {isRecommended && (
                      <span className="px-2 py-0.5 rounded bg-[#1EA7FF] text-white text-[10px] font-bold uppercase flex items-center gap-1">
                        <Award className="w-3 h-3" /> Recommended
                      </span>
                    )}
                  </div>

                  <div className="text-xs text-[#F5F7FA] leading-relaxed min-h-[12rem] p-3 rounded-lg bg-[#07111F] border border-[#243244]">
                    {cand ? highlightWords(selectedReq.original_text, cand.rewritten_text) : "No candidate data"}
                  </div>

                  {cand && (
                    <div className="pt-2 border-t border-[#243244] flex items-center justify-between text-xs">
                      <span className="text-[#8FA3BF]">INCOSE Score:</span>
                      <span className="font-mono font-bold text-[#1EA7FF]">{cand.score.toFixed(1)} / 100</span>
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          <div className="text-xs text-[#8FA3BF] text-center pt-2">
            Highlighted blue text represents modified or inserted keywords relative to the original requirement statement.
          </div>
        </div>
      )}
    </div>
  );
}

export default function ComparePage() {
  return (
    <Suspense fallback={<div className="p-8 text-center text-sm text-[#8FA3BF]">Loading comparison matrix...</div>}>
      <CompareContent />
    </Suspense>
  );
}
