"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { UploadCloud, History, Rocket, FileCheck, Wifi, Sparkles } from "lucide-react";

export function ProcessingEmptyState() {
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
            animate={{ y: [0, -10, 0] }}
            transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
          >
            <UploadCloud className="w-20 h-20 text-[#1EA7FF]" />
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
          No Active Processing Session
        </h1>
        <p className="text-[#8FA3BF] text-sm">
          Upload a requirements workbook to begin the AI-powered review pipeline.
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
          <span>View Run History</span>
        </Link>
      </motion.div>

      {/* Feature Cards */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.5 }}
        className="grid grid-cols-1 md:grid-cols-3 gap-4 max-w-4xl w-full"
      >
        <div className="drdo-card p-5 space-y-3 hover:border-[#1EA7FF]/40 transition">
          <div className="flex items-center gap-2 text-[#1EA7FF] mb-2">
            <Rocket className="w-5 h-5" />
            <span className="text-xs font-bold uppercase tracking-wider">AI Pipeline</span>
          </div>
          <p className="text-xs text-[#8FA3BF] leading-relaxed">
            Automatically analyzes requirements using LangGraph + Local LLM.
          </p>
        </div>

        <div className="drdo-card p-5 space-y-3 hover:border-[#1EA7FF]/40 transition">
          <div className="flex items-center gap-2 text-[#00C853] mb-2">
            <FileCheck className="w-5 h-5" />
            <span className="text-xs font-bold uppercase tracking-wider">EARS & INCOSE</span>
          </div>
          <p className="text-xs text-[#8FA3BF] leading-relaxed">
            Validates requirements against aerospace engineering standards.
          </p>
        </div>

        <div className="drdo-card p-5 space-y-3 hover:border-[#1EA7FF]/40 transition">
          <div className="flex items-center gap-2 text-[#FFB300] mb-2">
            <Wifi className="w-5 h-5" />
            <span className="text-xs font-bold uppercase tracking-wider">Offline Processing</span>
          </div>
          <p className="text-xs text-[#8FA3BF] leading-relaxed">
            Runs completely offline using FastAPI + Ollama.
          </p>
        </div>
      </motion.div>
    </motion.div>
  );
}
