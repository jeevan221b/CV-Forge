import { ArrowDown, ArrowLeft, ArrowUp, Download, Plus, Save, ShieldCheck, Trash2, TriangleAlert } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, errorMessage, formatDate } from "../api";
import { Alert, Badge, Button, Card, CardHeader, Field, PageHeader, Spinner, Tabs, Toggle } from "../components/ui";
import type { Bullet, Profile, Resume, Traced } from "../types";

const uid = (prefix: string) => `${prefix}_${Math.random().toString(16).slice(2, 10)}`;
const trace = (prefix: string): Traced => ({ id: uid(prefix), origin: "user", source_line: null, uncertain: false });
const newBullet = (): Bullet => ({ ...trace("blt"), text: "" });

function move<T>(list: T[], index: number, delta: number): T[] {
  const target = index + delta;
  if (target < 0 || target >= list.length) return list;
  const copy = [...list];
  [copy[index], copy[target]] = [copy[target], copy[index]];
  return copy;
}

function Source({ item }: { item: Traced }) {
  if (item.uncertain) return <Badge tone="amber" title="The parser was not sure about this entry">verify</Badge>;
  if (item.origin === "user") return <Badge tone="accent" title="Entered or changed by you">you</Badge>;
  return item.source_line ? (
    <Badge title="Line in the uploaded document this was read from">line {item.source_line}</Badge>
  ) : (
    <Badge title="Read from the uploaded document">document</Badge>
  );
}

function Text({ value, onChange, placeholder, rows }: { value: string; onChange: (v: string) => void; placeholder?: string; rows?: number }) {
  return rows ? (
    <textarea className="field resize-y" rows={rows} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />
  ) : (
    <input className="field" value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />
  );
}

function Bullets({ items, onChange, label = "Add bullet" }: { items: Bullet[]; onChange: (items: Bullet[]) => void; label?: string }) {
  return (
    <div className="space-y-2">
      {items.map((b, i) => (
        <div key={b.id} className="flex items-start gap-2">
          <span className="mt-2.5 text-slate-300" aria-hidden>•</span>
          <textarea
            className="field min-h-[38px] resize-y"
            rows={Math.max(1, Math.ceil(b.text.length / 90))}
            value={b.text}
            aria-label={`Bullet ${i + 1}`}
            onChange={(e) => onChange(items.map((x) => (x.id === b.id ? { ...x, text: e.target.value } : x)))}
          />
          <div className="mt-1.5 flex shrink-0 items-center gap-1">
            <Source item={b} />
            <IconButton label="Move up" onClick={() => onChange(move(items, i, -1))}><ArrowUp className="h-3.5 w-3.5" /></IconButton>
            <IconButton label="Move down" onClick={() => onChange(move(items, i, 1))}><ArrowDown className="h-3.5 w-3.5" /></IconButton>
            <IconButton label="Remove bullet" onClick={() => onChange(items.filter((x) => x.id !== b.id))}><Trash2 className="h-3.5 w-3.5" /></IconButton>
          </div>
        </div>
      ))}
      <Button size="sm" variant="ghost" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => onChange([...items, newBullet()])}>
        {label}
      </Button>
    </div>
  );
}

function IconButton({ label, onClick, children }: { label: string; onClick: () => void; children: ReactNode }) {
  return (
    <button type="button" aria-label={label} title={label} onClick={onClick} className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700">
      {children}
    </button>
  );
}

function Entry({ item, heading, onRemove, onMove, children }: { item: Traced; heading: string; onRemove: () => void; onMove: (delta: number) => void; children: ReactNode }) {
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50/60 p-4">
      <div className="mb-3 flex items-center gap-2">
        <p className="min-w-0 flex-1 truncate text-sm font-medium text-slate-800">{heading || "New entry"}</p>
        <Source item={item} />
        <IconButton label="Move up" onClick={() => onMove(-1)}><ArrowUp className="h-3.5 w-3.5" /></IconButton>
        <IconButton label="Move down" onClick={() => onMove(1)}><ArrowDown className="h-3.5 w-3.5" /></IconButton>
        <IconButton label="Remove entry" onClick={onRemove}><Trash2 className="h-3.5 w-3.5" /></IconButton>
      </div>
      {children}
    </div>
  );
}

