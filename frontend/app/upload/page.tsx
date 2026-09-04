"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { apiService } from "@/services/api";
import { UploadCloud, FileSpreadsheet, AlertCircle, CheckCircle2, ArrowRight } from "lucide-react";
import { motion } from "framer-motion";
import { useActiveRun } from "@/context/ActiveRunContext";

export default function UploadPage() {
  const router = useRouter();
  const { setActiveRunId } = useActiveRun();
  const [file, setFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);

  const handleFileDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragOver(false);
    setError(null);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const droppedFile = e.dataTransfer.files[0];
      validateAndSetFile(droppedFile);
    }
  };

  const validateAndSetFile = (f: File) => {
    if (!f.name.toLowerCase().endsWith(".xlsx")) {
      setError("Invalid file format. Only Microsoft Excel (.xlsx) workbooks are supported.");
      setFile(null);
      return;
    }
    setFile(f);
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    setError(null);
    if (e.target.files && e.target.files.length > 0) {
      validateAndSetFile(e.target.files[0]);
    }
  };

  const handleUpload = async () => {
    if (!file) return;
    setIsUploading(true);
    setError(null);

    try {
      // Analysis (EARS + INCOSE + violations, no LLM) now runs
      // synchronously inside POST /upload itself -- by the time this
      // resolves, the whole workbook's analysis table is already sitting
      // in the run, so there's nothing to poll a "processing" page for.
      // Straight to the workspace where a human picks what to Generate.
      const response = await apiService.uploadWorkbook(file);
      setActiveRunId(response.run_id);
      router.push("/review");
    } catch (err: any) {
      setError(err.message || "Upload failed. Please ensure the backend is running.");
      setIsUploading(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto space-y-6 select-none py-4">
      <div className="space-y-1">
        <h1 className="text-2xl font-bold text-[#F5F7FA]">Upload Requirements Workbook</h1>
        <p className="text-xs text-[#8FA3BF]">
          Select or drag a Microsoft Excel (`.xlsx`) file containing flight controller requirement specifications.
        </p>
      </div>

      {/* Drag and Drop Zone */}
      <motion.div
        initial={{ opacity: 0, y: 15 }}
        animate={{ opacity: 1, y: 0 }}
        className={`drdo-card p-10 text-center border-2 border-dashed transition-all duration-200 cursor-pointer ${
          isDragOver
            ? "border-[#1EA7FF] bg-[#1EA7FF]/10 scale-[1.01]"
            : file
            ? "border-[#00C853] bg-[#00C853]/5"
            : "border-[#243244] hover:border-[#1EA7FF]/50 bg-[#0F172A]"
        }`}
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragOver(true);
        }}
        onDragLeave={() => setIsDragOver(false)}
        onDrop={handleFileDrop}
        onClick={() => document.getElementById("fileInput")?.click()}
      >
        <input
          id="fileInput"
          type="file"
          accept=".xlsx"
          className="hidden"
          onChange={handleFileSelect}
        />

        <div className="space-y-4 pointer-events-none">
          <div className="w-16 h-16 mx-auto rounded-2xl bg-[#1EA7FF]/10 border border-[#1EA7FF]/30 flex items-center justify-center text-[#1EA7FF]">
            <UploadCloud className="w-8 h-8" />
          </div>

          <div>
            <h3 className="text-base font-semibold text-[#F5F7FA]">
              {file ? file.name : "Drag & drop your .xlsx workbook here"}
            </h3>
            <p className="text-xs text-[#8FA3BF] mt-1">
              {file
                ? `${(file.size / 1024).toFixed(1)} KB — Ready for processing`
                : "Or click anywhere to browse your local file system"}
            </p>
          </div>

          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-[#142036] border border-[#243244] text-[11px] text-[#8FA3BF]">
            <FileSpreadsheet className="w-3.5 h-3.5 text-[#1EA7FF]" />
            Supported: Microsoft Excel (.xlsx) files
          </div>
        </div>
      </motion.div>

      {/* Error Alert */}
      {error && (
        <div className="p-4 rounded-xl bg-[#FF4D4F]/10 border border-[#FF4D4F]/30 text-[#FF4D4F] text-xs flex items-center gap-3">
          <AlertCircle className="w-5 h-5 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Upload Action Button */}
      {file && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="drdo-card p-6 flex items-center justify-between"
        >
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-lg bg-[#00C853]/10 text-[#00C853]">
              <CheckCircle2 className="w-5 h-5" />
            </div>
            <div>
              <div className="text-sm font-semibold text-[#F5F7FA]">{file.name}</div>
              <div className="text-xs text-[#8FA3BF]">Validation passed. Direct local parsing.</div>
            </div>
          </div>

          <button
            onClick={handleUpload}
            disabled={isUploading}
            className="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-[#1EA7FF] hover:bg-[#008ee6] disabled:opacity-50 text-white font-semibold text-sm shadow-lg shadow-[#1EA7FF]/20 transition-all"
          >
            {isUploading ? (
              <>
                <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></span>
                <span>Uploading...</span>
              </>
            ) : (
              <>
                <span>Start Pipeline Analysis</span>
                <ArrowRight className="w-4 h-4" />
              </>
            )}
          </button>
        </motion.div>
      )}
    </div>
  );
}
