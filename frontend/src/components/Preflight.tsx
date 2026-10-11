import { CheckCircle2, TriangleAlert } from "lucide-react";
import type { SystemInfo } from "../types";

/** What can this machine do right now? Shown in Settings and before compiling. */
export function Preflight({ toolchain, compact = false }: { toolchain: SystemInfo["toolchain"]; compact?: boolean }) {
  const Row = ({ ok, label, value }: { ok: boolean; label: string; value: string }) => (
    <div className="flex items-start gap-2 text-sm">
      {ok ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" /> : <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />}
      <span className="text-slate-700"><span className="font-medium text-slate-900">{label}:</span> {value}</span>
    </div>
  );
  return (
    <div className="space-y-2.5">
      <Row ok={toolchain.can_compile} label="LaTeX compiler" value={toolchain.engine ? `${toolchain.engine} (${toolchain.engine_version || "version unknown"})` : "none detected — PDFs cannot be generated on this machine yet"} />
      <Row ok={toolchain.pdftotext} label="PDF text extraction" value={toolchain.pdftotext ? "pdftotext (Poppler)" : "built-in pypdf fallback (pdftotext not installed)"} />
      {toolchain.notes.map((n) => <p key={n} className="pl-6 text-xs leading-relaxed text-slate-500">{n}</p>)}
      {!compact && toolchain.missing.map((m) => (
        <div key={m.name} className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
          <p className="font-medium">{m.name} is missing</p>
          <p className="mt-0.5 leading-relaxed">{m.purpose}</p>
          <dl className="mt-2 space-y-1">
            {Object.entries(m.install).map(([os, cmd]) => (
              <div key={os} className="flex flex-col gap-0.5 sm:flex-row sm:gap-2">
                <dt className="w-28 shrink-0 font-medium">{os}</dt>
                <dd className="break-all font-mono">{cmd}</dd>
              </div>
            ))}
          </dl>
        </div>
      ))}
    </div>
  );
}
