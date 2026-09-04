"use client";

import { useState } from "react";
import { AlertTriangle, AlertCircle, Clock, Cpu, Info, ChevronDown, ChevronUp } from "lucide-react";

export const AI_ERROR_CODES = [
  "AI_SERVICE_UNAVAILABLE",
  "AI_RESPONSE_VALIDATION_FAILED",
  "AI_REQUEST_TIMEOUT",
  "AI_MODEL_NOT_FOUND",
  "AI_UNKNOWN_ERROR",
] as const;

export type AIErrorCode = (typeof AI_ERROR_CODES)[number];

export function isAIError(errorMessage?: string | null): boolean {
  if (!errorMessage) return false;
  return AI_ERROR_CODES.includes(errorMessage as AIErrorCode);
}

/** Maps a backend error code (e.g. "AI_SERVICE_UNAVAILABLE") to a short,
 * human-readable message -- for compact inline use (a per-row badge/note)
 * where the full AIErrorCard below would be too heavy. Falls back to the
 * raw code itself for anything not in ERROR_CONFIG, so an unrecognized
 * code is still visible rather than silently swallowed. */
export function describeAIError(errorCode?: string | null): string {
  if (!errorCode) return "Unknown error.";
  const config = errorCode in ERROR_CONFIG ? ERROR_CONFIG[errorCode as AIErrorCode] : null;
  return config ? config.description : errorCode;
}

interface AIErrorCardProps {
  errorCode?: string | null;
  technicalDetails?: string | null;
  onRetry?: () => void;
}

const ERROR_CONFIG: Record<AIErrorCode, { title: string; icon: typeof AlertTriangle; description: string }> = {
  AI_SERVICE_UNAVAILABLE: {
    title: "AI Service Unavailable",
    icon: AlertCircle,
    description: "The configured LLM endpoint is not running or cannot be reached.",
  },
  AI_RESPONSE_VALIDATION_FAILED: {
    title: "AI Response Validation Failed",
    icon: AlertTriangle,
    description: "The LLM returned an invalid response format while processing requirements.",
  },
  AI_REQUEST_TIMEOUT: {
    title: "AI Request Timeout",
    icon: Clock,
    description: "The LLM endpoint took too long to respond to the request.",
  },
  AI_MODEL_NOT_FOUND: {
    title: "AI Model Not Found",
    icon: Cpu,
    description: "The configured model name is not available on the LLM endpoint.",
  },
  AI_UNKNOWN_ERROR: {
    title: "AI Processing Error",
    icon: AlertTriangle,
    description: "An unexpected error occurred while processing requirements with the AI model.",
  },
};

export function AIErrorCard({ errorCode, technicalDetails, onRetry }: AIErrorCardProps) {
  const [showTechnicalDetails, setShowTechnicalDetails] = useState(false);
  
  const config = errorCode && errorCode in ERROR_CONFIG 
    ? ERROR_CONFIG[errorCode as AIErrorCode] 
    : ERROR_CONFIG.AI_UNKNOWN_ERROR;
  const Icon = config.icon;

  return (
    <div className="drdo-card p-6 space-y-4">
      <div className="flex items-start gap-3">
        <div className="p-2 rounded-lg bg-[#FF4D4F]/10 text-[#FF4D4F]">
          <Icon className="w-5 h-5" />
        </div>
        <div className="space-y-1 min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-[#F5F7FA]">
            ⚠ {config.title}
          </h3>
          <p className="text-xs text-[#8FA3BF] leading-relaxed">
            {config.description}
          </p>
        </div>
      </div>

      <div className="pl-7 space-y-4 text-xs text-[#8FA3BF]">
        <div>
          <p className="font-medium text-[#F5F7FA] mb-2">What this means:</p>
          <p className="leading-relaxed">
            This does NOT necessarily mean your Excel file is incorrect. The AI response 
            could not be validated, so processing has been stopped to avoid generating unreliable results.
          </p>
        </div>

        <div>
          <p className="font-medium text-[#F5F7FA] mb-2">Suggested actions:</p>
          <ul className="space-y-1.5">
            <li>✓ Retry processing the same file.</li>
            <li>✓ Restart the local Ollama service.</li>
            <li>✓ Verify the selected AI model is available.</li>
            <li>✓ Check that Ollama is running on the configured host and port.</li>
          </ul>
        </div>

        {onRetry && (
          <button
            onClick={onRetry}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-[#1EA7FF] hover:bg-[#008ee6] text-white text-xs font-semibold transition"
          >
            <Clock className="w-3.5 h-3.5" />
            <span>Retry Processing</span>
          </button>
        )}
      </div>

      <div className="flex items-start gap-2.5 p-3 rounded-lg bg-[#142036]/60 border border-[#243244] text-xs text-[#8FA3BF]">
        <Info className="w-3.5 h-3.5 text-[#1EA7FF] flex-shrink-0 mt-0.5" />
        <p className="leading-relaxed">
          <span className="font-medium text-[#F5F7FA]">Need help?</span>{" "}
          If the issue persists after retrying, check the Ollama service logs or contact the project administrator.
        </p>
      </div>

      {technicalDetails && (
        <div className="border-t border-[#243244] pt-4">
          <button
            onClick={() => setShowTechnicalDetails(!showTechnicalDetails)}
            className="flex items-center gap-2 text-xs text-[#8FA3BF] hover:text-[#F5F7FA] transition"
          >
            {showTechnicalDetails ? (
              <ChevronUp className="w-3.5 h-3.5" />
            ) : (
              <ChevronDown className="w-3.5 h-3.5" />
            )}
            <span className="font-medium">Technical Details</span>
          </button>
          
          {showTechnicalDetails && (
            <div className="mt-3 p-3 rounded-lg bg-[#0F172A] border border-[#243244]">
              <pre className="text-[10px] text-[#8FA3BF] whitespace-pre-wrap break-all font-mono">
                {technicalDetails}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
