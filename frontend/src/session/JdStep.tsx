import { ScanSearch } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import { Alert, Button, Card, CardHeader, Field } from "../components/ui";
import { useAction, type StepProps } from "./common";

export default function JdStep({ session, setSession, goto }: StepProps) {
  const [text, setText] = useState(session.jd_text);
  const [title, setTitle] = useState("");
  const [employer, setEmployer] = useState("");
  const { busy, error, setError, run } = useAction(setSession);
  const decided = session.suggestions.filter((s) => s.status !== "pending" && s.status !== "invalid").length;
  const changed = text.trim() !== session.jd_text.trim();

  const analyze = async () => {
    if (await run("jd", () => api.setJd(session.id, text, title, employer))) goto("requirements");
  };

  return (
    <Card>
      <CardHeader title="Job description" subtitle="Paste the full posting. It is analysed locally with rules — nothing is sent anywhere at this step." />
      <div className="space-y-4 px-5 py-4">
        {error && <Alert kind="error" onClose={() => setError(null)}>{error.message}</Alert>}
        <textarea
          className="field min-h-[22rem] resize-y font-mono text-[13px] leading-relaxed"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={"Paste the job description here…\n\nHeadings such as “Requirements”, “Responsibilities” and “Nice to have” help the analysis classify each line."}
          aria-label="Job description"
          spellCheck={false}
        />
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Job title (optional override)" hint="Leave empty to detect it from the posting.">
            <input className="field" value={title} onChange={(e) => setTitle(e.target.value)} placeholder={session.analysis?.job_title || "e.g. Backend Engineer"} />
          </Field>
          <Field label="Employer (optional)">
            <input className="field" value={employer} onChange={(e) => setEmployer(e.target.value)} placeholder={session.analysis?.employer || ""} />
          </Field>
        </div>
        {session.analysis && changed && (session.suggestions.length > 0 || session.generated) && (
          <Alert kind="warning" title="Re-analysing starts this session's tailoring over">
            Requirements will be re-extracted, so the current suggestions{decided ? ` (including ${decided} you already decided on)` : ""} and any generated documents for this session are discarded.
          </Alert>
        )}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-slate-500">{text.length.toLocaleString()} / 30,000 characters</p>
          <Button variant="primary" loading={busy === "jd"} disabled={!text.trim() || text.length > 30000} icon={<ScanSearch className="h-4 w-4" />} onClick={analyze}>
            {session.analysis ? "Re-analyse" : "Analyse requirements"}
          </Button>
        </div>
      </div>
    </Card>
  );
}
