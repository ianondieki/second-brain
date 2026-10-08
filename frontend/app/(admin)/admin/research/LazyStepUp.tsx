"use client";

import { useEffect, useRef, useState } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Button, buttonClass } from "@/components/ui/Button";

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
 * StepUp, fetched on first use. While it arrives a short status line holds focus where the pressed button was (StepUp
 * then takes it for its code field); if it cannot be fetched (offline), the generic sentence, "Try again" (focused)
 * and, where the step-up replaced a decision, "Cancel" back to it.
 */
export function LazyStepUp(props: StepUpProps) {
  const t = useStrings("adminResearch");
  const [Form, setForm] = useState<typeof import("./StepUp").StepUp | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const waiting = useRef<HTMLParagraphElement>(null);
  const retry = useRef<HTMLButtonElement>(null);
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
  useEffect(() => {
    if (failed) retry.current?.focus();
    else if (!Form) waiting.current?.focus({ preventScroll: true });
  }, [failed, Form]);
  if (Form) return <Form {...props} />;
  if (!failed) {
    return (
      <p ref={waiting} tabIndex={-1} role="status" className="text-sm text-ink-soft focus:outline-none" data-step-up-loading="">
        {t("stepUp.loading")}
      </p>
    );
  }
  return (
    <div role="alert" className="flex flex-col items-start gap-3" data-step-up-unavailable="">
      <p className="text-ink">{t("refusal.generic")}</p>
      <div className="flex flex-wrap items-center gap-3">
        <button
          ref={retry}
          type="button"
          className={buttonClass("secondary")}
          onClick={() => {
            setFailed(false);
            setAttempt((n) => n + 1);
          }}
        >
          {t("stepUp.retry")}
        </button>
        {props.onCancel ? (
          <Button variant="link" onClick={props.onCancel}>
            {t("stepUp.cancel")}
          </Button>
        ) : null}
      </div>
    </div>
  );
}
