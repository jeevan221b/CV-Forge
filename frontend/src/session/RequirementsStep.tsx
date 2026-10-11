import { ChevronDown, Plus, RotateCcw, Save, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { MATCH_ORDER, MATCH_SHORT, MATCH_TONE } from "../components/status";
import { Alert, Badge, Button, Card, CardHeader, Field, cx } from "../components/ui";
import type { Importance, MatchStatus, ReqCategory, Requirement } from "../types";
import { useAction, type StepProps } from "./common";

const CATEGORIES: { value: ReqCategory; label: string }[] = [
  { value: "required_skill", label: "Required skill" },
  { value: "preferred_skill", label: "Preferred skill" },
  { value: "responsibility", label: "Responsibility" },
  { value: "experience", label: "Experience" },
  { value: "qualification", label: "Qualification" },
  { value: "technology", label: "Technology / tool" },
  { value: "terminology", label: "Terminology" },
];
const IMPORTANCE: { value: Importance; label: string }[] = [
  { value: "must", label: "Must have" },
  { value: "important", label: "Important" },
  { value: "nice", label: "Nice to have" },
];
const STRENGTH = { demonstrated: "shown in experience", claimed: "listed only", related: "related" } as const;
const BAR: Record<MatchStatus, string> = {
  supported: "bg-emerald-500",
  needs_confirmation: "bg-amber-400",
  indirect: "bg-sky-400",
  unsupported: "bg-rose-400",
  unclear: "bg-slate-300",
};

export default function RequirementsStep({ session, setSession }: StepProps) {
  const analysis = session.analysis!;
  const [reqs, setReqs] = useState<Requirement[]>(analysis.requirements);
  const [title, setTitle] = useState(analysis.job_title);
  const [employer, setEmployer] = useState(analysis.employer);
  const [dirty, setDirty] = useState(false);
  const [filter, setFilter] = useState<MatchStatus | "all">("all");
  const [open, setOpen] = useState<string | null>(null);
  const { busy, error, setError, run } = useAction(setSession);

  useEffect(() => {
    setReqs(session.analysis!.requirements);
    setTitle(session.analysis!.job_title);
    setEmployer(session.analysis!.employer);
    setDirty(false);
  }, [session.analysis]);

  const matches = useMemo(() => new Map((session.match?.matches ?? []).map((m) => [m.requirement_id, m])), [session.match]);
  const score = session.match?.score;
  const total = score ? MATCH_ORDER.reduce((n, k) => n + (score.counts[k] ?? 0), 0) : 0;

  const patch = (id: string, change: Partial<Requirement>) => {
    setReqs((list) => list.map((r) => (r.id === id ? { ...r, ...change } : r)));
    setDirty(true);
  };
  const add = () => {
    const id = `req_${Math.random().toString(16).slice(2, 10)}`;
    setReqs((list) => [...list, { id, text: "", category: "required_skill", importance: "important", keywords: [], origin: "user" }]);
    setOpen(id);
    setDirty(true);
  };
  const save = () => run("save", () => api.setRequirements(session.id, title, employer, reqs.filter((r) => r.text.trim())));

  const visible = reqs.filter((r) => filter === "all" || matches.get(r.id)?.status === filter);

  return (
    <div className="space-y-6">
      {error && <Alert kind="error" onClose={() => setError(null)}>{error.message}</Alert>}
      {analysis.notes.map((n) => <Alert key={n} kind="warning">{n}</Alert>)}

      {score && (
        <Card>
          <div className="grid gap-6 px-5 py-5 md:grid-cols-[auto_1fr]">
            <div className="md:w-56">
              <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Estimated overlap</p>
              <p className="mt-1 text-4xl font-semibold tabular-nums tracking-tight text-slate-900">{score.value}<span className="text-xl text-slate-400">%</span></p>
              <p className="mt-1 text-xs text-slate-500">{score.label}</p>
            </div>
            <div className="min-w-0">
              <div className="flex h-2.5 overflow-hidden rounded-full bg-slate-100" role="img" aria-label="Requirements by status">
                {MATCH_ORDER.map((k) => (score.counts[k] ? <div key={k} className={BAR[k]} style={{ width: `${(100 * score.counts[k]) / Math.max(total, 1)}%` }} /> : null))}
              </div>
              <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5">
                {MATCH_ORDER.map((k) => (
                  <button key={k} type="button" onClick={() => setFilter(filter === k ? "all" : k)} className={cx("flex items-center gap-1.5 rounded px-1 text-xs", filter === k ? "bg-slate-100 font-medium text-slate-900" : "text-slate-600 hover:text-slate-900")}>
                    <span className={cx("h-2 w-2 rounded-full", BAR[k])} />
                    {session.status_labels[k]} <span className="tabular-nums text-slate-400">{score.counts[k] ?? 0}</span>
                  </button>
                ))}
              </div>
              <details className="mt-3 text-xs text-slate-500">
                <summary className="cursor-pointer font-medium text-slate-600 hover:text-slate-900">How this number is calculated</summary>
                <p className="mt-1.5 max-w-3xl leading-relaxed">{score.explanation}</p>
              </details>
            </div>
          </div>
        </Card>
      )}

      <Card>
        <CardHeader
          title={`Requirements (${reqs.length})`}
          subtitle="Extracted from the posting. Correct anything that is wrong, delete noise, add what was missed — then re-match. A keyword in your skills list alone is never counted as proof."
          action={
            <div className="flex flex-wrap gap-2">
              {filter !== "all" && <Button size="sm" variant="ghost" onClick={() => setFilter("all")}>Show all</Button>}
              <Button size="sm" icon={<Plus className="h-3.5 w-3.5" />} onClick={add}>Add requirement</Button>
            </div>
          }
        />
        <div className="grid gap-3 border-b border-slate-100 px-5 py-4 sm:grid-cols-2">
          <Field label="Job title"><input className="field" value={title} onChange={(e) => { setTitle(e.target.value); setDirty(true); }} /></Field>
          <Field label="Employer"><input className="field" value={employer} onChange={(e) => { setEmployer(e.target.value); setDirty(true); }} /></Field>
        </div>

        <ul className="divide-y divide-slate-100">
          {visible.map((r) => {
            const m = matches.get(r.id);
            const expanded = open === r.id;
            return (
              <li key={r.id} className="px-5 py-3.5">
                <div className="flex items-start gap-3">
                  <button type="button" aria-expanded={expanded} aria-label={expanded ? "Collapse" : "Edit requirement"} onClick={() => setOpen(expanded ? null : r.id)} className="mt-0.5 rounded p-0.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700">
                    <ChevronDown className={cx("h-4 w-4 transition-transform", expanded && "rotate-180")} />
                  </button>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm text-slate-900">{r.text || <span className="text-slate-400">New requirement</span>}</p>
                    <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                      <Badge>{CATEGORIES.find((c) => c.value === r.category)?.label}</Badge>
                      <Badge tone={r.importance === "must" ? "accent" : "neutral"}>{IMPORTANCE.find((i) => i.value === r.importance)?.label}</Badge>
                      {r.origin === "user" && <Badge tone="accent">edited by you</Badge>}
                      {r.keywords.map((k) => (
                        <span key={k} className={cx("rounded px-1.5 py-0.5 font-mono text-[11px]", m?.missing_terms.includes(k) ? "bg-rose-50 text-rose-700 line-through decoration-rose-300" : m?.matched_terms.includes(k) ? "bg-emerald-50 text-emerald-800" : "bg-slate-100 text-slate-600")}>
                          {k}
                        </span>
                      ))}
                    </div>
                    {m && (m.evidence.length > 0 || m.note) && (
                      <div className="mt-2.5 space-y-1.5 border-l-2 border-slate-200 pl-3">
                        {m.evidence.map((ev) => (
                          <p key={ev.evidence_id} className="text-xs leading-relaxed text-slate-600">
                            <span className="text-slate-800">“{ev.excerpt}”</span>{" "}
                            <span className="text-slate-400">— {ev.context} · {STRENGTH[ev.strength]}</span>
                          </p>
                        ))}
                        {m.note && <p className="text-xs italic leading-relaxed text-slate-500">{m.note}</p>}
                      </div>
                    )}
                    {m?.status === "unsupported" && (
                      <p className="mt-2 text-xs text-rose-700">Genuine gap — this stays in the report and is never written into the resume as a claim.</p>
                    )}
                  </div>
                  {m && !dirty ? <Badge tone={MATCH_TONE[m.status]}>{MATCH_SHORT[m.status]}</Badge> : <Badge>Not matched yet</Badge>}
                </div>

                {expanded && (
                  <div className="ml-8 mt-3 grid gap-3 rounded-md border border-slate-200 bg-slate-50/70 p-3 sm:grid-cols-2">
                    <Field label="Requirement" className="sm:col-span-2">
                      <textarea className="field resize-y" rows={2} value={r.text} onChange={(e) => patch(r.id, { text: e.target.value })} />
                    </Field>
                    <Field label="Category">
                      <select className="field" value={r.category} onChange={(e) => patch(r.id, { category: e.target.value as ReqCategory })}>
                        {CATEGORIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
                      </select>
                    </Field>
                    <Field label="Importance">
                      <select className="field" value={r.importance} onChange={(e) => patch(r.id, { importance: e.target.value as Importance })}>
                        {IMPORTANCE.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
                      </select>
                    </Field>
                    <Field label="Terms to look for in the resume" hint="Comma-separated. These exact skills or phrases are searched for; leave empty to compare wording instead." className="sm:col-span-2">
                      <input className="field font-mono text-xs" defaultValue={r.keywords.join(", ")} key={`${r.id}-${session.updated_at}`} onChange={(e) => patch(r.id, { keywords: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} />
                    </Field>
                    <div className="sm:col-span-2">
                      <Button size="sm" variant="danger" icon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => { setReqs((list) => list.filter((x) => x.id !== r.id)); setDirty(true); }}>
                        Remove requirement
                      </Button>
                    </div>
                  </div>
                )}
              </li>
            );
          })}
          {visible.length === 0 && <li className="px-5 py-8 text-center text-sm text-slate-500">No requirements {filter === "all" ? "yet. Add one above." : "with this status."}</li>}
        </ul>

        {dirty && (
          <div className="sticky bottom-0 flex flex-wrap items-center justify-between gap-3 rounded-b-lg border-t border-amber-200 bg-amber-50 px-5 py-3">
            <p className="text-sm text-amber-900">You have unsaved changes. Statuses shown above are out of date until you re-match.</p>
            <div className="flex gap-2">
              <Button size="sm" icon={<RotateCcw className="h-3.5 w-3.5" />} onClick={() => { setReqs(analysis.requirements); setTitle(analysis.job_title); setEmployer(analysis.employer); setDirty(false); }}>Discard</Button>
              <Button size="sm" variant="primary" loading={busy === "save"} icon={<Save className="h-3.5 w-3.5" />} onClick={save}>Save and re-match</Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
