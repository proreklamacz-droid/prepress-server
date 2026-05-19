"use client";

import { useState, useEffect } from "react";
import {
  api,
  ImpositionRequestBody,
  ImpositionResult,
  ImpositionState,
  SheetFormat,
  Job,
} from "@/lib/api";

const IMPOSITION_TYPES = [
  { value: "grid", label: "Grid (N-up)", desc: "Více stránek na arch, řádky × sloupce" },
  { value: "booklet_saddle", label: "Brožura (sešit)", desc: "2-up saddle stitch, automatické pořadí stránek" },
  { value: "cut_stack", label: "Cut & Stack", desc: "Každá stránka N-krát na archu (samolepky, vizitky)" },
];

const ROTATIONS = [
  { value: 0, label: "0°" },
  { value: 90, label: "90°" },
  { value: 180, label: "180°" },
  { value: 270, label: "270°" },
];

function NumInput({
  label,
  value,
  onChange,
  min = 0,
  max,
  step = 0.5,
  unit = "mm",
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: number;
  unit?: string;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <label className="text-xs text-zinc-500">{label}</label>
      <div className="flex items-center gap-1">
        <input
          type="number"
          className="w-20 bg-zinc-800 border border-zinc-700 text-zinc-100 rounded px-2 py-1 text-sm focus:outline-none focus:border-blue-500"
          value={value}
          min={min}
          max={max}
          step={step}
          onChange={(e) => onChange(parseFloat(e.target.value) || 0)}
        />
        {unit && <span className="text-xs text-zinc-600">{unit}</span>}
      </div>
    </div>
  );
}

function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-2 cursor-pointer select-none">
      <div
        className={`w-8 h-4 rounded-full transition-colors ${checked ? "bg-blue-600" : "bg-zinc-700"}`}
        onClick={() => onChange(!checked)}
      >
        <div
          className={`w-3.5 h-3.5 rounded-full bg-white mt-0.5 transition-transform shadow ${
            checked ? "translate-x-4" : "translate-x-0.5"
          }`}
        />
      </div>
      <span className="text-sm text-zinc-300">{label}</span>
    </label>
  );
}

