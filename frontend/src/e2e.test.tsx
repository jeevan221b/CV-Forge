/**
 * UI smoke test against a running CV Forge backend.
 *
 *   CVFORGE_E2E_URL=http://127.0.0.1:8000 npm run test:ui
 *
 * Skipped when CVFORGE_E2E_URL is not set. It uploads the fictional sample resume and creates and
 * deletes its own session, so point it at a throwaway data directory.
 */
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeAll, describe, expect, it } from "vitest";
import App from "./App";

const BASE = process.env.CVFORGE_E2E_URL ?? "";
const sample = (name: string) => resolve(process.cwd(), "../backend/samples", name);
let resumeId = "";
let sessionId = "";

const call = async (path: string, init?: RequestInit) => {
  const res = await fetch(`${BASE}/api${path}`, init);
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status} ${await res.text()}`);
  return res.json();
};
const json = (method: string, body: unknown): RequestInit => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const open = (path: string) => render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>);

describe.skipIf(!BASE)("CV Forge UI against a live backend", () => {
  beforeAll(async () => {
    const realFetch = globalThis.fetch;
    globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) =>
      realFetch(typeof input === "string" && input.startsWith("/") ? BASE + input : input, init)) as typeof fetch;
    window.scrollTo = () => {};
    URL.createObjectURL = () => "blob:test";
    URL.revokeObjectURL = () => {};

    // jsdom's FormData is not understood by Node's fetch, so build the multipart body by hand.
    const boundary = "----cvforge-ui-test";
    const body = `--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="sample_resume.tex"\r\n` +
      `Content-Type: application/x-tex\r\n\r\n${readFileSync(sample("sample_resume.tex"), "utf8")}\r\n--${boundary}--\r\n`;
    resumeId = (await call("/resumes", { method: "POST", body, headers: { "Content-Type": `multipart/form-data; boundary=${boundary}` } })).id;
    sessionId = (await call("/sessions", json("POST", { resume_id: resumeId }))).id;
  });
  afterEach(cleanup);

  it("dashboard shows master resume status, counts and the primary action", async () => {
    open("/");
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeTruthy();
    expect(await screen.findByText("Needs review")).toBeTruthy();
    expect(screen.getByRole("button", { name: /New tailoring session/ })).toBeTruthy();
    for (const label of ["Dashboard", "Master Resume", "New Tailoring Session", "Application History", "Settings"])
      expect(screen.getAllByRole("link", { name: label }).length).toBeGreaterThan(0);
  });

  it("profile editor loads parsed fields, edits a bullet and saves a new version", async () => {
    const user = userEvent.setup();
    open(`/resume/${resumeId}`);
    expect(await screen.findByDisplayValue("Avery Quill")).toBeTruthy();
    expect(screen.getByDisplayValue("Lanternfish Logistics")).toBeTruthy();
    expect(screen.getByText(/interpreted as entry headings/)).toBeTruthy(); // parser uncertainty is surfaced
    const bullet = screen.getByDisplayValue(/Wrote SQL reports for the finance team/);
    await user.type(bullet, " weekly");
    expect(screen.getByText("Unsaved changes")).toBeTruthy();
    await user.click(screen.getByRole("checkbox", { name: /I have checked this profile/ }));
    await user.click(screen.getAllByRole("button", { name: "Save profile" })[0]);
    expect(await screen.findByText(/Profile saved as version 2/)).toBeTruthy();
    const saved = await call(`/resumes/${resumeId}`);
    const edited = saved.profile.experience[1].bullets[1];
    expect(edited.text.endsWith("weekly")).toBe(true);
    expect(edited.origin).toBe("user");
    expect(saved.verified).toBe(true);
  });

  it("JD step analyses a pasted description and moves to the match report", async () => {
    const user = userEvent.setup();
    open(`/sessions/${sessionId}?step=jd`);
    const box = await screen.findByRole("textbox", { name: "Job description" });
    await user.click(box);
    await user.paste(readFileSync(sample("sample_jd.txt"), "utf8"));
    await user.click(screen.getByRole("button", { name: "Analyse requirements" }));
    expect(await screen.findByText("Estimated overlap")).toBeTruthy();
    expect(screen.getByText("Knowledge of Go")).toBeTruthy();
    expect(screen.getAllByText("Not supported").length).toBe(3);
    expect(screen.getAllByText(/Genuine gap/).length).toBe(3);
    expect(screen.getByText(/Docker containers on AWS ECS/)).toBeTruthy(); // evidence excerpt shown
  });

  it("requirements can be edited and re-matched", async () => {
    const user = userEvent.setup();
    open(`/sessions/${sessionId}?step=requirements`);
    await screen.findByText("Knowledge of Go");
    await user.click(screen.getByRole("button", { name: "Add requirement" }));
    await user.type(screen.getByRole("textbox", { name: "Requirement" }), "Experience with shipment manifests");
    await user.type(screen.getByRole("textbox", { name: /Terms to look for/ }), "shipment manifests");
    await user.click(screen.getByRole("button", { name: "Save and re-match" }));
    await waitFor(() => expect(screen.queryByText(/unsaved changes/)).toBeNull());
    const row = screen.getByText("Experience with shipment manifests", { selector: "p" }).closest("li")!;
    expect(within(row).getByText("Supported")).toBeTruthy();
    expect(within(row).getByText("edited by you")).toBeTruthy();
  });

  it("tailor step explains missing AI configuration or reviews suggestions", async () => {
    const user = userEvent.setup();
    const system = await call("/system");
    open(`/sessions/${sessionId}?step=tailor`);
    await screen.findByText("AI tailoring suggestions");
    if (!system.ai.configured) {
      expect(await screen.findByText("AI-powered tailoring is unavailable")).toBeTruthy();
      expect((screen.getByRole("button", { name: "Generate suggestions" }) as HTMLButtonElement).disabled).toBe(true);
      return;
    }
    if (!system.ai.consent) {
      await user.click(screen.getByRole("button", { name: "Generate suggestions" }));
      expect(await screen.findByRole("dialog", { name: "Send content to Groq?" })).toBeTruthy(); // consent first
      await user.click(screen.getByRole("button", { name: /I consent/ }));
    } else await user.click(screen.getByRole("button", { name: /Generate suggestions|Regenerate/ }));
    await screen.findByText(/pending$/, undefined, { timeout: 60000 });
    const cards = () => screen.getAllByText(/^Original — from your master resume$/).map((el) => el.closest("section")!);
    expect(cards().length).toBeGreaterThan(0);

    // A flagged suggestion cannot be accepted until the confirmation box is ticked.
    const flagged = cards().find((c) => within(c).queryByText("needs confirmation"));
    if (flagged) {
      const accept = within(flagged).getByRole("button", { name: "Confirm and accept" }) as HTMLButtonElement;
      expect(accept.disabled).toBe(true);
      await user.click(within(flagged).getByRole("button", { name: "Reject" }));
      await waitFor(async () => expect((await call(`/sessions/${sessionId}`)).suggestion_counts.rejected).toBe(1));
    }
    const clean = cards().find((c) => within(c).queryByRole("button", { name: "Accept" }));
    if (clean) {
      await user.click(within(clean).getByRole("button", { name: "Accept" }));
      await waitFor(async () => expect((await call(`/sessions/${sessionId}`)).suggestion_counts.accepted).toBe(1));
      expect(await screen.findByText("In the draft.")).toBeTruthy();
    }
    // Edit flow: an unverifiable number is caught and needs explicit confirmation.
    const pending = cards().find((c) => within(c).queryByRole("button", { name: "Edit" }) && within(c).queryByRole("button", { name: "Reject" }));
    if (pending) {
      await user.click(within(pending).getByRole("button", { name: "Edit" }));
      const area = within(pending).getByRole("textbox");
      await user.type(area, " for 250 customers");
      await user.click(within(pending).getByRole("button", { name: "Save edit" }));
      expect(await within(pending).findByText(/numbers or metrics that are not in the original/)).toBeTruthy();
      await within(pending).findByRole("button", { name: "Confirm and save" });
      expect((within(pending).getByRole("button", { name: "Confirm and save" }) as HTMLButtonElement).disabled).toBe(true);
      await user.click(within(pending).getByRole("button", { name: "Cancel" }));
    }
  });

  it("configure step saves options", async () => {
    const user = userEvent.setup();
    open(`/sessions/${sessionId}?step=configure`);
    await screen.findByText("Skills to list first");
    await user.click(screen.getByRole("button", { name: "SQL" }));
    await user.click(screen.getByRole("button", { name: "Move Education up" }));
    await waitFor(async () => {
      const cfg = (await call(`/sessions/${sessionId}`)).config;
      expect(cfg.prioritized_skills).toEqual(["SQL"]);
      expect(cfg.section_order.indexOf("education")).toBeLessThan(cfg.section_order.indexOf("projects"));
    });
  });

  it("generate step produces source, compiles when possible and shows validation", async () => {
    const user = userEvent.setup();
    const system = await call("/system");
    open(`/sessions/${sessionId}?step=output`);
    await user.click(await screen.findByRole("button", { name: "Generate LaTeX" }));
    expect(await screen.findByText(/Generated by CV Forge/)).toBeTruthy(); // source viewer
    if (!system.toolchain.can_compile) {
      expect((screen.getByRole("button", { name: "Compile PDF" }) as HTMLButtonElement).disabled).toBe(true);
      return;
    }
    await user.click(screen.getByRole("button", { name: "Compile PDF" }));
    await screen.findByRole("button", { name: "Recompile PDF" }, { timeout: 55000 });
    await user.click(screen.getByRole("tab", { name: /Validation/ }));
    expect(await screen.findByText("Every approved line appears in the PDF")).toBeTruthy();
    expect(screen.getByText("Qualification match")).toBeTruthy();
    expect(screen.getByText(/cannot guarantee compatibility/)).toBeTruthy();
    await user.click(screen.getByRole("tab", { name: "Extracted PDF text" }));
    expect(await screen.findByText(/Lanternfish Logistics/)).toBeTruthy();
  });

  it("export step offers downloads; history lists and deletes the session", async () => {
    const user = userEvent.setup();
    open(`/sessions/${sessionId}?step=export`);
    expect(await screen.findByRole("button", { name: "Download .tex" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Download report" })).toBeTruthy();
    cleanup();
    open("/history");
    await screen.findAllByRole("link", { name: "Backend Software Engineer" });
    const row = document.querySelector(`a[href="/sessions/${sessionId}"]`)!.closest("tr")!;
    await user.click(within(row).getByRole("button", { name: "Delete" }));
    await user.click(within(row).getByRole("button", { name: "Click again to confirm" }));
    await waitFor(() => expect(document.querySelector(`a[href="/sessions/${sessionId}"]`)).toBeNull());
    await call(`/resumes/${resumeId}`, { method: "DELETE" });
  });
});
