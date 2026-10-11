import { Braces, ExternalLink, FileCode2, FileText, FileType2, Trash2 } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { api, errorMessage } from "../api";
import { Alert, Button, Card, CardHeader, ConfirmButton } from "../components/ui";
import type { StepProps } from "./common";

export default function ExportStep({ session, goto }: StepProps) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const stale = !!session.generated?.stale;
  const base = `/sessions/${session.id}/files`;

  const download = async (kind: string) => {
    setBusy(kind);
    setError("");
    try {
      await api.download(`${base}/${kind}`);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy("");
    }
  };
  const remove = async () => {
    try {
      await api.deleteSession(session.id);
      navigate("/history");
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  const fmt = session.validation?.formatting;
  return (
    <div className="space-y-6">
      {error && <Alert kind="error" onClose={() => setError("")}>{error}</Alert>}
      {stale && (
        <Alert kind="warning" title="Files are out of date">
          The draft changed after these files were generated. <button type="button" className="font-medium underline" onClick={() => goto("output")}>Regenerate</button> before downloading.
        </Alert>
      )}
      {fmt && !fmt.ok && <Alert kind="warning" title="Validation reported failures">Review the Validation tab on the Generate step before sending this resume.</Alert>}

      <Card>
        <CardHeader title="Downloads" subtitle="Files are produced on this machine and served only to this browser." />
        <div className="grid gap-3 px-5 py-4 sm:grid-cols-2">
          <File icon={<FileCode2 className="h-5 w-5" />} title="LaTeX source (.tex)" detail={session.generated ? "Editable, self-contained, no custom class files." : "Generate the source first."}>
            <Button loading={busy === "tex"} disabled={!session.generated} onClick={() => void download("tex")}>Download .tex</Button>
          </File>
          <File icon={<FileType2 className="h-5 w-5" />} title="Resume (PDF)" detail={session.has_pdf && !stale ? `${fmt?.pages ?? "?"} page(s), compiled from the source above.` : "No PDF for the current source."}>
            <Button variant="primary" loading={busy === "pdf"} disabled={!session.has_pdf || stale} onClick={() => void download("pdf")}>Download PDF</Button>
          </File>
          <File icon={<FileText className="h-5 w-5" />} title="Match report (Markdown)" detail="Requirements, evidence excerpts, gaps, approved changes and document checks.">
            <Button loading={busy === "report.md"} disabled={!session.analysis} onClick={() => void download("report.md")}>Download report</Button>
          </File>
          <File icon={<Braces className="h-5 w-5" />} title="Full session record (JSON)" detail="Everything stored for this session, including the job description.">
            <Button loading={busy === "report.json"} onClick={() => void download("report.json")}>Download JSON</Button>
          </File>
        </div>
      </Card>

      <Card>
        <CardHeader title="Edit in Overleaf" />
        <div className="space-y-2 px-5 py-4 text-sm leading-relaxed text-slate-700">
          <ol className="list-decimal space-y-1 pl-5">
            <li>Download the <span className="font-mono text-xs">.tex</span> file above.</li>
            <li>In Overleaf choose <strong>New Project → Upload Project</strong> (zip the file first) or create a blank project and upload the file.</li>
            <li>Compile with pdfLaTeX, XeLaTeX or LuaLaTeX — the template supports all three.</li>
          </ol>
          <p className="text-xs text-slate-500">
            Uploading to Overleaf sends the document to a third party, and edits made there are outside CV Forge's fact checks.
          </p>
          <a href="https://www.overleaf.com/project" target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 text-xs font-medium text-accent-600 hover:underline">
            Open Overleaf <ExternalLink className="h-3 w-3" />
          </a>
        </div>
      </Card>

      <Card>
        <CardHeader title="Delete this session" subtitle="Removes the job description, report and generated files for this session. Your master resume is not affected."
          action={<ConfirmButton onConfirm={() => void remove()} icon={<Trash2 className="h-3.5 w-3.5" />}>Delete session</ConfirmButton>} />
      </Card>
    </div>
  );
}

function File({ icon, title, detail, children }: { icon: ReactNode; title: string; detail: string; children: ReactNode }) {
  return (
    <div className="flex items-center gap-3 rounded-md border border-slate-200 px-4 py-3">
      <span className="text-slate-400">{icon}</span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-slate-900">{title}</p>
        <p className="text-xs text-slate-500">{detail}</p>
      </div>
      {children}
    </div>
  );
}
