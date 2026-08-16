import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "MT5 Trading Desk",
  description: "Live MetaTrader 5 desk backed by the FastAPI bridge",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
