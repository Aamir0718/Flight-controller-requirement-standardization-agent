"use client";

import { useQuery } from "@tanstack/react-query";
import { apiService } from "@/services/api";
import { 
  BarChart, 
  Bar, 
  XAxis, 
  YAxis, 
  Tooltip, 
  ResponsiveContainer, 
  PieChart, 
  Pie, 
  Cell 
} from "recharts";
import { BarChart3, PieChart as PieChartIcon, Award, ShieldAlert, Cpu } from "lucide-react";
import { motion } from "framer-motion";
import { useActiveRun } from "@/context/ActiveRunContext";
import { AnalyticsEmptyState } from "@/components/empty-states/AnalyticsEmptyState";

export default function AnalyticsPage() {
  const { activeRunId } = useActiveRun();

  const { data: runs } = useQuery({
    queryKey: ["runs"],
    queryFn: () => apiService.listRuns(),
  });

  const { data: requirements } = useQuery({
    queryKey: ["requirements", activeRunId],
    queryFn: () => apiService.getRunRequirements(activeRunId!),
    enabled: !!activeRunId,
  });

  // Mock / Calculated chart data from real requirements if available
  const earsCounts: Record<string, number> = {};
  requirements?.forEach((req) => {
    const pattern = req.ears_pattern?.pattern || "Unknown";
    earsCounts[pattern] = (earsCounts[pattern] || 0) + 1;
  });

  const earsPieData = Object.keys(earsCounts).map((key) => ({
    name: key,
    value: earsCounts[key],
  }));

  const COLORS = ["#1EA7FF", "#00C853", "#FFB300", "#8B5CF6", "#FF4D4F"];

  const scoreData = requirements?.map((req, idx) => ({
    name: `REQ #${idx + 1}`,
    score: req.recommended_score,
  })) || [];

  // Show empty state if no requirements data
  if (!requirements || requirements.length === 0) {
    return <AnalyticsEmptyState />;
  }

  return (
    <div className="space-y-6 select-none py-2">
      {/* Header */}
      <div className="pb-4 border-b border-[#243244]">
        <div className="flex items-center gap-2 text-xs text-[#1EA7FF] font-semibold mb-1">
          <BarChart3 className="w-4 h-4" /> DRDO Analytics Engine
        </div>
        <h1 className="text-2xl font-bold text-[#F5F7FA]">Requirements Compliance & Quality Metrics</h1>
        <p className="text-xs text-[#8FA3BF]">
          INCOSE score distributions, EARS pattern classification breakdown, and quality defect analytics.
        </p>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
        <div className="drdo-card p-5 space-y-2">
          <span className="text-xs font-bold uppercase text-[#8FA3BF]">Analyzed Workbooks</span>
          <div className="text-2xl font-bold text-[#F5F7FA]">{runs?.length || 0}</div>
          <p className="text-xs text-[#00C853]">SQLite Persisted</p>
        </div>

        <div className="drdo-card p-5 space-y-2">
          <span className="text-xs font-bold uppercase text-[#8FA3BF]">Avg INCOSE Compliance</span>
          <div className="text-2xl font-bold text-[#1EA7FF]">
            {requirements && requirements.length > 0
              ? (
                  requirements.reduce((acc, r) => acc + r.recommended_score, 0) /
                  requirements.length
                ).toFixed(1)
              : "—"}%
          </div>
          <p className="text-xs text-[#8FA3BF]">Based on INCOSE Rulebook v2.0</p>
        </div>

        <div className="drdo-card p-5 space-y-2">
          <span className="text-xs font-bold uppercase text-[#8FA3BF]">Auto Pass Rate</span>
          <div className="text-2xl font-bold text-[#00C853]">
            {requirements && requirements.length > 0
              ? (
                  ((requirements.length - requirements.filter((r) => r.needs_human_review).length) /
                    requirements.length) *
                  100
                ).toFixed(0)
              : "—"}%
          </div>
          <p className="text-xs text-[#00C853]">Passed review threshold</p>
        </div>
      </div>

      {/* Charts Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* INCOSE Score Distribution Bar Chart */}
        <div className="drdo-card p-6 space-y-4">
          <div className="flex items-center justify-between pb-2 border-b border-[#243244]">
            <h2 className="text-sm font-bold text-[#F5F7FA] flex items-center gap-2">
              <Award className="w-4 h-4 text-[#1EA7FF]" />
              INCOSE Score per Requirement
            </h2>
          </div>
          <div className="h-64 w-full">
            {scoreData.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={scoreData}>
                  <XAxis dataKey="name" stroke="#8FA3BF" fontSize={11} />
                  <YAxis stroke="#8FA3BF" fontSize={11} domain={[0, 100]} />
                  <Tooltip
                    contentStyle={{ backgroundColor: "#0F172A", borderColor: "#243244", color: "#F5F7FA" }}
                  />
                  <Bar dataKey="score" fill="#1EA7FF" radius={[6, 6, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-full flex items-center justify-center text-xs text-[#8FA3BF]">
                Select a run from Run History or upload a workbook to view requirement metrics.
              </div>
            )}
          </div>
        </div>

        {/* EARS Pattern Distribution Pie Chart */}
        <div className="drdo-card p-6 space-y-4">
          <div className="flex items-center justify-between pb-2 border-b border-[#243244]">
            <h2 className="text-sm font-bold text-[#F5F7FA] flex items-center gap-2">
              <PieChartIcon className="w-4 h-4 text-[#8B5CF6]" />
              EARS Pattern Distribution
            </h2>
          </div>
          <div className="h-64 w-full flex items-center justify-center">
            {earsPieData.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={earsPieData}
                    cx="50%"
                    cy="50%"
                    innerRadius={50}
                    outerRadius={80}
                    paddingAngle={5}
                    dataKey="value"
                    label
                  >
                    {earsPieData.map((_, index) => (
                      <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{ backgroundColor: "#0F172A", borderColor: "#243244", color: "#F5F7FA" }}
                  />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <div className="text-center text-xs text-[#8FA3BF]">
                Select a run from Run History or upload a workbook to view EARS pattern distribution.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
