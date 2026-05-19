"use client";

import { useState, useEffect } from "react";
import { api, Job } from "@/lib/api";

interface RepairLog {
  id: string;
  action: string;
  description_cs: string;
  before_value: string | null;
  after_value: string | null;
  success: boolean;
  created_at: string;
}

interface RepairResult {
  status: string;
  steps_done: string[];
  warnings: string[];
  size_before_kb: number;
  size_after_kb: number;
  processing_time_ms: number;
  gs_version: string | null;
}

function Toggle({ label, desc, checked, onChange }: {
  label: string; desc?: string; checked: boolean; onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-start gap-3 cursor-pointer select-none">
      <div
        className={`mt-0.5 w-8 h-4 rounded-full flex-shrink-0 transition-colors ${checked ? "bg-blue-600" : "bg-zinc-700"}`}
        onClick={() => onChange(!checked)}
      >
        <div className={`w-3.5 h-3.5 rounded-full bg-white mt-0.5 transition-transform shadow ${checked ? "translate-x-4" : "translate-x-0.5"}`} />
      </div>
      <div>
        <p className="text-sm text-zinc-300">{label}</p>
        {desc && <p className="text-xs text-zinc-600">{desc}</p>}
      </div>
    </label>
  );
}

export default function PrepressPanel({ job, onDone }: { job: Job; onDone?: () => void }) {
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<RepairResult | null>(null);
  const [logs, setLogs] = useState<RepairLog[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Options
  const [flattenText, setFlattenText] = useState(true);
  const [flattenTransp, setFlattenTransp] = useState(true);
  const [convertCmyk, setConvertCmyk] = useState(true);
  const [cmykProfile, setCmykProfile] = useState("fogra39");
  const [compress, setCompress] = useState(true);

  // Načíst existující logy
  useEffect(() => {
    fetch(`/api/jobs/${job.id}/repair`)
      .then((r) => r.ok ? r.json() : [])
      .then((data) => Array.isArray(data) ? setLogs(data) : setLogs([]))
      .catch(() => {});
  }, [job.id]);

  const hasRepaired = logs.some((l) => l.success && l.action !== "warning");

  async function handleRun() {
    setRunning(true);
    setError(null);
    try {
      const res = await fetch(`/api/jobs/${job.id}/repair`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          flatten_text: flattenText,
          flatten_transparency: flattenTransp,
          convert_to_cmyk: convertCmyk,
          cmyk_profile: cmykProfile,
          compress,
        }),
      });
      if (!res.ok) {
        const body = await res.json();
        throw new Error(body.detail || "Prepress selhal.");
      }
      const data: RepairResult = await res.json();
      setResult(data);
      // Reload logs
      const logsRes = await fetch(`/api/jobs/${job.id}/repair`);
      if (logsRes.ok) setLogs(await logsRes.json());
      onDone?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Chyba.");
    } finally {
      setRunning(false);
    }
  }

  const stepIcons: Record<string, string> = {
    text_to_curves: "✦",
    embed_fonts: "✦",
    flatten_transparency: "◈",
    rgb_to_cmyk: "◉",
    icc_fogra39: "◉",
    icc_fogra47: "◉",
    compress: "⊡",
    warning: "⚠",
  };

  return (
    <div className="space-y-5">
      {/* Stav */}
      {hasRepaired && !result && (
        <div className="flex items-center gap-2 bg-green-950 border border-green-800 rounded-lg px-3 py-2">
          <span className="text-green-400 text-xs">✓</span>
          <p className="text-xs text-green-300">Prepress byl spuštěn — imposice použije opravený soubor automaticky.</p>
        </div>
      )}

      {/* Co se provede */}
      <div className="space-y-2">
        <p className="text-xs text-zinc-500 uppercase tracking-wider">Co provést</p>

        <Toggle
          label="Text → křivky"
          desc="Opraví neviditelný text z Canvy, Figmy, Google Docs. Nutné pro CorelDRAW."
          checked={flattenText}
          onChange={setFlattenText}
        />
        <Toggle
          label="Flatten průhledností"
          desc="Odstraní průhledné vrstvy — bezpečnější pro starší RIP systémy."
          checked={flattenTransp}
          onChange={setFlattenTransp}
        />
        <Toggle
          label="RGB → CMYK"
          desc="Převede všechny RGB objekty do tiskového CMYK barevného prostoru."
          checked={convertCmyk}
          onChange={setConvertCmyk}
        />

        {convertCmyk && (
          <div className="pl-8">
            <p className="text-xs text-zinc-600 mb-1">Profil</p>
            <div className="flex gap-1.5">
              {[
                { v: "fogra39", l: "Fogra39", d: "Coated (lesklý)" },
                { v: "fogra47", l: "Fogra47", d: "Uncoated (mat)" },
                { v: "default", l: "GS default", d: "" },
              ].map((p) => (
                <button
                  key={p.v}
                  onClick={() => setCmykProfile(p.v)}
                  className={`px-2 py-1 rounded text-xs transition-colors ${
                    cmykProfile === p.v
                      ? "bg-blue-600 text-white"
                      : "bg-zinc-800 text-zinc-400 hover:bg-zinc-700"
                  }`}
                  title={p.d}
                >
                  {p.l}
                </button>
              ))}
            </div>
          </div>
        )}

        <Toggle
          label="Komprese a optimalizace"
          desc="Zmenší velikost PDF bez ztráty kvality."
          checked={compress}
          onChange={setCompress}
        />
      </div>

      {/* Info */}
      <div className="bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2.5 text-xs text-zinc-500 space-y-0.5">
        <p>Výstup: <span className="text-zinc-300">{job.source_filename?.replace(".pdf", "")}_prepress.pdf</span></p>
        <p>Imposice automaticky použije tento soubor místo originálu.</p>
      </div>

      {/* Tlačítko */}
      <button
        onClick={handleRun}
        disabled={running}
        className="w-full bg-orange-700 hover:bg-orange-600 disabled:bg-zinc-700 disabled:text-zinc-500 text-white font-medium py-2.5 px-4 rounded-lg transition-colors text-sm"
      >
        {running ? "Zpracovávám…" : "Spustit Prepress Pipeline"}
      </button>

      {error && (
        <p className="text-red-400 text-xs bg-red-950 border border-red-800 rounded p-3">{error}</p>
      )}

      {/* Výsledek */}
      {result && (
        <div className="bg-zinc-950 border border-green-800 rounded-lg p-4 space-y-2">
          <p className="text-xs font-medium text-green-400 uppercase tracking-wider">
            Hotovo — {result.processing_time_ms} ms
          </p>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <p className="text-xs text-zinc-500">Před</p>
              <p className="text-sm font-medium text-zinc-100">{result.size_before_kb} KB</p>
            </div>
            <div>
              <p className="text-xs text-zinc-500">Po</p>
              <p className="text-sm font-medium text-zinc-100">{result.size_after_kb} KB</p>
            </div>
          </div>
          {result.warnings.map((w, i) => (
            <p key={i} className="text-xs text-amber-400">⚠ {w}</p>
          ))}
          <a
            href={`/api/jobs/${job.id}/repair/download`}
            download
            className="inline-block mt-1 text-sm text-blue-400 hover:text-blue-300 transition-colors"
          >
            Stáhnout prepressed PDF →
          </a>
        </div>
      )}

      {/* Log předchozích běhů */}
      {logs.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-xs text-zinc-500 uppercase tracking-wider">Log kroků</p>
          <div className="space-y-1">
            {logs.map((log) => (
              <div key={log.id} className="flex items-start gap-2">
                <span className={`text-xs mt-0.5 ${log.action === "warning" ? "text-amber-400" : "text-green-500"}`}>
                  {stepIcons[log.action] || "•"}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-zinc-300">{log.description_cs}</p>
                  {(log.before_value || log.after_value) && (
                    <p className="text-xs text-zinc-600">
                      {log.before_value && `${log.before_value}`}
                      {log.before_value && log.after_value && " → "}
                      {log.after_value && `${log.after_value}`}
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
