import { Check, Pencil, RefreshCw, RotateCcw, ShieldAlert, Sparkles, Undo2, X } from "lucide-react";
import { useMemo, useState } from "react";
import { ApiError, api, errorMessage } from "../api";
import { MATCH_SHORT, MATCH_TONE, SUGGESTION_LABEL, SUGGESTION_TONE } from "../components/status";
import { Alert, Badge, Button, Card, CardHeader, ConfirmButton, EmptyState, Modal, Tabs, cx } from "../components/ui";
import { useSystem } from "../system";
import type { Flag, Session, Suggestion } from "../types";
import { useAction, type StepProps } from "./common";

type Filter = "all" | "pending" | "approved" | "rejected";

/** Word-level diff (LCS) so changes are visible at a glance. */
function diffWords(a: string, b: string): { left: { t: string; changed: boolean }[]; right: { t: string; changed: boolean }[] } {
  const x = a.split(/\s+/).filter(Boolean);
  const y = b.split(/\s+/).filter(Boolean);
  const dp = Array.from({ length: x.length + 1 }, () => new Uint16Array(y.length + 1));
  for (let i = x.length - 1; i >= 0; i--)
    for (let j = y.length - 1; j >= 0; j--) dp[i][j] = x[i] === y[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const left: { t: string; changed: boolean }[] = [];
  const right: { t: string; changed: boolean }[] = [];
  let i = 0;
  let j = 0;
  while (i < x.length && j < y.length) {
    if (x[i] === y[j]) {
      left.push({ t: x[i++], changed: false });
      right.push({ t: y[j++], changed: false });
    } else if (dp[i + 1][j] >= dp[i][j + 1]) left.push({ t: x[i++], changed: true });
    else right.push({ t: y[j++], changed: true });
  }
  while (i < x.length) left.push({ t: x[i++], changed: true });
  while (j < y.length) right.push({ t: y[j++], changed: true });
  return { left, right };
}

function Diff({ words, tone }: { words: { t: string; changed: boolean }[]; tone: "removed" | "added" }) {
  if (words.length === 0) return <span className="text-slate-400">(empty)</span>;
  return (
    <>
      {words.map((w, i) => (
        <span key={i} className={w.changed ? (tone === "added" ? "rounded-sm bg-emerald-100 text-emerald-900" : "rounded-sm bg-rose-50 text-rose-700 line-through decoration-rose-300") : undefined}>
          {w.t}{" "}
        </span>
      ))}
    </>
  );
}

function Flags({ flags }: { flags: Flag[] }) {
  const shown = flags.filter((f) => f.severity !== "info");
  const info = flags.filter((f) => f.severity === "info");
  if (flags.length === 0) return null;
  return (
    <ul className="space-y-1.5">
      {[...shown, ...info].map((f) => (
        <li key={f.code} className={cx("flex gap-2 rounded-md border px-3 py-2 text-xs leading-relaxed", f.severity === "blocker" ? "border-rose-200 bg-rose-50 text-rose-900" : f.severity === "warning" ? "border-amber-200 bg-amber-50 text-amber-900" : "border-slate-200 bg-slate-50 text-slate-600")}>
          <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          <span>
            {f.message}
            {f.terms.length > 0 && <span className="ml-1 font-mono font-medium">{f.terms.join(", ")}</span>}
          </span>
        </li>
      ))}
    </ul>
  );
}

function SuggestionCard({ s, session, setSession, aiReady }: { s: Suggestion; session: Session; setSession: (x: Session) => void; aiReady: boolean }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(s.final_text ?? s.proposed_text);
  const [confirm, setConfirm] = useState(false);
  const [editFlags, setEditFlags] = useState<Flag[] | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const shown = s.status === "modified" && s.final_text ? s.final_text : s.proposed_text;
  const diff = useMemo(() => diffWords(s.original_text, shown), [s.original_text, shown]);
  const reqs = useMemo(() => new Map((session.analysis?.requirements ?? []).map((r) => [r.id, r])), [session.analysis]);
  const matches = useMemo(() => new Map((session.match?.matches ?? []).map((m) => [m.requirement_id, m])), [session.match]);
  const evidence = useMemo(() => new Map(session.evidence.map((e) => [e.id, e])), [session.evidence]);
  const decided = s.status === "accepted" || s.status === "modified" || s.status === "rejected";

  const act = async (key: string, fn: () => Promise<Session>, after?: () => void) => {
    setBusy(key);
    setError("");
    try {
      setSession(await fn());
      after?.();
    } catch (e) {
      if (e instanceof ApiError && e.code === "confirmation_required" && key === "edit") setEditFlags(e.flags ?? []);
      else setError(errorMessage(e));
    } finally {
      setBusy("");
    }
  };
  const closeEdit = () => {
    setEditing(false);
    setEditFlags(null);
    setConfirm(false);
  };

  return (
    <Card className={cx(s.status === "rejected" && "opacity-70")}>
      <header className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-5 py-3">
        <p className="min-w-0 flex-1 truncate text-sm font-medium text-slate-900">{s.target_label}</p>
        <Badge title="The model's own estimate — the checks below are what count">{s.confidence} confidence</Badge>
        {s.requires_confirmation && <Badge tone="amber"><ShieldAlert className="h-3 w-3" /> needs confirmation</Badge>}
        <Badge tone={SUGGESTION_TONE[s.status]}>{SUGGESTION_LABEL[s.status]}</Badge>
      </header>

      <div className="grid gap-px bg-slate-100 md:grid-cols-2">
        <div className="bg-white px-5 py-4">
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500">Original — from your master resume</p>
          <p className="text-sm leading-relaxed text-slate-700"><Diff words={diff.left} tone="removed" /></p>
        </div>
        <div className="bg-white px-5 py-4">
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500">{s.status === "modified" ? "Your edited wording" : "Proposed"}</p>
          {editing ? (
            <textarea className="field resize-y text-sm leading-relaxed" rows={Math.max(3, Math.ceil(text.length / 70))} value={text} onChange={(e) => { setText(e.target.value); setEditFlags(null); setConfirm(false); }} autoFocus />
          ) : (
            <p className="text-sm leading-relaxed text-slate-900"><Diff words={diff.right} tone="added" /></p>
          )}
        </div>
      </div>

      <div className="space-y-3 px-5 py-4">
        {s.reason && <p className="text-xs leading-relaxed text-slate-600"><span className="font-medium text-slate-800">Why: </span>{s.reason}</p>}

        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500">Supporting evidence</p>
            <ul className="space-y-1.5">
              {s.evidence_ids.map((id) => {
                const ev = evidence.get(id);
                return ev ? (
                  <li key={id} className="border-l-2 border-emerald-300 pl-2.5 text-xs leading-relaxed text-slate-600">
                    “{ev.text}” <span className="text-slate-400">— {ev.context}{id === s.target_id ? " (this item)" : ""}</span>
                  </li>
                ) : null;
              })}
            </ul>
          </div>
          <div>
            <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500">Related job requirements</p>
            {s.requirement_ids.length === 0 ? (
              <p className="text-xs text-slate-400">None linked — a general clarity improvement.</p>
            ) : (
              <ul className="space-y-1.5">
                {s.requirement_ids.map((id) => {
                  const r = reqs.get(id);
                  const m = matches.get(id);
                  return r ? (
                    <li key={id} className="flex items-start justify-between gap-2 text-xs leading-relaxed text-slate-600">
                      <span>{r.text}</span>
                      {m && <Badge tone={MATCH_TONE[m.status]}>{MATCH_SHORT[m.status]}</Badge>}
                    </li>
                  ) : null;
                })}
              </ul>
            )}
          </div>
        </div>

        <Flags flags={editing && editFlags ? editFlags : s.flags} />
        {error && <Alert kind="error" onClose={() => setError("")}>{error}</Alert>}

        {editing ? (
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-3">
            {editFlags && editFlags.some((f) => f.severity !== "info") ? (
              <label className="flex items-start gap-2 text-xs text-slate-700">
                <input type="checkbox" className="mt-0.5 h-4 w-4 accent-accent-700" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />
                I confirm every flagged point above is true and I can back it up.
              </label>
            ) : (
              <p className="text-xs text-slate-500">Your wording is checked against the master resume before it is saved.</p>
            )}
            <div className="flex gap-2">
              <Button size="sm" variant="ghost" onClick={closeEdit}>Cancel</Button>
              <Button size="sm" variant="primary" loading={busy === "edit"} disabled={!text.trim() || (!!editFlags?.some((f) => f.severity !== "info") && !confirm)} icon={<Check className="h-3.5 w-3.5" />}
                onClick={() => act("edit", () => api.decide(session.id, s.id, { action: "edit", text, confirm }), closeEdit)}>
                {editFlags ? "Confirm and save" : "Save edit"}
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-3">
            {!decided && s.requires_confirmation ? (
              <label className="flex items-start gap-2 text-xs text-slate-700">
                <input type="checkbox" className="mt-0.5 h-4 w-4 accent-accent-700" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />
                I confirm every flagged point above is true and I can back it up.
              </label>
            ) : (
              <span className="text-xs text-slate-500">
                {s.status === "accepted" && (s.confirmed ? "In the draft — you confirmed the flagged points." : "In the draft.")}
                {s.status === "modified" && (s.confirmed ? "Your wording is in the draft — you confirmed the flagged points." : "Your wording is in the draft.")}
                {s.status === "rejected" && "Not used. The original text stays in the draft."}
                {s.status === "pending" && "Not in the draft until you accept it."}
              </span>
            )}
            <div className="flex flex-wrap gap-2">
              {decided ? (
                <Button size="sm" loading={busy === "reset"} icon={<Undo2 className="h-3.5 w-3.5" />} onClick={() => act("reset", () => api.decide(session.id, s.id, { action: "reset" }))}>Undo decision</Button>
              ) : (
                <>
                  <Button size="sm" title={aiReady ? "Ask the model for a different wording" : "AI is not available"} disabled={!aiReady} loading={busy === "regen"} icon={<RefreshCw className="h-3.5 w-3.5" />}
                    onClick={() => act("regen", () => api.regenerate(session.id, s.id), () => setConfirm(false))}>Another wording</Button>
                  <Button size="sm" icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => { setText(s.final_text ?? s.proposed_text); setEditing(true); setConfirm(false); }}>Edit</Button>
                  <Button size="sm" variant="danger" loading={busy === "reject"} icon={<X className="h-3.5 w-3.5" />} onClick={() => act("reject", () => api.decide(session.id, s.id, { action: "reject" }))}>Reject</Button>
                  <Button size="sm" variant="primary" loading={busy === "accept"} disabled={s.requires_confirmation && !confirm} icon={<Check className="h-3.5 w-3.5" />}
                    onClick={() => act("accept", () => api.decide(session.id, s.id, { action: "accept", confirm }))}>
                    {s.requires_confirmation ? "Confirm and accept" : "Accept"}
                  </Button>
                </>
              )}
              {decided && s.status !== "rejected" && (
                <Button size="sm" icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => { setText(s.final_text ?? s.proposed_text); setEditing(true); setConfirm(false); }}>Edit</Button>
              )}
            </div>
          </div>
        )}
      </div>
    </Card>
  );
}