export default function ImpositionPanel({
  job,
  onDone,
}: {
  job: Job;
  onDone?: () => void;
}) {
  const [formats, setFormats] = useState<SheetFormat[]>([]);
  const [result, setResult] = useState<ImpositionResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showPreview, setShowPreview] = useState(false);

  // Form state
  const [type, setType] = useState<string>("grid");
  const [format, setFormat] = useState<string>("SRA3");
  const [customW, setCustomW] = useState(320);
  const [customH, setCustomH] = useState(450);
  const [rows, setRows] = useState(2);
  const [cols, setCols] = useState(2);
  const [gapH, setGapH] = useState(3);
  const [gapV, setGapV] = useState(3);
  const [marginT, setMarginT] = useState(10);
  const [marginR, setMarginR] = useState(10);
  const [marginB, setMarginB] = useState(10);
  const [marginL, setMarginL] = useState(10);
  const [scale, setScale] = useState(1.0);
  const [rotation, setRotation] = useState(0);
  const [marksCrop, setMarksCrop] = useState(true);
  const [marksFold, setMarksFold] = useState(false);
  const [marksInfo, setMarksInfo] = useState(true);
  const [marksReg, setMarksReg] = useState(true);

  useEffect(() => {
    api.getSheetFormats().then(setFormats).catch(() => {});
    // Load previous imposition result if any
    api.getImposition(job.id).then((state) => {
      if (state.status === "done" && state.config) {
        const c = state.config;
        setType(c.imposition_type);
        setFormat(c.sheet_format);
        setCustomW(c.sheet_width_mm);
        setCustomH(c.sheet_height_mm);
        setRows(c.rows);
        setCols(c.cols);
        setGapH(c.gap_h_mm);
        setGapV(c.gap_v_mm);
        setMarginT(c.margin_top_mm);
        setMarginR(c.margin_right_mm);
        setMarginB(c.margin_bottom_mm);
        setMarginL(c.margin_left_mm);
        setScale(c.scale);
        setRotation(c.rotation);
        setMarksCrop(c.marks_crop);
        setMarksFold(c.marks_fold);
        setMarksInfo(c.marks_info);
        setMarksReg(c.marks_registration);
        setShowPreview(true);
      }
    }).catch(() => {});
  }, [job.id]);

  async function handleRun() {
    setRunning(true);
    setError(null);
    setShowPreview(false);

    const body: ImpositionRequestBody = {
      imposition_type: type,
      sheet_format: format,
      sheet_width_mm: customW,
      sheet_height_mm: customH,
      rows,
      cols,
      gap_h_mm: gapH,
      gap_v_mm: gapV,
      margin_top_mm: marginT,
      margin_right_mm: marginR,
      margin_bottom_mm: marginB,
      margin_left_mm: marginL,
      scale,
      rotation,
      marks_crop: marksCrop,
      marks_fold: marksFold,
      marks_info: marksInfo,
      marks_registration: marksReg,
    };

    try {
      const res = await api.startImposition(job.id, body);
      setResult(res);
      setShowPreview(true);
      onDone?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Imposice selhala.");
    } finally {
      setRunning(false);
    }
  }

  const selectedFormat = formats.find((f) => f.name === format);

  return (
    <div className="space-y-5">
      {/* Typ imposice */}
      <div>
        <p className="text-xs text-zinc-500 uppercase tracking-wider mb-2">Typ imposice</p>
        <div className="grid gap-2">
          {IMPOSITION_TYPES.map((t) => (
            <label
              key={t.value}
              className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                type === t.value
                  ? "border-blue-600 bg-blue-950/40"
                  : "border-zinc-700 hover:border-zinc-600"
              }`}
            >
              <input
                type="radio"
                name="type"
                value={t.value}
                checked={type === t.value}
                onChange={() => setType(t.value)}
                className="mt-0.5 accent-blue-500"
              />
              <div>
                <p className="text-sm font-medium text-zinc-200">{t.label}</p>
                <p className="text-xs text-zinc-500">{t.desc}</p>
              </div>
            </label>
          ))}
        </div>
      </div>

      {/* Formát archu */}
      <div>
        <p className="text-xs text-zinc-500 uppercase tracking-wider mb-2">Formát archu</p>
        <select
          value={format}
          onChange={(e) => setFormat(e.target.value)}
          className="w-full bg-zinc-800 border border-zinc-700 text-zinc-100 rounded px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
        >
          {formats.map((f) => (
            <option key={f.name} value={f.name}>
              {f.name} ({f.width_mm} × {f.height_mm} mm)
            </option>
          ))}
          <option value="custom">Vlastní rozměr</option>
        </select>

        {format === "custom" && (
          <div className="flex gap-3 mt-2">
            <NumInput label="Šířka" value={customW} onChange={setCustomW} min={50} max={2000} step={1} />
            <NumInput label="Výška" value={customH} onChange={setCustomH} min={50} max={2000} step={1} />
          </div>
        )}

        {selectedFormat && format !== "custom" && (
          <p className="text-xs text-zinc-600 mt-1">
            {selectedFormat.width_mm} × {selectedFormat.height_mm} mm
          </p>
        )}
      </div>

      {/* Grid: řádky × sloupce */}
      {type !== "booklet_saddle" && (
        <div>
          <p className="text-xs text-zinc-500 uppercase tracking-wider mb-2">Layout</p>
          <div className="flex flex-wrap gap-3">
            <NumInput label="Řádky" value={rows} onChange={(v) => setRows(Math.max(1, Math.round(v)))} min={1} max={20} step={1} unit="" />
            <NumInput label="Sloupce" value={cols} onChange={(v) => setCols(Math.max(1, Math.round(v)))} min={1} max={20} step={1} unit="" />
            <NumInput label="Mezera H" value={gapH} onChange={setGapH} />
            <NumInput label="Mezera V" value={gapV} onChange={setGapV} />
          </div>
          <p className="text-xs text-zinc-600 mt-1">
            {rows * cols} stránek na arch
          </p>
        </div>
      )}

      {/* Okraje */}
      <div>
        <p className="text-xs text-zinc-500 uppercase tracking-wider mb-2">Okraje (mm)</p>
        <div className="flex flex-wrap gap-3">
          <NumInput label="Nahoře" value={marginT} onChange={setMarginT} />
          <NumInput label="Vpravo" value={marginR} onChange={setMarginR} />
          <NumInput label="Dole" value={marginB} onChange={setMarginB} />
          <NumInput label="Vlevo" value={marginL} onChange={setMarginL} />
        </div>
      </div>

      {/* Rotace + scale */}
      <div className="flex flex-wrap gap-4">
        <div>
          <p className="text-xs text-zinc-500 mb-1">Rotace</p>
          <div className="flex gap-1">
            {ROTATIONS.map((r) => (
              <button
                key={r.value}
                onClick={() => setRotation(r.value)}
                className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                  rotation === r.value
                    ? "bg-blue-600 text-white"
                    : "bg-zinc-800 text-zinc-400 hover:bg-zinc-700"
                }`}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>
        <NumInput label="Měřítko" value={scale} onChange={setScale} min={0.1} max={2} step={0.05} unit="×" />
      </div>

      {/* Tiskové značky */}
      <div>
        <p className="text-xs text-zinc-500 uppercase tracking-wider mb-2">Tiskové značky</p>
        <div className="grid grid-cols-2 gap-2">
          <Toggle label="Ořezové" checked={marksCrop} onChange={setMarksCrop} />
          <Toggle label="Pasovací" checked={marksReg} onChange={setMarksReg} />
          <Toggle label="Info text" checked={marksInfo} onChange={setMarksInfo} />
          <Toggle label="Falc (přeložení)" checked={marksFold} onChange={setMarksFold} />
        </div>
      </div>

      {/* Run button */}
      <button
        onClick={handleRun}
        disabled={running}
        className="w-full bg-blue-600 hover:bg-blue-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white font-medium py-2.5 px-4 rounded-lg transition-colors text-sm"
      >
        {running ? "Generuji imposici…" : "Spustit imposici"}
      </button>

      {error && (
        <p className="text-red-400 text-xs bg-red-950 border border-red-800 rounded p-3">{error}</p>
      )}

      {/* Result summary */}
      {result && (
        <div className="bg-zinc-950 border border-green-800 rounded-lg p-4 space-y-1">
          <p className="text-xs font-medium text-green-400 uppercase tracking-wider mb-2">
            Hotovo — {result.processing_time_ms} ms
          </p>
          <div className="grid grid-cols-3 gap-3">
            <div>
              <p className="text-xs text-zinc-500">Archů</p>
              <p className="text-sm font-medium text-zinc-100">{result.sheet_count}</p>
            </div>
            <div>
              <p className="text-xs text-zinc-500">Stránek/arch</p>
              <p className="text-sm font-medium text-zinc-100">{result.pages_per_sheet}</p>
            </div>
            <div>
              <p className="text-xs text-zinc-500">Celkem str.</p>
              <p className="text-sm font-medium text-zinc-100">{result.total_pages_imposed}</p>
            </div>
          </div>
          {result.warnings.length > 0 && (
            <div className="mt-2 space-y-1">
              {result.warnings.map((w, i) => (
                <p key={i} className="text-xs text-amber-400">⚠ {w}</p>
              ))}
            </div>
          )}
          <a
            href={api.impositionDownloadUrl(job.id)}
            download
            className="inline-block mt-3 text-sm text-blue-400 hover:text-blue-300 transition-colors"
          >
            Stáhnout imposed PDF →
          </a>
        </div>
      )}

      {/* Sheet preview */}
      {showPreview && (
        <div>
          <p className="text-xs text-zinc-500 uppercase tracking-wider mb-2">Náhled archu</p>
          <div className="bg-zinc-950 rounded-lg overflow-hidden flex items-center justify-center min-h-[200px]">
            <img
              src={`${api.sheetPreviewUrl(job.id)}?t=${Date.now()}`}
              alt="Náhled archu"
              className="max-w-full max-h-[500px] object-contain"
              onError={(e) => {
                (e.target as HTMLImageElement).style.display = "none";
              }}
            />
          </div>
        </div>
      )}
    </div>
  );
}
