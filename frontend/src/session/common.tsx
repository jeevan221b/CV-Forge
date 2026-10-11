import { useCallback, useState } from "react";
import { ApiError, errorMessage } from "../api";
import type { Session } from "../types";

export type StepId = "resume" | "jd" | "requirements" | "tailor" | "configure" | "output" | "export";
export const STEPS: { id: StepId; label: string; covers: string }[] = [
  { id: "resume", label: "Resume", covers: "Select master resume" },
  { id: "jd", label: "Job description", covers: "Enter JD" },
  { id: "requirements", label: "Requirements", covers: "Analyse requirements and match" },
  { id: "tailor", label: "Tailor", covers: "Generate and review suggestions" },
  { id: "configure", label: "Configure", covers: "Configure the resume" },
  { id: "output", label: "Generate", covers: "Generate LaTeX, compile and validate" },
  { id: "export", label: "Export", covers: "Download files" },
];

export interface StepProps {
  session: Session;
  setSession: (s: Session) => void;
  goto: (step: StepId) => void;
}

/** Runs a backend call that returns the updated session, tracking busy/error state. */
export function useAction(setSession: (s: Session) => void) {
  const [busy, setBusy] = useState<string>("");
  const [error, setError] = useState<ApiError | null>(null);
  const run = useCallback(
    async (key: string, fn: () => Promise<Session>): Promise<boolean> => {
      setBusy(key);
      setError(null);
      try {
        setSession(await fn());
        return true;
      } catch (e) {
        setError(e instanceof ApiError ? e : new ApiError(0, "error", errorMessage(e)));
        return false;
      } finally {
        setBusy("");
      }
    },
    [setSession],
  );
  return { busy, error, setError, run };
}
