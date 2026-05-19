"use client";

import { useEffect, useState, useCallback } from "react";
import { api, Job } from "@/lib/api";
import UploadZone from "@/components/UploadZone";
import JobList from "@/components/JobList";

export default function Dashboard() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchJobs = useCallback(async () => {
    try {
      const data = await api.listJobs();
      setJobs(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Nepodařilo se načíst joby.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchJobs();
  }, [fetchJobs]);

  function handleUpload(job: Job) {
    setJobs((prev) => [job, ...prev]);
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-zinc-100">Dashboard</h1>
        <p className="text-zinc-500 mt-1 text-sm">
          Nahrajte PDF soubor pro preflight kontrolu nebo imposici
        </p>
      </div>

      <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6">
        <h2 className="text-sm font-medium text-zinc-400 uppercase tracking-wider mb-4">
          Nahrát soubor
        </h2>
        <UploadZone onUpload={handleUpload} />
      </div>

      <div>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-medium text-zinc-400 uppercase tracking-wider">
            Soubory ({jobs.length})
          </h2>
          <button
            onClick={fetchJobs}
            className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
          >
            Obnovit
          </button>
        </div>
        <JobList jobs={jobs} loading={loading} error={error} />
      </div>
    </div>
  );
}
