"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { UploadCloud, History, FileText, Sparkles, CheckCircle2, Download, ArrowRight } from "lucide-react";

const timelineSteps = [
  { icon: UploadCloud, label: "Upload Workbook", color: "text-[#1EA7FF]" },
  { icon: Sparkles, label: "AI Analysis", color: "text-[#8B5CF6]" },
  { icon: FileText, label: "Human Review", color: "text-[#FFB300]" },
  { icon: Download, label: "Export Approved Report", color: "text-[#00C853]" },
];

export function ReviewEmptyState() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5 }}
      className="flex flex-col items-center justify-center min-h-[60vh] py-16 px-4"
    >
      {/* Animated Icon */}
      <motion.div
        initial={{ scale: 0.8, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ delay: 0.2, duration: 0.5 }}
        className="mb-8 relative"
      >
        <div className="absolute inset-0 bg-[#1EA7FF]/20 blur-3xl rounded-full" />
        <div className="relative p-8 rounded-3xl bg-[#0F172A] border border-[#243244]">
          <motion.div
            animate={{ rotate: [0, 5, -5, 0] }}
            transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
          >
            <FileText className="w-20 h-20 text-[#1EA7FF]" />
          </motion.div>
        </div>
      </motion.div>

      {/* Title and Subtitle */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.3 }}
        className="text-center mb-8 max-w-xl"
      >
        <h1 className="text-3xl font-bold text-[#F5F7FA] mb-3">
          Review Workspace
        </h1>
        <p className="text-[#8FA3BF] text-sm">
          No review session selected. Upload and process a workbook to review AI-generated requirement improvements.
        </p>
      </motion.div>

      {/* Action Buttons */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.4 }}
        className="flex flex-wrap items-center justify-center gap-4 mb-12"
      >
        <Link
          href="/upload"
          className="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-[#1EA7FF] hover:bg-[#008ee6] text-white text-sm font-semibold shadow-lg shadow-[#1EA7FF]/20 transition-all hover:scale-105"
        >
          <UploadCloud className="w-4 h-4" />
          <span>Upload Workbook</span>
        </Link>
        <Link
          href="/history"
          className="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-[#0F172A] border border-[#243244] hover:border-[#1EA7FF]/40 text-[#F5F7FA] text-sm font-semibold transition-all hover:scale-105"
        >
          <History className="w-4 h-4" />
          <span>Run History</span>
        </Link>
      </motion.div>

      {/* Preview Timeline */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.5 }}
        className="max-w-3xl w-full"
      >
        <div className="drdo-card p-6 space-y-4">
          <h3 className="text-xs font-bold uppercase tracking-wider text-[#8FA3BF] mb-4">
            Review Pipeline Preview
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {timelineSteps.map((step, idx) => (
              <motion.div
                key={idx}
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: 0.6 + idx * 0.1 }}
                className="relative"
              >
                <div className="drdo-card p-4 space-y-3 hover:border-[#1EA7FF]/40 transition">
                  <step.icon className={`w-6 h-6 ${step.color}`} />
                  <div className="text-xs font-semibold text-[#F5F7FA]">
                    {step.label}
                  </div>
                  <div className="text-[10px] text-[#8FA3BF] font-mono">
                    Step 0{idx + 1}
                  </div>
                </div>
                {idx < timelineSteps.length - 1 && (
                  <ArrowRight className="hidden lg:block absolute -right-2 top-1/2 -translate-y-1/2 text-[#243244] w-4 h-4" />
                )}
              </motion.div>
            ))}
          </div>
        </div>
      </motion.div>
    </motion.div>
  );
}
