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

  getPreflight: (id: string): Promise<PreflightResult> =>
    request(`/jobs/${id}/preflight`),

  previewUrl: (id: string): string => `${BASE}/jobs/${id}/preview`,

  downloadUrl: (id: string): string => `${BASE}/jobs/${id}/download`,
};
