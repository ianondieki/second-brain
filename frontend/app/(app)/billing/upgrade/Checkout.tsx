"use client";

import { useEffect, useReducer, useRef, useState, type ReactNode, type Ref } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { ButtonLink } from "@/components/ui/ButtonLink";
import { cn } from "@/components/ui/cn";
import { RadioGroup } from "@/components/ui/RadioGroup";
import { AlertIcon, CheckIcon, ClockIcon } from "@/components/ui/status-icons";

import { formatKes } from "../plans";
import { checkoutCalls, type CheckoutCalls } from "./calls";
import {
  canRetryStart,
  failureReason,
  initialPhase,
  nextPoll,
  reduce,
  stepOf,
  type Checkout as CheckoutOut,
  type Phase,
  type SimulatedOutcome,
  type StartProblem,
} from "./machine";
import { StandaloneLink } from "@/components/ui/StandaloneLink";

export interface CheckoutProps {
  plan: { code: string; name: string };
  /** "KES 499 a month", formatted on the server. */
  price: string;
  /** The plan's entitlements in plain words. */
  lines: string[];
  /** The "Sample prices, not final" label (D-44) when prices are placeholders. */
  sample?: ReactNode;
  /** The checkout is the fake one: label it "Simulated M-Pesa" and offer the simulated outcomes (D-36). */
  simulated: boolean;
  orgId?: string;
  /** Plan & billing for the same subject. */
  billingHref: string;
  /** The page the person came from (a 402), offered once the plan is active. */
  nextHref?: string;
  /** A checkout named in the address (a reload, or the other plan's checkout in progress): polled at once. */
  initialCheckoutId?: string;
  /** The request's language, to format a checkout's amount as the server formats prices. */
  locale: string;
  calls?: CheckoutCalls;
}

const OUTCOMES: readonly SimulatedOutcome[] = ["succeed", "fail", "cancel"];

/** Keeps the checkout in the address, so a reload carries on polling it instead of starting another. */
function syncAddress(checkoutId: string | null) {
  const url = new URL(window.location.href);
  if ((url.searchParams.get("checkout") ?? null) === checkoutId) return;
  if (checkoutId) url.searchParams.set("checkout", checkoutId);
  else url.searchParams.delete("checkout");
  window.history.replaceState(window.history.state, "", url);
}

/**
 * The simulated M-Pesa checkout (REQ-BIL-08; docs/spec/05): confirm the plan and price, then "Check your phone" while
 * the page polls GET /api/billing/checkouts/{id} with a growing wait (machine.ts), then the outcome with a way back.
 * One primary action at a time; the step is announced and takes focus when it changes.
 */