export default function TailorStep({ session, setSession, goto }: StepProps) {
  const { system, refresh } = useSystem();
  const { busy, error, setError, run } = useAction(setSession);
  const [filter, setFilter] = useState<Filter>("all");
  const [askConsent, setAskConsent] = useState(false);
  const [consentError, setConsentError] = useState("");

  const ai = system?.ai;
  const valid = session.suggestions.filter((s) => s.status !== "invalid");
  const invalid = session.suggestions.filter((s) => s.status === "invalid");
  const counts = session.suggestion_counts;
  const approved = counts.accepted + counts.modified;
  const decided = approved + counts.rejected;
  const list = valid.filter((s) => filter === "all" || (filter === "pending" && s.status === "pending") || (filter === "approved" && (s.status === "accepted" || s.status === "modified")) || (filter === "rejected" && s.status === "rejected"));

  const generate = () => run("generate", () => api.generateSuggestions(session.id));
  const start = () => {
    if (!ai?.consent) setAskConsent(true);
    else void generate();
  };
  const giveConsent = async () => {
    setConsentError("");
    try {
      await api.updateSettings({ ai_consent: true });
      await refresh();
      setAskConsent(false);
      void generate();
    } catch (e) {
      setConsentError(errorMessage(e));
    }
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader
          title="AI tailoring suggestions"
          subtitle={ai ? `Uses ${ai.provider} · ${ai.model}. The model may only rewrite your summary, bullets and skill order; every suggestion is checked against your master resume before you see it.` : undefined}
          action={
            <div className="flex flex-wrap gap-2">
              {decided > 0 && (
                <ConfirmButton confirmLabel="Click again to reset" icon={<RotateCcw className="h-3.5 w-3.5" />} onConfirm={() => void run("reset", () => api.resetSuggestions(session.id))}>
                  Reset draft to master
                </ConfirmButton>
              )}
              {session.suggestions.length > 0 && decided > 0 ? (
                <ConfirmButton confirmLabel="Discard decisions and regenerate" icon={<Sparkles className="h-3.5 w-3.5" />} onConfirm={start}>Regenerate all</ConfirmButton>
              ) : (
                <Button variant="primary" loading={busy === "generate"} disabled={!ai?.configured} icon={<Sparkles className="h-4 w-4" />} onClick={start}>
                  {session.suggestions.length ? "Regenerate suggestions" : "Generate suggestions"}
                </Button>
              )}
            </div>
          }
        />
        <div className="space-y-3 px-5 py-4">
          {ai && !ai.configured && (
            <Alert kind="info" title="AI-powered tailoring is unavailable">
              {ai.setup_hint} You can still continue: the Configure and Generate steps build a resume from your master content, reordered for this role.
            </Alert>
          )}
          {error && (
            <Alert kind={error.code === "ai_rate_limited" || error.code === "ai_quota_exceeded" ? "warning" : "error"} title={error.code.startsWith("ai_") ? "The AI request did not complete — nothing was changed" : undefined} onClose={() => setError(null)}>
              {error.message}
            </Alert>
          )}
          {busy === "generate" && <p className="text-sm text-slate-500" role="status">Asking the model for grounded rewrites… this usually takes 5–30 seconds.</p>}
          {session.suggestions.length > 0 && (
            <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-sm text-slate-600">
              <span><strong className="font-semibold text-slate-900">{approved}</strong> in the draft</span>
              <span><strong className="font-semibold text-slate-900">{counts.pending}</strong> pending</span>
              <span><strong className="font-semibold text-slate-900">{counts.rejected}</strong> rejected</span>
              {invalid.length > 0 && <span><strong className="font-semibold text-rose-700">{invalid.length}</strong> blocked by validation</span>}
              <span className="text-xs text-slate-400">Pending and rejected suggestions never reach the resume.</span>
            </div>
          )}
        </div>
      </Card>

      {session.suggestions.length === 0 ? (
        <Card>
          <EmptyState icon={<Sparkles className="h-6 w-6" />} title="No suggestions yet" action={<Button onClick={() => goto("configure")}>Continue without AI</Button>}>
            Generate suggestions to see side-by-side rewrites with their supporting evidence, or continue with your master content as it is.
          </EmptyState>
        </Card>
      ) : (
        <>
          <Tabs<Filter> value={filter} onChange={setFilter} tabs={[
            { id: "all", label: `All (${valid.length})` },
            { id: "pending", label: `Pending (${counts.pending})` },
            { id: "approved", label: `Accepted (${approved})` },
            { id: "rejected", label: `Rejected (${counts.rejected})` },
          ]} />
          <div className="space-y-4">
            {list.map((s) => <SuggestionCard key={`${s.id}-${s.proposed_text.length}-${s.status}`} s={s} session={session} setSession={setSession} aiReady={!!ai?.configured && !!ai?.consent} />)}
            {list.length === 0 && <p className="py-8 text-center text-sm text-slate-500">Nothing in this view.</p>}
          </div>

          {invalid.length > 0 && (
            <Card>
              <details>
                <summary className="cursor-pointer px-5 py-3.5 text-sm font-medium text-slate-800">
                  {invalid.length} suggestion{invalid.length > 1 ? "s" : ""} blocked by validation <span className="font-normal text-slate-500">— these cannot be applied</span>
                </summary>
                <ul className="divide-y divide-slate-100 border-t border-slate-100">
                  {invalid.map((s) => (
                    <li key={s.id} className="px-5 py-3 text-sm">
                      <p className="text-rose-800">{s.invalid_reason}</p>
                      <p className="mt-1 text-xs text-slate-500">{s.target_label ? `${s.target_label}: ` : ""}“{s.proposed_text}”</p>
                    </li>
                  ))}
                </ul>
              </details>
            </Card>
          )}
        </>
      )}

      {askConsent && ai && (
        <Modal
          title="Send content to Groq?"
          onClose={() => setAskConsent(false)}
          footer={
            <>
              <Button onClick={() => setAskConsent(false)}>Cancel</Button>
              <Button variant="primary" onClick={giveConsent}>I consent — generate suggestions</Button>
            </>
          }
        >
          <p className="mb-3">{ai.privacy_notice}</p>
          <p className="text-slate-500">You are asked once. You can withdraw consent at any time in Settings, and no request is ever sent unless you press a button that asks for AI output.</p>
          {consentError && <Alert kind="error" className="mt-3">{consentError}</Alert>}
        </Modal>
      )}
    </div>
  );
}
