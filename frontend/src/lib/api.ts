// All requests go through Next.js rewrites: /api/* → backend/api/*
const BASE = "/api";

export interface PageDimension {
  page: number;
  width_mm: number;
  height_mm: number;
  media_box: number[];
  trim_box: number[] | null;
  bleed_box: number[] | null;
  crop_box: number[] | null;
}

export interface PreflightResult {
  id: string;
  job_id: string;
  created_at: string;
  fonts_ok: boolean;
  fonts_issues: { name: string; page: number; issue_type: string }[];
  resolution_ok: boolean;
  resolution_issues: { page: number; dpi: number; location: string }[];
  resolution_min_dpi: number | null;
  colorspace: "cmyk" | "rgb" | "mixed" | "unknown" | null;
  colorspace_issues: { page: number; type: string; object: string }[];
  transparency_issues: { page: number; type: string }[];
  overprint_issues: unknown[];
  ink_coverage_max: number | null;
  ink_coverage_issues: unknown[];
  hairlines_found: boolean;
  hairlines_issues: unknown[];
  spot_colors: { name: string; page: number; converted: boolean }[];
  layers_issues: unknown[];
  dtf_white_layer: boolean | null;
  dtf_transparent_bg: boolean | null;
  dtf_gamut_issues: unknown[] | null;
  llm_report_cs: string | null;
  severity: "ok" | "warning" | "error";
}

export interface Job {
  id: string;
  created_at: string;
  updated_at: string;
  source_filename: string;
  source_size_bytes: number;
  source_hash: string;
  client_type: string;
  client_id: string | null;
  status: "queued" | "processing" | "done" | "error" | "needs_attention";
  processed_on: string | null;
  processing_time_ms: number | null;
  notes: string | null;
  page_count: number | null;
  pdf_version: string | null;
  is_encrypted: boolean;
  page_dimensions: PageDimension[] | null;
  preflight?: PreflightResult | null;
}

export interface ImpositionConfig {
  id: string;
  job_id: string;
  imposition_type: "grid" | "booklet_saddle" | "cut_stack";
  sheet_format: string;
  sheet_width_mm: number;
  sheet_height_mm: number;
  rows: number;
  cols: number;
  gap_h_mm: number;
  gap_v_mm: number;
  margin_top_mm: number;
  margin_right_mm: number;
  margin_bottom_mm: number;
  margin_left_mm: number;
  scale: number;
  rotation: number;
  marks_crop: boolean;
  marks_fold: boolean;
  marks_info: boolean;
  marks_registration: boolean;
  output_path: string | null;
}

export interface ImpositionResult {
  status: string;
  job_id: string;
  output_path: string;
  sheet_count: number;
  pages_per_sheet: number;
  total_pages_imposed: number;
  sheet_width_mm: number;
  sheet_height_mm: number;
  processing_time_ms: number;
  warnings: string[];
}

export interface ImpositionState {
  status: "not_run" | "done" | "output_missing";
  job_id: string;
  config?: ImpositionConfig;
}

export interface SheetFormat {
  name: string;
  width_mm: number;
  height_mm: number;
}

export interface StorageStats {
  total_jobs: number;
  status_counts: Record<string, number>;
  disk: {
    uploads_bytes: number;
    outputs_bytes: number;
    total_bytes: number;
  };
  oldest_job: string | null;
  newest_job: string | null;
}

export interface CropMarkBody {
  enabled?: boolean;
  style?: "lines" | "frame";
  length_mm?: number;
  offset_mm?: number;
  line_width_mm?: number;
  color?: string;
}

export interface ImpositionRequestBody {
  imposition_type?: string;
  sheet_format?: string;
  sheet_width_mm?: number;
  sheet_height_mm?: number;
  rows?: number;
  cols?: number;
  gap_h_mm?: number;
  gap_v_mm?: number;
  margin_top_mm?: number;
  margin_right_mm?: number;
  margin_bottom_mm?: number;
  margin_left_mm?: number;
  h_align?: string;
  v_align?: string;
  scale?: number;
  rotation?: number;
  crop_marks?: CropMarkBody;
  marks_fold?: boolean;
  marks_info?: boolean;
  marks_registration?: boolean;
  page_range?: number[] | null;
  auto_fit?: boolean;
  back_job_id?: string;
}

export interface Preset {
  id: string;
  name: string;
  description: string | null;
  settings: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, options);
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${body}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  listJobs: (): Promise<Job[]> => request("/jobs"),

  getJob: (id: string): Promise<Job> => request(`/jobs/${id}`),

  uploadJob: (file: File, onProgress?: (pct: number) => void): Promise<Job> => {
    return new Promise((resolve, reject) => {
      const form = new FormData();
      form.append("file", file);

      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${BASE}/jobs/upload`);

      if (onProgress) {
        xhr.upload.addEventListener("progress", (e) => {
          if (e.lengthComputable) {
            onProgress(Math.round((e.loaded / e.total) * 100));
          }
        });
      }

      xhr.addEventListener("load", () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(JSON.parse(xhr.responseText) as Job);
        } else {
          reject(new Error(`${xhr.status}: ${xhr.responseText}`));
        }
      });

      xhr.addEventListener("error", () => reject(new Error("Upload selhal.")));
      xhr.send(form);
    });
  },

  deleteJob: (id: string): Promise<{ deleted: boolean; job_id: string }> =>
    request(`/jobs/${id}`, { method: "DELETE" }),

  startPreflight: (
    id: string
  ): Promise<{ status: string; job_id: string }> =>
    request(`/jobs/${id}/preflight`, { method: "POST" }),

  flattenJob: (
    id: string
  ): Promise<{ job_id: string; success: boolean; message: string }> =>
    request(`/jobs/${id}/flatten`, { method: "POST" }),

  getPreflight: (id: string): Promise<PreflightResult> =>
    request(`/jobs/${id}/preflight`),

  // Imposice
  startImposition: (id: string, body: ImpositionRequestBody): Promise<ImpositionResult> =>
    request(`/jobs/${id}/impose`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  getImposition: (id: string): Promise<ImpositionState> =>
    request(`/jobs/${id}/impose`),

  getSheetFormats: (): Promise<SheetFormat[]> =>
    request("/jobs/imposition/formats"),

  sheetPreviewUrl: (id: string): string => `${BASE}/jobs/${id}/impose/preview`,
  impositionDownloadUrl: (id: string): string => `${BASE}/jobs/${id}/impose/download`,

  // Stats & cleanup
  getStats: (): Promise<StorageStats> => request("/jobs/stats"),

  runCleanup: (olderThanDays?: number): Promise<{
    deleted_jobs: number;
    freed_bytes: number;
    older_than_days: number;
    cutoff: string;
    errors: string[];
  }> => {
    const qs = olderThanDays ? `?older_than_days=${olderThanDays}` : "";
    return request(`/jobs/cleanup${qs}`, { method: "POST" });
  },

  previewUrl: (id: string): string => `${BASE}/jobs/${id}/preview`,

  downloadUrl: (id: string): string => `${BASE}/jobs/${id}/download`,

  // Presets
  listPresets: (): Promise<Preset[]> => request("/presets"),

  createPreset: (data: { name: string; description?: string; settings: Record<string, unknown> }): Promise<Preset> =>
    request("/presets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),

  updatePreset: (id: string, data: { name?: string; description?: string; settings?: Record<string, unknown> }): Promise<Preset> =>
    request(`/presets/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),

  deletePreset: (id: string): Promise<{ deleted: boolean; id: string }> =>
    request(`/presets/${id}`, { method: "DELETE" }),
};
