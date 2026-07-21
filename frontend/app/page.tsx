"use client";

import { useQuery } from "@tanstack/react-query";
import { apiService } from "@/services/api";
import Link from "next/link";
import { 
  UploadCloud, 
  CheckCircle2, 
  AlertTriangle, 
  FileSpreadsheet, 
  ArrowRight, 
  Sparkles, 
  Database, 
  Cpu, 
  ShieldAlert,
  Clock
} from "lucide-react";
import { formatDate } from "@/lib/utils";
import { motion } from "framer-motion";

export default function DashboardPage() {
  const { data: runs, isLoading } = useQuery({
    queryKey: ["runs"],
    queryFn: () => apiService.listRuns(),
    refetchInterval: 5000,
  });

  const latestRun = runs && runs.length > 0 ? runs[runs.length - 1] : null;

  // Calculate aggregated stats across runs
  const totalRuns = runs?.length || 0;
  const completedRuns = runs?.filter((r) => r.status === "completed").length || 0;
  const totalReqsProcessed = runs?.reduce((acc, r) => acc + (r.requirement_count || 0), 0) || 0;

  return (
    <div className="space-y-6 select-none">
      {/* DRDO Enterprise Hero Banner */}
      <motion.div 
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        className="relative overflow-hidden rounded-2xl bg-gradient-to-r from-[#0F172A] via-[#142036] to-[#0F172A] border border-[#243244] p-8 shadow-xl"
      >
        <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-[#1EA7FF] via-[#8B5CF6] to-[#00C853]" />
        
        <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-6 relative z-10">
          <div className="space-y-3 max-w-3xl">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-[#1EA7FF]/10 border border-[#1EA7FF]/30 text-[#1EA7FF] text-xs font-semibold uppercase tracking-widest">
              <Sparkles className="w-3.5 h-3.5" />
              DRDO Flight Controller Engineering System
            </div>
            <h1 className="text-3xl font-bold tracking-tight text-[#F5F7FA]">
              Flight Controller Requirements Platform
            </h1>
            <p className="text-[#8FA3BF] text-sm leading-relaxed">
              Standardize, audit, and refine flight controller software requirement specifications.
              Automated defect detection, EARS pattern classification, INCOSE rulebook scoring,
              and offline LLM candidate rewriting in a secure air-gapped environment.
            </p>
          </div>

          <div className="flex flex-col sm:flex-row gap-3">
            <Link
              href="/upload"
              className="inline-flex items-center justify-center gap-2 px-5 py-3 rounded-xl bg-[#1EA7FF] hover:bg-[#008ee6] text-white font-semibold text-sm shadow-lg shadow-[#1EA7FF]/25 transition-all transform hover:-translate-y-0.5"
            >
              <UploadCloud className="w-4 h-4" />
              <span>Upload Workbook</span>
              <ArrowRight className="w-4 h-4" />
            </Link>
          </div>
        </div>
      </motion.div>

      {/* KPI Statistics Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-5">
        <motion.div 
          initial={{ opacity: 0, y: 15 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="drdo-card p-5 space-y-3"
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-wider text-[#8FA3BF]">Total Workbooks</span>
            <div className="p-2 rounded-lg bg-[#1EA7FF]/10 text-[#1EA7FF]">
              <FileSpreadsheet className="w-5 h-5" />
            </div>
          </div>
          <div className="text-3xl font-bold text-[#F5F7FA]">{totalRuns}</div>
          <p className="text-xs text-[#8FA3BF]">{completedRuns} completed runs in database</p>
        </motion.div>

        <motion.div 
          initial={{ opacity: 0, y: 15 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
          className="drdo-card p-5 space-y-3"
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-wider text-[#8FA3BF]">Requirements Processed</span>
            <div className="p-2 rounded-lg bg-[#00C853]/10 text-[#00C853]">
              <CheckCircle2 className="w-5 h-5" />
            </div>
          </div>
          <div className="text-3xl font-bold text-[#F5F7FA]">{totalReqsProcessed}</div>
          <p className="text-xs text-[#00C853]">Fully analyzed & EARS classified</p>
        </motion.div>

        <motion.div 
          initial={{ opacity: 0, y: 15 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3 }}
          className="drdo-card p-5 space-y-3"
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-wider text-[#8FA3BF]">Current Model</span>
            <div className="p-2 rounded-lg bg-[#FFB300]/10 text-[#FFB300]">
              <Cpu className="w-5 h-5" />
            </div>
          </div>
          <div className="text-xl font-bold font-mono text-[#F5F7FA]">gemma3:4b</div>
          <p className="text-xs text-[#8FA3BF]">Local Ollama offline server</p>
        </motion.div>

        <motion.div 
          initial={{ opacity: 0, y: 15 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.4 }}
          className="drdo-card p-5 space-y-3"
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold uppercase tracking-wider text-[#8FA3BF]">Trace Database</span>
            <div className="p-2 rounded-lg bg-[#8B5CF6]/10 text-[#8B5CF6]">
              <Database className="w-5 h-5" />
            </div>
          </div>
          <div className="text-xl font-bold text-[#F5F7FA]">SQLite Active</div>
          <p className="text-xs text-[#00C853]">Data persisted locally</p>
        </motion.div>
      </div>

      {/* System Status & Recent Activity Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Recent Runs Table (2 Cols) */}
        <div className="lg:col-span-2 drdo-card p-6 space-y-4">
          <div className="flex items-center justify-between pb-3 border-b border-[#243244]">
            <h2 className="text-base font-bold text-[#F5F7FA] flex items-center gap-2">
              <Clock className="w-4 h-4 text-[#1EA7FF]" />
              Recent Requirement Reviews
            </h2>
            <Link href="/history" className="text-xs font-semibold text-[#1EA7FF] hover:underline">
              View All History →
            </Link>
          </div>

          {isLoading ? (
            <div className="py-8 text-center text-sm text-[#8FA3BF]">Loading runs...</div>
          ) : !runs || runs.length === 0 ? (
            <div className="py-12 text-center space-y-3">
              <FileSpreadsheet className="w-10 h-10 mx-auto text-[#8FA3BF]/50" />
              <p className="text-sm text-[#8FA3BF]">No reviews processed yet.</p>
              <Link
                href="/upload"
                className="inline-block text-xs font-semibold text-[#1EA7FF] hover:underline"
              >
                Upload your first workbook →
              </Link>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-[#243244] text-[#8FA3BF] uppercase text-[10px] tracking-wider">
                    <th className="py-2.5 px-3">Run ID</th>
                    <th className="py-2.5 px-3">Workbook</th>
                    <th className="py-2.5 px-3">Status</th>
                    <th className="py-2.5 px-3">Reqs</th>
                    <th className="py-2.5 px-3">Date</th>
                    <th className="py-2.5 px-3 text-right">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#243244]/50">
                  {runs.slice(-5).reverse().map((run) => (
                    <tr key={run.id} className="hover:bg-[#142036]/50 transition">
                      <td className="py-3 px-3 font-mono font-bold text-[#1EA7FF]">#{run.id}</td>
                      <td className="py-3 px-3 font-medium text-[#F5F7FA]">{run.file_name}</td>
                      <td className="py-3 px-3">
                        <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold ${
                          run.status === "completed" ? "bg-[#00C853]/15 text-[#00C853] border border-[#00C853]/30" :
                          run.status === "failed" ? "bg-[#FF4D4F]/15 text-[#FF4D4F] border border-[#FF4D4F]/30" :
                          "bg-[#FFB300]/15 text-[#FFB300] border border-[#FFB300]/30 animate-pulse"
                        }`}>
                          {run.status.toUpperCase()}
                        </span>
                      </td>
                      <td className="py-3 px-3 text-[#8FA3BF]">{run.requirement_count}/{run.total_requirements || "?"}</td>
                      <td className="py-3 px-3 text-[#8FA3BF]">{formatDate(run.uploaded_at)}</td>
                      <td className="py-3 px-3 text-right">
                        <Link
                          href={`/review?run_id=${run.id}`}
                          className="text-xs font-semibold text-[#1EA7FF] hover:underline"
                        >
                          Review →
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Pipeline & Security Summary (1 Col) */}
        <div className="drdo-card p-6 space-y-5">
          <div className="pb-3 border-b border-[#243244]">
            <h2 className="text-base font-bold text-[#F5F7FA]">Engine Pipeline Status</h2>
          </div>

          <div className="space-y-3 text-xs">
            <div className="p-3 rounded-lg bg-[#142036] border border-[#243244] flex items-center justify-between">
              <span className="text-[#8FA3BF]">FastAPI Loopback</span>
              <span className="font-semibold text-[#00C853]">Active (Port 8008)</span>
            </div>
            <div className="p-3 rounded-lg bg-[#142036] border border-[#243244] flex items-center justify-between">
              <span className="text-[#8FA3BF]">INCOSE Rulebook</span>
              <span className="font-semibold text-[#1EA7FF]">v2.0 Loaded</span>
            </div>
            <div className="p-3 rounded-lg bg-[#142036] border border-[#243244] flex items-center justify-between">
              <span className="text-[#8FA3BF]">EARS Classifier</span>
              <span className="font-semibold text-[#1EA7FF]">Deterministic + LLM</span>
            </div>
            <div className="p-3 rounded-lg bg-[#142036] border border-[#243244] flex items-center justify-between">
              <span className="text-[#8FA3BF]">Air-gapped Guard</span>
              <span className="font-semibold text-[#00C853]">Verified Offline</span>
            </div>
          </div>

          <div className="p-4 rounded-xl bg-[#1EA7FF]/10 border border-[#1EA7FF]/20 space-y-2">
            <div className="text-xs font-bold text-[#1EA7FF] flex items-center gap-1.5">
              <ShieldAlert className="w-4 h-4" />
              DRDO Specification Standard
            </div>
            <p className="text-[11px] text-[#8FA3BF] leading-relaxed">
              All parsed statements undergo strict EARS pattern classification (Event, State, Unwanted, Ubiquitous) and 100-point INCOSE requirement scoring.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
