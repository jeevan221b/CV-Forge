import { FileText, ShieldCheck, Trash2, TriangleAlert } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, errorMessage, formatDate } from "../api";
import { UploadBox } from "../components/UploadBox";
import { Alert, Badge, Card, CardHeader, ConfirmButton, EmptyState, PageHeader, Spinner } from "../components/ui";
import type { ResumeSummary } from "../types";

export default function MasterResume() {
  const navigate = useNavigate();
  const [resumes, setResumes] = useState<ResumeSummary[] | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    api.resumes().then(setResumes).catch((e) => setError(errorMessage(e)));
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  const remove = async (id: string) => {
    try {
      await api.deleteResume(id);
      load();
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  return (
    <>
      <PageHeader
        title="Master Resume"
        subtitle="Your master resume is the single source of facts. Import it once, verify the extracted profile, and reuse it for every application."
      />
      <UploadBox onCreated={(r) => navigate(`/resume/${r.id}`)} />
      {error && <Alert kind="error" className="mt-4" onClose={() => setError("")}>{error}</Alert>}

      <Card className="mt-6">
        <CardHeader title="Saved profiles" subtitle="Deleting a profile removes the uploaded document too. Existing sessions keep their own snapshot." />
        {!resumes ? (
          <Spinner />
        ) : resumes.length === 0 ? (
          <EmptyState icon={<FileText className="h-6 w-6" />} title="Nothing imported yet">
            A fictional sample resume lives in <span className="font-mono text-xs">backend/samples/sample_resume.tex</span> if you want to try the workflow first.
          </EmptyState>
        ) : (
          <ul className="divide-y divide-slate-100">
            {resumes.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center gap-3 px-5 py-3.5">
                <div className="min-w-0 flex-1">
                  <Link to={`/resume/${r.id}`} className="text-sm font-medium text-slate-900 hover:text-accent-700 hover:underline">
                    {r.name}
                  </Link>
                  <p className="truncate text-xs text-slate-500">
                    Version {r.version} · {r.source_kind === "manual" ? "entered manually" : r.source_filename} · updated {formatDate(r.updated_at)}
                  </p>
                </div>
                {r.verified ? (
                  <Badge tone="green"><ShieldCheck className="h-3 w-3" /> Verified</Badge>
                ) : (
                  <Badge tone="amber"><TriangleAlert className="h-3 w-3" /> Needs review</Badge>
                )}
                <ConfirmButton onConfirm={() => void remove(r.id)} icon={<Trash2 className="h-3.5 w-3.5" />}>
                  Delete
                </ConfirmButton>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}
