"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  UploadCloud,
  FileCheck2,
  Columns3,
  BarChart3,
  History,
  Download,
  Settings,
  ShieldCheck,
  GitBranch,
  Ruler,
  ListChecks
} from "lucide-react";
import { cn } from "@/lib/utils";

// No "Processing Status" nav entry: analysis now runs synchronously
// inside POST /upload (see src/ui/api.py's module docstring), so there's
// no separate processing phase left to show a status page for -- Upload
// goes straight to Requirement Review. src/app/processing/ still exists
// on disk but is unreachable from navigation; only LLM generation is ever
// asynchronous now, and its live status is the per-row badge on the
// Review page itself, not a separate page.
const navItems = [
  { name: "Dashboard", href: "/", icon: LayoutDashboard },
  { name: "Upload Workbook", href: "/upload", icon: UploadCloud },
  { name: "Requirement Review", href: "/review", icon: FileCheck2 },
  { name: "Requirements List", href: "/requirements-list", icon: ListChecks },
  { name: "Comparison Matrix", href: "/compare", icon: Columns3 },
  { name: "Consistency Analysis", href: "/consistency", icon: GitBranch },
  { name: "Embedding Distance", href: "/embedding-distance", icon: Ruler },
  { name: "Analytics & Reports", href: "/analytics", icon: BarChart3 },
  { name: "Run History", href: "/history", icon: History },
  { name: "Export Center", href: "/export", icon: Download },
  { name: "Settings", href: "/settings", icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-64 bg-[#050B14] border-r border-[#243244] flex flex-col justify-between h-screen sticky top-0 z-30 select-none">
      <div>
        {/* DRDO Branding Header */}
        <div className="p-5 border-b border-[#243244] flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-[#1EA7FF] to-[#008ee6] flex items-center justify-center shadow-lg shadow-[#1EA7FF]/20 text-white font-bold">
            ✈️
          </div>
          <div>
            <div className="text-xs font-bold uppercase tracking-wider text-[#1EA7FF]">DRDO ENGINE</div>
            <div className="text-sm font-semibold text-[#F5F7FA]">Requirements Platform</div>
          </div>
        </div>

        {/* Navigation Links */}
        <nav className="p-3 space-y-1">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex items-center gap-3 px-3.5 py-2.5 rounded-lg text-sm font-medium transition-all duration-200",
                  isActive
                    ? "bg-[#1EA7FF]/15 text-[#1EA7FF] border border-[#1EA7FF]/30 font-semibold shadow-sm"
                    : "text-[#8FA3BF] hover:text-[#F5F7FA] hover:bg-[#0F172A]"
                )}
              >
                <Icon className={cn("w-4 h-4", isActive ? "text-[#1EA7FF]" : "text-[#8FA3BF]")} />
                <span>{item.name}</span>
              </Link>
            );
          })}
        </nav>
      </div>

      {/* Security & System Info Footer */}
      <div className="p-4 m-3 rounded-xl bg-[#0F172A] border border-[#243244] space-y-2">
        <div className="flex items-center gap-2 text-xs font-semibold text-[#00C853]">
          <ShieldCheck className="w-4 h-4" />
          <span>Local-First Analysis</span>
        </div>
        <p className="text-[11px] text-[#8FA3BF] leading-relaxed">
          Local SQLite storage. Analysis, editing, and export are fully local — only Generate and
          contradiction detection reach the configured DRDO-internal LLM endpoint.
        </p>
      </div>
    </aside>
  );
}
