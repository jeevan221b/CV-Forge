import { ArrowLeft, ArrowRight, Check } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, errorMessage, formatDate } from "../api";
import { SessionStatus } from "../components/status";
import { Alert, Badge, Button, Card, CardHeader, Spinner, cx } from "../components/ui";
import { STEPS, type StepId } from "../session/common";
import ConfigureStep from "../session/ConfigureStep";
import ExportStep from "../session/ExportStep";
import JdStep from "../session/JdStep";
import OutputStep from "../session/OutputStep";
import RequirementsStep from "../session/RequirementsStep";
import TailorStep from "../session/TailorStep";
import type { Session } from "../types";

function defaultStep(s: Session): StepId {
  if (!s.analysis) return "jd";
  if (s.generated) return "output";
  if (s.suggestions.length) return "tailor";
  return "requirements";
}

function isDone(step: StepId, s: Session): boolean {
  switch (step) {
    case "resume":
      return true;
    case "jd":
      return !!s.analysis;
    case "requirements":
      return !!s.match;
    case "tailor":
      return s.suggestions.some((x) => x.status === "accepted" || x.status === "modified" || x.status === "rejected");
    case "configure":
      return !!s.generated;
    case "output":
      return !!s.compile?.ok && !s.generated?.stale;
    case "export":
      return false;
  }
}

export default function SessionPage() {
  const { id = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const [session, setSession] = useState<Session | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setSession(null);
    api.session(id).then(setSession).catch((e) => setError(errorMessage(e)));
  }, [id]);

  const goto = useCallback(
    (step: StepId) => {
      setParams({ step }, { replace: false });
      window.scrollTo(0, 0);
    },
    [setParams],
  );

  if (error) return <Alert kind="error">{error} <Link to="/history" className="underline">Back to history</Link></Alert>;
  if (!session) return <Spinner />;

  const requested = params.get("step") as StepId | null;
  const step: StepId = STEPS.some((s) => s.id === requested) ? requested! : defaultStep(session);
  const needsJd = !session.analysis && (step === "requirements" || step === "tailor");
  const index = STEPS.findIndex((s) => s.id === step);
  const props = { session, setSession, goto };

  return (
    <>
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="truncate text-xl font-semibold tracking-tight text-slate-900">
            {session.job_title || "New tailoring session"}
            {session.employer && <span className="font-normal text-slate-500"> · {session.employer}</span>}
          </h1>
          <p className="mt-1 text-xs text-slate-500">
            From “{session.resume_name}” version {session.resume_version} · started {formatDate(session.created_at)}
          </p>
        </div>
        <SessionStatus status={session.status} />
      </div>

      <nav aria-label="Steps" className="mb-6 overflow-x-auto">
        <ol className="flex min-w-max items-center gap-1 rounded-lg border border-slate-200 bg-white p-1.5">
          {STEPS.map((s, i) => {
            const active = s.id === step;
            const done = isDone(s.id, session);
            return (
              <li key={s.id}>
                <button
                  type="button"
                  title={s.covers}
                  aria-current={active ? "step" : undefined}
                  onClick={() => goto(s.id)}
                  className={cx(
                    "flex items-center gap-2 rounded-md px-3 py-1.5 text-sm transition-colors",
                    active ? "bg-accent-700 font-medium text-white" : "text-slate-600 hover:bg-slate-100",
                  )}
                >
                  <span
                    className={cx(
                      "flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-semibold",
                      active ? "bg-black/20 text-white" : done ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-500",
                    )}
                  >
                    {done && !active ? <Check className="h-3 w-3" /> : i + 1}
                  </span>
                  {s.label}
                </button>
              </li>
            );
          })}
        </ol>
      </nav>

      {needsJd ? (
        <Alert kind="info" title="Add a job description first">
          This step needs an analysed job description. <button type="button" className="font-medium underline" onClick={() => goto("jd")}>Go to Job description</button>
        </Alert>
      ) : (
        <>
          {step === "resume" && <ResumeStep session={session} />}
          {step === "jd" && <JdStep {...props} />}
          {step === "requirements" && <RequirementsStep {...props} />}
          {step === "tailor" && <TailorStep {...props} />}
          {step === "configure" && <ConfigureStep {...props} />}
          {step === "output" && <OutputStep {...props} />}
          {step === "export" && <ExportStep {...props} />}
        </>
      )}

      <div className="mt-8 flex items-center justify-between border-t border-slate-200 pt-4">
        <Button variant="ghost" disabled={index === 0} icon={<ArrowLeft className="h-4 w-4" />} onClick={() => goto(STEPS[index - 1].id)}>
          {index > 0 ? STEPS[index - 1].label : "Back"}
        </Button>
        {index < STEPS.length - 1 && (
          <Button onClick={() => goto(STEPS[index + 1].id)}>
            {STEPS[index + 1].label} <ArrowRight className="h-4 w-4" />
          </Button>
        )}
      </div>
    </>
  );
}

function ResumeStep({ session }: { session: Session }) {
  const p = session.profile;
  const bullets = p.experience.reduce((n, e) => n + e.bullets.length, 0) + p.projects.reduce((n, e) => n + e.bullets.length, 0);
  return (
    <Card>
      <CardHeader
        title="Master resume snapshot"
        subtitle="Taken when this session was created. Edits to the master resume afterwards do not change this session, and nothing here changes the master."
        action={<Badge tone="accent">Version {session.resume_version}</Badge>}
      />
      <div className="grid gap-6 px-5 py-4 sm:grid-cols-2">
        <dl className="space-y-2 text-sm">
          <Row label="Profile" value={session.resume_name} />
          <Row label="Candidate" value={p.contact.name || "—"} />
          <Row label="Contact" value={[p.contact.email, p.contact.phone, p.contact.location].filter(Boolean).join(" · ") || "—"} />
          <Row label="Contents" value={`${p.experience.length} positions, ${p.projects.length} projects, ${p.education.length} education, ${bullets} bullets, ${p.skills.reduce((n, g) => n + g.items.length, 0)} skills`} />
        </dl>
        <div className="space-y-2 text-sm text-slate-600">
          {p.experience.map((e) => (
            <p key={e.id}>
              <span className="font-medium text-slate-900">{e.title}</span>
              {e.employer && `, ${e.employer}`} <span className="text-xs text-slate-400">{e.dates}</span>
            </p>
          ))}
          {session.resume_id ? (
            <p className="pt-2 text-xs text-slate-500">
              Need to fix a fact? <Link className="font-medium text-accent-600 underline" to={`/resume/${session.resume_id}`}>Edit the master profile</Link>, then start a new session.
            </p>
          ) : (
            <p className="pt-2 text-xs text-slate-500">The master profile this session came from has since been deleted; the snapshot remains.</p>
          )}
        </div>
      </div>
    </Card>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-3">
      <dt className="w-24 shrink-0 text-xs text-slate-500">{label}</dt>
      <dd className="min-w-0 break-words text-slate-900">{value}</dd>
    </div>
  );
}
