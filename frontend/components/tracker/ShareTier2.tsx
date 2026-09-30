"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";

import type { confirmStepUp } from "./calls";
import { shareTier2, type ShareOutcome, type ShareRefusal } from "./share";
import { StepUp } from "./StepUp";

export interface ShareTier2Props {
  engagementId: string;
  orgName: string;
  /** Two-step sign-in is on (the step-up needs a code). */
  enrolled: boolean;
  shareImpl?: (engagementId: string) => Promise<ShareOutcome>;
  confirmImpl?: typeof confirmStepUp;
}

type Mode = "idle" | "confirm" | "stepUp" | "done";

/**
 * "Share the full proposal" on an engagement an organisation opened (REQ-ENG-04): the developer confirms, gives a
 * fresh authenticator code when the API asks for one (403 step_up_required; the tracker's StepUp), and the full
 * proposal is granted to that organisation, who still opens it only under the Evaluation NDA. The confirmation
 * says so in the approved logging phrasing (docs/spec/04 4.2) and that it cannot be taken back.
 */
export function ShareTier2({
  engagementId,
  orgName,
  enrolled,
  shareImpl = shareTier2,
  confirmImpl,
}: ShareTier2Props) {
  const t = useStrings("tier2Share");
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("idle");
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<Exclude<ShareRefusal, "stepUp"> | null>(null);
  const notice = useRef<HTMLDivElement>(null);
  const question = useRef<HTMLParagraphElement>(null);
  // Never the screen's primary action: sharing the full proposal cannot be taken back (P10-F ux review).
  const variant = "secondary";

  useEffect(() => {
    if (refusal || mode === "done") notice.current?.focus();
  }, [refusal, mode]);
  useEffect(() => {
    if (mode === "confirm") question.current?.focus();
  }, [mode]);

  async function share(retried = false) {
    if (busy && !retried) return;
    setBusy(true);
    setRefusal(null);
    const outcome = await shareImpl(engagementId);
    setBusy(false);
    if (outcome.ok) {
      setMode("done");
      router.refresh();
      focusWhenShown("share-status");
      return;
    }
    if (outcome.refusal === "stepUp" && !retried) {
      setMode("stepUp");
      return;
    }
    setMode("idle");
    setRefusal(outcome.refusal === "stepUp" ? "generic" : outcome.refusal);
    if (outcome.refusal === "ended" || outcome.refusal === "notFound") router.refresh();
  }

  function cancel() {
    setRefusal(null);
    setMode("idle");
    requestAnimationFrame(() => document.getElementById("share-open")?.focus());
  }

  return (
    <section aria-labelledby="share-heading" data-tier2-share="" className="flex flex-col items-start gap-4">
      <h2 id="share-heading" className="text-lg text-ink">
        {t("title")}
      </h2>
      {mode === "done" ? (
        <Alert ref={notice} tone="ok" className="w-full">
          {t("sharedNow", { org: orgName })}
        </Alert>
      ) : null}
      {refusal ? (
        <Alert ref={notice} tone="error" className="w-full">
          <p data-refusal={refusal}>{t(`refusal.${refusal}`)}</p>
        </Alert>
      ) : null}

      {mode === "idle" ? (
        <>
          <p className="max-w-[60ch] text-ink">{t("notShared", { org: orgName })}</p>
          <Button id="share-open" variant={variant} className="w-full sm:w-auto" onClick={() => setMode("confirm")}>
            {t("share")}
          </Button>
        </>
      ) : null}

      {mode === "confirm" ? (
        <>
          <p ref={question} tabIndex={-1} className="max-w-[60ch] text-ink focus:outline-none" data-share-confirm="">
            {t("confirm", { org: orgName })}
          </p>
          <div className="flex w-full flex-col gap-3 sm:w-auto sm:flex-row">
            <Button variant={variant} busy={busy} onClick={() => void share()}>
              {busy ? t("sharing") : t("share")}
            </Button>
            <Button variant="secondary" busy={busy} onClick={cancel}>
              {t("cancel")}
            </Button>
          </div>
        </>
      ) : null}

      {mode === "stepUp" ? (
        <div className="w-full">
          <StepUp
            enrolled={enrolled}
            primary={false}
            onCancel={cancel}
            onConfirmed={() => share(true)}
            confirmImpl={confirmImpl}
          />
        </div>
      ) : null}
    </section>
  );
}

/**
 * Once the refreshed page replaces this form with the server's "You shared ..." line, focus moves to it (WCAG 2.4.3),
 * so the confirmation is announced where the control was. Gives up after a few seconds.
 */
function focusWhenShown(id: string) {
  const started = Date.now();
  const timer = setInterval(() => {
    const target = document.getElementById(id);
    if (target) target.focus();
    if (target || Date.now() - started > 5000) clearInterval(timer);
  }, 100);
}
