import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PrePress Server",
  description: "PDF předtisková příprava — Království Tisku",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="cs" className="dark">
      <body className="bg-zinc-950 text-zinc-100 min-h-screen antialiased">
        <nav className="border-b border-zinc-800 px-6 py-4 flex items-center gap-3">
          <div className="w-2 h-2 rounded-full bg-blue-500" />
          <span className="font-semibold tracking-wide text-zinc-100">
            PrePress Server
          </span>
          <span className="ml-2 text-xs text-zinc-500 uppercase tracking-widest">
            Předtisková příprava
          </span>
        </nav>
        <main className="max-w-6xl mx-auto px-6 py-8">{children}</main>
      </body>
    </html>
  );
}
