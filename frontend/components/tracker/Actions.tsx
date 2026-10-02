"use client";

import { useRouter } from "next/navigation";
import { lazy, Suspense, useEffect, useRef, useState } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";

import { confirmStepUp, runCommand, type Refusal } from "./calls";
import type { Member } from "./CommandForm";
import {
  commandRequest,
  isEndingCommand,
  isFormCommand,
  isSheetCommand,
  type ActionItem,
  type CommandRequest,
  type FormCommand,
  type FormInput,
  type SheetCommand,
} from "./model";
import { StepUp } from "./StepUp";

// The forms load when one opens (docs/spec/07 item 5: the tracker stays within the JS budget); they never render on
// the server, so React.lazy adds no layout shift.
const CommandForm = lazy(() => import("./CommandForm").then((m) => ({ default: m.CommandForm })));
const SideSheet = lazy(() => import("./SideSheet").then((m) => ({ default: m.SideSheet })));

export interface ActionsProps {
  engagementId: string;
  lockVersion: number;
  /** The caller's buttons, from the API's `actions` only (model.actionItems). */
  items: ActionItem[];
  /** The other party's name, for the confirmations. */
  counterpart: string;
  /** Two-step sign-in is on (the step-up needs a code). */
  enrolled: boolean;
  /** approve: the organisation's members; null when they could not be read. */
  members?: Member[] | null;
  myUserId?: string;
  /** The recorded final payment ("250,000"), for the developer's confirmation hint. */
  recorded?: string | null;
  /** answer_info: the organisation's open question and the day it was asked. */
  question?: { body: string; date: string } | null;
  /** resume: the day the hold was due to end. */
  resumeOn?: string | null;
  /** The page's language, for the dates and counts the sheets write. */
  locale?: string;
  runImpl?: typeof runCommand;
  confirmImpl?: typeof confirmStepUp;
}

type Mode =
  | { kind: "list" }
  | { kind: "form"; item: ActionItem & { command: FormCommand } }
  | { kind: "sheet"; item: ActionItem & { command: SheetCommand } }
  | { kind: "confirm"; item: ActionItem }
  | { kind: "stepUp"; item: ActionItem; request: CommandRequest };

type Notice = { tone: "ok" | "error"; refusal?: Refusal } | null;

/**
 * The caller's action buttons (docs/spec/06 6.9: "the action button appears only for that party"): one per command in
 * the API's `actions`, the awaited one primary. Commands with a body open their form, ending steps ask first, and
 * signatures, endorsements and payments ask for a fresh authenticator code when the API says so (403
 * step_up_required), then run once more. A 409 (the engagement changed, or the step is no longer possible) and a 404
 * refresh the page and say so.
 */
