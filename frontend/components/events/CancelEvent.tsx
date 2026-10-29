"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog, openConfirm } from "@/components/ui/ConfirmDialog";

import { eventCalls, type EventCalls, type EventPoster } from "./calls";
import type { EventRefused } from "./event-draft";

/**
 * "Cancel this event" (REQ-DEV-02; P22 card B default (1): the poster or staff cancel a draft or published event): a
 * secondary button, then a confirmation that says what cancelling does (developers no longer see it, and no reminder
 * is sent) before anything does. Done, or cancelled meanwhile (409), the page reads again; any other refusal stays in
 * the dialog in words.
 */
export function CancelEvent({
  target,
  eventId,
  poster,
  calls: given,
}: {
  target: EventPoster;
  eventId: string;
  poster: string;
  calls?: EventCalls;
}) {
  const t = useStrings("eventForm");
  const router = useRouter();
  const calls = useRef(given ?? eventCalls()).current;
  const dialog = useRef<HTMLDialogElement>(null);
  const [busy, setBusy] = useState(false);
  const [refused, setRefused] = useState<EventRefused | null>(null);

  async function run() {
    if (busy) return;
    setBusy(true);
    setRefused(null);
    const outcome = await calls.cancel(target, eventId);
    setBusy(false);
    if (outcome.ok || outcome.refusal === "notCancellable") {
      dialog.current?.close();
      router.refresh();
      return;
    }
    setRefused(outcome);
  }

  return (
    <>
      <Button variant="secondary" onClick={() => openConfirm(dialog.current)} data-cancel-event="">
        {t("cancelEvent.open")}
      </Button>
      <ConfirmDialog
        ref={dialog}
        title={t("cancelEvent.title")}
        confirmLabel={t("cancelEvent.confirm")}
        busyLabel={t("cancelEvent.cancelling")}
        cancelLabel={t("cancelEvent.keep")}
        busy={busy}
        tone="danger"
        onConfirm={() => void run()}
        onClose={() => setRefused(null)}
        problem={
          refused ? (
            <Alert>
              <p data-refusal={refused.refusal}>{t(`refusal.${refused.refusal}`, { org: poster })}</p>
            </Alert>
          ) : null
        }
      >
        <p>{t("cancelEvent.body")}</p>
      </ConfirmDialog>
    </>
  );
}
