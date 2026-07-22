"use client";

import "./globals.css";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopNav } from "@/components/layout/TopNav";
import { ActiveRunProvider } from "@/context/ActiveRunContext";

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            refetchOnWindowFocus: false,
            retry: 1,
          },
        },
      })
  );

  return (
    <html lang="en" className="dark">
      <body className="bg-[#07111F] text-[#F5F7FA] min-h-screen flex antialiased">
        <QueryClientProvider client={queryClient}>
          <ActiveRunProvider>
            {/* Sidebar */}
            <Sidebar />

            {/* Main Workspace Area */}
            <div className="flex-1 flex flex-col min-w-0">
              <TopNav />
              <main className="flex-1 p-6 max-w-[1600px] w-full mx-auto space-y-6">
                {children}
              </main>
            </div>
          </ActiveRunProvider>
        </QueryClientProvider>
      </body>
    </html>
  );
}
