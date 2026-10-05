"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { COMPARE_MAX, COMPARE_MIN } from "../../shortlist";

export interface CompareBarProps {
  /** The compare page without ids, keeping ?org= for members of several organisations ("…/compare?org=…" or "…/compare"). */
  action: string;
  /** The words, formatted on the server; `{count}` is filled here. */
  labels: { compare: string; chosen: string; hint: string; tooFew: string; tooMany: string };
}

/**
 * Compare, the Shortlist's one primary action, at the end of its form (REQ-REPO-02). The form works without script (a
 * GET with repeated `ids`); with it, this counts the ticked boxes, says how many are chosen, keeps the press until 2 to
 * 4 are, and opens the page at its short address (`?ids=a,b`).
 */
export function CompareBar({ action, labels }: CompareBarProps) {
  const router = useRouter();
  // Read at submit time, so the listeners are set once per form (not again whenever the router object changes).
  const routerRef = useRef(router);
  useEffect(() => {
    routerRef.current = router;
  }, [router]);
  const root = useRef<HTMLDivElement>(null);
  const [ids, setIds] = useState<string[]>([]);
  const [problem, setProblem] = useState<"tooFew" | "tooMany" | null>(null);

  useEffect(() => {
    const form = root.current?.closest("form");
    if (!form) return;
    const read = () =>
      Array.from(form.querySelectorAll<HTMLInputElement>('input[name="ids"]:checked'), (box) => box.value);
    const change = () => {
      setIds(read());
      setProblem(null);
    };
    const submit = (event: SubmitEvent) => {
      event.preventDefault();
      const chosen = read();
      if (chosen.length < COMPARE_MIN || chosen.length > COMPARE_MAX) {
        setProblem(chosen.length < COMPARE_MIN ? "tooFew" : "tooMany");
        return;
      }
      const separator = action.includes("?") ? "&" : "?";
      routerRef.current.push(`${action}${separator}ids=${chosen.map(encodeURIComponent).join(",")}`);
    };
    setIds(read());
    form.addEventListener("change", change);
    form.addEventListener("submit", submit);
    return () => {
      form.removeEventListener("change", change);
      form.removeEventListener("submit", submit);
    };
  }, [action]);

  const fill = (text: string) => text.replace("{count}", String(ids.length));
  return (
    <div ref={root} className="flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-5">
      <button type="submit" className="btn btn-primary" data-primary="" aria-describedby="compare-count">
        {labels.compare}
      </button>
      <p id="compare-count" role="status" className={problem ? "text-sm font-semibold text-error" : "text-sm text-ink-soft"}>
        {problem ? labels[problem] : ids.length > 0 ? fill(labels.chosen) : labels.hint}
      </p>
    </div>
  );
}
