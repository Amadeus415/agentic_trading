import type { Metadata } from "next";
import { Suspense, type ReactNode } from "react";
import { listFunds } from "@/lib/fund";

import { AppShell } from "@/components/app-shell";

import "./globals.css";

export const metadata: Metadata = {
  title: "Edgecraft Fund",
  description: "Edgecraft paper-trading fund dashboard",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  let funds: string[] = [];
  try { funds = listFunds().map((fund) => fund.fund_id); } catch { /* Empty setup remains readable. */ }
  return (
    <html lang="en" className="dark h-full antialiased">
      <body className="min-h-full flex flex-col">
        <Suspense><AppShell funds={funds}>{children}</AppShell></Suspense>
      </body>
    </html>
  );
}
