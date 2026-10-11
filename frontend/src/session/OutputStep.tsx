import { CheckCircle2, CircleAlert, Copy, FileCode2, FileDown, Hammer, Info, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";
import { Preflight } from "../components/Preflight";
import { Alert, Badge, Button, Card, CardHeader, EmptyState, Tabs, cx } from "../components/ui";
import { useSystem } from "../system";
import type { Check, Session, Validation } from "../types";
import { useAction, type StepProps } from "./common";

type Tab = "pdf" | "source" | "text" | "checks";
const ICON = {
  pass: <CheckCircle2 className="h-4 w-4 text-emerald-600" />,
  warn: <CircleAlert className="h-4 w-4 text-amber-500" />,
  fail: <XCircle className="h-4 w-4 text-rose-600" />,
  info: <Info className="h-4 w-4 text-slate-400" />,
};

function PdfPreview({ session }: { session: Session }) {
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  const stamp = session.compile?.compiled_at;
  useEffect(() => {
    let alive = true;
    let created = "";
    setUrl("");
    setError("");
    api
      .blob(`/sessions/${session.id}/files/pdf?inline=1`)
      .then(({ blob }) => {
        if (!alive) return;
        created = URL.createObjectURL(blob);
        setUrl(created);
      })
      .catch((e) => alive && setError(errorMessage(e)));
    return () => {
      alive = false;
      if (created) URL.revokeObjectURL(created);
    };
  }, [session.id, stamp]);
  if (error) return <Alert kind="error">{error}</Alert>;
  if (!url) return <p className="py-10 text-center text-sm text-slate-500">Loading PDF…</p>;
  return (
    <object data={url} type="application/pdf" className="h-[75vh] w-full rounded-md border border-slate-200 bg-slate-100" aria-label="Generated resume PDF">
      <p className="p-6 text-sm text-slate-600">This browser cannot show PDFs inline. Use the download button on the Export step.</p>
    </object>
  );
}

function Checks({ checks }: { checks: Check[] }) {
  const groups = checks.reduce<Record<string, Check[]>>((acc, c) => ({ ...acc, [c.category]: [...(acc[c.category] ?? []), c] }), {});
  return (
    <div className="divide-y divide-slate-100">
      {Object.entries(groups).map(([category, items]) => (
        <div key={category} className="grid gap-2 px-5 py-3.5 md:grid-cols-[11rem_1fr]">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{category}</p>
          <ul className="space-y-2.5">
            {items.map((c) => (
              <li key={c.id + c.detail} className="flex gap-2.5">
                <span className="mt-0.5 shrink-0" title={c.status}>{ICON[c.status]}</span>
                <div className="min-w-0">
                  <p className="text-sm text-slate-900">{c.label}</p>
                  {c.detail && <p className="text-xs leading-relaxed text-slate-500">{c.detail}</p>}
                  {c.items.length > 0 && (
                    <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs text-slate-700">
                      {c.items.slice(0, 12).map((it) => <li key={it} className="break-words">{it}</li>)}
                      {c.items.length > 12 && <li className="list-none text-slate-400">+ {c.items.length - 12} more</li>}
                    </ul>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

function Qualification({ q }: { q: Validation["qualification"] }) {
  const Terms = ({ items, tone }: { items: string[]; tone: string }) =>
    items.length ? (
      <div className="flex flex-wrap gap-1">{items.map((t) => <span key={t} className={cx("rounded px-1.5 py-0.5 font-mono text-[11px]", tone)}>{t}</span>)}</div>
    ) : (
      <p className="text-xs text-slate-400">None.</p>
    );
  return (
    <div className="space-y-5 px-5 py-4">
      <div className="flex flex-wrap gap-x-8 gap-y-2 text-sm">
        {q.score && <p><span className="text-2xl font-semibold tabular-nums text-slate-900">{q.score.value}%</span> <span className="text-xs text-slate-500">estimated overlap ({q.score.label.toLowerCase()})</span></p>}
        <p><span className="text-2xl font-semibold tabular-nums text-slate-900">{q.required_supported}/{q.required_total}</span> <span className="text-xs text-slate-500">must-have requirements supported by explicit evidence</span></p>
      </div>
      <div className="grid gap-5 md:grid-cols-2">
        <div>
          <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-rose-700">Unsupported requirements — genuine gaps ({q.gaps.length})</p>
          {q.gaps.length ? <ul className="list-disc space-y-1 pl-4 text-sm text-slate-700">{q.gaps.map((g) => <li key={g.id}>{g.text}</li>)}</ul> : <p className="text-xs text-slate-400">None.</p>}
        </div>
        <div>
          <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-amber-700">Potentially supported or indirect ({q.needs_confirmation.length})</p>
          {q.needs_confirmation.length ? <ul className="list-disc space-y-1 pl-4 text-sm text-slate-700">{q.needs_confirmation.map((g) => <li key={g.id}>{g.text}</li>)}</ul> : <p className="text-xs text-slate-400">None.</p>}
        </div>
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        <div><p className="mb-1.5 text-xs font-medium text-slate-600">JD terms present in this resume</p><Terms items={q.terminology.present} tone="bg-emerald-50 text-emerald-800" /></div>
        <div><p className="mb-1.5 text-xs font-medium text-slate-600">Documented in your master, not in this draft</p><Terms items={q.terminology.documented_but_not_in_this_draft} tone="bg-amber-50 text-amber-800" /></div>
        <div><p className="mb-1.5 text-xs font-medium text-slate-600">JD terms you have no evidence for</p><Terms items={q.terminology.not_documented} tone="bg-rose-50 text-rose-700" /></div>
      </div>
      <div>
        <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">Claims you confirmed manually ({q.user_confirmed_claims.length})</p>
        {q.user_confirmed_claims.length ? (
          <ul className="space-y-2">
            {q.user_confirmed_claims.map((c) => (
              <li key={c.id} className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-900">
                <span className="font-medium">{c.target}:</span> “{c.text}” — {c.flags.map((f) => f.message).join(" ")}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-slate-400">None — everything in the draft was verified automatically against your master resume.</p>
        )}
      </div>
      <p className="text-xs text-slate-500">{q.note}</p>
    </div>
  );
}

export default function OutputStep({ session, setSession, goto }: StepProps) {
  const { system } = useSystem();
  const { busy, error, setError, run } = useAction(setSession);
  const [tab, setTab] = useState<Tab>("pdf");
  const [copied, setCopied] = useState(false);

  const stale = !!session.generated?.stale;
  const canCompile = !!system?.toolchain.can_compile;
  const v = session.validation;
  const fmt = v?.formatting;
  const pending = session.suggestion_counts.pending;

  const generate = async () => {
    if (await run("generate", () => api.generateTex(session.id))) setTab("source");
  };
  const compile = async () => {
    if (await run("compile", () => api.compile(session.id))) setTab("pdf");
  };
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(session.tex ?? "");
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  };

  return (
    <div className="space-y-6">
      {error && <Alert kind="error" onClose={() => setError(null)}>{error.message}</Alert>}

      <Card>
        <CardHeader
          title="Generate and compile"
          subtitle="The LaTeX comes from a fixed ATS-oriented template filled with your approved draft. The PDF is compiled from exactly that source, with shell escape disabled."
        />
        <div className="grid gap-5 px-5 py-4 lg:grid-cols-2">
          <div className="space-y-3">
            <Step n={1} done={!!session.generated && !stale} title="LaTeX source"
              detail={session.generated ? (stale ? "Out of date — the draft or configuration changed since it was generated." : `Generated. SHA-256 ${session.generated.tex_sha256.slice(0, 12)}…`) : "Not generated yet."}>
              <Button variant={!session.generated || stale ? "primary" : "secondary"} loading={busy === "generate"} icon={<FileCode2 className="h-4 w-4" />} onClick={generate}>
                {session.generated ? "Regenerate LaTeX" : "Generate LaTeX"}
              </Button>
            </Step>
            <Step n={2} done={!!session.compile?.ok && !stale} title="PDF"
              detail={!canCompile ? "No LaTeX compiler on this machine — download the .tex and compile it elsewhere (e.g. Overleaf)." : session.compile ? (session.compile.ok ? `Compiled with ${session.compile.engine} in ${session.compile.seconds}s.` : "The last compile failed — no PDF exists for this source.") : "Not compiled yet."}>
              <Button variant={session.generated && !stale && !session.compile?.ok ? "primary" : "secondary"} loading={busy === "compile"} disabled={!session.generated || stale || !canCompile} icon={<Hammer className="h-4 w-4" />} onClick={compile}>
                {session.compile?.ok ? "Recompile PDF" : "Compile PDF"}
              </Button>
            </Step>
            {busy === "compile" && <p className="text-xs text-slate-500" role="status">Compiling… the very first Tectonic run downloads packages and can take a few minutes.</p>}
          </div>
          <div className="space-y-3">
            {system && <Preflight toolchain={system.toolchain} compact />}
            {pending > 0 && (
              <Alert kind="info">
                {pending} suggestion{pending > 1 ? "s are" : " is"} still pending and will not be included. <button type="button" className="font-medium underline" onClick={() => goto("tailor")}>Review</button>
              </Alert>
            )}
          </div>
        </div>
      </Card>

      {session.compile && !session.compile.ok && (
        <Alert kind="error" title="PDF compilation failed">
          <p>{session.compile.error} Your .tex source is preserved and can still be downloaded.</p>
          {session.compile.log_excerpt && <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded bg-black/30 p-3 font-mono text-[11px] leading-relaxed text-rose-950">{session.compile.log_excerpt}</pre>}
        </Alert>
      )}
      {stale && <Alert kind="warning" title="Source is out of date">You changed the draft or configuration after generating. Regenerate the LaTeX before compiling or exporting, so the files match what you approved.</Alert>}

      {session.generated ? (
        <Card>
          <div className="flex flex-wrap items-end justify-between gap-3 px-5 pt-3">
            <Tabs<Tab> value={tab} onChange={setTab} tabs={[
              { id: "pdf", label: "PDF preview" },
              { id: "source", label: "LaTeX source" },
              { id: "text", label: "Extracted PDF text" },
              { id: "checks", label: <>Validation {fmt?.summary && (fmt.summary.fail ? <Badge tone="red">{fmt.summary.fail} failed</Badge> : fmt.summary.warn ? <Badge tone="amber">{fmt.summary.warn} warnings</Badge> : <Badge tone="green">passed</Badge>)}</> },
            ]} />
            <Button size="sm" variant="ghost" icon={<FileDown className="h-3.5 w-3.5" />} onClick={() => goto("export")}>Go to export</Button>
          </div>
          <div className="px-5 py-4">
            {tab === "pdf" && (session.has_pdf && !stale ? <PdfPreview session={session} /> : <EmptyState title="No PDF for the current source">{canCompile ? "Compile the source to preview it here." : "Install a LaTeX compiler (see Settings) or compile the .tex on Overleaf."}</EmptyState>)}
            {tab === "source" && (
              <div>
                <div className="mb-2 flex items-center justify-between gap-2">
                  <p className="text-xs text-slate-500">Read-only view of the generated file. To edit it, download it and open it in your editor or upload it to Overleaf.</p>
                  <Button size="sm" icon={<Copy className="h-3.5 w-3.5" />} onClick={copy}>{copied ? "Copied" : "Copy"}</Button>
                </div>
                <pre className="max-h-[70vh] overflow-auto rounded-md border border-slate-200 bg-stone-50 p-4 font-mono text-[12px] leading-relaxed text-slate-800">{session.tex}</pre>
              </div>
            )}
            {tab === "text" && (fmt?.extracted_text ? (
              <div>
                <p className="mb-2 text-xs text-slate-500">This is what a text-based parser reads from the PDF, in reading order. Check that nothing is missing, merged or out of order.</p>
                <pre className="max-h-[70vh] overflow-auto whitespace-pre-wrap rounded-md border border-slate-200 bg-slate-50 p-4 font-mono text-[12px] leading-relaxed text-slate-800">{fmt.extracted_text}</pre>
              </div>
            ) : <EmptyState title="No extracted text yet">Text is extracted after a successful compile.</EmptyState>)}
            {tab === "checks" && !v && <EmptyState title="No validation report yet">Validation runs automatically after a successful compile.</EmptyState>}
          </div>
          {tab === "checks" && v && fmt && (
            <>
              <div className="border-t border-slate-100 px-5 py-3">
                <h3 className="text-sm font-semibold text-slate-900">Document and formatting checks</h3>
                <p className="text-xs text-slate-500">Can software read this file, and does it contain exactly what you approved?</p>
              </div>
              <Checks checks={fmt.checks} />
              <div className="border-t border-slate-200 px-5 py-3">
                <h3 className="text-sm font-semibold text-slate-900">Qualification match</h3>
                <p className="text-xs text-slate-500">Separate from formatting: how your documented experience relates to this job.</p>
              </div>
              <Qualification q={v.qualification} />
              <p className="border-t border-slate-100 px-5 py-3 text-xs leading-relaxed text-slate-500">{fmt.disclaimer}</p>
            </>
          )}
        </Card>
      ) : (
        <Card><EmptyState icon={<FileCode2 className="h-6 w-6" />} title="Nothing generated yet">Generate the LaTeX source to see it here, then compile it into a PDF.</EmptyState></Card>
      )}
    </div>
  );
}

function Step({ n, done, title, detail, children }: { n: number; done: boolean; title: string; detail: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-md border border-slate-200 px-4 py-3">
      <span className={cx("flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold", done ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-500")}>{done ? <CheckCircle2 className="h-4 w-4" /> : n}</span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-slate-900">{title}</p>
        <p className="text-xs text-slate-500">{detail}</p>
      </div>
      {children}
    </div>
  );
}
