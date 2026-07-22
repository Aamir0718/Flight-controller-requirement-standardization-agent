"use client";

import Link from "next/link";
import { motion } from "framer-motion";
import { UploadCloud, History, Clock } from "lucide-react";

export function HistoryEmptyState() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5 }}
      className="flex flex-col items-center justify-center min-h-[60vh] py-16 px-4"
    >
      {/* Animated Timeline Icon */}
      <motion.div
        initial={{ scale: 0.8, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ delay: 0.2, duration: 0.5 }}
        className="mb-8 relative"
      >
        <div className="absolute inset-0 bg-[#1EA7FF]/20 blur-3xl rounded-full" />
        <div className="relative p-8 rounded-3xl bg-[#0F172A] border border-[#243244]">
          <motion.div
            animate={{ rotate: [0, 10, -10, 0] }}
            transition={{ duration: 4, repeat: Infinity, ease: "easeInOut" }}
          >
            <Clock className="w-20 h-20 text-[#1EA7FF]" />
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
          No Previous Runs
        </h1>
        <p className="text-[#8FA3BF] text-sm">
          Your completed requirement reviews will appear here.
        </p>
      </motion.div>

      {/* Action Button */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.4 }}
      >
        <Link
          href="/upload"
          className="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-[#1EA7FF] hover:bg-[#008ee6] text-white text-sm font-semibold shadow-lg shadow-[#1EA7FF]/20 transition-all hover:scale-105"
        >
          <UploadCloud className="w-4 h-4" />
          <span>Start First Review</span>
        </Link>
      </motion.div>
    </motion.div>
  );
}
