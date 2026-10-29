"use client";

import { useEffect, useRef, useState } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { ConfirmDialog, openConfirm } from "@/components/ui/ConfirmDialog";
import { RadioGroup } from "@/components/ui/RadioGroup";
import { TextAreaField } from "@/components/ui/TextAreaField";
import { TextField } from "@/components/ui/TextField";

import type { TeamCalls } from "../teams/calls";
import { charCount, NOTE_MAX, pluralForm, type InviteRefusal, type Peer, type ProblemCard } from "../teams/teams";

const SEARCH_ID = "team-up-search";
const NOTE_ID = "team-up-note";
/** Typing settles this long before the search runs. */
const SETTLE_MS = 300;
/** The note's count shows from this many characters before the limit. */
const METER_FROM = 100;

/**
 * The Team up sheet (REQ-DEV-03; D-58): one field to find the problem or Brief (the newest published ones first, then
 * those whose words match what is typed, five at a time, one chosen), an optional note of up to 300 characters, and
 * "Send invitation" as its one action. A refusal is one sentence above the buttons. It opens as a modal on mount and
 * reports once it closes: `onDone(true)` when the invitation went.
 */
export function TeamUpSheet({
  peer,
  locale,
  calls,
  onDone,
}: {
  peer: Peer;
  locale: string;
  calls: Pick<TeamCalls, "problems" | "invite">;
  onDone: (sent: boolean) => void;
}) {
  const t = useStrings("teamUp");
  const dialog = useRef<HTMLDialogElement>(null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<ProblemCard[] | null>(null);
  const [search, setSearch] = useState<"busy" | "idle" | "failed">("busy");
  const [chosen, setChosen] = useState<ProblemCard | null>(null);
  const [note, setNote] = useState("");
  const [problem, setProblem] = useState<InviteRefusal | "choose" | null>(null);
  const [busy, setBusy] = useState(false);
  const sent = useRef(false);
  const asked = useRef(0);

  useEffect(() => {
    openConfirm(dialog.current);
    // A form sheet: focus goes to its first field, not to Cancel.
    document.getElementById(SEARCH_ID)?.focus();
  }, []);

  useEffect(() => {
    const ask = ++asked.current;
    const timer = setTimeout(
      async () => {
        setSearch("busy");
        const found = await calls.problems(query);
        if (ask !== asked.current) return;
        setResults(found ?? []);
        setSearch(found ? "idle" : "failed");
      },
      query ? SETTLE_MS : 0,
    );
    return () => clearTimeout(timer);
  }, [calls, query]);

  async function send() {
    if (busy) return;
    if (!chosen) {
      setProblem("choose");
      return;
    }
    if (charCount(note.trim()) > NOTE_MAX) {
      setProblem("noteTooLong");
      document.getElementById(NOTE_ID)?.focus();
      return;
    }
    setBusy(true);
    setProblem(null);
    const outcome = await calls.invite(peer.user_id, chosen.id, note);
    setBusy(false);
    if (!outcome.ok) {
      setProblem(outcome.refusal);
      return;
    }
    sent.current = true;
    dialog.current?.close();
  }

  // The chosen problem stays listed while other words are searched.
  const shown = chosen && results && !results.some((item) => item.id === chosen.id) ? [chosen, ...results] : (results ?? []);
  const left = NOTE_MAX - charCount(note);
  const legend = query.trim() ? t("sheet.results") : t("sheet.suggested");

  return (
    <ConfirmDialog
      ref={dialog}
      size="lg"
      title={t("sheet.title", { name: peer.handle })}
      confirmLabel={t("sheet.send")}
      busyLabel={t("sheet.sending")}
      cancelLabel={t("sheet.cancel")}
      busy={busy}
      onConfirm={() => void send()}
      problem={problem ? <Alert>{problem === "choose" ? t("sheet.choose") : t(`refusal.${problem}`)}</Alert> : null}
      onClose={() => onDone(sent.current)}
      bodyProps={{ "data-team-up-sheet": "", className: "flex flex-col gap-5" }}
    >
      <p className="text-ink-soft">{t("sheet.lead")}</p>
      <TextField
        id={SEARCH_ID}
        type="search"
        label={t("sheet.search")}
        hint={t("sheet.searchHint")}
        value={query}
        maxLength={100}
        autoComplete="off"
        onChange={(event) => setQuery(event.currentTarget.value)}
      />
      <div className="flex flex-col gap-2" data-problem-results="">
        <p aria-live="polite" className="text-sm text-ink-soft empty:hidden">
          {search === "busy" ? t("sheet.searching") : search === "failed" ? t("sheet.searchFailed") : shown.length === 0 ? t("sheet.none") : ""}
        </p>
        {shown.length > 0 ? (
          <RadioGroup<string>
            id="team-up-problem"
            name="team-up-problem"
            legend={legend}
            value={chosen?.id ?? null}
            onChange={(id) => {
              setChosen(shown.find((item) => item.id === id) ?? null);
              if (problem === "choose") setProblem(null);
            }}
            options={shown.map((item) => ({ value: item.id, label: item.title, hint: item.niche?.label ?? undefined }))}
          />
        ) : null}
      </div>
      <TextAreaField
        id={NOTE_ID}
        label={t("sheet.note")}
        hint={t("sheet.noteHint")}
        rows={3}
        value={note}
        onChange={(event) => {
          setNote(event.currentTarget.value);
          if (problem === "noteTooLong") setProblem(null);
        }}
        meter={
          left <= METER_FROM ? (
            <span data-meter={left < 0 ? "over" : "left"} className={left < 0 ? "font-semibold text-error" : undefined}>
              {left < 0
                ? t(`sheet.meterOver.${pluralForm(-left, locale)}`, { count: -left })
                : t(`sheet.meterLeft.${pluralForm(left, locale)}`, { count: left })}
            </span>
          ) : undefined
        }
      />
    </ConfirmDialog>
  );
}
