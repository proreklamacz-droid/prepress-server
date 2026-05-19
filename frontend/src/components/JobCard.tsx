"use client";

import { useRouter } from "next/navigation";
import type { Job } from "@/lib/api";
import StatusBadge from "./StatusBadge";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
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
  });
}

export default function JobCard({ job }: { job: Job }) {
  const router = useRouter();

  return (
    <div
      className="bg-zinc-900 border border-zinc-800 rounded-lg p-4 cursor-pointer hover:border-zinc-600 transition-colors"
      onClick={() => router.push(`/job/${job.id}`)}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="font-medium text-zinc-100 truncate" title={job.source_filename}>
            {job.source_filename}
          </p>
          <p className="text-xs text-zinc-500 mt-0.5">
            {job.page_count != null ? `${job.page_count} str.` : "—"}{" "}
            &bull; {formatBytes(job.source_size_bytes)}{" "}
            &bull; {formatDate(job.created_at)}
          </p>
        </div>
        <StatusBadge status={job.status} />
      </div>

      {job.notes && (
        <p className="mt-2 text-xs text-zinc-500 truncate" title={job.notes}>
          {job.notes}
        </p>
      )}
    </div>
  );
}
