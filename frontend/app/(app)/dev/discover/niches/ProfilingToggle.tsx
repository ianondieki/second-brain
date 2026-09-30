"use client";

import { useRef, useState } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { CheckIcon, InfoIcon } from "@/components/ui/status-icons";

import { setProfiling } from "./calls";
import type { ProfilingProblem } from "./picker";

export interface ProfilingToggleProps {
  /** The profiling consent as GET /api/me/consents gives it: the decision, the wording and its version. */
  consent: { granted: boolean; text: string; version: string };
  setImpl?: typeof setProfiling;
}

/**
 * The profiling consent's setting (docs/spec/06 6.7: an opt-out toggle, DPA s.35; default off). The wording is the
 * API's, shown verbatim, and the decision is recorded on that version (409 when it changed meanwhile). The state is
 * icon, words and colour together; the button is secondary (the page's primary action is "Save niches").
 */
export function ProfilingToggle({ consent, setImpl = setProfiling }: ProfilingToggleProps) {
  const t = useStrings("likedNiches");
  const [granted, setGranted] = useState(consent.granted);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<ProfilingProblem | null>(null);
  const alert = useRef<HTMLDivElement>(null);
  const Icon = granted ? CheckIcon : InfoIcon;

  async function flip() {
    if (busy) return;
    setBusy(true);
    setProblem(null);
    const outcome = await setImpl(!granted, consent.version);
    setBusy(false);
    if (outcome.ok) {
      setGranted(outcome.value.granted);
    } else {
      setProblem(outcome.problem);
      requestAnimationFrame(() => alert.current?.focus());
    }
  }

  return (
    <section id="profiling" aria-labelledby="profiling-title" className="flex flex-col items-start gap-3 border-t border-line pt-6">
      <h2 id="profiling-title" className="text-lg text-ink">
        {t("profiling.title")}
      </h2>
      <p className="max-w-[62ch] text-ink-soft">{t("profiling.lead")}</p>
      <figure className="flex flex-col gap-1">
        <figcaption className="text-sm text-ink-soft">{t("profiling.wording")}</figcaption>
        <blockquote className="max-w-[62ch] border-l-2 border-line pl-3 text-ink">{consent.text}</blockquote>
      </figure>
      <p
        role="status"
        data-profiling={granted ? "on" : "off"}
        className={cn("flex items-start gap-2 font-medium", granted ? "text-ok" : "text-ink")}
      >
        <Icon className="mt-0.5 size-5 shrink-0" />
        <span>{granted ? t("profiling.on") : t("profiling.off")}</span>
      </p>
      {problem ? <Alert ref={alert}>{t(`profiling.problem.${problem}`)}</Alert> : null}
      {/* "Turn on" alone says little out of context: the section title describes it. */}
      <Button variant="secondary" busy={busy} onClick={flip} aria-describedby="profiling-title">
        {busy ? t("profiling.saving") : granted ? t("profiling.turnOff") : t("profiling.turnOn")}
      </Button>
    </section>
  );
}
