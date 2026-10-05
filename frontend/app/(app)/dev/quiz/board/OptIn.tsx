"use client";

import { useRouter } from "next/navigation";
import { useRef, useState, useTransition } from "react";

import { useStrings } from "@/components/ClientStrings";

import { quizCalls, type QuizCalls } from "../calls";

/**
 * The board opt-in (REQ-DEV-01): a switch with its one-sentence explanation (who sees what). It answers at once, then
 * the API keeps it and the page is fetched again so the caller's line and the list follow; a refusal turns it back and
 * says so.
 */
export function OptIn({ initial, calls: given }: { initial: boolean; calls?: QuizCalls }) {
  const t = useStrings("quizPlay");
  const router = useRouter();
  const calls = useRef(given ?? quizCalls()).current;
  const [on, setOn] = useState(initial);
  const [status, setStatus] = useState("");
  const [failed, setFailed] = useState<"signedOut" | "failed" | null>(null);
  const [busy, setBusy] = useState(false);
  const [, startRefresh] = useTransition();

  async function flip() {
    if (busy) return;
    const next = !on;
    setOn(next);
    setBusy(true);
    setFailed(null);
    setStatus("");
    const outcome = await calls.optIn(next);
    setBusy(false);
    if (outcome !== "ok") {
      setOn(!next);
      setFailed(outcome);
      return;
    }
    setStatus(next ? t("optIn.joined") : t("optIn.left"));
    startRefresh(() => router.refresh());
  }

  return (
    <div className="flex flex-col gap-1" data-opt-in={on ? "on" : "off"}>
      <span className="inline-flex items-center gap-3">
        <button
          type="button"
          role="switch"
          aria-checked={on}
          aria-describedby="opt-in-explain"
          onClick={() => void flip()}
          className="group inline-flex min-h-11 items-center gap-3 font-semibold text-ink"
        >
          <span
            aria-hidden="true"
            className="relative h-6 w-10 shrink-0 rounded-full border border-ink-soft bg-field transition-colors group-aria-checked:border-accent group-aria-checked:bg-accent motion-reduce:transition-none"
          >
            <span className="absolute top-0.5 left-0.5 size-4 rounded-full bg-ink-soft transition-transform group-aria-checked:translate-x-4 group-aria-checked:bg-on-accent motion-reduce:transition-none" />
          </span>
          {t("optIn.label")}
        </button>
        <span aria-hidden="true" className="text-sm text-ink-soft">
          {on ? t("optIn.on") : t("optIn.off")}
        </span>
      </span>
      <p id="opt-in-explain" className="max-w-[60ch] text-sm text-ink-soft">
        {t("optIn.explain")}
      </p>
      {failed ? (
        <p role="alert" className="text-sm text-error">
          {t(`optIn.${failed}`)}
        </p>
      ) : null}
      <p role="status" className="text-sm text-ok empty:hidden">
        {status}
      </p>
    </div>
  );
}
