"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Form, SubmitButton } from "@/components/ui/Form";
import { SelectField } from "@/components/ui/SelectField";

import { getRun, startRun } from "./calls";
import { refusalKey, RUN_POLL_MS, RUN_POLLS, type NicheOption, type Refusal } from "./research";
import { StepUp } from "./StepUp";

type Phase =
  | { kind: "idle" }
  | { kind: "starting" }
  | { kind: "polling"; runId: string; name: string; polls: number }
  | { kind: "finished"; name: string }
  | { kind: "slow"; name: string }
  | { kind: "refused"; refusal: Exclude<Refusal, { kind: "stepUp" }> }
  | { kind: "stepUp" };

export interface StartRunProps {
  options: readonly NicheOption[];
  /** A run already going when the page was drawn: its status is followed as if it had just been started. */
  active?: { runId: string; name: string } | null;
  startImpl?: typeof startRun;
  getRunImpl?: typeof getRun;
  pollMs?: number;
}

/**
 * "Start run", the research page's one primary action (REQ-RES-01; POST /api/admin/research/runs, Kenya only): the
 * run is followed with GET …/runs/{id} every 1.5 s until it is no longer running, then the page is fetched again so
 * its card and its outcome appear. After about a minute the admin is told to refresh later. Refusals are fixed
 * sentences; a stale second factor asks for a fresh code, then starts the run.
 */
export function StartRun({
  options,
  active = null,
  startImpl = startRun,
  getRunImpl = getRun,
  pollMs = RUN_POLL_MS,
}: StartRunProps) {
  const t = useStrings("adminResearch");
  const router = useRouter();
  const [niche, setNiche] = useState(options[0]?.slug ?? "");
  const [phase, setPhase] = useState<Phase>(
    active ? { kind: "polling", runId: active.runId, name: active.name, polls: 0 } : { kind: "idle" },
  );
  const refusalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (phase.kind !== "polling") return;
    let live = true;
    const timer = setTimeout(async () => {
      const outcome = await getRunImpl(phase.runId);
      if (!live) return;
      if (outcome.ok && outcome.data.status !== "running") {
        setPhase({ kind: "finished", name: phase.name });
        router.refresh();
      } else if (phase.polls + 1 >= RUN_POLLS || (!outcome.ok && outcome.refusal.kind !== "refusal")) {
        setPhase({ kind: "slow", name: phase.name });
      } else {
        setPhase({ ...phase, polls: phase.polls + 1 });
      }
    }, pollMs);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [phase, getRunImpl, pollMs, router]);

  useEffect(() => {
    if (phase.kind === "refused") refusalRef.current?.focus();
  }, [phase]);

  const label = options.find((option) => option.slug === niche)?.label ?? niche;

  async function start() {
    setPhase({ kind: "starting" });
    const outcome = await startImpl(niche);
    if (outcome.ok) {
      setPhase({ kind: "polling", runId: outcome.data.id, name: label, polls: 0 });
    } else if (outcome.refusal.kind === "stepUp") {
      setPhase({ kind: "stepUp" });
    } else {
      setPhase({ kind: "refused", refusal: outcome.refusal });
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (phase.kind === "starting" || phase.kind === "polling" || !niche) return;
    void start();
  }

  if (phase.kind === "stepUp") {
    return <StepUp onConfirmed={start} onCancel={() => setPhase({ kind: "idle" })} />;
  }

  const busy = phase.kind === "starting" || phase.kind === "polling";
  const status =
    phase.kind === "polling"
      ? t("start.running", { name: phase.name })
      : phase.kind === "finished"
        ? t("start.finished", { name: phase.name })
        : phase.kind === "slow"
          ? t("start.slow", { name: phase.name })
          : "";

  return (
    <Form onSubmit={submit} className="flex flex-col gap-4">
      {phase.kind === "refused" ? (
        <Alert ref={refusalRef}>
          <p data-refusal={refusalKey(phase.refusal)}>{t(refusalKey(phase.refusal))}</p>
        </Alert>
      ) : null}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end">
        <div className="min-w-0 sm:w-80">
          <SelectField
            id="run-niche"
            name="niche"
            label={t("start.niche")}
            hint={t("start.nicheHint")}
            value={niche}
            onChange={(event) => setNiche(event.target.value)}
          >
            {options.map((option) => (
              <option key={option.slug} value={option.slug}>
                {option.label}
              </option>
            ))}
          </SelectField>
        </div>
        <SubmitButton variant="primary" busy={busy}>
          {phase.kind === "starting" ? t("start.starting") : t("start.submit")}
        </SubmitButton>
      </div>
      <dl className="flex gap-2 text-ink">
        <dt className="text-ink-soft">{t("start.country")}</dt>
        <dd className="font-medium">{t("start.kenya")}</dd>
      </dl>
      <div className="flex flex-col items-start gap-3">
        <p role="status" data-run-status={phase.kind} className="max-w-[60ch] text-ink empty:hidden">
          {status}
        </p>
        {phase.kind === "slow" ? (
          <Button variant="secondary" onClick={() => router.refresh()}>
            {t("start.refresh")}
          </Button>
        ) : null}
      </div>
    </Form>
  );
}
