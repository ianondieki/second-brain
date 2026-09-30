"use client";

import { useRef, useState, type FormEvent } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button, standaloneLinkClass } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import { CheckIcon } from "@/components/ui/status-icons";

import { saveChoices } from "./calls";
import {
  CHANNELS,
  changedDecisions,
  isOffered,
  notificationChoices,
  type Channel,
  type NotificationChoice,
  type NotificationPurpose,
  type SaveRefusal,
} from "./choices";

export const NOTIFICATIONS_PATH = "/settings/notifications";

/** A refusal's one action, where there is one: read the new wording, or sign in again. */
const REFUSAL_ACTION: Partial<Record<SaveRefusal, { key: "reload" | "logIn"; href: string }>> = {
  changed: { key: "reload", href: NOTIFICATIONS_PATH },
  signedOut: { key: "logIn", href: "/login" },
};

export interface NotificationChoicesProps {
  /** The notification consents as GET /api/me/consents gave them (choices.ts notificationChoices). */
  initial: NotificationChoice[];
  saveImpl?: typeof saveChoices;
}

type Ticked = Partial<Record<NotificationPurpose, boolean>>;
const tickedOf = (choices: readonly NotificationChoice[]): Ticked =>
  Object.fromEntries(choices.map((choice) => [choice.purpose, choice.granted]));

/**
 * The notification choices, one checkbox per consent grouped by channel, each labelled with the API's wording
 * verbatim, and "Save choices" as the screen's one primary action. A save sends the changed decisions on the version
 * shown; a refusal is one fixed sentence (and its one action) that takes focus. WhatsApp is not available yet: its
 * box can be unticked (a withdrawal) but not ticked.
 */
export function NotificationChoices({ initial, saveImpl = saveChoices }: NotificationChoicesProps) {
  const t = useStrings("notificationSettings");
  const [shown, setShown] = useState(initial);
  const [ticked, setTicked] = useState<Ticked>(() => tickedOf(initial));
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [refusal, setRefusal] = useState<SaveRefusal | null>(null);
  const alert = useRef<HTMLDivElement>(null);

  function tick(purpose: NotificationPurpose, value: boolean) {
    setTicked((was) => ({ ...was, [purpose]: value }));
    setSaved(false);
    setRefusal(null);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setSaved(false);
    setRefusal(null);
    const decisions = changedDecisions(shown, ticked);
    if (Object.keys(decisions).length === 0) {
      setSaved(true);
      return;
    }
    setBusy(true);
    const outcome = await saveImpl(decisions);
    setBusy(false);
    if (outcome.ok) {
      const now = notificationChoices(outcome.items);
      setShown(now);
      setTicked(tickedOf(now));
      setSaved(true);
    } else {
      setRefusal(outcome.refusal);
      requestAnimationFrame(() => alert.current?.focus());
    }
  }

  const channels = (Object.keys(CHANNELS) as Channel[])
    .map((channel) => ({
      channel,
      choices: shown.filter((choice) => (CHANNELS[channel] as readonly string[]).includes(choice.purpose)),
    }))
    .filter((group) => group.choices.length > 0);
  const action = refusal ? REFUSAL_ACTION[refusal] : undefined;

  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-8" data-notification-choices="">
      {channels.map(({ channel, choices }) => (
        <fieldset key={channel} data-channel={channel}>
          <legend className="text-lg font-semibold text-ink">{t(`channel.${channel}`)}</legend>
          <div className="mt-1 flex flex-col">
            {choices.map((choice) => {
              const offered = isOffered(choice);
              const hintId = `consent-${choice.purpose}-hint`;
              return (
                <div key={choice.purpose} data-consent={choice.purpose}>
                  <Checkbox
                    id={`consent-${choice.purpose}`}
                    name={choice.purpose}
                    label={choice.text}
                    checked={ticked[choice.purpose] ?? false}
                    disabled={!offered}
                    aria-describedby={offered ? undefined : hintId}
                    onChange={(event) => tick(choice.purpose, event.currentTarget.checked)}
                  />
                  {offered ? null : (
                    <p id={hintId} className="-mt-1 pb-2 pl-8 text-sm text-ink-soft">
                      {t("notYet")}
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        </fieldset>
      ))}

      {refusal ? (
        <Alert ref={alert}>
          <p data-refusal={refusal}>{t(`refused.${refusal}`)}</p>
          {action ? (
            <a href={action.href} className={standaloneLinkClass}>
              {t(`action.${action.key}`)}
            </a>
          ) : null}
        </Alert>
      ) : null}

      <div className="flex flex-col items-start gap-3 sm:flex-row sm:items-center sm:gap-4">
        <Button type="submit" variant="primary" busy={busy}>
          {busy ? t("saving") : t("save")}
        </Button>
        {/* Always in the page, so the confirmation is announced when it appears. */}
        <p role="status" className="flex min-h-6 items-center gap-2 font-medium text-ok" data-saved={saved ? "" : undefined}>
          {saved ? (
            <>
              <CheckIcon className="size-5 shrink-0" />
              <span>{t("saved")}</span>
            </>
          ) : null}
        </p>
      </div>
    </form>
  );
}
