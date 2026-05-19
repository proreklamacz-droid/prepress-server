"use client";

import { useState, useRef, DragEvent, ChangeEvent } from "react";
import { api, Job } from "@/lib/api";

interface UploadZoneProps {
  onUpload: (job: Job) => void;
}

export default function UploadZone({ onUpload }: UploadZoneProps) {
  const [dragging, setDragging] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  function formatBytes(bytes: number): string {
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  }

  function handleDragOver(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragging(true);
  }

  function handleDragLeave(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragging(false);
  }

  function handleDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) selectFile(file);
  }

  function handleInputChange(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) selectFile(file);
  }

  function selectFile(file: File) {
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setError("Prosím nahrajte soubor ve formátu PDF.");
      return;
    }
    setError(null);
    setSelectedFile(file);
  }

  async function handleUpload() {
    if (!selectedFile) return;
    setUploading(true);
    setProgress(0);
    setError(null);

    try {
      const job = await api.uploadJob(selectedFile, setProgress);
      setSelectedFile(null);
      setProgress(0);
      if (inputRef.current) inputRef.current.value = "";
      onUpload(job);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Nahrávání selhalo.");
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="space-y-3">
      <div
        className={`border-2 border-dashed rounded-xl p-10 text-center cursor-pointer transition-colors ${
          dragging
            ? "border-blue-500 bg-blue-950/30"
            : "border-zinc-700 hover:border-zinc-500"
        }`}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf"
          className="hidden"
          onChange={handleInputChange}
        />

        {selectedFile ? (
          <div className="space-y-1">
            <p className="text-zinc-100 font-medium">{selectedFile.name}</p>
            <p className="text-zinc-500 text-sm">{formatBytes(selectedFile.size)}</p>
          </div>
        ) : (
          <div className="space-y-2">
            <p className="text-zinc-400">
              Přetáhněte PDF soubor sem nebo{" "}
              <span className="text-blue-400 underline">klikněte pro výběr</span>
            </p>
            <p className="text-zinc-600 text-xs">Maximální velikost: 500 MB</p>
          </div>
        )}
      </div>

      {uploading && (
        <div className="space-y-1.5">
          <div className="flex justify-between text-xs text-zinc-500">
            <span>Nahrávám...</span>
            <span>{progress}%</span>
          </div>
          <div className="h-1.5 bg-zinc-800 rounded-full overflow-hidden">
            <div
              className="h-full bg-blue-500 transition-all duration-200"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>
      )}

      {error && (
        <p className="text-red-400 text-sm">{error}</p>
      )}

      {selectedFile && !uploading && (
        <button
          onClick={handleUpload}
          className="w-full bg-blue-600 hover:bg-blue-500 text-white font-medium py-2.5 px-4 rounded-lg transition-colors"
        >
          Nahrát a analyzovat
        </button>
      )}
    </div>
  );
}
