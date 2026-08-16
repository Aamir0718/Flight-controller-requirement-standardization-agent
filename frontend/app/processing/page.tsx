"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { apiService } from "@/services/api";
import { useEffect, useRef, useState } from "react";
import {
  CheckCircle2,
  Loader2,
  ArrowRight,
  Cpu,
  ShieldAlert,
  SquareTerminal,
  CircleDashed,
  Ban,
  CircleMinus,
} from "lucide-react";
import { motion } from "framer-motion";
import {
  InvalidExcelErrorCard,
  isInvalidExcelError,
} from "@/components/errors/InvalidExcelErrorCard";
import {
  AIErrorCard,
  isAIError,
} from "@/components/errors/AIErrorCard";
import { useActiveRun } from "@/context/ActiveRunContext";
import { ProcessingEmptyState } from "@/components/empty-states/ProcessingEmptyState";
import { StageEvent } from "@/types";

// The real LangGraph pipeline nodes (src/pipeline/graph.py), in execution
// order, run once per requirement -- distinct from the higher-level
// 8-stage rail above, which describes the whole-run flow. ComplianceCheck
// gates GenerateCandidates: a requirement that isn't EARS-compliant is
// rejected right there and never reaches the LLM (see RejectNonEars,
// handled separately below since it replaces the rest of this rail).
const PIPELINE_STAGES: { key: string; label: string }[] = [
  { key: "Parse", label: "Parse Requirement Text" },
  { key: "RuleFlag", label: "Rule Engine Flag Detection" },
  { key: "ClassifyPattern", label: "EARS Pattern Classification" },
  { key: "ComplianceCheck", label: "EARS Compliance Gate (pre-LLM)" },
  { key: "GenerateCandidates", label: "LLM Candidate Generation (Ollama)" },
  { key: "ScoreAndRecommend", label: "INCOSE Scoring & Recommendation" },
  { key: "Finalize", label: "Finalize & Review Gate" },
];

function formatClockTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString("en-US", { hour12: false });
  } catch {
    return "--:--:--";
  }
}

