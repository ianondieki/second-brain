"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { SHORTLIST_HEADING_ID, type ShortlistProblem } from "../../shortlist";
import { setShortlisted } from "../shortlist-calls";

export interface RemoveEntryProps {
  orgId: string;
  proposalId: string;
  /** The words, formatted on the server: the button, its full name (with the title), busy, and each problem. */
  labels: { remove: string; name: string; busy: string; problem: Record<ShortlistProblem, string> };
  setImpl?: typeof setShortlisted;
}

/**
 * Take one entry off the shortlist (REQ-REPO-02; reviewer, signatory or admin). No confirmation: the shortlist is a
 * working list and the star puts it back. The list is read again once the API agrees; a refusal is one sentence.
 */
export function RemoveEntry({ orgId, proposalId, labels, setImpl = setShortlisted }: RemoveEntryProps) {
  const router = useRouter();
  const root = useRef<HTMLSpanElement>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<ShortlistProblem | null>(null);

  async function remove() {
    if (busy) return;
    setBusy(true);
    setProblem(null);
    const outcome = await setImpl(orgId, proposalId, false);
    if (outcome.ok) {
      // Focus would fall to the page once this row leaves: the list keeps it, or the Shortlist's heading when this was
      // the last entry (the list then gives way to the empty state).
      const list = root.current?.closest<HTMLElement>("[data-shortlist-list]");
      const last = (list?.querySelectorAll("[data-shortlist-entry]").length ?? 0) <= 1;
      (last ? document.getElementById(SHORTLIST_HEADING_ID) : list)?.focus();
      router.refresh();
      return; // the row leaves with the refreshed list
    }
    setBusy(false);
    setProblem(outcome.problem);
  }

  return (
    <span ref={root} className="flex flex-col items-end gap-1">
      <button
        type="button"
        onClick={remove}
        aria-disabled={busy || undefined}
        aria-label={busy ? undefined : labels.name}
        data-remove-entry=""
        className="btn btn-link relative"
      >
        {busy ? labels.busy : labels.remove}
      </button>
      {problem ? (
        <span role="alert" className="max-w-56 text-right text-sm text-error">
          {labels.problem[problem]}
        </span>
      ) : null}
    </span>
  );
}
