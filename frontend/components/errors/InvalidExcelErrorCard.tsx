"use client";

import { AlertCircle, Info } from "lucide-react";

export const EXCEL_ERROR_CODES = [
  "INVALID_EXCEL_FILE",
  "PARSE_ERROR",
  "INVALID_FILE_TYPE",
] as const;

export type ExcelErrorCode = (typeof EXCEL_ERROR_CODES)[number];

const LEGACY_EXCEL_ERROR_PATTERNS = [
  "badzipfile",
  "parseissue",
  "failed_to_open_workbook",
  "failed to parse",
  "failed_to_parse_sheet",
  "not a zip file",
  "invalidfileexception",
  "unsupportedformatexception",
];

export function isInvalidExcelError(errorMessage?: string | null): boolean {
  if (!errorMessage) return false;

  const normalized = errorMessage.trim();
  if (EXCEL_ERROR_CODES.includes(normalized as ExcelErrorCode)) {
    return true;
  }

  const lower = normalized.toLowerCase();
  return LEGACY_EXCEL_ERROR_PATTERNS.some((pattern) => lower.includes(pattern));
}

export function InvalidExcelErrorCard() {
  return (
    <div className="drdo-card p-6 space-y-4">
      <div className="flex items-start gap-3">
        <AlertCircle className="w-4 h-4 text-[#FF4D4F] flex-shrink-0 mt-0.5" />
        <div className="space-y-1 min-w-0">
          <h3 className="text-sm font-semibold text-[#F5F7FA]">
            ❌ Invalid or Corrupted Excel File
          </h3>
          <p className="text-xs text-[#8FA3BF] leading-relaxed">
            The uploaded workbook could not be opened or processed.
          </p>
        </div>
      </div>

      <div className="pl-7 space-y-4 text-xs text-[#8FA3BF]">
        <div>
          <p className="font-medium text-[#F5F7FA] mb-2">Possible reasons:</p>
          <ul className="space-y-1.5">
            <li>• The workbook is corrupted.</li>
            <li>• The file is not a valid Microsoft Excel (.xlsx) file.</li>
            <li>• The upload was incomplete.</li>
          </ul>
        </div>

        <div>
          <p className="font-medium text-[#F5F7FA] mb-2">How to fix it:</p>
          <ul className="space-y-1.5">
            <li>✓ Open the workbook in Microsoft Excel.</li>
            <li>
              ✓ Click <span className="font-medium text-[#F5F7FA]">File → Save As</span>
            </li>
            <li>✓ Save it again as a Microsoft Excel Workbook (.xlsx)</li>
            <li>✓ Upload the new file.</li>
          </ul>
        </div>
      </div>

      <div className="flex items-start gap-2.5 p-3 rounded-lg bg-[#142036]/60 border border-[#243244] text-xs text-[#8FA3BF]">
        <Info className="w-3.5 h-3.5 text-[#1EA7FF] flex-shrink-0 mt-0.5" />
        <p className="leading-relaxed">
          <span className="font-medium text-[#F5F7FA]">Need help?</span>{" "}
          If the problem continues after saving the workbook again, try exporting a
          fresh Excel file from the original source.
        </p>
      </div>
    </div>
  );
}