function Section({ title, hint, onAdd, addLabel, children }: { title: string; hint?: string; onAdd?: () => void; addLabel?: string; children: ReactNode }) {
  return (
    <Card>
      <CardHeader
        title={title}
        subtitle={hint}
        action={onAdd && <Button size="sm" icon={<Plus className="h-3.5 w-3.5" />} onClick={onAdd}>{addLabel}</Button>}
      />
      <div className="space-y-3 px-5 py-4">{children}</div>
    </Card>
  );
}

const empty = <p className="text-sm text-slate-400">Nothing here yet.</p>;

export default function ResumeEditor() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [resume, setResume] = useState<Resume | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [name, setName] = useState("");
  const [verified, setVerified] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [side, setSide] = useState<"review" | "text">("review");

  const adopt = (r: Resume) => {
    setResume(r);
    setProfile(structuredClone(r.profile));
    setName(r.name);
    setVerified(r.verified);
    setDirty(false);
  };
  useEffect(() => {
    api.resume(id).then(adopt).catch((e) => setError(errorMessage(e)));
  }, [id]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  if (error && !resume) return <Alert kind="error">{error}</Alert>;
  if (!resume || !profile) return <Spinner />;

  const set = (patch: Partial<Profile>) => {
    setProfile({ ...profile, ...patch });
    setDirty(true);
    setSaved(false);
  };
  function patchList<K extends "skills" | "experience" | "projects" | "education" | "certifications" | "other">(key: K, itemId: string, patch: Partial<Profile[K][number]>) {
    set({ [key]: (profile![key] as Traced[]).map((x) => (x.id === itemId ? { ...x, ...patch } : x)) } as Partial<Profile>);
  }
  function removeFrom(key: keyof Profile, itemId: string) {
    set({ [key]: (profile![key] as Traced[]).filter((x) => x.id !== itemId) } as Partial<Profile>);
  }
  function moveIn(key: keyof Profile, index: number, delta: number) {
    set({ [key]: move(profile![key] as Traced[], index, delta) } as Partial<Profile>);
  }

  const save = async () => {
    setSaving(true);
    setError("");
    try {
      const clean = { ...profile, contact: { ...profile.contact, links: profile.contact.links.filter(Boolean) } };
      adopt(await api.saveResume(resume.id, clean, name, verified));
      setSaved(true);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  const c = profile.contact;
  return (
    <>
      <Link to="/resume" className="mb-3 inline-flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-slate-800">
        <ArrowLeft className="h-3.5 w-3.5" /> All profiles
      </Link>
      <PageHeader
        title={resume.name}
        subtitle={`Version ${resume.version} · ${resume.source_kind === "manual" ? "entered manually" : `imported from ${resume.source_filename}`} · updated ${formatDate(resume.updated_at)}`}
        action={
          <div className="flex flex-wrap items-center gap-2">
            {resume.verified && !dirty ? <Badge tone="green"><ShieldCheck className="h-3 w-3" /> Verified</Badge> : <Badge tone="amber"><TriangleAlert className="h-3 w-3" /> {dirty ? "Unsaved changes" : "Needs review"}</Badge>}
            <Button onClick={() => navigate(`/sessions/new?resume=${resume.id}`)} disabled={dirty}>Tailor with this profile</Button>
            <Button variant="primary" loading={saving} icon={<Save className="h-4 w-4" />} onClick={save}>Save profile</Button>
          </div>
        }
      />
      {error && <Alert kind="error" className="mb-4" onClose={() => setError("")}>{error}</Alert>}
      {saved && <Alert kind="success" className="mb-4" onClose={() => setSaved(false)}>Profile saved as version {resume.version}. New tailoring sessions will use it; existing sessions keep their snapshot.</Alert>}

      <div className="grid gap-6 xl:grid-cols-3">
        <div className="space-y-6 xl:col-span-2">
          <Section title="Profile name and contact">
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Profile name (only shown in CV Forge)"><Text value={name} onChange={(v) => { setName(v); setDirty(true); }} /></Field>
              <Field label="Full name"><Text value={c.name} onChange={(v) => set({ contact: { ...c, name: v } })} /></Field>
              <Field label="Email"><Text value={c.email} onChange={(v) => set({ contact: { ...c, email: v } })} /></Field>
              <Field label="Phone"><Text value={c.phone} onChange={(v) => set({ contact: { ...c, phone: v } })} /></Field>
              <Field label="Location"><Text value={c.location} onChange={(v) => set({ contact: { ...c, location: v } })} /></Field>
              <Field label="Links" hint="One per line (LinkedIn, GitHub, portfolio)">
                <Text rows={3} value={c.links.join("\n")} onChange={(v) => set({ contact: { ...c, links: v.split("\n").map((s) => s.trim()).filter((s, i, a) => s || i === a.length - 1) } })} />
              </Field>
            </div>
          </Section>

          <Section title="Professional summary">
            <Text rows={4} value={profile.summary} onChange={(v) => set({ summary: v })} placeholder="Optional. Leave empty if your resume has none." />
          </Section>

          <Section title="Skills" hint="One row per category; separate skills with commas." addLabel="Add category"
            onAdd={() => set({ skills: [...profile.skills, { ...trace("skl"), category: "", items: [] }] })}>
            {profile.skills.length === 0 && empty}
            {profile.skills.map((g, i) => (
              <div key={g.id} className="flex flex-wrap items-start gap-2 sm:flex-nowrap">
                <input className="field sm:w-44" placeholder="Category" value={g.category} aria-label="Skill category" onChange={(e) => patchList("skills", g.id, { category: e.target.value })} />
                <SkillItems value={g.items} onChange={(items) => patchList("skills", g.id, { items })} />
                <div className="mt-1.5 flex shrink-0 items-center gap-1">
                  <Source item={g} />
                  <IconButton label="Move up" onClick={() => moveIn("skills", i, -1)}><ArrowUp className="h-3.5 w-3.5" /></IconButton>
                  <IconButton label="Move down" onClick={() => moveIn("skills", i, 1)}><ArrowDown className="h-3.5 w-3.5" /></IconButton>
                  <IconButton label="Remove category" onClick={() => removeFrom("skills", g.id)}><Trash2 className="h-3.5 w-3.5" /></IconButton>
                </div>
              </div>
            ))}
          </Section>

          <Section title="Work experience" addLabel="Add position"
            onAdd={() => set({ experience: [...profile.experience, { ...trace("exp"), employer: "", title: "", location: "", dates: "", bullets: [newBullet()] }] })}>
            {profile.experience.length === 0 && empty}
            {profile.experience.map((e, i) => (
              <Entry key={e.id} item={e} heading={[e.title, e.employer].filter(Boolean).join(" — ")} onRemove={() => removeFrom("experience", e.id)} onMove={(d) => moveIn("experience", i, d)}>
                <div className="mb-3 grid gap-3 sm:grid-cols-2">
                  <Field label="Job title"><Text value={e.title} onChange={(v) => patchList("experience", e.id, { title: v })} /></Field>
                  <Field label="Employer"><Text value={e.employer} onChange={(v) => patchList("experience", e.id, { employer: v })} /></Field>
                  <Field label="Dates"><Text value={e.dates} placeholder="Mar 2022 – Present" onChange={(v) => patchList("experience", e.id, { dates: v })} /></Field>
                  <Field label="Location"><Text value={e.location} onChange={(v) => patchList("experience", e.id, { location: v })} /></Field>
                </div>
                <Bullets items={e.bullets} onChange={(bullets) => patchList("experience", e.id, { bullets })} />
              </Entry>
            ))}
          </Section>

          <Section title="Projects" addLabel="Add project"
            onAdd={() => set({ projects: [...profile.projects, { ...trace("prj"), name: "", tech: "", dates: "", link: "", bullets: [newBullet()] }] })}>
            {profile.projects.length === 0 && empty}
            {profile.projects.map((p, i) => (
              <Entry key={p.id} item={p} heading={p.name} onRemove={() => removeFrom("projects", p.id)} onMove={(d) => moveIn("projects", i, d)}>
                <div className="mb-3 grid gap-3 sm:grid-cols-2">
                  <Field label="Project name"><Text value={p.name} onChange={(v) => patchList("projects", p.id, { name: v })} /></Field>
                  <Field label="Technologies"><Text value={p.tech} onChange={(v) => patchList("projects", p.id, { tech: v })} /></Field>
                  <Field label="Dates"><Text value={p.dates} onChange={(v) => patchList("projects", p.id, { dates: v })} /></Field>
                  <Field label="Link"><Text value={p.link} onChange={(v) => patchList("projects", p.id, { link: v })} /></Field>
                </div>
                <Bullets items={p.bullets} onChange={(bullets) => patchList("projects", p.id, { bullets })} />
              </Entry>
            ))}
          </Section>

          <Section title="Education" addLabel="Add education"
            onAdd={() => set({ education: [...profile.education, { ...trace("edu"), institution: "", degree: "", location: "", dates: "", details: [] }] })}>
            {profile.education.length === 0 && empty}
            {profile.education.map((ed, i) => (
              <Entry key={ed.id} item={ed} heading={[ed.degree, ed.institution].filter(Boolean).join(" — ")} onRemove={() => removeFrom("education", ed.id)} onMove={(d) => moveIn("education", i, d)}>
                <div className="mb-3 grid gap-3 sm:grid-cols-2">
                  <Field label="Institution"><Text value={ed.institution} onChange={(v) => patchList("education", ed.id, { institution: v })} /></Field>
                  <Field label="Degree"><Text value={ed.degree} onChange={(v) => patchList("education", ed.id, { degree: v })} /></Field>
                  <Field label="Dates"><Text value={ed.dates} onChange={(v) => patchList("education", ed.id, { dates: v })} /></Field>
                  <Field label="Location"><Text value={ed.location} onChange={(v) => patchList("education", ed.id, { location: v })} /></Field>
                </div>
                <Bullets items={ed.details} label="Add detail" onChange={(details) => patchList("education", ed.id, { details })} />
              </Entry>
            ))}
          </Section>

          <Section title="Certifications" addLabel="Add certification"
            onAdd={() => set({ certifications: [...profile.certifications, { ...trace("crt"), name: "", issuer: "", date: "" }] })}>
            {profile.certifications.length === 0 && empty}
            {profile.certifications.map((ct, i) => (
              <div key={ct.id} className="flex flex-wrap items-start gap-2 lg:flex-nowrap">
                <input className="field" placeholder="Certification" aria-label="Certification name" value={ct.name} onChange={(e) => patchList("certifications", ct.id, { name: e.target.value })} />
                <input className="field lg:w-56" placeholder="Issuer" aria-label="Issuer" value={ct.issuer} onChange={(e) => patchList("certifications", ct.id, { issuer: e.target.value })} />
                <input className="field lg:w-28" placeholder="Date" aria-label="Date" value={ct.date} onChange={(e) => patchList("certifications", ct.id, { date: e.target.value })} />
                <div className="mt-1.5 flex shrink-0 items-center gap-1">
                  <Source item={ct} />
                  <IconButton label="Move up" onClick={() => moveIn("certifications", i, -1)}><ArrowUp className="h-3.5 w-3.5" /></IconButton>
                  <IconButton label="Remove certification" onClick={() => removeFrom("certifications", ct.id)}><Trash2 className="h-3.5 w-3.5" /></IconButton>
                </div>
              </div>
            ))}
          </Section>

          <Section title="Other sections" hint="Awards, publications, languages, volunteering…" addLabel="Add section"
            onAdd={() => set({ other: [...profile.other, { ...trace("oth"), title: "", items: [newBullet()] }] })}>
            {profile.other.length === 0 && empty}
            {profile.other.map((o, i) => (
              <Entry key={o.id} item={o} heading={o.title} onRemove={() => removeFrom("other", o.id)} onMove={(d) => moveIn("other", i, d)}>
                <Field label="Section title" className="mb-3"><Text value={o.title} onChange={(v) => patchList("other", o.id, { title: v })} /></Field>
                <Bullets items={o.items} label="Add item" onChange={(items) => patchList("other", o.id, { items })} />
              </Entry>
            ))}
          </Section>
        </div>

        <aside className="space-y-4 xl:sticky xl:top-6 xl:self-start">
          <Card>
            <div className="space-y-3 px-5 py-4">
              <Toggle
                checked={verified}
                onChange={(v) => { setVerified(v); setDirty(true); }}
                label="I have checked this profile against my resume"
                hint="Marks the profile as verified and clears the parser's uncertainty flags when you save."
              />
              <Button variant="primary" className="w-full" loading={saving} icon={<Save className="h-4 w-4" />} onClick={save}>Save profile</Button>
              {resume.source_kind !== "manual" && (
                <Button className="w-full" icon={<Download className="h-4 w-4" />} onClick={() => void api.download(`/resumes/${resume.id}/original`).catch((e) => setError(errorMessage(e)))}>
                  Download original upload
                </Button>
              )}
              <p className="text-xs leading-relaxed text-slate-500">
                The uploaded file is kept byte-for-byte. Saving here only changes the structured profile and creates a new version number.
              </p>
            </div>
          </Card>
          <Card>
            <div className="px-5 pt-3">
              <Tabs value={side} onChange={setSide} tabs={[{ id: "review", label: `To review (${resume.warnings.length + resume.issues.length})` }, { id: "text", label: "Extracted text" }]} />
            </div>
            <div className="max-h-[32rem] overflow-y-auto px-5 py-4">
              {side === "review" ? (
                resume.warnings.length + resume.issues.length === 0 ? (
                  <p className="text-sm text-slate-500">No parser warnings or missing fields.</p>
                ) : (
                  <div className="space-y-4 text-sm">
                    {resume.issues.length > 0 && (
                      <div>
                        <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-rose-700">Missing or invalid</p>
                        <ul className="list-disc space-y-1 pl-4 text-slate-700">{resume.issues.map((w) => <li key={w}>{w}</li>)}</ul>
                      </div>
                    )}
                    {resume.warnings.length > 0 && (
                      <div>
                        <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-amber-700">Parser notes</p>
                        <ul className="list-disc space-y-1.5 pl-4 text-slate-700">{resume.warnings.map((w) => <li key={w} className="break-words">{w}</li>)}</ul>
                      </div>
                    )}
                    <p className="text-xs text-slate-500">Fix anything wrong in the form on the left — that is the manual correction path for content the parser could not read reliably.</p>
                  </div>
                )
              ) : resume.extracted_text ? (
                <pre className="whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-slate-700">{resume.extracted_text}</pre>
              ) : (
                <p className="text-sm text-slate-500">No text was extracted from a source document.</p>
              )}
            </div>
          </Card>
        </aside>
      </div>
    </>
  );
}

/** Comma-separated editor that keeps what the user is typing (including a trailing comma). */
function SkillItems({ value, onChange }: { value: string[]; onChange: (items: string[]) => void }) {
  const [text, setText] = useState(value.join(", "));
  useEffect(() => {
    const parsed = text.split(",").map((s) => s.trim()).filter(Boolean);
    if (parsed.join("|") !== value.join("|")) setText(value.join(", "));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);
  return (
    <input
      className="field"
      placeholder="Python, SQL, …"
      aria-label="Skills"
      value={text}
      onChange={(e) => {
        setText(e.target.value);
        onChange(e.target.value.split(",").map((s) => s.trim()).filter(Boolean));
      }}
    />
  );
}
