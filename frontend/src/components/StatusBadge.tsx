import type { Job } from "@/lib/api";

const config: Record<
  Job["status"],
  { label: string; className: string; pulse?: boolean }
> = {
  queued: {
    label: "Ve frontě",
    className: "bg-zinc-700 text-zinc-300",
  },
  processing: {
    label: "Zpracovává se",
    className: "bg-blue-900 text-blue-300",
    pulse: true,
  },
  done: {
    label: "Hotovo",
    className: "bg-green-900 text-green-300",
  },
  error: {
    label: "Chyba",
    className: "bg-red-900 text-red-300",
  },
  needs_attention: {
    label: "Vyžaduje pozornost",
    className: "bg-amber-900 text-amber-300",
  },
};

export default function StatusBadge({ status }: { status: Job["status"] }) {
  const { label, className, pulse } = config[status] ?? config["queued"];
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium ${className}`}
    >
      {pulse && (
        <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />
      )}
      {label}
    </span>
  );
}
