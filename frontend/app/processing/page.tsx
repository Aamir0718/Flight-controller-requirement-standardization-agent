"use client";

import { useQuery } from "@tanstack/react-query";
import { useSearchParams, useRouter } from "next/navigation";
import { apiService } from "@/services/api";
import { useEffect, Suspense } from "react";
import { 
  CheckCircle2, 
  Loader2, 
  AlertCircle, 
  ArrowRight, 
  Cpu, 
  FileSpreadsheet, 
  Sparkles, 
  ShieldAlert 
} from "lucide-react";
import { motion } from "framer-motion";

function ProcessingContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const runIdParam = searchParams.get("run_id");
  const runId = runIdParam ? parseInt(runIdParam, 10) : null;

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

  useEffect(() => {
    if (run?.status === "completed") {
      const timer = setTimeout(() => {
        router.push(`/review?run_id=${runId}`);
      }, 1200);
      return () => clearTimeout(timer);
    }
  }, [run?.status, runId, router]);

  if (!runId) {
    return (
      <div className="py-12 text-center text-[#8FA3BF] text-sm">
        No active run specified. Please upload a workbook first.
      </div>
    );
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

      {/* Failure State Container */}
      {isFailed && (
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
              <li>If the model was not found, run <code className="text-[#1EA7FF]">ollama pull gemma3:4b</code> or <code className="text-[#1EA7FF]">ollama pull llama3.1</code>.</li>
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
            onClick={() => router.push(`/review?run_id=${runId}`)}
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
  return (
    <Suspense fallback={<div className="p-8 text-center text-sm text-[#8FA3BF]">Loading status...</div>}>
      <ProcessingContent />
    </Suspense>
  );
}
