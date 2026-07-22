"use client";

import { useRouter } from "next/navigation";
import { useActiveRun } from "@/context/ActiveRunContext";

type RunDestination = "/review" | "/processing";

export function useSelectRun() {
  const { setActiveRunId } = useActiveRun();
  const router = useRouter();

  return (runId: number, destination: RunDestination = "/review") => {
    setActiveRunId(runId);
    router.push(destination);
  };
}
