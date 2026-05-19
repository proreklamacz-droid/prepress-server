"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, Job, PreflightResult } from "@/lib/api";
import StatusBadge from "@/components/StatusBadge";

function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("cs-CZ", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function CheckRow({
  label,
  ok,
  detail,
}: {
  label: string;
  ok: boolean;
  detail?: string;
}) {
  return (
    <div className="flex items-start gap-3 py-2 border-b border-zinc-800 last:border-0">
      <span
        className={`mt-0.5 text-xs font-bold rounded px-1.5 py-0.5 ${
          ok
            ? "bg-green-900 text-green-300"
            : "bg-red-900 text-red-300"
        }`}
      >
        {ok ? "OK" : "ERR"}
      </span>
      <div>
        <p className="text-sm text-zinc-200">{label}</p>
        {detail && <p className="text-xs text-zinc-500 mt-0.5">{detail}</p>}
      </div>
    </div>
  );
}

function ColorspaceBadge({ cs }: { cs: string | null }) {
  const map: Record<string, string> = {
    cmyk: "bg-green-900 text-green-300",
    rgb: "bg-red-900 text-red-300",
    mixed: "bg-amber-900 text-amber-300",
    unknown: "bg-zinc-700 text-zinc-400",
  };
  const cls = cs ? (map[cs] ?? map["unknown"]) : map["unknown"];
  return (
    <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium uppercase ${cls}`}>
      {cs ?? "—"}
    </span>
  );
}

export default function JobDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();

  const [job, setJob] = useState<Job | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [preflightRunning, setPreflightRunning] = useState(false);
  const [preflightError, setPreflightError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchJob = useCallback(async () => {
    try {
      const data = await api.getJob(id);
      setJob(data);
      setError(null);
      return data;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Chyba při načítání.");
      return null;
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    fetchJob();
  }, [fetchJob]);

  // Stop polling when job is no longer processing
  useEffect(() => {
    if (job && job.status !== "processing" && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
      setPreflightRunning(false);
    }
  }, [job?.status]);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  async function handleStartPreflight() {
    if (!job) return;
    setPreflightError(null);
    setPreflightRunning(true);
    try {
      await api.startPreflight(id);
      // Optimistically mark as processing
      setJob((prev) => prev ? { ...prev, status: "processing" } : prev);
      // Poll every 3s until done
      pollRef.current = setInterval(async () => {
        const updated = await fetchJob();
        if (updated && updated.status !== "processing" && updated.status !== "queued") {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          setPreflightRunning(false);
        }
      }, 3000);
    } catch (err) {
      setPreflightError(err instanceof Error ? err.message : "Spuštění selhalo.");
      setPreflightRunning(false);
    }
  }

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="h-6 bg-zinc-800 rounded w-48 animate-pulse" />
        <div className="h-40 bg-zinc-900 rounded-xl animate-pulse" />
      </div>
    );
  }

  if (error || !job) {
    return (
      <div className="text-red-400 text-sm">
        {error ?? "Job nenalezen."}
      </div>
    );
  }

  const firstPage = job.page_dimensions?.[0];
  const preflight = job.preflight;

  return (
    <div className="space-y-6">
      {/* Back link */}
      <button
        onClick={() => router.push("/")}
        className="text-sm text-zinc-500 hover:text-zinc-300 transition-colors flex items-center gap-1"
      >
        ← Zpět na dashboard
      </button>

      {/* Header */}
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-xl font-semibold text-zinc-100 break-all">
              {job.source_filename}
            </h1>
            <p className="text-xs text-zinc-500 mt-1">
              Nahráno: {formatDate(job.created_at)}
            </p>
          </div>
          <StatusBadge status={job.status} />
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-5">
          <Stat label="Stránek" value={job.page_count?.toString() ?? "—"} />
          <Stat label="Velikost" value={formatBytes(job.source_size_bytes)} />
          <Stat label="PDF verze" value={job.pdf_version ?? "—"} />
          <Stat
            label="1. str. rozměr"
            value={
              firstPage
                ? `${firstPage.width_mm} × ${firstPage.height_mm} mm`
                : "—"
            }
          />
        </div>

        {job.is_encrypted && (
          <p className="mt-3 text-xs text-amber-400">
            Soubor je zašifrovaný — některé kontroly nemusí fungovat.
          </p>
        )}
      </div>

      {/* Preview + actions row */}
      <div className="grid md:grid-cols-2 gap-6">
        {/* Preview */}
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 flex flex-col gap-3">
          <h2 className="text-xs font-medium text-zinc-400 uppercase tracking-wider">
            Náhled první stránky
          </h2>
          <div className="bg-zinc-950 rounded-lg overflow-hidden flex items-center justify-center min-h-[200px]">
            <img
              src={api.previewUrl(job.id)}
              alt="Náhled PDF"
              className="max-w-full max-h-[400px] object-contain"
              onError={(e) => {
                (e.target as HTMLImageElement).style.display = "none";
              }}
            />
          </div>
          <a
            href={api.downloadUrl(job.id)}
            className="text-center text-sm text-blue-400 hover:text-blue-300 transition-colors"
            download
          >
            Stáhnout PDF
          </a>
        </div>

        {/* Actions */}
        <div className="space-y-4">
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 space-y-3">
            <h2 className="text-xs font-medium text-zinc-400 uppercase tracking-wider">
              Akce
            </h2>

            <button
              onClick={handleStartPreflight}
              disabled={preflightRunning || job.status === "processing"}
              className="w-full bg-blue-600 hover:bg-blue-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white font-medium py-2.5 px-4 rounded-lg transition-colors text-sm"
            >
              {preflightRunning || job.status === "processing"
                ? "Kontroluji..."
                : "Spustit Preflight"}
            </button>

            {preflightError && (
              <p className="text-red-400 text-xs">{preflightError}</p>
            )}

            <button
              disabled
              className="w-full bg-zinc-800 text-zinc-600 font-medium py-2.5 px-4 rounded-lg text-sm cursor-not-allowed"
            >
              Imposice (brzy)
            </button>
            <button
              disabled
              className="w-full bg-zinc-800 text-zinc-600 font-medium py-2.5 px-4 rounded-lg text-sm cursor-not-allowed"
            >
              Smart Repair (brzy)
            </button>
          </div>

          {job.notes && (
            <div className="bg-amber-950 border border-amber-800 rounded-xl p-4">
              <p className="text-xs text-amber-400">{job.notes}</p>
            </div>
          )}
        </div>
      </div>

      {/* Preflight results */}
      {preflight && (
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6 space-y-5">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-medium text-zinc-200">
              Výsledky Preflight
            </h2>
            <SeverityBadge severity={preflight.severity} />
          </div>

          <div className="space-y-0">
            <CheckRow
              label="Fonty"
              ok={preflight.fonts_ok}
              detail={
                preflight.fonts_issues.length > 0
                  ? `${preflight.fonts_issues.length} nevložených fontů`
                  : "Všechny fonty jsou vloženy"
              }
            />
            <CheckRow
              label={`Rozlišení obrázků${preflight.resolution_min_dpi ? ` (min. ${preflight.resolution_min_dpi} DPI)` : ""}`}
              ok={preflight.resolution_ok}
              detail={
                preflight.resolution_issues.length > 0
                  ? `${preflight.resolution_issues.length} obrázků pod minimem`
                  : preflight.resolution_min_dpi
                  ? `Nejnižší DPI: ${preflight.resolution_min_dpi}`
                  : "Žádné rastrové obrázky"
              }
            />
            <div className="flex items-center gap-3 py-2 border-b border-zinc-800">
              <ColorspaceBadge cs={preflight.colorspace} />
              <div>
                <p className="text-sm text-zinc-200">Barevný model</p>
                {preflight.colorspace_issues.length > 0 && (
                  <p className="text-xs text-zinc-500">
                    {preflight.colorspace_issues.length} RGB objektů
                  </p>
                )}
              </div>
            </div>
          </div>

          {/* LLM Report */}
          {preflight.llm_report_cs && (
            <div className="bg-zinc-950 border border-zinc-700 rounded-lg p-4">
              <p className="text-xs font-medium text-zinc-400 uppercase tracking-wider mb-2">
                Doporučení (AI)
              </p>
              <p className="text-sm text-zinc-300 leading-relaxed">
                {preflight.llm_report_cs}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-zinc-500">{label}</p>
      <p className="text-sm font-medium text-zinc-100 mt-0.5">{value}</p>
    </div>
  );
}

function SeverityBadge({ severity }: { severity: "ok" | "warning" | "error" }) {
  const map = {
    ok: "bg-green-900 text-green-300",
    warning: "bg-amber-900 text-amber-300",
    error: "bg-red-900 text-red-300",
  };
  const labels = { ok: "V pořádku", warning: "Varování", error: "Chyba" };
  return (
    <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium ${map[severity]}`}>
      {labels[severity]}
    </span>
  );
}
