import { ArrowDown, ArrowUp, FileCog } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { Alert, Badge, Button, Card, CardHeader, Field, Toggle, cx } from "../components/ui";
import type { ResumeConfig } from "../types";
import { useAction, type StepProps } from "./common";

const LABELS: Record<string, string> = {
  summary: "Summary",
  skills: "Skills",
  experience: "Experience",
  projects: "Projects",
  education: "Education",
  certifications: "Certifications",
  other: "Other sections",
};
const OPTIONAL: Record<string, keyof ResumeConfig> = {
  summary: "include_summary",
  projects: "include_projects",
  certifications: "include_certifications",
  other: "include_other",
};

export default function ConfigureStep({ session, setSession, goto }: StepProps) {
  const [config, setConfig] = useState<ResumeConfig>(session.config);
  const [role, setRole] = useState(session.config.target_role);
  const { busy, error, setError, run } = useAction(setSession);
  useEffect(() => {
    setConfig(session.config);
    setRole(session.config.target_role);
  }, [session.config]);

  const save = (patch: Partial<ResumeConfig>) => {
    const next = { ...config, ...patch };
    setConfig(next);
    void run("config", () => api.setConfig(session.id, next));
  };
  const moveSection = (index: number, delta: number) => {
    const order = [...config.section_order];
    const target = index + delta;
    if (target < 0 || target >= order.length) return;
    [order[index], order[target]] = [order[target], order[index]];
    save({ section_order: order });
  };

  const d = session.draft;
  const has: Record<string, boolean> = {
    summary: !!d.summary.trim(),
    skills: d.skills.length > 0,
    experience: d.experience.length > 0,
    projects: d.projects.length > 0,
    education: d.education.length > 0,
    certifications: d.certifications.length > 0,
    other: d.other.length > 0,
  };
  const allSkills = Array.from(new Set(d.skills.flatMap((g) => g.items)));
  const picked = config.prioritized_skills;
  const toggleSkill = (skill: string) => save({ prioritized_skills: picked.includes(skill) ? picked.filter((s) => s !== skill) : [...picked, skill] });
  const suggested = Array.from(new Set((session.match?.matches ?? []).flatMap((m) => m.matched_terms))).filter((t) => allSkills.some((s) => s.toLowerCase() === t.toLowerCase()));

  return (
    <div className="space-y-6">
      {error && <Alert kind="error" onClose={() => setError(null)}>{error.message}</Alert>}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="Sections" subtitle="Order and visibility only — these options never rewrite content." action={busy === "config" ? <Badge>Saving…</Badge> : <Badge tone="green">Saved</Badge>} />
          <ul className="divide-y divide-slate-100">
            {config.section_order.map((key, i) => {
              const flag = OPTIONAL[key];
              const included = flag ? (config[flag] as boolean) : true;
              return (
                <li key={key} className="flex items-center gap-3 px-5 py-2.5">
                  <span className="w-5 text-xs tabular-nums text-slate-400">{i + 1}</span>
                  <span className={cx("flex-1 text-sm", has[key] && included ? "text-slate-900" : "text-slate-400")}>
                    {LABELS[key]}
                    {!has[key] && <span className="ml-2 text-xs">(empty in this resume)</span>}
                  </span>
                  {flag ? (
                    <label className="flex items-center gap-1.5 text-xs text-slate-600">
                      <input type="checkbox" className="h-4 w-4 accent-accent-700" checked={included} disabled={!has[key]} onChange={(e) => save({ [flag]: e.target.checked } as Partial<ResumeConfig>)} />
                      Include
                    </label>
                  ) : (
                    <span className="text-xs text-slate-400">Always included</span>
                  )}
                  <button type="button" aria-label={`Move ${LABELS[key]} up`} disabled={i === 0} onClick={() => moveSection(i, -1)} className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700 disabled:opacity-30"><ArrowUp className="h-4 w-4" /></button>
                  <button type="button" aria-label={`Move ${LABELS[key]} down`} disabled={i === config.section_order.length - 1} onClick={() => moveSection(i, 1)} className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700 disabled:opacity-30"><ArrowDown className="h-4 w-4" /></button>
                </li>
              );
            })}
          </ul>
        </Card>

        <Card>
          <CardHeader title="Document" />
          <div className="space-y-4 px-5 py-4">
            <Field label="Target role" hint="Used for the PDF title and download file names. It is not printed as a job title on the resume.">
              <input className="field" value={role} onChange={(e) => setRole(e.target.value)} onBlur={() => role !== config.target_role && save({ target_role: role })} />
            </Field>
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label="Page limit">
                <select className="field" value={config.max_pages} onChange={(e) => save({ max_pages: Number(e.target.value) })}>
                  {[1, 2, 3, 4].map((n) => <option key={n} value={n}>{n} page{n > 1 ? "s" : ""}</option>)}
                </select>
              </Field>
              <Field label="Paper">
                <select className="field" value={config.paper} onChange={(e) => save({ paper: e.target.value as ResumeConfig["paper"] })}>
                  <option value="letter">US Letter</option>
                  <option value="a4">A4</option>
                </select>
              </Field>
              <Field label="Font size">
                <select className="field" value={config.font_size} onChange={(e) => save({ font_size: Number(e.target.value) as ResumeConfig["font_size"] })}>
                  {[10, 11, 12].map((n) => <option key={n} value={n}>{n} pt</option>)}
                </select>
              </Field>
            </div>
            <p className="text-xs leading-relaxed text-slate-500">
              The page limit is checked after compiling and reported as a warning if exceeded. Content is never cut or shrunk automatically — a second page is better than an unreadable or incomplete first one.
            </p>
            <Toggle checked={config.include_summary} onChange={(v) => save({ include_summary: v })} label="Include professional summary" hint={has.summary ? undefined : "Your draft has no summary, so nothing will be printed either way."} />
          </div>
        </Card>
      </div>

      <Card>
        <CardHeader
          title="Skills to list first"
          subtitle="Click skills in the order you want them to lead their category. Only skills already in your resume are offered; nothing can be added here."
          action={picked.length > 0 && <Button size="sm" variant="ghost" onClick={() => save({ prioritized_skills: [] })}>Clear</Button>}
        />
        <div className="space-y-3 px-5 py-4">
          {allSkills.length === 0 && <p className="text-sm text-slate-400">The draft has no skills.</p>}
          <div className="flex flex-wrap gap-1.5">
            {allSkills.map((skill) => {
              const rank = picked.indexOf(skill);
              return (
                <button key={skill} type="button" aria-pressed={rank >= 0} onClick={() => toggleSkill(skill)}
                  className={cx("rounded-full border px-2.5 py-1 text-xs transition-colors", rank >= 0 ? "border-accent-600 bg-accent-700 text-white" : "border-slate-300 bg-white text-slate-700 hover:border-slate-400")}>
                  {rank >= 0 && <span className="mr-1 tabular-nums opacity-70">{rank + 1}</span>}
                  {skill}
                </button>
              );
            })}
          </div>
          {suggested.length > 0 && suggested.some((s) => !picked.some((p) => p.toLowerCase() === s.toLowerCase())) && (
            <p className="text-xs text-slate-500">
              Mentioned in the job description and documented in your resume: {suggested.join(", ")}.{" "}
              <button type="button" className="font-medium text-accent-600 underline" onClick={() => save({ prioritized_skills: Array.from(new Set([...picked, ...allSkills.filter((s) => suggested.some((t) => t.toLowerCase() === s.toLowerCase()))])) })}>
                Prioritise these
              </button>
            </p>
          )}
        </div>
      </Card>

      <div className="flex justify-end">
        <Button variant="primary" icon={<FileCog className="h-4 w-4" />} onClick={() => goto("output")}>Continue to generate</Button>
      </div>
    </div>
  );
}