export function Checkout(props: CheckoutProps) {
  const t = useStrings("checkout");
  const calls = props.calls ?? checkoutCalls;
  const [phase, dispatch] = useReducer(reduce, undefined, () => initialPhase(props.initialCheckoutId, Date.now()));
  const [outcome, setOutcome] = useState<SimulatedOutcome>("succeed");
  const heading = useRef<HTMLHeadingElement>(null);
  const alert = useRef<HTMLDivElement>(null);
  const shownKind = useRef(phase.kind);

  // A new step takes focus (its heading), and a refused start its alert, so the change is where the reader is.
  useEffect(() => {
    if (phase.kind === shownKind.current && !(phase.kind === "confirm" && phase.refusal)) return;
    const moved = phase.kind !== shownKind.current;
    shownKind.current = phase.kind;
    if (phase.kind === "confirm" && phase.refusal) alert.current?.focus();
    else if (moved && phase.kind !== "starting") heading.current?.focus();
  }, [phase]);

  useEffect(() => {
    if (phase.kind === "pending" || phase.kind === "stalled") syncAddress(phase.id);
    else if (phase.kind === "confirm") syncAddress(null);
  }, [phase]);

  // Polling: one read per pending phase, after the wait machine.ts gives; a new phase (the answer) schedules the next.
  useEffect(() => {
    if (phase.kind !== "pending") return;
    const next = nextPoll(phase, Date.now());
    if (next === "stop") {
      dispatch({ type: "timedOut" });
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      const read = await calls.read(phase.id, controller.signal);
      if (controller.signal.aborted) return;
      dispatch(read.ok ? { type: "polled", checkout: read.checkout } : { type: "pollFailed", problem: read.problem });
    }, next.wait);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [phase, calls]);

  async function start() {
    if (phase.kind !== "confirm") return;
    dispatch({ type: "start" });
    const started = await calls.start({
      planCode: props.plan.code,
      orgId: props.orgId,
      simulate: props.simulated ? outcome : undefined,
    });
    dispatch(
      started.ok
        ? { type: "started", checkout: started.checkout, at: Date.now() }
        : { type: "refused", refusal: started.refusal, at: Date.now() },
    );
  }

  const headingProps = { ref: heading, tabIndex: -1, className: "text-lg text-ink focus:outline-none" };
  // A simulated checkout sends no prompt to any phone, so its waiting step does not say "Check your phone".
  const simulated = props.simulated || (phase.kind === "pending" && phase.checkout?.simulated === true);
  const waitingTitle = simulated ? t("simulatedTitle") : t("phoneTitle");
  const body =
    phase.kind === "confirm" || phase.kind === "starting" ? (
        <Confirm
          {...props}
          busy={phase.kind === "starting"}
          problem={phase.kind === "confirm" ? phase.refusal?.problem : undefined}
          outcome={outcome}
          onOutcome={setOutcome}
          onStart={() => void start()}
          alertRef={alert}
          headingRef={heading}
        />
      ) : phase.kind === "pending" || phase.kind === "stalled" ? (
        <section aria-labelledby="checkout-step" className="flex flex-col gap-4" data-phase={phase.kind}>
          <h2 id="checkout-step" {...headingProps}>
            {waitingTitle}
          </h2>
          {simulated || phase.checkout?.simulated ? (
            <p className="max-w-[60ch] text-ink">{t("phoneLeadSimulated")}</p>
          ) : phase.checkout ? (
            <p className="max-w-[60ch] text-ink">
              {t("phoneLead", { price: formatKes(phase.checkout.amount_kes_minor, props.locale) })}
            </p>
          ) : null}
          {phase.kind === "pending" ? (
            <>
              <p role="status" className="flex items-center gap-2 font-medium text-ink">
                <ClockIcon className="size-5 shrink-0 text-accent motion-safe:animate-pulse" />
                {phase.checkout ? t("waiting") : t("checking")}
              </p>
              <p className="max-w-[60ch] text-sm text-ink-soft">{t("canLeave")}</p>
            </>
          ) : (
            <>
              <Alert tone="info">{t("stalled")}</Alert>
              <div>
                <Button variant="primary" onClick={() => dispatch({ type: "checkAgain", at: Date.now() })}>
                  {t("checkAgain")}
                </Button>
              </div>
            </>
          )}
        </section>
      ) : phase.kind === "lost" ? (
        <section
          aria-labelledby="checkout-step"
          className="flex flex-col gap-4"
          data-phase="lost"
          data-checkout-blocked={isOwnAction(phase.problem) ? undefined : ""}
        >
          <h2 id="checkout-step" {...headingProps}>
            {waitingTitle}
          </h2>
          <Alert>
            <p>{t(phase.problem === "notFound" ? "problem.checkoutNotFound" : `problem.${phase.problem}`)}</p>
            <ProblemAction problem={phase.problem} billingHref={props.billingHref} />
          </Alert>
        </section>
      ) : (
        <Result phase={phase} {...props} headingProps={headingProps} onRestart={() => dispatch({ type: "restart" })} />
      );
  return (
    <div className="mt-6 flex flex-col gap-8">
      <Steps current={stepOf(phase)} />
      {/* The step's words and controls, with the phone beside them from 1024 px (above them on a phone): what the
          M-Pesa prompt shows at this step, drawn, so the state reads at a glance. */}
      <div className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_17rem] lg:gap-12">
        <div className="order-2 min-w-0 lg:order-1">{body}</div>
        <div className="order-1 lg:order-2">
          <Phone phase={phase} plan={props.plan.name} price={props.price} simulated={simulated} />
        </div>
      </div>
    </div>
  );
}

/**
 * The phone beside the steps (D-52): a drawn handset whose screen shows what the M-Pesa prompt shows at this step. It
 * is decoration (aria-hidden): the headings, status and alerts beside it carry the meaning, so nothing is said twice.
 */
