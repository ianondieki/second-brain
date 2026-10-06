"use client";

import { useRef, useState } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Button } from "@/components/ui/Button";

import { StepUp } from "../StepUp";
import { trendCalls, type TrendCalls } from "./calls";

/**
 * "Draft trends now" (REQ-DEV-02; POST /api/admin/research/trend-runs): a secondary action (the page's primary one is
 * starting a research run) that queues the weekly task at once. The line after it says what follows; a stale second
 * factor asks for a fresh code first.
 */
export function DraftTrends({ calls: given }: { calls?: TrendCalls }) {
  const t = useStrings("adminResearch");
  const calls = useRef(given ?? trendCalls()).current;
  const [busy, setBusy] = useState(false);
  const [stepUp, setStepUp] = useState(false);
  const [said, setSaid] = useState<"queued" | "failed" | null>(null);

  async function run() {
    if (busy) return;
    setBusy(true);
    setSaid(null);
    const outcome = await calls.draft();
    setBusy(false);
    if (!outcome.ok && outcome.refusal.kind === "stepUp") return setStepUp(true);
    setStepUp(false);
    setSaid(outcome.ok ? "queued" : "failed");
  }

  if (stepUp) return <StepUp onConfirmed={run} onCancel={() => setStepUp(false)} />;
  return (
    <div className="flex flex-col items-start gap-2">
      <Button variant="secondary" busy={busy} onClick={() => void run()} data-draft-trends="">
        {busy ? t("trends.drafting") : t("trends.draftNow")}
      </Button>
      <p role="status" className={said === "failed" ? "text-sm text-error" : "text-sm text-ink-soft"} data-draft-status={said ?? ""}>
        {said ? t(`trends.${said}`) : ""}
      </p>
    </div>
  );
}
