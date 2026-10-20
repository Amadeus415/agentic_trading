import type { Metadata } from "next";
import { Manrope } from "next/font/google";
import { Suspense, type ReactNode } from "react";
import { listFunds } from "@/lib/fund";

import { AppShell } from "@/components/app-shell";

import "./globals.css";

const manrope = Manrope({ subsets: ["latin"], variable: "--font-manrope" });

export const metadata: Metadata = {
  title: "Edgecraft",
  description: "A paper prediction-market fund, measured against the S&P 500.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  let funds: string[] = [];
  try { funds = listFunds().map((fund) => fund.fund_id); } catch { /* Empty setup remains readable. */ }
  return (
    <html lang="en" className={manrope.variable}>
      <body>
        <Suspense><AppShell funds={funds}>{children}</AppShell></Suspense>
      </body>
    </html>
  );
}