export function Actions(props: ActionsProps) {
  const t = useStrings("trackerActions");
  const router = useRouter();
  const { runImpl = runCommand } = props;
  const [mode, setMode] = useState<Mode>({ kind: "list" });
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice>(null);
  const noticeRef = useRef<HTMLDivElement>(null);
  // The step-up retries its step once, and only while its form is still open (not after Cancel or a refresh).
  const stepUpOpen = useRef(false);

  // A refreshed engagement brings new buttons: the list is what the API allows now (adjusted while rendering, as
  // React recommends for state that follows a prop).
  const [seenVersion, setSeenVersion] = useState(props.lockVersion);
  if (seenVersion !== props.lockVersion) {
    setSeenVersion(props.lockVersion);
    setMode({ kind: "list" });
  }

  useEffect(() => {
    if (notice) noticeRef.current?.focus();
  }, [notice]);

  // Focus follows what opened (WCAG 2.4.3): a form or confirmation takes it on its heading (the step-up on its code
  // field), and Cancel gives it back to the button that opened it.
  const root = useRef<HTMLDivElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const opener = useRef<string | null>(null);
  const returnFocus = useRef(false);
  useEffect(() => {
    if (mode.kind === "form" || mode.kind === "confirm") heading.current?.focus();
    if (mode.kind === "list" && returnFocus.current) {
      returnFocus.current = false;
      const button = root.current?.querySelector<HTMLElement>(`[data-action-key="${opener.current}"]`);
      button?.focus();
    }
  }, [mode.kind]);

  function cancel() {
    stepUpOpen.current = false;
    setNotice(null);
    returnFocus.current = true;
    setMode({ kind: "list" });
  }

  function requestFor(item: ActionItem, input?: FormInput): CommandRequest {
    return commandRequest(item.command, props.engagementId, props.lockVersion, { milestoneId: item.milestone?.id, input });
  }

  async function run(item: ActionItem, request: CommandRequest, retried = false) {
    if (busy && !retried) return;
    setBusy(true);
    setNotice(null);
    const outcome = await runImpl(request);
    setBusy(false);
    if (outcome.ok) {
      setMode({ kind: "list" });
      setNotice({ tone: "ok" });
      router.refresh();
      return;
    }
    if (outcome.refusal === "stepUp" && !retried) {
      stepUpOpen.current = true;
      setMode({ kind: "stepUp", item, request });
      return;
    }
    // A form or sheet stays open with its refusal when the input was refused (a hold's date past what is left of
    // the engagement's days on hold too); everything else goes back to the buttons.
    const keepForm =
      (mode.kind === "form" || mode.kind === "sheet") &&
      (outcome.status === 422 || outcome.refusal === "paymentMismatch" || outcome.refusal === "holdLimit");
    if (!keepForm) setMode({ kind: "list" });
    setNotice({ tone: "error", refusal: outcome.refusal === "stepUp" ? "generic" : outcome.refusal });
    if (outcome.status === 409 || outcome.status === 404) router.refresh();
  }

  function press(item: ActionItem) {
    setNotice(null);
    opener.current = keyOf(item);
    if (isFormCommand(item.command)) setMode({ kind: "form", item: item as ActionItem & { command: FormCommand } });
    else if (isSheetCommand(item.command)) setMode({ kind: "sheet", item: item as ActionItem & { command: SheetCommand } });
    else if (isEndingCommand(item.command)) setMode({ kind: "confirm", item });
    else void run(item, requestFor(item));
  }

  const message = notice ? (
    <Alert ref={noticeRef} tone={notice.tone} className="w-full">
      {notice.tone === "ok" ? t("done") : t(`refusal.${notice.refusal ?? "generic"}`)}
    </Alert>
  ) : null;

  // The list's notice sits outside the section, so "Done" stays (with focus) when the step leaves no buttons. A sheet
  // stays over the list (the page behind it inert) and shows its own refusals.
  const listNotice = mode.kind === "list" ? message : null;
  const listed = mode.kind === "list" || mode.kind === "sheet";
  return (
    <div ref={root} className="flex flex-col gap-4">
      {listNotice}
      {props.items.length === 0 && listed ? null : (
    <section aria-labelledby="actions-heading" data-actions="" className="flex flex-col gap-4">
      <h2 id="actions-heading" ref={heading} tabIndex={-1} className="text-lg text-ink">
        {listed ? t("title") : label(mode.item)}
      </h2>

      {listed ? (
        <>
          <ul className="flex flex-col gap-3 sm:flex-row sm:flex-wrap">
            {props.items.map((item) => (
              <li key={`${item.command}-${item.milestone?.id ?? ""}`}>
                {/* Ending steps (withdraw, decline) are the danger variant: outlined in the error colour, never filled. */}
                {isEndingCommand(item.command) ? (
                  <Button
                    variant="danger"
                    busy={busy}
                    className="w-full sm:w-auto"
                    onClick={() => press(item)}
                    data-command={item.command}
                    data-action-key={keyOf(item)}
                  >
                    {label(item)}
                  </Button>
                ) : (
                  <Button
                    variant={item.primary ? "primary" : "secondary"}
                    busy={busy}
                    className="w-full sm:w-auto"
                    onClick={() => press(item)}
                    data-command={item.command}
                    data-action-key={keyOf(item)}
                    data-milestone={item.milestone?.seq}
                  >
                    {busy && item.primary ? t("busy") : label(item)}
                  </Button>
                )}
              </li>
            ))}
          </ul>
        </>
      ) : null}

      {mode.kind === "confirm" ? (
        <div className="flex flex-col gap-4">
          <p className="max-w-[60ch] text-ink">{t(`confirm.${endingKey(mode.item.command)}`, { name: props.counterpart })}</p>
          {message}
          <div className="flex flex-col gap-3 sm:flex-row">
            <Button
              variant="danger"
              busy={busy}
              className="w-full sm:w-auto"
              onClick={() => void run(mode.item, requestFor(mode.item))}
            >
              {busy ? t("busy") : label(mode.item)}
            </Button>
            <Button variant="secondary" onClick={cancel}>
              {t("cancel")}
            </Button>
          </div>
        </div>
      ) : null}

      {mode.kind === "form" ? (
        <Suspense fallback={<p className="text-ink-soft">{t("busy")}</p>}>
          <CommandForm
            command={mode.item.command}
            busy={busy}
            notice={message}
            members={props.members}
            myUserId={props.myUserId}
            recorded={props.recorded}
            onCancel={cancel}
            onSubmit={(input) => void run(mode.item, requestFor(mode.item, input))}
          />
        </Suspense>
      ) : null}

      {mode.kind === "sheet" ? (
        <Suspense fallback={null}>
          <SideSheet
            command={mode.item.command}
            busy={busy}
            problem={message}
            counterpart={props.counterpart}
            question={props.question}
            resumeOn={props.resumeOn}
            locale={props.locale}
            onClose={cancel}
            onSubmit={(input) => void run(mode.item, requestFor(mode.item, input as FormInput))}
          />
        </Suspense>
      ) : null}

      {mode.kind === "stepUp" ? (
        <StepUp
          enrolled={props.enrolled}
          onCancel={cancel}
          onConfirmed={async () => {
            if (!stepUpOpen.current) return;
            stepUpOpen.current = false;
            await run(mode.item, mode.request, true);
          }}
          confirmImpl={props.confirmImpl}
        />
      ) : null}
    </section>
      )}
    </div>
  );

  function label(item: ActionItem): string {
    return item.milestone
      ? t(`milestone.${item.command as "start_milestone"}`, { number: item.milestone.seq })
      : t(`command.${item.command}`);
  }
}

/** A button's identity across renders: its command, and its milestone for the sub-tracker's. */
function keyOf(item: ActionItem): string {
  return item.milestone ? `${item.command}:${item.milestone.id}` : item.command;
}

function endingKey(command: ActionItem["command"]): "withdraw" | "decline_interest" | "decline" {
  return command === "withdraw" ? "withdraw" : command === "decline_interest" ? "decline_interest" : "decline";
}
