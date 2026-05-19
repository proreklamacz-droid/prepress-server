"use client";

import { useState, useEffect } from "react";
import {
  api,
  ImpositionRequestBody,
  ImpositionResult,
  SheetFormat,
  Job,
} from "@/lib/api";

const IMPOSITION_TYPES = [
  { value: "grid", label: "Grid (N-up)", desc: "Více stránek na arch, řádky × sloupce" },
  { value: "booklet_saddle", label: "Brožura (sešit)", desc: "2-up saddle stitch, automatické pořadí" },
  { value: "cut_stack", label: "Cut & Stack", desc: "Každá stránka N-krát (samolepky, vizitky)" },
];

const ROTATIONS = [
  { value: 0, label: "0°" },
  { value: 90, label: "90°" },
  { value: 180, label: "180°" },
  { value: 270, label: "270°" },
];

const ALIGNS_H = [
  { value: "left", label: "←" },
  { value: "center", label: "⊕" },
  { value: "right", label: "→" },
];
const ALIGNS_V = [
  { value: "top", label: "↑" },
  { value: "center", label: "⊕" },
  { value: "bottom", label: "↓" },
];

const MARK_COLORS = [
  { value: "black", label: "Černá" },
  { value: "white", label: "Bílá" },
  { value: "custom", label: "Vlastní #" },
];

// ─── helpers ─────────────────────────────────────────────────────────────────

function NumInput({
  label,
  value,
  onChange,
  min = 0,
  max,
  step = 0.5,
  unit = "mm",
  width = "w-20",
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: number;
  unit?: string;
  width?: string;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <label className="text-xs text-zinc-500">{label}</label>
      <div className="flex items-center gap-1">
        <input
          type="number"
          className={`${width} bg-zinc-800 border border-zinc-700 text-zinc-100 rounded px-2 py-1 text-sm focus:outline-none focus:border-blue-500`}
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

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-center gap-2 cursor-pointer select-none">
      <div
        className={`w-8 h-4 rounded-full transition-colors ${checked ? "bg-blue-600" : "bg-zinc-700"}`}
        onClick={() => onChange(!checked)}
      >
        <div className={`w-3.5 h-3.5 rounded-full bg-white mt-0.5 transition-transform shadow ${checked ? "translate-x-4" : "translate-x-0.5"}`} />
      </div>
      <span className="text-sm text-zinc-300">{label}</span>
    </label>
  );
}

function BtnGroup<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div className="flex gap-1">
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${
            value === o.value ? "bg-blue-600 text-white" : "bg-zinc-800 text-zinc-400 hover:bg-zinc-700"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <p className="text-xs text-zinc-500 uppercase tracking-wider">{title}</p>
      {children}
    </div>
  );
}

// ─── main component ──────────────────────────────────────────────────────────

