"use client";

import Link from "next/link";
import { UploadCloud } from "lucide-react";

type NoActiveRunEmptyStateProps = {
  message: string;
};

export function NoActiveRunEmptyState({ message }: NoActiveRunEmptyStateProps) {
  return (
    <div className="py-16 text-center space-y-4">
      <p className="text-[#8FA3BF] text-sm">{message}</p>
      <Link
        href="/upload"
        className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-[#1EA7FF] hover:bg-[#008ee6] text-white text-sm font-semibold shadow-lg shadow-[#1EA7FF]/20 transition"
      >
        <UploadCloud className="w-4 h-4" />
        <span>Upload Workbook</span>
      </Link>
    </div>
  );
}
