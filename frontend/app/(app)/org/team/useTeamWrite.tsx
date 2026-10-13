"use client";

import { useRouter } from "next/navigation";
import { lazy, Suspense, useEffect, useRef, useState, type ReactNode } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button, standaloneLinkClass } from "@/components/ui/Button";

import type { TeamOutcome, TeamRefusal } from "./calls";
import type { Paywall } from "./team";

// The fresh-code form (the tracker's StepUp, with its code field) is a chunk of its own, fetched only when the API asks
// for it: the page's first load stays under the 150 KB budget (docs/spec/07 item 5).
// Offline (or a newer deploy replaced the chunk): the refusal's "no connection" line and Cancel instead of an error page.
const StepUp = lazy(() =>
  import("@/components/tracker/StepUp").then(
    (module) => ({ default: module.StepUp }),
    () => ({ default: StepUpUnavailable }),
  ),
);

function StepUpUnavailable({ onCancel }: { onCancel: () => void }) {
  const t = useStrings("teamAdmin");
  return (
    <div className="flex flex-col items-start gap-3" data-step-up="unavailable">
      <Alert className="w-full">
        <p>{t("refusal.network")}</p>
      </Alert>
      <Button variant="secondary" onClick={onCancel}>
        {t("cancel")}
      </Button>
    </div>
  );
}

/** Refusals after which the page is out of date: it is read again under the sentence. */
const STALE: ReadonlySet<TeamRefusal> = new Set(["invitation_closed", "notFound", "unknown_niche", "already_member"]);

export interface TeamWrite {
  busy: boolean;
  /** The refusal's sentence (an Alert that takes focus), or null. */
  problem: ReactNode;
  /** The fresh-code step while the API asks for it, in place of the control that asked; else null. */
  stepUp: ReactNode;
  /**
   * Runs `call`; on success `onDone` and the page is read again (router.refresh). A step-up asked for is shown
   * (`stepUp`), then the call runs once more; any other refusal is said in words (`problem`).
   */
  run: <T>(call: () => Promise<TeamOutcome<T>>, onDone?: (value: T) => void) => Promise<void>;
  /** Forget the last refusal (the person changed what they were doing). */
  reset: () => void;
}

/**
 * One write of the Team page with its busy state, its refusal in words and the step-up an invitation, a removal or a
 * role change may ask for first (ADR-002: an authenticator code within 12 hours). `enrolled`: two-step sign-in is on
 * (without it the step-up can only point to turning it on). `primary`: the code's Confirm is the screen's one primary
 * action (only where it replaces the invitation form, whose Send is that action otherwise).
 */
export function useTeamWrite({
  enrolled,
  primary = false,
  paywall,
}: {
  enrolled: boolean;
  primary?: boolean;
  /** Where a 402 plan_limit (the plan's seats) leads (team.ts Paywall, built on the server). */
  paywall?: Paywall;
}): TeamWrite {
  const t = useStrings("teamAdmin");
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [refused, setRefused] = useState<{ refusal: TeamRefusal; limit?: number; upgrade?: string } | null>(null);
  const [retry, setRetry] = useState<(() => Promise<void>) | null>(null);
  const notice = useRef<HTMLDivElement>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  // Focus follows what changed (WCAG 2.4.3): a refusal takes it, so it is read at once and the next Tab goes on from it.
  useEffect(() => {
    if (refused) notice.current?.focus();
  }, [refused]);

  async function run<T>(call: () => Promise<TeamOutcome<T>>, onDone?: (value: T) => void, retried = false) {
    if (busy && !retried) return;
    setBusy(true);
    setRefused(null);
    const outcome = await call();
    if (!mounted.current) return;
    setBusy(false);
    if (outcome.ok) {
      setRetry(null);
      onDone?.(outcome.value);
      router.refresh();
      return;
    }
    if (outcome.refusal === "stepUp" && !retried) {
      setRetry(() => () => run(call, onDone, true));
      return;
    }
    setRetry(null);
    // A second step-up request right after a fresh code is not asked again: it is said as a passing failure.
    setRefused({
      refusal: outcome.refusal === "stepUp" ? "generic" : outcome.refusal,
      limit: outcome.limit,
      upgrade: outcome.upgrade,
    });
    if (STALE.has(outcome.refusal)) router.refresh();
  }

  const offer = refused?.upgrade ? paywall?.plans[refused.upgrade] : undefined;
  const plan = offer?.name;
  const problem = refused ? (
    <Alert ref={notice} className="w-full">
      <p data-refusal={refused.refusal}>
        {refused.refusal === "plan_limit" && plan
          ? t("refusal.plan_limitUpgrade", { plan })
          : t(`refusal.${refused.refusal}`, { limit: refused.limit ?? 20 })}
      </p>
      {refused.refusal === "plan_limit" && paywall ? (
        // The page's own links (built on the server from the plan codes), never a URL from the answer.
        <a
          href={offer?.href ?? paywall.billing}
          className={standaloneLinkClass}
          data-upgrade={refused.upgrade ?? ""}
        >
          {plan ? t("upgradeTo", { plan }) : t("seePlans")}
        </a>
      ) : refused.refusal === "org_not_verified" ? (
        <a href="/help" className={standaloneLinkClass}>
          {t("verificationHelp")}
        </a>
      ) : null}
    </Alert>
  ) : null;

  const stepUp = retry ? (
    <Suspense fallback={<p role="status" className="text-sm text-ink-soft">{t("loading")}</p>}>
      <StepUp
        enrolled={enrolled}
        primary={primary}
        onConfirmed={retry}
        onCancel={() => {
          setRetry(null);
          setBusy(false);
        }}
      />
    </Suspense>
  ) : null;

  return { busy, problem, stepUp, run, reset: () => setRefused(null) };
}
