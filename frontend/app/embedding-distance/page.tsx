"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiService } from "@/services/api";
import { useActiveRun } from "@/context/ActiveRunContext";
import { motion } from "framer-motion";
import {
  Ruler,
  AlertCircle,
  AlertTriangle,
  RefreshCw,
  Search,
  ArrowUpDown,
  Cpu,
} from "lucide-react";
import { EmbeddingPair } from "@/types";

type SortKey = "similarity" | "req_1_number" | "req_2_number";
type SortDir = "asc" | "desc";

const PAGE_SIZE = 50;

function similarityColor(similarity: number): string {
  if (similarity >= 0.95) return "text-[#FF4D4F]";
  if (similarity >= 0.8) return "text-[#FFB300]";
  return "text-[#8FA3BF]";
}

function similarityBarColor(similarity: number): string {
  if (similarity >= 0.95) return "bg-[#FF4D4F]";
  if (similarity >= 0.8) return "bg-[#FFB300]";
  return "bg-[#1EA7FF]";
}

export default function EmbeddingDistancePage() {
  const { activeRunId } = useActiveRun();
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("similarity");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [page, setPage] = useState(0);

  const {
    data: matrixData,
    isLoading,
    isError,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ["embedding_matrix", activeRunId],
    queryFn: () => apiService.getEmbeddingMatrix(activeRunId!),
    enabled: !!activeRunId,
  });

  const { data: requirements } = useQuery({
    queryKey: ["requirements", activeRunId],
    queryFn: () => apiService.getRunRequirements(activeRunId!),
    enabled: !!activeRunId,
  });

  const textById = useMemo(() => {
    const map = new Map<number, string>();
    (requirements || []).forEach((r) => {
      if (r.id !== undefined) map.set(Number(r.id), r.recommended_text || r.original_text);
    });
    return map;
  }, [requirements]);

  const pairs = matrixData?.pairs || [];

  const filteredAndSorted = useMemo(() => {
    const query = search.trim().toLowerCase();
    let result = pairs;

    if (query) {
      result = result.filter((p) => {
        if (
          `#${p.req_1_number}`.includes(query) ||
          `#${p.req_2_number}`.includes(query) ||
          String(p.req_1_number) === query ||
          String(p.req_2_number) === query
        ) {
          return true;
        }
        const t1 = textById.get(p.req_id_1)?.toLowerCase() || "";
        const t2 = textById.get(p.req_id_2)?.toLowerCase() || "";
        return t1.includes(query) || t2.includes(query);
      });
    }

    const sorted = [...result].sort((a, b) => {
      const dir = sortDir === "asc" ? 1 : -1;
      return (a[sortKey] - b[sortKey]) * dir;
    });
    return sorted;
  }, [pairs, search, sortKey, sortDir, textById]);

  const totalPages = Math.max(1, Math.ceil(filteredAndSorted.length / PAGE_SIZE));
  const clampedPage = Math.min(page, totalPages - 1);
  const pageItems = filteredAndSorted.slice(
    clampedPage * PAGE_SIZE,
    clampedPage * PAGE_SIZE + PAGE_SIZE
  );

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
    setPage(0);
  };

  if (!activeRunId) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-center">
          <AlertCircle className="w-16 h-16 text-[#8FA3BF] mx-auto mb-4" />
          <h2 className="text-xl font-bold text-[#F5F7FA] mb-2">No Active Run Selected</h2>
          <p className="text-[#8FA3BF] text-sm">
            Select a run from the history to view the embedding distance matrix.
          </p>
        </div>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-center">
          <RefreshCw className="w-8 h-8 text-[#1EA7FF] animate-spin mx-auto mb-4" />
          <p className="text-[#8FA3BF] text-sm">Computing pairwise embedding distances...</p>
        </div>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-center">
          <AlertTriangle className="w-16 h-16 text-[#FF4D4F] mx-auto mb-4" />
          <h2 className="text-xl font-bold text-[#F5F7FA] mb-2">Computation Failed</h2>
          <p className="text-[#8FA3BF] text-sm mb-4">
            Failed to compute the embedding distance matrix.
          </p>
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-[#1EA7FF] hover:bg-[#008ee6] disabled:opacity-50 text-white text-sm font-semibold transition"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isFetching ? "animate-spin" : ""}`} />
            <span>Retry</span>
          </button>
        </div>
      </div>
    );
  }

  const n = matrixData?.total_requirements || 0;
  const totalPairs = pairs.length;
  const mostSimilar = pairs.length > 0 ? Math.max(...pairs.map((p) => p.similarity)) : 0;
  const avgSimilarity =
    pairs.length > 0 ? pairs.reduce((s, p) => s + p.similarity, 0) / pairs.length : 0;

  return (
    <div className="space-y-6 select-none">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex items-center justify-between"
      >
        <div>
          <div className="flex items-center gap-2 text-xs text-[#1EA7FF] font-semibold mb-1">
            <Ruler className="w-4 h-4" />
            Pairwise Vector Comparison
          </div>
          <h1 className="text-2xl font-bold text-[#F5F7FA]">Embedding Distance Matrix</h1>
          <p className="text-xs text-[#8FA3BF] mt-1">
            Cosine similarity, distance, and angle between every combination of requirements
            (n·(n-1)/2 pairs) -- independent of the duplicate/similarity thresholds used in
            Consistency Analysis.
          </p>
        </div>
        <div className="flex items-center gap-2 text-[10px] font-mono font-bold px-3 py-1.5 rounded-lg bg-[#0F172A] border border-[#243244] text-[#8FA3BF]">
          <Cpu className="w-3.5 h-3.5" />
          <span>{matrixData?.method === "sentence-transformers" ? "SENTENCE-TRANSFORMERS" : "TF-IDF"}</span>
        </div>
      </motion.div>

      {/* Summary Cards */}
      <motion.div
        initial={{ opacity: 0, y: 15 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4"
      >
        <div className="drdo-card p-5 space-y-3">
          <span className="text-xs font-bold uppercase tracking-wider text-[#8FA3BF]">
            Total Requirements
          </span>
          <div className="text-3xl font-bold text-[#F5F7FA]">{n}</div>
        </div>
        <div className="drdo-card p-5 space-y-3">
          <span className="text-xs font-bold uppercase tracking-wider text-[#8FA3BF]">
            Total Pairs Compared
          </span>
          <div className="text-3xl font-bold text-[#F5F7FA]">{totalPairs}</div>
        </div>
        <div className="drdo-card p-5 space-y-3">
          <span className="text-xs font-bold uppercase tracking-wider text-[#8FA3BF]">
            Highest Similarity
          </span>
          <div className={`text-3xl font-bold ${similarityColor(mostSimilar)}`}>
            {(mostSimilar * 100).toFixed(1)}%
          </div>
        </div>
        <div className="drdo-card p-5 space-y-3">
          <span className="text-xs font-bold uppercase tracking-wider text-[#8FA3BF]">
            Average Similarity
          </span>
          <div className="text-3xl font-bold text-[#F5F7FA]">{(avgSimilarity * 100).toFixed(1)}%</div>
        </div>
      </motion.div>

      {/* Search + Table */}
      <motion.div
        initial={{ opacity: 0, y: 15 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
        className="drdo-card p-6 space-y-4"
      >
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <h2 className="text-base font-bold text-[#F5F7FA] flex items-center gap-2">
            <Ruler className="w-4 h-4 text-[#1EA7FF]" />
            All Pairwise Comparisons
          </h2>
          <div className="relative w-full md:w-80">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-[#8FA3BF]" />
            <input
              type="text"
              placeholder="Search by #ID or requirement text..."
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(0);
              }}
              className="w-full bg-[#142036] border border-[#243244] rounded-lg pl-9 pr-4 py-2 text-xs text-[#F5F7FA] placeholder-[#8FA3BF] focus:outline-none focus:border-[#1EA7FF]"
            />
          </div>
        </div>

        {pairs.length < 2 ? (
          <div className="py-12 text-center text-[#8FA3BF] text-sm">
            {n < 2
              ? "At least 2 requirements are needed to compute pairwise distances."
              : "No pairs to display."}
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-[#243244] text-[#8FA3BF] uppercase text-[10px] tracking-wider">
                    <th
                      className="py-3 px-3 cursor-pointer select-none hover:text-[#F5F7FA]"
                      onClick={() => toggleSort("req_1_number")}
                    >
                      <span className="inline-flex items-center gap-1">
                        Req #1 <ArrowUpDown className="w-3 h-3" />
                      </span>
                    </th>
                    <th
                      className="py-3 px-3 cursor-pointer select-none hover:text-[#F5F7FA]"
                      onClick={() => toggleSort("req_2_number")}
                    >
                      <span className="inline-flex items-center gap-1">
                        Req #2 <ArrowUpDown className="w-3 h-3" />
                      </span>
                    </th>
                    <th className="py-3 px-3">Requirement Text</th>
                    <th
                      className="py-3 px-3 cursor-pointer select-none hover:text-[#F5F7FA]"
                      onClick={() => toggleSort("similarity")}
                    >
                      <span className="inline-flex items-center gap-1">
                        Similarity <ArrowUpDown className="w-3 h-3" />
                      </span>
                    </th>
                    <th className="py-3 px-3">Distance</th>
                    <th className="py-3 px-3">Angle</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#243244]/50">
                  {pageItems.map((p: EmbeddingPair) => (
                    <tr
                      key={`${p.req_id_1}-${p.req_id_2}`}
                      className="hover:bg-[#142036]/50 transition align-top"
                    >
                      <td className="py-3 px-3 font-mono font-bold text-[#1EA7FF] whitespace-nowrap">
                        #{p.req_1_number}
                      </td>
                      <td className="py-3 px-3 font-mono font-bold text-[#1EA7FF] whitespace-nowrap">
                        #{p.req_2_number}
                      </td>
                      <td className="py-3 px-3 text-[#8FA3BF] max-w-md">
                        <div className="line-clamp-1">
                          <span className="text-[#F5F7FA]">#{p.req_1_number}:</span>{" "}
                          {textById.get(p.req_id_1) || "-"}
                        </div>
                        <div className="line-clamp-1">
                          <span className="text-[#F5F7FA]">#{p.req_2_number}:</span>{" "}
                          {textById.get(p.req_id_2) || "-"}
                        </div>
                      </td>
                      <td className="py-3 px-3">
                        <div className="flex items-center gap-2">
                          <span className={`font-mono font-bold ${similarityColor(p.similarity)}`}>
                            {(p.similarity * 100).toFixed(1)}%
                          </span>
                          <div className="w-16 h-1.5 bg-[#142036] rounded-full overflow-hidden border border-[#243244]">
                            <div
                              className={`h-full ${similarityBarColor(p.similarity)}`}
                              style={{ width: `${Math.max(0, Math.min(100, p.similarity * 100))}%` }}
                            />
                          </div>
                        </div>
                      </td>
                      <td className="py-3 px-3 text-[#8FA3BF] font-mono">
                        {p.distance.toFixed(3)}
                      </td>
                      <td className="py-3 px-3 text-[#8FA3BF] font-mono">
                        {p.angle_degrees.toFixed(1)}°
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            <div className="flex items-center justify-between pt-3 text-xs text-[#8FA3BF]">
              <span>
                Showing {clampedPage * PAGE_SIZE + 1}-
                {Math.min((clampedPage + 1) * PAGE_SIZE, filteredAndSorted.length)} of{" "}
                {filteredAndSorted.length} pairs
              </span>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  disabled={clampedPage === 0}
                  className="px-3 py-1.5 rounded-lg border border-[#243244] bg-[#142036] disabled:opacity-40 hover:border-[#1EA7FF]/40 transition font-semibold"
                >
                  Previous
                </button>
                <span className="font-mono">
                  {clampedPage + 1} / {totalPages}
                </span>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                  disabled={clampedPage >= totalPages - 1}
                  className="px-3 py-1.5 rounded-lg border border-[#243244] bg-[#142036] disabled:opacity-40 hover:border-[#1EA7FF]/40 transition font-semibold"
                >
                  Next
                </button>
              </div>
            </div>
          </>
        )}
      </motion.div>
    </div>
  );
}