function ProcessingContent() {
  const router = useRouter();
  const { activeRunId } = useActiveRun();
  const runId = activeRunId;

  const { data: healthData } = useQuery({
    queryKey: ["health"],
    queryFn: () => apiService.getHealth(),
    refetchInterval: 30000,
  });

  const { data: run, isError } = useQuery({
    queryKey: ["run_status", runId],
    queryFn: () => apiService.getRunStatus(runId!),
    enabled: !!runId,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (data?.status === "completed" || data?.status === "failed") {
        return false;
      }
      return 1500;
    },
  });

  // Live per-requirement stage + console log, polled incrementally: each
  // request only asks for events after the highest seq already received,
  // so the log below just grows instead of being re-fetched wholesale.
  const [events, setEvents] = useState<StageEvent[]>([]);
  const lastSeqRef = useRef<number>(-1);
  const consoleEndRef = useRef<HTMLDivElement>(null);

  const { data: progressData } = useQuery({
    queryKey: ["run_progress", runId],
    queryFn: () => apiService.getRunProgress(runId!, lastSeqRef.current),
    enabled: !!runId,
    refetchInterval: () => {
      if (run?.status === "completed" || run?.status === "failed") return false;
      return 1200;
    },
  });

  useEffect(() => {
    if (progressData?.events && progressData.events.length > 0) {
      setEvents((prev) => [...prev, ...progressData.events]);
      const maxSeq = progressData.events.reduce((m, e) => Math.max(m, e.seq), lastSeqRef.current);
      lastSeqRef.current = maxSeq;
    }
  }, [progressData]);

  // Run switched (or page revisited for a different run) -- start the
  // console fresh rather than mixing in a previous run's events.
  useEffect(() => {
    setEvents([]);
    lastSeqRef.current = -1;
  }, [runId]);

  useEffect(() => {
    consoleEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [events]);

  useEffect(() => {
    if (run?.status === "completed") {
      const timer = setTimeout(() => {
        router.push("/review");
      }, 1200);
      return () => clearTimeout(timer);
    }
  }, [run?.status, runId, router]);

  if (!runId) {
    return <ProcessingEmptyState />;
  }

  const total = run?.total_requirements || 0;
  const done = run?.requirement_count || 0;
  const isCompleted = run?.status === "completed";
  const isFailed = run?.status === "failed";

  const stages = [
    { label: "Upload & File Persistence", complete: true },
    { label: "Parsing Spreadsheet Structure", complete: Boolean(total) || isCompleted },
    { label: "Requirement & Defect Detection", complete: done > 0 || isCompleted },
    { label: "INCOSE Scorer & Rule Engine", complete: done > 0 || isCompleted },
    { label: "EARS Pattern Classification", complete: done > 0 || isCompleted },
    { label: "LLM Rewriting (Gemma 3 / Llama 3)", complete: done > 0 || isCompleted },
    { label: "Deterministic Candidate Scoring", complete: done > 0 || isCompleted },
    { label: "Human-in-the-Loop Review Queue", complete: isCompleted },
  ];

  const currentRequirementIndex = progressData?.current_requirement_index ?? null;
  const currentStage = progressData?.current_stage ?? null;
  const currentRequirementEvents = events.filter(
    (e) => e.requirement_index === currentRequirementIndex
  );
  const showLivePanel = !isFailed && (Boolean(total) || events.length > 0);

  return (
    <div className="max-w-4xl mx-auto space-y-6 select-none py-4">
      {/* Header */}
      <div className="space-y-1">
        <div className="inline-flex items-center gap-2 px-2.5 py-0.5 rounded-full bg-[#1EA7FF]/10 text-[#1EA7FF] text-xs font-semibold">
          <Cpu className="w-3.5 h-3.5" />
          Run #{runId} Active Pipeline
        </div>
        <h1 className="text-2xl font-bold text-[#F5F7FA]">
          {run?.file_name || "Requirements Workbook"}
        </h1>
        <p className="text-xs text-[#8FA3BF]">
          Pipeline executing offline via LangGraph + FastAPI + Local Ollama LLM.
        </p>
      </div>

      {/* Progress Card */}
      <div className="drdo-card p-6 space-y-4">
        <div className="flex items-center justify-between text-xs">
          <span className="font-semibold text-[#F5F7FA]">
            {isCompleted
              ? "Analysis Complete!"
              : isFailed
              ? "Pipeline Failed"
              : `Processing Requirements (${done} of ${total || "?"})`}
          </span>
          <span className="font-mono text-[#1EA7FF]">
            {total ? `${Math.round((done / total) * 100)}%` : "0%"}
          </span>
        </div>

        {/* Progress Bar */}
        <div className="w-full h-2.5 bg-[#142036] rounded-full overflow-hidden border border-[#243244]">
          <motion.div
            className={`h-full ${
              isFailed ? "bg-[#FF4D4F]" : isCompleted ? "bg-[#00C853]" : "bg-[#1EA7FF]"
            }`}
            initial={{ width: "0%" }}
            animate={{
              width: total ? `${Math.min((done / total) * 100, 100)}%` : "5%",
            }}
            transition={{ duration: 0.3 }}
          />
        </div>
      </div>

      {/* Animated 8-Stage Pipeline Visualization */}
      <div className="drdo-card p-6 space-y-4">
        <h2 className="text-sm font-bold text-[#F5F7FA] uppercase tracking-wider text-[#8FA3BF]">
          8-Stage Execution Rail
        </h2>

        <div className="space-y-2.5">
          {stages.map((stage, idx) => (
            <motion.div
              key={idx}
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: idx * 0.05 }}
              className={`p-3.5 rounded-xl border flex items-center justify-between text-xs transition-all ${
                stage.complete
                  ? "bg-[#00C853]/10 border-[#00C853]/30 text-[#00C853]"
                  : idx === done && !isFailed
                  ? "bg-[#1EA7FF]/10 border-[#1EA7FF]/40 text-[#1EA7FF] font-semibold"
                  : "bg-[#142036]/50 border-[#243244] text-[#8FA3BF]"
              }`}
            >
              <div className="flex items-center gap-3">
                <span className="font-mono text-[11px] opacity-60">0{idx + 1}.</span>
                <span>{stage.label}</span>
              </div>

              {stage.complete ? (
                <CheckCircle2 className="w-4 h-4 text-[#00C853]" />
              ) : idx === done && !isFailed ? (
                <Loader2 className="w-4 h-4 text-[#1EA7FF] animate-spin" />
              ) : (
                <span className="w-2 h-2 rounded-full bg-[#243244]" />
              )}
            </motion.div>
          ))}
        </div>
      </div>

      {/* Live Per-Requirement Pipeline + Execution Console */}
      {showLivePanel && (
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
          {/* Per-requirement 6-node LangGraph rail */}
          <div className="drdo-card p-6 space-y-4 lg:col-span-2">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-bold text-[#F5F7FA] uppercase tracking-wider text-[#8FA3BF]">
                Live Requirement Pipeline
              </h2>
              {currentRequirementIndex !== null && !isCompleted && (
                <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-[#1EA7FF]/10 text-[#1EA7FF] border border-[#1EA7FF]/30">
                  REQ {currentRequirementIndex + 1} / {total || "?"}
                </span>
              )}
            </div>

            {currentRequirementIndex === null ? (
              <div className="py-8 text-center text-xs text-[#8FA3BF] flex flex-col items-center gap-2">
                <CircleDashed className="w-5 h-5 animate-spin" />
                <span>Waiting for the pipeline to start...</span>
              </div>
            ) : (
              <div className="space-y-2">
                {(() => {
                  const rejectedEvent = currentRequirementEvents.find(
                    (e) => e.stage === "RejectNonEars"
                  );
                  const rejectedAtIdx = PIPELINE_STAGES.findIndex(
                    (s) => s.key === "ComplianceCheck"
                  );

                  return PIPELINE_STAGES.map((stage, idx) => {
                    const stageEvent = currentRequirementEvents.find((e) => e.stage === stage.key);
                    const isDone = Boolean(stageEvent);
                    const isRunning = !isDone && currentStage === stage.key;
                    const isActiveButPending =
                      !isDone &&
                      !isRunning &&
                      currentStage !== null &&
                      PIPELINE_STAGES.findIndex((s) => s.key === currentStage) > idx;
                    // A stage with no event yet but whose index is behind the
                    // current stage (e.g. we jumped straight to Finalize on a
                    // very fast requirement) is treated as done too, since
                    // LangGraph always runs these nodes strictly in order.
                    const complete = isDone || isActiveButPending;
                    // Once ComplianceCheck rejects a requirement, everything
                    // after it never runs -- GenerateCandidates never gets
                    // called, so show those as skipped, not "pending forever".
                    const skipped = Boolean(rejectedEvent) && idx > rejectedAtIdx;

                    return (
                      <div
                        key={stage.key}
                        className={`p-3 rounded-xl border flex items-center justify-between text-xs transition-all ${
                          skipped
                            ? "bg-[#142036]/30 border-[#243244] text-[#8FA3BF]/50 line-through"
                            : complete
                            ? "bg-[#00C853]/10 border-[#00C853]/30 text-[#00C853]"
                            : isRunning
                            ? "bg-[#1EA7FF]/10 border-[#1EA7FF]/40 text-[#1EA7FF] font-semibold"
                            : "bg-[#142036]/50 border-[#243244] text-[#8FA3BF]"
                        }`}
                      >
                        <div className="flex items-center gap-2.5 min-w-0">
                          <span className="font-mono text-[10px] opacity-60 flex-shrink-0">
                            0{idx + 1}.
                          </span>
                          <span className="truncate">{stage.label}</span>
                        </div>
                        {skipped ? (
                          <CircleMinus className="w-4 h-4 flex-shrink-0 text-[#8FA3BF]/50" />
                        ) : complete ? (
                          <CheckCircle2 className="w-4 h-4 flex-shrink-0 text-[#00C853]" />
                        ) : isRunning ? (
                          <Loader2 className="w-4 h-4 flex-shrink-0 text-[#1EA7FF] animate-spin" />
                        ) : (
                          <span className="w-2 h-2 rounded-full bg-[#243244] flex-shrink-0" />
                        )}
                      </div>
                    );
                  });
                })()}

                {currentRequirementEvents.find((e) => e.stage === "RejectNonEars") ? (
                  <div className="mt-2 p-3 rounded-xl bg-[#FF4D4F]/10 border border-[#FF4D4F]/30 flex items-start gap-2.5">
                    <Ban className="w-4 h-4 flex-shrink-0 text-[#FF4D4F] mt-0.5" />
                    <p className="text-[11px] text-[#FF4D4F] leading-relaxed">
                      {currentRequirementEvents.find((e) => e.stage === "RejectNonEars")?.message}
                    </p>
                  </div>
                ) : (
                  currentRequirementEvents.find((e) => e.stage === "Finalize") && (
                    <p className="text-[11px] text-[#8FA3BF] pt-1 pl-1">
                      {currentRequirementEvents.find((e) => e.stage === "Finalize")?.message}
                    </p>
                  )
                )}
              </div>
            )}
          </div>

          {/* Execution console -- every stage event, streamed live */}
          <div className="drdo-card p-6 space-y-3 lg:col-span-3 flex flex-col">
            <h2 className="text-sm font-bold text-[#F5F7FA] uppercase tracking-wider text-[#8FA3BF] flex items-center gap-2">
              <SquareTerminal className="w-4 h-4 text-[#1EA7FF]" />
              Execution Console
            </h2>
            <div className="bg-[#07111F] border border-[#243244] rounded-xl p-3 font-mono text-[11px] leading-relaxed h-72 overflow-y-auto">
              {events.length === 0 ? (
                <div className="text-[#8FA3BF] h-full flex items-center justify-center">
                  Waiting for pipeline output...
                </div>
              ) : (
                <>
                  {events.map((e) => {
                    const isRejection =
                      e.stage === "RejectNonEars" ||
                      (e.stage === "ComplianceCheck" && e.message.includes("FAILED"));
                    return (
                      <div key={e.seq} className="flex gap-2 py-0.5">
                        <span className="text-[#8FA3BF] flex-shrink-0">{formatClockTime(e.ts)}</span>
                        <span className="text-[#1EA7FF] flex-shrink-0">
                          REQ {e.requirement_index + 1}
                        </span>
                        <span className="text-[#8B5CF6] flex-shrink-0">· {e.stage}</span>
                        <span
                          className={
                            isRejection || e.status === "failed"
                              ? "text-[#FF4D4F]"
                              : e.status === "running"
                              ? "text-[#FFB300]"
                              : "text-[#F5F7FA]"
                          }
                        >
                          → {e.message}
                        </span>
                      </div>
                    );
                  })}
                  <div ref={consoleEndRef} />
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Failure State Container */}
      {isFailed && isInvalidExcelError(run?.error_message) && (
        <InvalidExcelErrorCard />
      )}

      {isFailed && isAIError(run?.error_message) && (
        <AIErrorCard 
          errorCode={run?.error_message}
          onRetry={() => router.push("/upload")}
        />
      )}

      {isFailed && !isInvalidExcelError(run?.error_message) && !isAIError(run?.error_message) && (
        <div className="drdo-card p-6 border-[#FF4D4F]/40 bg-[#FF4D4F]/5 space-y-4">
          <div className="flex items-start gap-3">
            <ShieldAlert className="w-5 h-5 text-[#FF4D4F] flex-shrink-0 mt-0.5" />
            <div>
              <h3 className="text-sm font-bold text-[#FF4D4F]">Backend Execution Error</h3>
              <p className="text-xs text-[#8FA3BF] mt-1 font-mono">
                {run?.error_message || "Unknown pipeline error"}
              </p>
            </div>
          </div>

          <div className="p-4 rounded-xl bg-[#0F172A] border border-[#243244] text-xs space-y-2">
            <div className="font-semibold text-[#F5F7FA]">Resolution Steps:</div>
            <ul className="list-disc list-inside space-y-1 text-[#8FA3BF]">
              <li>If the model was not found, run <code className="text-[#1EA7FF]">ollama pull {healthData?.model || "your-model"}</code>.</li>
              <li>Ensure local Ollama service is active (<code className="text-[#1EA7FF]">ollama serve</code>).</li>
              <li>Confirm the spreadsheet is a valid <code className="text-[#1EA7FF]">.xlsx</code> file.</li>
            </ul>
          </div>
        </div>
      )}

      {/* Completion Action */}
      {isCompleted && (
        <div className="p-4 rounded-xl bg-[#00C853]/10 border border-[#00C853]/30 flex items-center justify-between text-xs">
          <div className="flex items-center gap-2 text-[#00C853] font-semibold">
            <CheckCircle2 className="w-4 h-4" />
            <span>Analysis completed successfully! Redirecting to review workspace...</span>
          </div>
          <button
            onClick={() => router.push("/review")}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-[#00C853] text-white font-semibold hover:bg-[#00b048] transition"
          >
            <span>Proceed to Review</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </div>
      )}
    </div>
  );
}

export default function ProcessingPage() {
  return <ProcessingContent />;
}
