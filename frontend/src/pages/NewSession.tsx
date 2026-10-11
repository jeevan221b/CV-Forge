import { ArrowRight, ShieldCheck, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, errorMessage, formatDate } from "../api";
import { UploadBox } from "../components/UploadBox";
import { Alert, Badge, Button, Card, CardHeader, PageHeader, Spinner, cx } from "../components/ui";
import type { ResumeSummary } from "../types";

export default function NewSession() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [resumes, setResumes] = useState<ResumeSummary[] | null>(null);
  const [selected, setSelected] = useState(params.get("resume") ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .resumes()
      .then((list) => {
        setResumes(list);
        setSelected((cur) => (list.some((r) => r.id === cur) ? cur : list[0]?.id ?? ""));
      })
      .catch((e) => setError(errorMessage(e)));
  }, []);

  const start = async () => {
    setBusy(true);
    setError("");
    try {
      const session = await api.createSession(selected);
      navigate(`/sessions/${session.id}?step=jd`);
    } catch (e) {
      setError(errorMessage(e));
      setBusy(false);
    }
  };

  const chosen = resumes?.find((r) => r.id === selected);
  return (
    <>
      <PageHeader
        title="New Tailoring Session"
        subtitle="Step 1 of 7 — choose the master resume to start from. The session works on its own copy; your master resume and other sessions are never changed."
      />
      {error && <Alert kind="error" className="mb-4" onClose={() => setError("")}>{error}</Alert>}
      {!resumes ? (
        <Spinner />
      ) : (
        <div className="space-y-6">
          {resumes.length > 0 && (
            <Card>
              <CardHeader title="Saved master profiles" />
              <ul className="divide-y divide-slate-100" role="radiogroup" aria-label="Master resume">
                {resumes.map((r) => (
                  <li key={r.id}>
                    <label className={cx("flex cursor-pointer items-center gap-3 px-5 py-3.5", selected === r.id && "bg-accent-50/60")}>
                      <input type="radio" name="resume" className="h-4 w-4 accent-accent-700" checked={selected === r.id} onChange={() => setSelected(r.id)} />
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium text-slate-900">{r.name}</p>
                        <p className="truncate text-xs text-slate-500">Version {r.version} · updated {formatDate(r.updated_at)}</p>
                      </div>
                      {r.verified ? <Badge tone="green"><ShieldCheck className="h-3 w-3" /> Verified</Badge> : <Badge tone="amber"><TriangleAlert className="h-3 w-3" /> Needs review</Badge>}
                    </label>
                  </li>
                ))}
              </ul>
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 px-5 py-4">
                <p className="text-xs text-slate-500">
                  {chosen && !chosen.verified ? (
                    <>This profile has not been verified. <Link className="font-medium text-accent-600 underline" to={`/resume/${chosen.id}`}>Review it first</Link> so tailoring is based on checked facts.</>
                  ) : (
                    "The session will snapshot this version."
                  )}
                </p>
                <Button variant="primary" loading={busy} disabled={!selected} icon={<ArrowRight className="h-4 w-4" />} onClick={start}>
                  Start session
                </Button>
              </div>
            </Card>
          )}
          <div>
            <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">{resumes.length ? "Or import another resume" : "Import a resume to begin"}</p>
            <UploadBox onCreated={(r) => navigate(`/resume/${r.id}`)} />
          </div>
        </div>
      )}
    </>
  );
}
