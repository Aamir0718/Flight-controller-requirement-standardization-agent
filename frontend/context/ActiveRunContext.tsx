"use client";

import { createContext, useCallback, useContext, useState } from "react";

type ActiveRunContextValue = {
  activeRunId: number | null;
  setActiveRunId: (id: number | null) => void;
  clearActiveRun: () => void;
};

const ActiveRunContext = createContext<ActiveRunContextValue | null>(null);

export function ActiveRunProvider({ children }: { children: React.ReactNode }) {
  const [activeRunId, setActiveRunIdState] = useState<number | null>(null);

  const setActiveRunId = useCallback((id: number | null) => {
    setActiveRunIdState(id);
  }, []);

  const clearActiveRun = useCallback(() => {
    setActiveRunIdState(null);
  }, []);

  return (
    <ActiveRunContext.Provider value={{ activeRunId, setActiveRunId, clearActiveRun }}>
      {children}
    </ActiveRunContext.Provider>
  );
}

export function useActiveRun() {
  const context = useContext(ActiveRunContext);
  if (!context) {
    throw new Error("useActiveRun must be used within an ActiveRunProvider");
  }
  return context;
}
