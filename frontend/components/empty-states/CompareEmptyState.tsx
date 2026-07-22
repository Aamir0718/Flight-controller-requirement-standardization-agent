"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { UploadCloud, History, Columns3, ArrowDown, FileText, Sparkles } from "lucide-react";

export function CompareEmptyState() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5 }}
      className="flex flex-col items-center justify-center min-h-[60vh] py-16 px-4"
    >
      {/* Animated Split View Icon */}
      <motion.div
        initial={{ scale: 0.8, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ delay: 0.2, duration: 0.5 }}
        className="mb-8 relative"
      >
        <div className="absolute inset-0 bg-[#1EA7FF]/20 blur-3xl rounded-full" />
        <div className="relative p-8 rounded-3xl bg-[#0F172A] border border-[#243244]">
          <motion.div
            animate={{ scale: [1, 1.05, 1] }}
            transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
          >
            <Columns3 className="w-20 h-20 text-[#1EA7FF]" />
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
          No Comparison Available
        </h1>
        <p className="text-[#8FA3BF] text-sm">
          Process a workbook to compare original and rewritten requirements.
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
          <span>View Previous Runs</span>
        </Link>
      </motion.div>

      {/* Sample Comparison Cards */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.5 }}
        className="max-w-2xl w-full"
      >
        <div className="drdo-card p-6 space-y-4">
          <h3 className="text-xs font-bold uppercase tracking-wider text-[#8FA3BF] mb-4">
            Comparison Preview
          </h3>
          
          {/* Original Requirement Card */}
          <motion.div
            initial={{ opacity: 0, x: -10 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.6 }}
            className="drdo-card p-4 space-y-2 bg-[#0F172A]"
          >
            <div className="flex items-center gap-2 text-xs font-bold text-[#8FA3BF]">
              <FileText className="w-4 h-4" />
              <span>Original Requirement</span>
            </div>
            <div className="text-xs text-[#F5F7FA] font-mono blur-sm select-none">
              The system shall provide the ability to control the flight path...
            </div>
          </motion.div>

          {/* Arrow */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.7 }}
            className="flex justify-center"
          >
            <ArrowDown className="w-5 h-5 text-[#1EA7FF]" />
          </motion.div>

          {/* AI Rewrite Card */}
          <motion.div
            initial={{ opacity: 0, x: 10 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.8 }}
            className="drdo-card p-4 space-y-2 bg-[#1EA7FF]/10 border-[#1EA7FF]/30"
          >
            <div className="flex items-center gap-2 text-xs font-bold text-[#1EA7FF]">
              <Sparkles className="w-4 h-4" />
              <span>AI Rewrite</span>
            </div>
            <div className="text-xs text-[#F5F7FA] font-mono blur-sm select-none">
              The flight control system shall enable precise trajectory management...
            </div>
          </motion.div>
        </div>
      </motion.div>
    </motion.div>
  );
}
