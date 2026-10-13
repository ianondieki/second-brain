"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { useStrings } from "@/components/ClientStrings";
import { StepUp } from "@/components/tracker/StepUp";
import { Alert } from "@/components/ui/Alert";

import type { TeamOutcome, TeamRefusal } from "./calls";

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
export function useTeamWrite({ enrolled, primary = false }: { enrolled: boolean; primary?: boolean }): TeamWrite {
  const t = useStrings("teamAdmin");
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [refused, setRefused] = useState<{ refusal: TeamRefusal; limit?: number } | null>(null);
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
    setRefused({ refusal: outcome.refusal === "stepUp" ? "generic" : outcome.refusal, limit: outcome.limit });
    if (STALE.has(outcome.refusal)) router.refresh();
  }

  const problem = refused ? (
    <Alert ref={notice} className="w-full">
      <p data-refusal={refused.refusal}>{t(`refusal.${refused.refusal}`, { limit: refused.limit ?? 20 })}</p>
    </Alert>
  ) : null;

  const stepUp = retry ? (
    <StepUp
      enrolled={enrolled}
      primary={primary}
      onConfirmed={retry}
      onCancel={() => {
        setRetry(null);
        setBusy(false);
      }}
    />
  ) : null;

  return { busy, problem, stepUp, run, reset: () => setRefused(null) };
}
