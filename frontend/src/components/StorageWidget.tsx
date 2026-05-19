"use client";

import { useState, useEffect } from "react";
import { api, StorageStats } from "@/lib/api";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export default function StorageWidget({ onCleanup }: { onCleanup?: () => void }) {
  const [stats, setStats] = useState<StorageStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [cleaning, setCleaning] = useState(false);
  const [cleanupResult, setCleanupResult] = useState<string | null>(null);
  const [showConfirm, setShowConfirm] = useState(false);

  async function fetchStats() {
    try {
      const s = await api.getStats();
      setStats(s);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchStats();
  }, []);

  async function handleCleanup() {
    setCleaning(true);
    setCleanupResult(null);
    setShowConfirm(false);
    try {
      const res = await api.runCleanup(30);
      setCleanupResult(
        res.deleted_jobs === 0
          ? "Žádné staré joby k mazání."
          : `Smazáno ${res.deleted_jobs} jobů, uvolněno ${formatBytes(res.freed_bytes)}.`
      );
      await fetchStats();
      onCleanup?.();
    } catch (err) {
      setCleanupResult("Cleanup selhal: " + (err instanceof Error ? err.message : String(err)));
    } finally {
      setCleaning(false);
    }
  }

  if (loading) {
    return (
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 animate-pulse h-24" />
    );
  }

  if (!stats) return null;

  const statusColors: Record<string, string> = {
    done: "text-green-400",
    error: "text-red-400",
    processing: "text-blue-400",
    queued: "text-zinc-400",
    needs_attention: "text-amber-400",
  };

  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xs font-medium text-zinc-400 uppercase tracking-wider">
          Úložiště
        </h2>
        <button
          onClick={fetchStats}
          className="text-xs text-zinc-600 hover:text-zinc-400 transition-colors"
        >
          ↻
        </button>
      </div>

      {/* Disk */}
      <div className="grid grid-cols-3 gap-3">
        <div>
          <p className="text-xs text-zinc-500">Nahrávky</p>
          <p className="text-sm font-medium text-zinc-100">
            {formatBytes(stats.disk.uploads_bytes)}
          </p>
        </div>
        <div>
          <p className="text-xs text-zinc-500">Výstupy</p>
          <p className="text-sm font-medium text-zinc-100">
            {formatBytes(stats.disk.outputs_bytes)}
          </p>
        </div>
        <div>
          <p className="text-xs text-zinc-500">Celkem</p>
          <p className="text-sm font-medium text-zinc-100">
            {formatBytes(stats.disk.total_bytes)}
          </p>
        </div>
      </div>

      {/* Status breakdown */}
      {Object.keys(stats.status_counts).length > 0 && (
        <div className="flex flex-wrap gap-2">
          {Object.entries(stats.status_counts).map(([status, count]) => (
            <span
              key={status}
              className={`text-xs ${statusColors[status] ?? "text-zinc-400"}`}
            >
              {status}: {count}
            </span>
          ))}
        </div>
      )}

      {/* Cleanup */}
      <div className="flex items-center gap-3">
        {!showConfirm ? (
          <button
            onClick={() => setShowConfirm(true)}
            className="text-xs text-zinc-500 hover:text-red-400 transition-colors"
          >
            Smazat joby starší 30 dní
          </button>
        ) : (
          <div className="flex items-center gap-2">
            <span className="text-xs text-zinc-400">Opravdu smazat?</span>
            <button
              onClick={handleCleanup}
              disabled={cleaning}
              className="text-xs text-red-400 hover:text-red-300 font-medium transition-colors"
            >
              {cleaning ? "Mažu…" : "Ano, smazat"}
            </button>
            <button
              onClick={() => setShowConfirm(false)}
              className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
            >
              Zrušit
            </button>
          </div>
        )}
      </div>

      {cleanupResult && (
        <p className="text-xs text-zinc-500">{cleanupResult}</p>
      )}
    </div>
  );
}
