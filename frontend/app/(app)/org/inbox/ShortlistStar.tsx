"use client";

import { useState } from "react";

import type { ShortlistProblem } from "../shortlist";
import { setShortlisted } from "./shortlist-calls";
import { StarIcon } from "./StarIcon";

export interface ShortlistStarProps {
  orgId: string;
  proposalId: string;
  /** Whether the proposal is on the organisation's shortlist as the page was read. */
  initial: boolean;
  /** The words, formatted on the server (no i18n runtime in this island). */
  labels: { add: string; remove: string; problem: Record<ShortlistProblem, string> };
  /** "icon": the star alone (an Inbox row); "button": the star and its words (a proposal or match page). */
  variant?: "icon" | "button";
  /** The id of what the star is for (its row's title): each star's description differs. */
  describedBy?: string;
  setImpl?: typeof setShortlisted;
}

/**
 * Add a proposal to the organisation's shortlist, or take it off (REQ-REPO-02): a button named by what a press does
 * ("Add to shortlist" / "Remove from shortlist"), so the name carries the state; no aria-pressed, since a toggle's
 * name must not change with its state (WAI-ARIA APG, Button). It changes at once and goes back, with one sentence saying why, when the API refuses.
 * Shown only to the roles that may change the shortlist (reviewer, signatory, admin); others see ShortlistMark.
 */
export function ShortlistStar({
  orgId,
  proposalId,
  initial,
  labels,
  variant = "icon",
  describedBy,
  setImpl = setShortlisted,
}: ShortlistStarProps) {
  const [on, setOn] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<ShortlistProblem | null>(null);
  const name = on ? labels.remove : labels.add;

  async function press() {
    if (busy) return;
    const next = !on;
    setOn(next);
    setBusy(true);
    setProblem(null);
    const outcome = await setImpl(orgId, proposalId, next);
    setBusy(false);
    if (!outcome.ok) {
      setOn(!next);
      setProblem(outcome.problem);
    }
  }

  const icon = variant === "icon";
  return (
    <span className={icon ? "relative -mt-2.5 -mr-2.5 flex flex-col items-end" : "flex flex-col items-start gap-2"}>
      <button
        type="button"
        aria-label={icon ? name : undefined}
        aria-describedby={describedBy}
        aria-disabled={busy || undefined}
        onClick={press}
        data-shortlist={on ? "on" : "off"}
        className={
          icon
            ? "relative inline-flex size-11 items-center justify-center rounded-full text-ink-soft hover:bg-accent-wash data-[shortlist=on]:text-accent"
            : "btn btn-secondary gap-2 data-[shortlist=on]:[&>svg]:text-accent"
        }
      >
        <StarIcon on={on} className={icon ? "size-6" : "size-5"} />
        {icon ? null : name}
      </button>
      {problem ? (
        <span role="alert" className="max-w-56 text-sm text-error">
          {labels.problem[problem]}
        </span>
      ) : null}
    </span>
  );
}
