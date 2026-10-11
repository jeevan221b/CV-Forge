import { FolderOpen, PlusCircle, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, errorMessage, formatDate } from "../api";
import { SessionStatus } from "../components/status";
import { Alert, Button, Card, ConfirmButton, EmptyState, PageHeader, Spinner } from "../components/ui";
import type { SessionSummary } from "../types";

export default function HistoryPage() {
  const navigate = useNavigate();
  const [sessions, setSessions] = useState<SessionSummary[] | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => {
    api.sessions().then(setSessions).catch((e) => setError(errorMessage(e)));
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  const remove = async (id: string) => {
    try {
      await api.deleteSession(id);
      load();
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  return (
    <>
      <PageHeader
        title="Application History"
        subtitle="Every tailoring session keeps its job description, match report, approved changes and generated documents."
        action={<Button variant="primary" icon={<PlusCircle className="h-4 w-4" />} onClick={() => navigate("/sessions/new")}>New session</Button>}
      />
      {error && <Alert kind="error" className="mb-4" onClose={() => setError("")}>{error}</Alert>}
      <Card>
        {!sessions ? (
          <Spinner />
        ) : sessions.length === 0 ? (
          <EmptyState icon={<FolderOpen className="h-6 w-6" />} title="No sessions yet">Sessions appear here once you start tailoring.</EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead className="border-b border-slate-200 text-xs font-medium text-slate-500">
                <tr>
                  <th className="px-5 py-3 font-medium">Role</th>
                  <th className="px-3 py-3 font-medium">Master resume</th>
                  <th className="px-3 py-3 font-medium">Status</th>
                  <th className="px-3 py-3 font-medium" title="Heuristic estimate of documented overlap — not an ATS score">Est. overlap</th>
                  <th className="px-3 py-3 font-medium">Created</th>
                  <th className="px-5 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {sessions.map((s) => (
                  <tr key={s.id} className="hover:bg-slate-50/70">
                    <td className="px-5 py-3">
                      <Link to={`/sessions/${s.id}`} className="font-medium text-slate-900 hover:text-accent-700 hover:underline">{s.job_title || "Untitled role"}</Link>
                      {s.employer && <p className="text-xs text-slate-500">{s.employer}</p>}
                    </td>
                    <td className="px-3 py-3 text-slate-600">{s.resume_name} <span className="text-xs text-slate-400">v{s.resume_version}</span></td>
                    <td className="px-3 py-3"><SessionStatus status={s.status} /></td>
                    <td className="px-3 py-3 tabular-nums text-slate-600">{s.match_score == null ? "—" : `${s.match_score}%`}</td>
                    <td className="whitespace-nowrap px-3 py-3 text-xs text-slate-500">{formatDate(s.created_at)}</td>
                    <td className="px-5 py-3 text-right">
                      <ConfirmButton onConfirm={() => void remove(s.id)} icon={<Trash2 className="h-3.5 w-3.5" />}>Delete</ConfirmButton>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
