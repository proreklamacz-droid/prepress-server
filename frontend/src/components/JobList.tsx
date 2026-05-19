"use client";

import type { Job } from "@/lib/api";
import JobCard from "./JobCard";

interface JobListProps {
  jobs: Job[];
  loading: boolean;
  error: string | null;
}

export default function JobList({ jobs, loading, error }: JobListProps) {
  if (loading) {
    return (
      <div className="space-y-3">
        {[1, 2, 3].map((i) => (
          <div
            key={i}
            className="bg-zinc-900 border border-zinc-800 rounded-lg h-16 animate-pulse"
          />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-950 border border-red-800 rounded-lg p-4 text-red-300 text-sm">
        Chyba při načítání: {error}
      </div>
    );
  }

  if (jobs.length === 0) {
    return (
      <div className="text-center py-16 text-zinc-600">
        <p className="text-lg">Zatím žádné soubory</p>
        <p className="text-sm mt-1">Nahrajte PDF soubor výše</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {jobs.map((job) => (
        <JobCard key={job.id} job={job} />
      ))}
    </div>
  );
}
