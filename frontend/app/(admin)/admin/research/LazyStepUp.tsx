"use client";

import { useEffect, useState } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Button } from "@/components/ui/Button";

import type { StepUpProps } from "./StepUp";

// The fresh-code form (StepUp) is a chunk of its own, fetched only when the API asks for it: a console page then
// carries none of it until then (the moderation case page was over the 150 KB budget with it; P25). One request,
// however often it is asked for; a failed one is forgotten, so "Try again" fetches it again.
let chunk: Promise<typeof import("./StepUp")> | null = null;
function loadStepUp() {
  chunk ??= import("./StepUp").catch((error: unknown) => {
    chunk = null;
    throw error;
  });
  return chunk;
}

/**
 * StepUp, fetched on first use. While it arrives nothing shows (it takes focus when it does, as before); if it cannot
 * be fetched (offline), the generic sentence and "Try again" stand in its place.
 */
export function LazyStepUp(props: StepUpProps) {
  const t = useStrings("adminResearch");
  const [Form, setForm] = useState<typeof import("./StepUp").StepUp | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    loadStepUp().then(
      (module) => live && setForm(() => module.StepUp),
      () => live && setFailed(true),
    );
    return () => {
      live = false;
    };
  }, [attempt]);
  if (Form) return <Form {...props} />;
  if (!failed) return null;
  return (
    <div role="alert" className="flex flex-col items-start gap-3" data-step-up-unavailable="">
      <p className="text-ink">{t("refusal.generic")}</p>
      <Button
        variant="secondary"
        onClick={() => {
          setFailed(false);
          setAttempt((n) => n + 1);
        }}
      >
        {t("stepUp.retry")}
      </Button>
    </div>
  );
}