function Phone({ phase, plan, price, simulated }: { phase: Phase; plan: string; price: string; simulated: boolean }) {
  const t = useStrings("checkout");
  const kind = phase.kind;
  const state =
    kind === "succeeded" ? "paid" : kind === "failed" || kind === "cancelled" ? "notPaid" : kind === "pending" || kind === "stalled" || kind === "starting" ? "waiting" : "prompt";
  return (
    <div aria-hidden="true" data-phone={state} className="mx-auto w-full max-w-[15rem] lg:mx-0 lg:max-w-none">
      <div className="rounded-[1.75rem] border-[6px] border-bezel bg-paper p-3 shadow-card">
        <div className="mx-auto mb-3 h-1.5 w-16 rounded-full bg-line" />
        <div className="flex min-h-[15rem] flex-col rounded-[1rem] border border-line bg-field p-4">
          <p className="text-xs font-semibold tracking-[0.08em] text-ink-soft uppercase">
            {simulated ? t("phone.simulated") : t("phone.title")}
          </p>
          {state === "paid" ? (
            <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center">
              <span className="flex size-12 items-center justify-center rounded-full bg-warm-wash text-warm">
                <CheckIcon className="size-6" />
              </span>
              <p className="font-semibold text-ink">{t("phone.paid")}</p>
              <p className="text-sm text-ink-soft tabular-nums">{price}</p>
            </div>
          ) : state === "notPaid" ? (
            <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center">
              <span className="flex size-12 items-center justify-center rounded-full bg-error-wash text-error">
                <AlertIcon className="size-6" />
              </span>
              <p className="font-semibold text-ink">{t("phone.notPaid")}</p>
            </div>
          ) : (
            <div className="flex flex-1 flex-col gap-4 pt-4">
              <p className="text-ink [overflow-wrap:anywhere]">{t("phone.prompt", { price, plan })}</p>
              {state === "waiting" ? (
                <p className="mt-auto flex items-center gap-2 text-sm font-medium text-ink-soft">
                  <ClockIcon className="size-4 shrink-0 text-accent motion-safe:animate-pulse" />
                  {t("phone.waiting")}
                </p>
              ) : (
                <>
                  <p className="text-sm text-ink-soft">{t("phone.pin")}</p>
                  <p className="font-mono text-lg tracking-[0.4em] text-ink">····</p>
                  <div className="mt-auto flex gap-2">
                    <span className="flex-1 rounded-control border border-line py-1.5 text-center text-sm font-medium text-ink-soft">{t("phone.cancel")}</span>
                    <span className="flex-1 rounded-control bg-accent py-1.5 text-center text-sm font-semibold text-on-accent">{t("phone.send")}</span>
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/** The three steps as an ordered list with aria-current="step" (docs/spec/07 item 6); not buttons: it only shows. */
function Steps({ current }: { current: 1 | 2 | 3 }) {
  const t = useStrings("checkout");
  const names = [t("step.confirm"), t("step.phone"), t("step.done")];
  return (
    <ol aria-label={t("stepsLabel")} className="grid grid-cols-3 gap-2">
      {names.map((name, index) => {
        const step = index + 1;
        const done = step < current;
        return (
          <li
            key={name}
            aria-current={step === current ? "step" : undefined}
            data-done={done ? "" : undefined}
            className={cn(
              "flex min-w-0 items-start gap-1 border-t-4 pt-2 text-sm leading-snug",
              step === current
                ? "border-accent font-semibold text-ink"
                : done
                  ? "border-accent-line font-medium text-ink"
                  : "border-line font-medium text-ink-soft",
            )}
          >
            {done ? (
              <>
                <CheckIcon className="mt-px size-4 shrink-0 text-accent" />
                <span aria-hidden="true">{name}</span>
                <span className="sr-only">{t("stepDone", { name })}</span>
              </>
            ) : (
              name
            )}
          </li>
        );
      })}
    </ol>
  );
}

function Confirm({
  alertRef,
  headingRef,
  ...props
}: CheckoutProps & {
  busy: boolean;
  problem?: StartProblem;
  outcome: SimulatedOutcome;
  onOutcome: (outcome: SimulatedOutcome) => void;
  onStart: () => void;
  alertRef: Ref<HTMLDivElement>;
  /** Takes focus when the step opens again ("Try again" after a failed or cancelled payment). */
  headingRef: Ref<HTMLHeadingElement>;
}) {
  const t = useStrings("checkout");
  const { problem } = props;
  const blocked = problem !== undefined && !canRetryStart(problem);
  return (
    <section
      aria-labelledby="checkout-step"
      className="flex flex-col gap-6"
      data-phase="confirm"
      // A refusal that carries its own way back: the page's back link steps aside (upgrade/page.tsx).
      data-checkout-blocked={blocked && !isOwnAction(problem) ? "" : undefined}
    >
      {/* The step's heading names what it shows, then the price: no small label over a big number. */}
      <div>
        <h2 id="checkout-step" ref={headingRef} tabIndex={-1} className="text-lg text-ink focus:outline-none">
          {t("youPay")}
        </h2>
        <p className="mt-1 text-xl font-semibold text-ink tabular-nums" data-price="">
          {props.price}
        </p>
        {props.sample ? <div className="mt-2">{props.sample}</div> : null}
      </div>

      {props.lines.length > 0 ? (
        <div>
          <h3 className="font-semibold text-ink">{t("whatYouGet")}</h3>
          <ul className="mt-2 flex flex-col gap-1 text-ink">
            {props.lines.map((line) => (
              <li key={line} className="flex gap-2">
                <span aria-hidden="true" className="mt-[0.7em] size-1 shrink-0 rounded-full bg-ink-soft" />
                <span>{line}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {props.simulated ? (
        <div className="flex flex-col gap-4">
          <p className="max-w-[60ch] text-sm text-ink-soft">{t("simulatedNote")}</p>
          <RadioGroup
            id="checkout-outcome"
            name="simulate"
            legend={t("outcomeLegend")}
            value={props.outcome}
            onChange={props.onOutcome}
            options={OUTCOMES.map((value) => ({ value, label: t(`outcome.${value}`) }))}
          />
        </div>
      ) : null}

      {problem ? (
        <Alert ref={alertRef}>
          {/* otherPending never stays on this step (machine.ts follows that checkout). */}
          <p>{t(`problem.${problem === "otherPending" ? "failed" : problem}`)}</p>
          <ProblemAction problem={problem} billingHref={props.billingHref} />
        </Alert>
      ) : null}

      {blocked ? null : (
        <div className="pt-2">
          <Button variant="primary" busy={props.busy} onClick={props.onStart}>
            {props.busy ? t("starting") : props.simulated ? t("paySimulated") : t("pay")}
          </Button>
        </div>
      )}
    </section>
  );
}

/** Refusals whose action is not the way back to Plan & billing (sign in, the second factor). */
function isOwnAction(problem: StartProblem | "notFound" | undefined): boolean {
  return problem === "signedOut" || problem === "mfaRequired" || problem === "mfaSetup";
}

/** The one action a refusal offers, when there is one. */
function ProblemAction({ problem, billingHref }: { problem: StartProblem | "notFound"; billingHref: string }) {
  const t = useStrings("checkout");
  const link = (href: string, label: string) => (
    <StandaloneLink href={href}>
      {label}
    </StandaloneLink>
  );
  if (problem === "signedOut") return link("/login", t("action.logIn"));
  if (problem === "mfaRequired") return link("/auth/mfa", t("action.enterCode"));
  if (problem === "mfaSetup") return link("/settings/security", t("action.turnOnMfa"));
  if (canRetryStart(problem)) return null; // the primary button below tries again
  return link(billingHref, t("backToBilling"));
}

function Result({
  phase,
  headingProps,
  onRestart,
  ...props
}: CheckoutProps & {
  phase: Extract<Phase, { kind: "succeeded" | "failed" | "cancelled" }>;
  headingProps: { ref: Ref<HTMLHeadingElement>; tabIndex: number; className: string };
  onRestart: () => void;
}) {
  const t = useStrings("checkout");
  const checkout: CheckoutOut = phase.checkout;
  // The page's back link (above the title) stays the way to Plan & billing; each outcome has one action of its own.
  if (phase.kind === "succeeded") {
    const next = checkout.plan_active ? props.nextHref : undefined;
    return (
      <section aria-labelledby="checkout-step" className="flex flex-col gap-4" data-phase="succeeded">
        <h2 id="checkout-step" {...headingProps}>
          {t("succeededTitle")}
        </h2>
        <Alert tone="ok">
          {checkout.plan_active ? t("succeeded", { plan: checkout.plan_name }) : t("succeededNotActive")}
        </Alert>
        <div>
          <ButtonLink href={next ?? props.billingHref} variant="primary" className="no-underline">
            {next ? t("continue") : t("seeYourPlan")}
          </ButtonLink>
        </div>
      </section>
    );
  }
  const sentence =
    phase.kind === "cancelled" ? t("cancelled") : t(`failed.${failureReason(checkout)}`);
  return (
    <section aria-labelledby="checkout-step" className="flex flex-col gap-4" data-phase={phase.kind}>
      <h2 id="checkout-step" {...headingProps}>
        {phase.kind === "cancelled" ? t("cancelledTitle") : t("failedTitle")}
      </h2>
      <Alert>{sentence}</Alert>
      <div>
        <Button variant="primary" onClick={onRestart}>
          {t("tryAgain")}
        </Button>
      </div>
    </section>
  );
}
