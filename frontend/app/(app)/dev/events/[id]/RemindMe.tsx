"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/Button";

import { reminderCalls, type ReminderCalls } from "../calls";
import { reminderLine, type EmailState, type ReminderLine, type ReminderRefusal } from "../reminder";

export interface RemindMeLabels {
  remind: string;
  reminding: string;
  decline: string;
  declining: string;
  set: string;
  removed: string;
  refusal: Record<ReminderRefusal, string>;
}

export interface RemindMeProps {
  eventId: string;
  /** The developer already asked to be reminded (the page's read). */
  initial: boolean;
  /** The day-before email's gate as the page read it (null: not read; the line waits for the API's answer). */
  email: EmailState | null;
  labels: RemindMeLabels;
  /** What will come, worded on the server (the Settings link inside one of them). */
  lines: Record<ReminderLine, ReactNode>;
  calls?: ReminderCalls;
}

type Status = "set" | "removed" | null;

/**
 * "Remind me" (REQ-DEV-02; D-61; P22 card B default (4)), the event page's one primary action: one email the day
 * before (with the reminders consent and a verified address) and one notice here on the morning. The line under it says
 * which of the two will come. Pressed, it becomes the secondary "Don't remind me" and focus moves to the line that
 * says the reminder is set; declined, "Remind me" comes back and the line says nothing will be sent.
 */
export function RemindMe({ eventId, initial, email: initialEmail, labels, lines, calls: given }: RemindMeProps) {
  const calls = useRef(given ?? reminderCalls()).current;
  const [on, setOn] = useState(initial);
  const [email, setEmail] = useState(initialEmail);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<Status>(null);
  const [refusal, setRefusal] = useState<ReminderRefusal | null>(null);
  const line = useRef<HTMLParagraphElement>(null);

  useEffect(() => {
    if (status || refusal) line.current?.focus();
  }, [status, refusal]);

  async function press() {
    if (busy) return;
    setBusy(true);
    setRefusal(null);
    setStatus(null);
    if (on) {
      const outcome = await calls.decline(eventId);
      setBusy(false);
      if (!outcome.ok) return setRefusal(outcome.refusal);
      setOn(false);
      setStatus("removed");
      return;
    }
    const outcome = await calls.remind(eventId);
    setBusy(false);
    if (!outcome.ok) return setRefusal(outcome.refusal);
    setEmail(outcome.value.email);
    setOn(true);
    setStatus("set");
  }

  const what = email ? lines[reminderLine(email)] : null;
  return (
    <div className="flex flex-col items-start gap-3" data-reminder={on ? "on" : "off"}>
      <Button variant={on ? "secondary" : "primary"} busy={busy} onClick={() => void press()} aria-describedby="reminder-line">
        {busy ? (on ? labels.declining : labels.reminding) : on ? labels.decline : labels.remind}
      </Button>
      <p
        id="reminder-line"
        ref={line}
        tabIndex={-1}
        role="status"
        className="max-w-[60ch] text-sm text-ink-soft focus:outline-none"
        data-reminder-line={refusal ? `refused-${refusal}` : status ?? (on ? "on" : "off")}
      >
        {refusal ? (
          <span className="font-semibold text-error">{labels.refusal[refusal]}</span>
        ) : status === "removed" ? (
          <span className="font-semibold text-ink">{labels.removed}</span>
        ) : (
          <>
            {on ? <span className="mr-1 font-semibold text-ok">{labels.set}</span> : null}
            {what}
          </>
        )}
      </p>
    </div>
  );
}
