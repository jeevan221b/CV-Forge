import type { MatchStatus, SuggestionStatus } from "../types";
import { Badge, type Tone } from "./ui";

export const MATCH_TONE: Record<MatchStatus, Tone> = {
  supported: "green",
  needs_confirmation: "amber",
  indirect: "blue",
  unsupported: "red",
  unclear: "neutral",
};
export const MATCH_SHORT: Record<MatchStatus, string> = {
  supported: "Supported",
  needs_confirmation: "Needs confirmation",
  indirect: "Indirect",
  unsupported: "Not supported",
  unclear: "Unclear",
};
export const MATCH_ORDER: MatchStatus[] = ["supported", "needs_confirmation", "indirect", "unsupported", "unclear"];

const SESSION: Record<string, { label: string; tone: Tone }> = {
  draft: { label: "Started", tone: "neutral" },
  analyzed: { label: "Analysed", tone: "blue" },
  tailoring: { label: "In review", tone: "amber" },
  generated: { label: "Source generated", tone: "accent" },
  compiled: { label: "PDF ready", tone: "green" },
};
export function SessionStatus({ status }: { status: string }) {
  const s = SESSION[status] ?? { label: status, tone: "neutral" as Tone };
  return <Badge tone={s.tone}>{s.label}</Badge>;
}

export const SUGGESTION_TONE: Record<SuggestionStatus, Tone> = {
  pending: "neutral",
  accepted: "green",
  modified: "accent",
  rejected: "red",
  invalid: "red",
};
export const SUGGESTION_LABEL: Record<SuggestionStatus, string> = {
  pending: "Pending",
  accepted: "Accepted",
  modified: "Edited & accepted",
  rejected: "Rejected",
  invalid: "Rejected by validation",
};
