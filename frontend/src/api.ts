import type { Profile, Requirement, Resume, ResumeConfig, ResumeSummary, Session, SessionSummary, SystemInfo, Flag } from "./types";

// All requests go to the CV Forge backend. The frontend never contacts the AI provider.
const TOKEN_KEY = "cvforge_access_token";

export class ApiError extends Error {
  status: number;
  code: string;
  flags?: Flag[];
  retryAfter?: number;
  constructor(status: number, code: string, message: string, extra: { flags?: Flag[]; retry_after?: number } = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.flags = extra.flags;
    this.retryAfter = extra.retry_after;
  }
}

export const getToken = () => {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
};
export const setToken = (value: string) => {
  try {
    if (value) localStorage.setItem(TOKEN_KEY, value);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable */
  }
};

let onUnauthorized: (() => void) | null = null;
export const setUnauthorizedHandler = (fn: () => void) => {
  onUnauthorized = fn;
};

async function request(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let res: Response;
  try {
    res = await fetch(`/api${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "network", "Cannot reach the CV Forge backend. Is it running?");
  }
  if (!res.ok) {
    let detail: any = null;
    try {
      detail = (await res.json()).detail;
    } catch {
      /* not JSON */
    }
    if (res.status === 401) onUnauthorized?.();
    const message = typeof detail === "string" ? detail : detail?.message ?? `Request failed (HTTP ${res.status}).`;
    throw new ApiError(res.status, detail?.code ?? "error", message, detail ?? {});
  }
  return res;
}

async function json<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const res = await request(path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return res.json() as Promise<T>;
}

export type DecisionBody = { action: "accept" | "reject" | "edit" | "reset"; text?: string; confirm?: boolean };

export const api = {
  system: () => json<SystemInfo>("/system"),
  updateSettings: (body: { ai_consent?: boolean; retention_days?: number }) =>
    json<{ ai_consent: boolean; retention_days: number; purged_sessions: number }>("/settings", "PUT", body),
  purge: () => json<{ purged_sessions: number }>("/settings/purge", "POST"),

  resumes: () => json<ResumeSummary[]>("/resumes"),
  resume: (id: string) => json<Resume>(`/resumes/${id}`),
  uploadResume: async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return (await request("/resumes", { method: "POST", body: form })).json() as Promise<Resume>;
  },
  createManualResume: (name: string) => json<Resume>("/resumes/manual", "POST", { name }),
  saveResume: (id: string, profile: Profile, name: string, verified: boolean) =>
    json<Resume>(`/resumes/${id}`, "PUT", { profile, name, verified }),
  deleteResume: (id: string) => json<{ deleted: boolean }>(`/resumes/${id}`, "DELETE"),

  sessions: () => json<SessionSummary[]>("/sessions"),
  session: (id: string) => json<Session>(`/sessions/${id}`),
  createSession: (resume_id: string) => json<Session>("/sessions", "POST", { resume_id }),
  deleteSession: (id: string) => json<{ deleted: boolean }>(`/sessions/${id}`, "DELETE"),
  setJd: (id: string, jd_text: string, job_title: string, employer: string) =>
    json<Session>(`/sessions/${id}/jd`, "PUT", { jd_text, job_title, employer }),
  setRequirements: (id: string, job_title: string, employer: string, requirements: Requirement[]) =>
    json<Session>(`/sessions/${id}/requirements`, "PUT", { job_title, employer, requirements }),
  generateSuggestions: (id: string) => json<Session>(`/sessions/${id}/suggestions/generate`, "POST"),
  decide: (id: string, suggestionId: string, body: DecisionBody) =>
    json<Session>(`/sessions/${id}/suggestions/${suggestionId}/decision`, "POST", body),
  regenerate: (id: string, suggestionId: string) =>
    json<Session>(`/sessions/${id}/suggestions/${suggestionId}/regenerate`, "POST"),
  resetSuggestions: (id: string) => json<Session>(`/sessions/${id}/suggestions/reset`, "POST"),
  setConfig: (id: string, config: ResumeConfig) => json<Session>(`/sessions/${id}/config`, "PUT", config),
  generateTex: (id: string) => json<Session>(`/sessions/${id}/generate`, "POST"),
  compile: (id: string) => json<Session>(`/sessions/${id}/compile`, "POST"),

  /** Fetch a generated file with credentials and hand it to the browser. */
  blob: async (path: string) => {
    const res = await request(path);
    const name = /filename="?([^";]+)"?/.exec(res.headers.get("content-disposition") ?? "")?.[1] ?? "download";
    return { blob: await res.blob(), name };
  },
  download: async (path: string) => {
    const { blob, name } = await api.blob(path);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  },
};

export const errorMessage = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong.");

export const formatDate = (iso: string) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
};
