"use client";

import { motion } from "framer-motion";
import { BarChart3, FileSpreadsheet, Award, TrendingUp } from "lucide-react";

export function AnalyticsEmptyState() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5 }}
      className="space-y-6"
    >
      {/* Empty Chart Placeholders */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Bar Chart Placeholder */}
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.2 }}
          className="drdo-card p-6 space-y-4"
        >
          <div className="flex items-center justify-between pb-2 border-b border-[#243244]">
            <h2 className="text-sm font-bold text-[#F5F7FA] flex items-center gap-2">
              <Award className="w-4 h-4 text-[#1EA7FF]" />
              INCOSE Score per Requirement
            </h2>
          </div>
          <div className="h-64 w-full flex flex-col items-center justify-center text-center space-y-3">
            <BarChart3 className="w-12 h-12 text-[#243244]" />
            <p className="text-xs text-[#8FA3BF]">No analytics available yet.</p>
          </div>
        </motion.div>

        {/* Pie Chart Placeholder */}
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.3 }}
          className="drdo-card p-6 space-y-4"
        >
          <div className="flex items-center justify-between pb-2 border-b border-[#243244]">
            <h2 className="text-sm font-bold text-[#F5F7FA] flex items-center gap-2">
              <TrendingUp className="w-4 h-4 text-[#8B5CF6]" />
              EARS Pattern Distribution
            </h2>
          </div>
          <div className="h-64 w-full flex flex-col items-center justify-center text-center space-y-3">
            <div className="w-20 h-20 rounded-full border-4 border-dashed border-[#243244]" />
            <p className="text-xs text-[#8FA3BF]">No analytics available yet.</p>
          </div>
        </motion.div>
      </div>

      {/* Empty KPI Cards */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.4 }}
        className="grid grid-cols-1 md:grid-cols-3 gap-5"
      >
        <div className="drdo-card p-5 space-y-2">
          <div className="flex items-center gap-2 text-xs font-bold text-[#8FA3BF]">
            <FileSpreadsheet className="w-4 h-4" />
            <span>Processed Files</span>
          </div>
          <div className="text-3xl font-bold text-[#F5F7FA]">0</div>
          <p className="text-xs text-[#8FA3BF]">No data available</p>
        </div>

        <div className="drdo-card p-5 space-y-2">
          <div className="flex items-center gap-2 text-xs font-bold text-[#8FA3BF]">
            <Award className="w-4 h-4" />
            <span>Requirements Reviewed</span>
          </div>
          <div className="text-3xl font-bold text-[#F5F7FA]">0</div>
          <p className="text-xs text-[#8FA3BF]">No data available</p>
        </div>

        <div className="drdo-card p-5 space-y-2">
          <div className="flex items-center gap-2 text-xs font-bold text-[#8FA3BF]">
            <TrendingUp className="w-4 h-4" />
            <span>Average INCOSE Score</span>
          </div>
          <div className="text-3xl font-bold text-[#F5F7FA]">0</div>
          <p className="text-xs text-[#8FA3BF]">No data available</p>
        </div>
      </motion.div>

      {/* Additional Empty KPI */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.5 }}
        className="drdo-card p-5 space-y-2"
      >
        <div className="flex items-center gap-2 text-xs font-bold text-[#8FA3BF]">
          <Award className="w-4 h-4" />
          <span>Acceptance Rate</span>
        </div>
        <div className="text-3xl font-bold text-[#F5F7FA]">0%</div>
        <p className="text-xs text-[#8FA3BF]">No data available</p>
      </motion.div>
    </motion.div>
  );
}
