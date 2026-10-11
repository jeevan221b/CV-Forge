import { ArrowRight, CheckCircle2, FileText, FolderOpen, PlusCircle, ShieldCheck, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, errorMessage, formatDate } from "../api";
import { SessionStatus } from "../components/status";
import { Alert, Badge, Button, Card, CardHeader, EmptyState, PageHeader, Spinner } from "../components/ui";
import { useSystem } from "../system";
import type { ResumeSummary, SessionSummary } from "../types";

export default function Dashboard() {
  const navigate = useNavigate();
  const { system } = useSystem();
  const [resumes, setResumes] = useState<ResumeSummary[] | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([api.resumes(), api.sessions()])
      .then(([r, s]) => {
        setResumes(r);
        setSessions(s);
      })
      .catch((e) => setError(errorMessage(e)));
  }, []);

  if (error) return <Alert kind="error">{error}</Alert>;
  if (!resumes) return <Spinner />;
  const master = resumes[0];
  const drafts = sessions.filter((s) => s.status === "generated" || s.status === "compiled").length;

  return (
    <>
      <PageHeader
        title="Dashboard"
        subtitle="Tailor your resume to a job description using only what your master resume actually documents."
        action={
          <Button variant="primary" icon={<PlusCircle className="h-4 w-4" />} onClick={() => navigate("/sessions/new")}>
            New tailoring session
          </Button>
        }
      />

      <div className="grid gap-4 sm:grid-cols-3">
        <Stat icon={<FileText className="h-4 w-4" />} label="Master resumes" value={resumes.length} />
        <Stat icon={<FolderOpen className="h-4 w-4" />} label="Tailoring sessions" value={sessions.length} />
        <Stat icon={<CheckCircle2 className="h-4 w-4" />} label="Saved drafts" value={drafts} hint="Sessions with generated LaTeX" />
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-5">
        <Card className="lg:col-span-2">
          <CardHeader title="Master resume" action={<Link to="/resume" className="text-xs font-medium text-accent-600 hover:underline">Manage</Link>} />
          {master ? (
            <div className="space-y-3 px-5 py-4">
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-sm font-medium text-slate-900">{master.name}</p>
                {master.verified ? (
                  <Badge tone="green"><ShieldCheck className="h-3 w-3" /> Verified</Badge>
                ) : (
                  <Badge tone="amber"><TriangleAlert className="h-3 w-3" /> Needs review</Badge>
                )}
              </div>
              <p className="text-xs text-slate-500">
                Version {master.version} · imported from {master.source_filename} · updated {formatDate(master.updated_at)}
              </p>
              {!master.verified && (
                <p className="text-xs leading-relaxed text-slate-600">
                  Review the extracted profile and mark it verified, so tailoring starts from facts you have checked.
                </p>
              )}
              <Button size="sm" onClick={() => navigate(`/resume/${master.id}`)}>
                {master.verified ? "Open profile" : "Review profile"}
              </Button>
            </div>
          ) : (
            <EmptyState icon={<FileText className="h-6 w-6" />} title="No master resume yet" action={<Button variant="primary" onClick={() => navigate("/resume")}>Import resume</Button>}>
              Import your LaTeX resume once; every tailoring session starts from it.
            </EmptyState>
          )}
        </Card>

        <Card className="lg:col-span-3">
          <CardHeader title="Recent sessions" action={<Link to="/history" className="text-xs font-medium text-accent-600 hover:underline">View all</Link>} />
          {sessions.length === 0 ? (
            <EmptyState icon={<FolderOpen className="h-6 w-6" />} title="No sessions yet">
              Start a session, paste a job description and review the evidence-based match report.
            </EmptyState>
          ) : (
            <ul className="divide-y divide-slate-100">
              {sessions.slice(0, 5).map((s) => (
                <li key={s.id}>
                  <Link to={`/sessions/${s.id}`} className="flex items-center gap-3 px-5 py-3 hover:bg-slate-50">
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-slate-900">{s.job_title || "Untitled role"}</p>
                      <p className="truncate text-xs text-slate-500">
                        {[s.employer, formatDate(s.updated_at)].filter(Boolean).join(" · ")}
                      </p>
                    </div>
                    <SessionStatus status={s.status} />
                    <ArrowRight className="h-4 w-4 shrink-0 text-slate-300" aria-hidden />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      {system && (!system.ai.configured || !system.toolchain.can_compile) && (
        <div className="mt-6 space-y-3">
          {!system.ai.configured && (
            <Alert kind="info" title="AI tailoring is not configured">
              Importing, editing, JD analysis and matching all work without it. {system.ai.setup_hint}
            </Alert>
          )}
          {!system.toolchain.can_compile && (
            <Alert kind="warning" title="No LaTeX compiler found">
              You can still generate and download the .tex source. See <Link to="/settings" className="underline">Settings</Link> for install instructions.
            </Alert>
          )}
        </div>
      )}
    </>
  );
}

function Stat({ icon, label, value, hint }: { icon: React.ReactNode; label: string; value: number; hint?: string }) {
  return (
    <Card className="px-5 py-4">
      <div className="flex items-center gap-2 text-xs font-medium text-slate-500">
        <span className="text-slate-400">{icon}</span>
        {label}
      </div>
      <p className="mt-2 text-2xl font-semibold tabular-nums text-slate-900">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-slate-400">{hint}</p>}
    </Card>
  );
}