export default function ImpositionPanel({ job, onDone }: { job: Job; onDone?: () => void }) {
  const [formats, setFormats] = useState<SheetFormat[]>([]);
  const [result, setResult] = useState<ImpositionResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showPreview, setShowPreview] = useState(false);
  const [previewKey, setPreviewKey] = useState(0);

  // Layout
  const [type, setType] = useState("grid");
  const [format, setFormat] = useState("SRA3");
  const [customW, setCustomW] = useState(320);
  const [customH, setCustomH] = useState(450);
  const [rows, setRows] = useState(2);
  const [cols, setCols] = useState(2);
  const [gapH, setGapH] = useState(0);
  const [gapV, setGapV] = useState(0);
  const [marginT, setMarginT] = useState(10);
  const [marginR, setMarginR] = useState(10);
  const [marginB, setMarginB] = useState(10);
  const [marginL, setMarginL] = useState(10);
  const [hAlign, setHAlign] = useState<"left" | "center" | "right">("center");
  const [vAlign, setVAlign] = useState<"top" | "center" | "bottom">("center");
  const [scale, setScale] = useState(1.0);
  const [rotation, setRotation] = useState(0);

  // Marks
  const [marksEnabled, setMarksEnabled] = useState(true);
  const [marksStyle, setMarksStyle] = useState<"lines" | "frame">("lines");
  const [marksLength, setMarksLength] = useState(5.0);
  const [marksOffset, setMarksOffset] = useState(3.0);
  const [marksLineW, setMarksLineW] = useState(0.1);
  const [marksColorPreset, setMarksColorPreset] = useState<"black" | "white" | "custom">("black");
  const [marksColorHex, setMarksColorHex] = useState("#000000");
  const [marksFold, setMarksFold] = useState(false);
  const [marksInfo, setMarksInfo] = useState(true);
  const [marksReg, setMarksReg] = useState(true);

  useEffect(() => {
    api.getSheetFormats().then(setFormats).catch(() => {});
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
        setMarksEnabled(c.marks_crop);
        setMarksFold(c.marks_fold);
        setMarksInfo(c.marks_info);
        setMarksReg(c.marks_registration);
        setShowPreview(true);
      }
    }).catch(() => {});
  }, [job.id]);

  const marksColor = marksColorPreset === "custom" ? marksColorHex : marksColorPreset;

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
      h_align: hAlign,
      v_align: vAlign,
      scale,
      rotation,
      crop_marks: {
        enabled: marksEnabled,
        style: marksStyle,
        length_mm: marksLength,
        offset_mm: marksOffset,
        line_width_mm: marksLineW,
        color: marksColor,
      },
      marks_fold: marksFold,
      marks_info: marksInfo,
      marks_registration: marksReg,
    };

    try {
      const res = await api.startImposition(job.id, body);
      setResult(res);
      setPreviewKey((k) => k + 1);
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
    <div className="space-y-5 overflow-y-auto max-h-[70vh] pr-1">

      {/* Typ */}
      <Section title="Typ imposice">
        <div className="grid gap-1.5">
          {IMPOSITION_TYPES.map((t) => (
            <label
              key={t.value}
              className={`flex items-start gap-3 p-2.5 rounded-lg border cursor-pointer transition-colors ${
                type === t.value ? "border-blue-600 bg-blue-950/40" : "border-zinc-700 hover:border-zinc-600"
              }`}
            >
              <input type="radio" name="type" value={t.value} checked={type === t.value}
                onChange={() => setType(t.value)} className="mt-0.5 accent-blue-500" />
              <div>
                <p className="text-sm font-medium text-zinc-200">{t.label}</p>
                <p className="text-xs text-zinc-500">{t.desc}</p>
              </div>
            </label>
          ))}
        </div>
      </Section>

      {/* Formát */}
      <Section title="Formát archu">
        <select value={format} onChange={(e) => setFormat(e.target.value)}
          className="w-full bg-zinc-800 border border-zinc-700 text-zinc-100 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-blue-500">
          {formats.map((f) => (
            <option key={f.name} value={f.name}>{f.name} ({f.width_mm} × {f.height_mm} mm)</option>
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
          <p className="text-xs text-zinc-600">{selectedFormat.width_mm} × {selectedFormat.height_mm} mm</p>
        )}
      </Section>

      {/* Grid */}
      {type !== "booklet_saddle" && (
        <Section title="Layout">
          <div className="flex flex-wrap gap-3">
            <NumInput label="Řádky" value={rows} onChange={(v) => setRows(Math.max(1, Math.round(v)))} min={1} max={20} step={1} unit="" />
            <NumInput label="Sloupce" value={cols} onChange={(v) => setCols(Math.max(1, Math.round(v)))} min={1} max={20} step={1} unit="" />
            <NumInput label="Mezera H" value={gapH} onChange={setGapH} step={0.1} />
            <NumInput label="Mezera V" value={gapV} onChange={setGapV} step={0.1} />
          </div>
          <p className="text-xs text-zinc-600">{rows * cols} stránek na arch</p>
        </Section>
      )}

      {/* Okraje */}
      <Section title="Okraje (mm)">
        <div className="flex flex-wrap gap-3">
          <NumInput label="Nahoře" value={marginT} onChange={setMarginT} />
          <NumInput label="Vpravo" value={marginR} onChange={setMarginR} />
          <NumInput label="Dole" value={marginB} onChange={setMarginB} />
          <NumInput label="Vlevo" value={marginL} onChange={setMarginL} />
        </div>
      </Section>

      {/* Zarovnání */}
      <Section title="Pozice bloku na archu">
        <div className="flex gap-4 flex-wrap">
          <div>
            <p className="text-xs text-zinc-600 mb-1">Horizontálně</p>
            <BtnGroup options={ALIGNS_H} value={hAlign} onChange={(v) => setHAlign(v as "left" | "center" | "right")} />
          </div>
          <div>
            <p className="text-xs text-zinc-600 mb-1">Vertikálně</p>
            <BtnGroup options={ALIGNS_V} value={vAlign} onChange={(v) => setVAlign(v as "top" | "center" | "bottom")} />
          </div>
        </div>
      </Section>

      {/* Rotace + měřítko */}
      <div className="flex flex-wrap gap-4">
        <div>
          <p className="text-xs text-zinc-500 mb-1">Rotace</p>
          <BtnGroup options={ROTATIONS} value={String(rotation) as any} onChange={(v) => setRotation(Number(v))} />
        </div>
        <NumInput label="Měřítko" value={scale} onChange={setScale} min={0.1} max={2} step={0.01} unit="×" />
      </div>

      {/* Ořezové značky */}
      <Section title="Ořezové značky / rám">
        <Toggle label="Aktivní" checked={marksEnabled} onChange={setMarksEnabled} />

        {marksEnabled && (
          <div className="space-y-3 pl-2 border-l border-zinc-700 mt-2">
            {/* Styl */}
            <div>
              <p className="text-xs text-zinc-600 mb-1">Styl</p>
              <BtnGroup
                options={[{ value: "lines", label: "Čárky" }, { value: "frame", label: "Rám" }]}
                value={marksStyle}
                onChange={(v) => setMarksStyle(v as "lines" | "frame")}
              />
            </div>

            {/* Parametry čárek */}
            {marksStyle === "lines" && (
              <div className="flex flex-wrap gap-3">
                <NumInput label="Délka" value={marksLength} onChange={setMarksLength} min={0.5} max={30} step={0.5} />
                <NumInput label="Odsazení" value={marksOffset} onChange={setMarksOffset} min={0} max={20} step={0.5} />
              </div>
            )}

            {/* Tloušťka vždy */}
            <NumInput label="Tloušťka čáry" value={marksLineW} onChange={setMarksLineW} min={0.05} max={1} step={0.05} />

            {/* Barva */}
            <div>
              <p className="text-xs text-zinc-600 mb-1">Barva</p>
              <div className="flex gap-2 flex-wrap">
                {MARK_COLORS.map((c) => (
                  <button key={c.value} onClick={() => setMarksColorPreset(c.value as any)}
                    className={`px-2.5 py-1 rounded text-xs font-medium border transition-colors ${
                      marksColorPreset === c.value
                        ? "border-blue-500 bg-blue-950 text-blue-300"
                        : "border-zinc-700 bg-zinc-800 text-zinc-400 hover:border-zinc-600"
                    }`}>
                    {c.value === "black" && <span className="inline-block w-2.5 h-2.5 rounded-full bg-zinc-900 border border-zinc-600 mr-1.5 align-middle" />}
                    {c.value === "white" && <span className="inline-block w-2.5 h-2.5 rounded-full bg-white border border-zinc-600 mr-1.5 align-middle" />}
                    {c.label}
                  </button>
                ))}
              </div>
              {marksColorPreset === "custom" && (
                <div className="flex items-center gap-2 mt-2">
                  <input type="color" value={marksColorHex}
                    onChange={(e) => setMarksColorHex(e.target.value)}
                    className="w-8 h-8 rounded border border-zinc-700 cursor-pointer bg-transparent" />
                  <input type="text" value={marksColorHex}
                    onChange={(e) => setMarksColorHex(e.target.value)}
                    className="w-24 bg-zinc-800 border border-zinc-700 text-zinc-100 rounded px-2 py-1 text-xs focus:outline-none focus:border-blue-500" />
                </div>
              )}
            </div>
          </div>
        )}

        {/* Ostatní značky */}
        <div className="grid grid-cols-2 gap-2 mt-2">
          <Toggle label="Falc" checked={marksFold} onChange={setMarksFold} />
          <Toggle label="Pasovací" checked={marksReg} onChange={setMarksReg} />
          <Toggle label="Info text" checked={marksInfo} onChange={setMarksInfo} />
        </div>
      </Section>

      {/* Tlačítko */}
      <button onClick={handleRun} disabled={running}
        className="w-full bg-blue-600 hover:bg-blue-500 disabled:bg-zinc-700 disabled:text-zinc-500 text-white font-medium py-2.5 px-4 rounded-lg transition-colors text-sm">
        {running ? "Generuji imposici…" : "Spustit imposici"}
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
          <div className="grid grid-cols-3 gap-3">
            <div><p className="text-xs text-zinc-500">Archů</p><p className="text-sm font-medium text-zinc-100">{result.sheet_count}</p></div>
            <div><p className="text-xs text-zinc-500">Str./arch</p><p className="text-sm font-medium text-zinc-100">{result.pages_per_sheet}</p></div>
            <div><p className="text-xs text-zinc-500">Celkem</p><p className="text-sm font-medium text-zinc-100">{result.total_pages_imposed}</p></div>
          </div>
          {result.warnings.map((w, i) => (
            <p key={i} className="text-xs text-amber-400">⚠ {w}</p>
          ))}
          <a href={api.impositionDownloadUrl(job.id)} download
            className="inline-block mt-1 text-sm text-blue-400 hover:text-blue-300 transition-colors">
            Stáhnout imposed PDF →
          </a>
        </div>
      )}

      {/* Náhled archu */}
      {showPreview && (
        <div>
          <p className="text-xs text-zinc-500 uppercase tracking-wider mb-2">Náhled archu</p>
          <div className="bg-zinc-950 rounded-lg overflow-hidden flex items-center justify-center min-h-[160px]">
            <img
              key={previewKey}
              src={`${api.sheetPreviewUrl(job.id)}?t=${previewKey}`}
              alt="Náhled archu"
              className="max-w-full max-h-[500px] object-contain"
              onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
            />
          </div>
        </div>
      )}
    </div>
  );
}
