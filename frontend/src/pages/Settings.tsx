import { KeyRound, Trash2 } from "lucide-react";
import { useState } from "react";
import { api, errorMessage, formatDate, getToken, setToken } from "../api";
import { Preflight } from "../components/Preflight";
import { Alert, Badge, Button, Card, CardHeader, Field, PageHeader, Spinner, Toggle } from "../components/ui";
import { useSystem } from "../system";

const RETENTION = [
  { value: 0, label: "Keep until I delete them" },
  { value: 30, label: "30 days" },
  { value: 90, label: "90 days" },
  { value: 180, label: "180 days" },
  { value: 365, label: "1 year" },
];

export default function SettingsPage() {
  const { system, refresh } = useSystem();
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [token, setTokenValue] = useState(getToken());

  if (!system) return <Spinner />;
  const run = async (fn: () => Promise<string>) => {
    setError("");
    try {
      setNotice(await fn());
      await refresh();
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  return (
    <>
      <PageHeader title="Settings" subtitle={`CV Forge ${system.version}. Secrets and model settings are read from backend/.env on the server — they are never stored in the browser.`} />
      {error && <Alert kind="error" className="mb-4" onClose={() => setError("")}>{error}</Alert>}
      {notice && <Alert kind="success" className="mb-4" onClose={() => setNotice("")}>{notice}</Alert>}

      <div className="space-y-6">
        <Card>
          <CardHeader title="AI tailoring" subtitle="Optional. Everything except suggestion generation works without it." action={system.ai.configured ? <Badge tone="green">Configured</Badge> : <Badge tone="amber">Not configured</Badge>} />
          <div className="space-y-4 px-5 py-4">
            <dl className="grid gap-x-8 gap-y-2 text-sm sm:grid-cols-2">
              <Item label="Provider" value={system.ai.provider} />
              <Item label="Model (GROQ_MODEL)" value={system.ai.model} mono />
              <Item label="API key (GROQ_API_KEY)" value={system.ai.configured ? "set on the server" : "missing"} />
              <Item label="Structured output" value={system.ai.structured_output} />
            </dl>
            {!system.ai.configured && <Alert kind="info" title="How to enable">{system.ai.setup_hint}</Alert>}
            <div className="rounded-md border border-slate-200 bg-slate-50 p-4">
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-600">What leaves this machine</p>
              <p className="text-sm leading-relaxed text-slate-700">{system.ai.privacy_notice}</p>
              <div className="mt-3">
                <Toggle
                  checked={system.ai.consent}
                  onChange={(v) => void run(async () => { await api.updateSettings({ ai_consent: v }); return v ? "Consent recorded. AI requests are now allowed." : "Consent withdrawn. No further AI requests will be sent."; })}
                  label="I consent to sending this content to Groq when I request AI suggestions"
                  hint={system.ai.consent && system.ai.consent_at ? `Given ${formatDate(system.ai.consent_at)}. Untick to withdraw.` : "Required before the first AI request. No request is ever sent automatically."}
                />
              </div>
            </div>
          </div>
        </Card>

        <Card>
          <CardHeader title="Document toolchain" subtitle="Detected on the server each time this page loads." />
          <div className="px-5 py-4"><Preflight toolchain={system.toolchain} /></div>
        </Card>

        <Card>
          <CardHeader title="Privacy and storage" subtitle="Local-first: no analytics, no telemetry, no outbound requests except AI suggestions you ask for." />
          <div className="space-y-4 px-5 py-4">
            <dl className="grid gap-x-8 gap-y-2 text-sm sm:grid-cols-2">
              <Item label="Data directory" value={system.server.data_dir} mono />
              <Item label="Stored" value={`${system.counts.resumes} master profile(s), ${system.counts.sessions} session(s)`} />
              <Item label="Listening on" value={`${system.server.host}:${system.server.port}${system.server.local_only ? " (this machine only)" : ""}`} mono />
              <Item label="Access token" value={system.server.access_token_required ? "required" : "not set"} />
            </dl>
            {!system.server.local_only && !system.server.access_token_required && (
              <Alert kind="warning" title="Reachable from the network without a token">Set CVFORGE_ACCESS_TOKEN in backend/.env, or bind to 127.0.0.1.</Alert>
            )}
            <div className="flex flex-wrap items-end gap-3">
              <Field label="Automatically delete tailoring sessions after" hint="Applies to sessions and their generated files. Master resumes are never deleted automatically." className="max-w-sm flex-1">
                <select
                  className="field"
                  value={system.retention_days}
                  onChange={(e) => void run(async () => { const r = await api.updateSettings({ retention_days: Number(e.target.value) }); return `Retention updated.${r.purged_sessions ? ` ${r.purged_sessions} expired session(s) deleted.` : ""}`; })}
                >
                  {RETENTION.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
                  {!RETENTION.some((r) => r.value === system.retention_days) && <option value={system.retention_days}>{system.retention_days} days</option>}
                </select>
              </Field>
              <Button icon={<Trash2 className="h-4 w-4" />} disabled={!system.retention_days} onClick={() => void run(async () => `${(await api.purge()).purged_sessions} expired session(s) deleted.`)}>
                Purge expired now
              </Button>
            </div>
            <p className="text-xs leading-relaxed text-slate-500">Individual uploads and sessions can be deleted at any time from Master Resume and Application History.</p>
          </div>
        </Card>

        <Card>
          <CardHeader title="This browser" subtitle="Only needed when the server was started with CVFORGE_ACCESS_TOKEN (for example when reached over Tailscale)." />
          <div className="flex flex-wrap items-end gap-3 px-5 py-4">
            <Field label="Access token" className="max-w-sm flex-1">
              <input className="field" type="password" value={token} onChange={(e) => setTokenValue(e.target.value)} placeholder="Not set" autoComplete="off" />
            </Field>
            <Button icon={<KeyRound className="h-4 w-4" />} onClick={() => { setToken(token.trim()); setNotice(token.trim() ? "Access token saved in this browser." : "Access token cleared."); void refresh(); }}>
              Save token
            </Button>
          </div>
        </Card>
      </div>
    </>
  );
}

function Item({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className={`break-words text-slate-900 ${mono ? "font-mono text-xs" : ""}`}>{value}</dd>
    </div>
  );
}
