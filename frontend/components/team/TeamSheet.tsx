"use client";

import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Avatar } from "@/components/ui/Avatar";
import { Button, buttonClass } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { SheetHandle, sheetClass } from "@/components/ui/ConfirmDialog";
import { TextField } from "@/components/ui/TextField";
import { formatDay } from "@/lib/format";

import {
  NOTE_MAX,
  STANCES,
  teamCalls,
  type Stance,
  type Team,
  type TeamCalls,
  type TeamOutcome,
  type TeamRefusal,
} from "./calls";

// The Team sheet (REQ-ENG-15; D-68; docs/spec/03 roles: a reviewer "may Recommend internally without changing state"):
// over the organisation's tracker, a native modal <dialog> drawn as the tracker's other sheets are (a bottom sheet on
// phones, D-52). It reads GET …/team when it opens: who the engagement may be assigned to (owners, admins,
// reviewers and signatories), who it is assigned to and every member's recommendation with its note; an owner,
// admin, reviewer or signatory also assigns it and says their own view. Nothing here reaches the developer: the
// sheet is mounted only on the organisation's tracker, and its calls are under /api/orgs/{org_id}. Loaded when it
// opens (components/tracker/lazy.tsx), so the tracker's first load carries none of it.

export interface TeamSheetProps {
  orgId: string;
  engagementId: string;
  /** The caller is an owner, admin, reviewer or signatory: they may assign and recommend (the API decides again). */
  canTriage: boolean;
  myUserId: string;
  /** Where focus lands when it opens: the assignment, or the recommendations. */
  focus?: "assign" | "recommendations";
  locale?: string;
  /** The sheet closed; `changed` when anything was saved (the tracker behind it refreshes). */
  onClose: (changed: boolean) => void;
  calls?: Partial<TeamCalls>;
}

type Said = { tone: "ok" | "error"; text: string; n: number } | null;

const TRIAGE_ROLES = new Set(["owner", "admin", "reviewer", "signatory"]);
const NOBODY = "";

export function TeamSheet(props: TeamSheetProps) {
  const t = useStrings("teamSheet");
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const id = useId();
  const locale = props.locale ?? "en";
  const [calls] = useState<TeamCalls>(() => ({ ...teamCalls(props.orgId, props.engagementId), ...props.calls }));
  const [team, setTeam] = useState<Team | null>(null);
  const [failed, setFailed] = useState(false);
  const changed = useRef(false);
  // Each status line is a new one (its key), so a repeated refusal is said again.
  const said = useRef(0);
  const [busy, setBusy] = useState<"assign" | "save" | "remove" | null>(null);
  const [assignee, setAssignee] = useState<string | null>(null);
  const [stance, setStance] = useState<Stance | null>(null);
  const [note, setNote] = useState("");
  const [assignSaid, setAssignSaid] = useState<Said>(null);
  const [mineSaid, setMineSaid] = useState<Said>(null);
  const [noteError, setNoteError] = useState<string | undefined>();
  const [stanceError, setStanceError] = useState<string | undefined>();

  function take(next: Team) {
    setTeam(next);
    setAssignee(next.assignee?.user_id ?? NOBODY);
    const mine = next.recommendations.find((r) => r.user_id === props.myUserId);
    setStance(mine?.stance ?? null);
    setNote(mine?.note ?? "");
  }

  async function load() {
    setFailed(false);
    const outcome = await calls.read();
    if (outcome.ok) take(outcome.team);
    else setFailed(true);
  }

  // Opens as a modal once mounted, and reads the team.
  useEffect(() => {
    const dialog = ref.current;
    if (dialog && !dialog.open) dialog.showModal();
    dialog?.querySelector<HTMLElement>("[data-dialog-cancel]")?.focus();
    void calls.read().then((outcome) => (outcome.ok ? take(outcome.team) : setFailed(true)));
    // Once, on open.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Once the team is on screen, focus goes where the opener asked: the assignment or the recommendations.
  const placed = useRef(false);
  useEffect(() => {
    if (!team || placed.current) return;
    placed.current = true;
    const target =
      props.focus === "assign" && props.canTriage
        ? ref.current?.querySelector<HTMLElement>("input[name$='-assignee']:checked")
        : ref.current?.querySelector<HTMLElement>("[data-team-recommendations] h3");
    target?.focus();
  }, [team, props.focus, props.canTriage]);

  function refusalText(refusal: TeamRefusal): string {
    return t(`refusal.${refusal}`);
  }

  async function settle(outcome: TeamOutcome, say: (said: Said) => void, okText: (team: Team) => string) {
    if (outcome.ok) {
      changed.current = true;
      take(outcome.team);
      say({ tone: "ok", text: okText(outcome.team), n: ++said.current });
      return;
    }
    say({ tone: "error", text: refusalText(outcome.refusal), n: ++said.current });
    // Someone changed it at the same moment: show the latest, the refusal stays.
    if (outcome.refusal === "conflict") {
      const latest = await calls.read();
      if (latest.ok) take(latest.team);
    }
  }

  async function assign(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || assignee === null) return;
    setBusy("assign");
    setAssignSaid(null);
    const outcome = await calls.assign(assignee || null);
    setBusy(null);
    await settle(outcome, setAssignSaid, (next) =>
      next.assignee ? t("assigned", { name: next.assignee.display_name }) : t("unassignedDone"),
    );
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setNoteError(undefined);
    if (!stance) {
      setStanceError(t("chooseStance"));
      document.getElementById(`${id}-stance-pursue`)?.focus();
      return;
    }
    setStanceError(undefined);
    setBusy("save");
    setMineSaid(null);
    const outcome = await calls.recommend(stance, note);
    setBusy(null);
    if (!outcome.ok && outcome.refusal === "invalidNote") {
      setNoteError(refusalText("invalidNote"));
      document.getElementById(`${id}-note`)?.focus();
      return;
    }
    await settle(outcome, setMineSaid, () => t("saved"));
  }

  async function remove() {
    if (busy) return;
    setBusy("remove");
    setMineSaid(null);
    const outcome = await calls.withdraw();
    setBusy(null);
    await settle(outcome, setMineSaid, () => t("removed"));
  }

  const mine = team?.recommendations.find((r) => r.user_id === props.myUserId) ?? null;
  const others = team?.recommendations ?? [];
  const members = (team?.members ?? []).filter((m) => TRIAGE_ROLES.has(m.role));
  const name = (person: { user_id: string; display_name: string }) =>
    person.user_id === props.myUserId ? t("you", { name: person.display_name }) : person.display_name;
  const count = new Intl.NumberFormat(`${locale}-KE`);

  let body: ReactNode;
  if (failed) {
    body = (
      <div role="alert" className="flex flex-col items-start gap-3">
        <p className="text-ink">{t("failed")}</p>
        <Button variant="secondary" onClick={() => void load()}>
          {t("retry")}
        </Button>
      </div>
    );
  } else if (!team) {
    // A skeleton of the list it is about to show (three rows), said once for screen readers.
    body = (
      <div aria-busy="true" data-team-loading="">
        <p className="sr-only" role="status">
          {t("loading")}
        </p>
        <div aria-hidden="true" className="flex flex-col gap-3">
          {[0, 1, 2].map((row) => (
            <div key={row} className="flex items-center gap-3">
              <span className="size-9 rounded-full bg-line" />
              <span className="h-3 w-40 rounded-full bg-line" />
            </div>
          ))}
        </div>
      </div>
    );
  } else {
    body = (
      <div className="flex flex-col gap-7">
        {/* Who it is assigned to: a choice for the triage roles, a sentence for the others. */}
        {props.canTriage ? (
          <form noValidate onSubmit={(event) => void assign(event)} data-team-assign="" className="flex flex-col gap-3">
            <fieldset className="flex flex-col gap-2">
              <legend className="mb-1 font-semibold text-ink">{t("assignLegend")}</legend>
              {[{ user_id: NOBODY, display_name: t("nobody"), role: null as string | null }, ...members].map(
                (member) => {
                  const optionId = `${id}-assignee-${member.user_id || "nobody"}`;
                  return (
                    <label
                      key={member.user_id || "nobody"}
                      htmlFor={optionId}
                      data-member={member.user_id || "nobody"}
                      className={cn(
                        "flex min-h-12 cursor-pointer items-center gap-3 rounded-control border border-line bg-field px-3 py-2",
                        "has-checked:border-accent has-checked:bg-accent-wash",
                        "has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-accent",
                      )}
                    >
                      <input
                        id={optionId}
                        type="radio"
                        name={`${id}-assignee`}
                        value={member.user_id}
                        checked={assignee === member.user_id}
                        onChange={() => {
                          setAssignee(member.user_id);
                          setAssignSaid(null);
                        }}
                        className="size-5 shrink-0 cursor-pointer accent-accent focus-visible:outline-none"
                      />
                      {member.user_id ? <Avatar name={member.display_name} size="sm" /> : null}
                      <span className="min-w-0 flex-1 [overflow-wrap:anywhere] text-ink">
                        {member.user_id ? name(member) : member.display_name}
                      </span>
                      {member.role ? (
                        <span className="shrink-0 text-sm text-ink-soft">{t(`role.${member.role as "owner"}`)}</span>
                      ) : null}
                    </label>
                  );
                },
              )}
            </fieldset>
            {assignSaid ? (
              <Alert key={assignSaid.n} tone={assignSaid.tone}>
                {assignSaid.text}
              </Alert>
            ) : null}
            <div>
              <button
                type="submit"
                aria-disabled={busy !== null || undefined}
                className={buttonClass("secondary", "w-full sm:w-auto")}
              >
                {busy === "assign" ? t("assigning") : t("assign")}
              </button>
            </div>
          </form>
        ) : (
          <p className="text-ink" data-team-assignee="">
            {team.assignee ? t("assignedTo", { name: name(team.assignee) }) : t("nobodyAssigned")}
          </p>
        )}

        <section data-team-recommendations="" aria-labelledby={`${id}-recs`} className="flex flex-col gap-3">
          <h3 id={`${id}-recs`} tabIndex={-1} className="font-semibold text-ink focus-visible:outline-none">
            {t("recommendations")}
          </h3>
          {others.length === 0 ? (
            <p className="text-ink-soft">{t("noRecommendations")}</p>
          ) : (
            <ul className="flex flex-col divide-y divide-line">
              {others.map((rec) => (
                <li key={rec.user_id} data-recommendation={rec.stance} className="flex gap-3 py-3 first:pt-0">
                  <Avatar name={rec.display_name} size="sm" />
                  <div className="min-w-0 flex-1">
                    <p className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
                      <span className="font-semibold [overflow-wrap:anywhere] text-ink">{name(rec)}</span>
                      <span className="text-ink">{t(`stance.${rec.stance}`)}</span>
                      <time dateTime={rec.updated_at} className="text-sm text-ink-soft">
                        {formatDay(locale, rec.updated_at)}
                      </time>
                    </p>
                    {/* The note is the member's own words: text only, never markup. */}
                    {rec.note ? <p className="mt-1 [overflow-wrap:anywhere] text-ink-soft">{rec.note}</p> : null}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        {props.canTriage ? (
          <form
            noValidate
            onSubmit={(event) => void save(event)}
            data-team-mine=""
            className="flex flex-col gap-4 border-t border-line pt-6"
          >
            <div>
              <h3 className="font-semibold text-ink">{t("mineTitle")}</h3>
              <p className="text-sm text-ink-soft">{t("mineLead")}</p>
            </div>
            <fieldset aria-describedby={stanceError ? `${id}-stance-error` : undefined}>
              <legend className="mb-2 font-medium text-ink">{t("stanceLegend")}</legend>
              {stanceError ? (
                <p id={`${id}-stance-error`} className="mb-2 text-sm font-medium text-error">
                  {stanceError}
                </p>
              ) : null}
              {/* Three segments of one control: each a radio, 44 px tall, the chosen one filled with the accent wash. */}
              <div className="grid grid-cols-3 overflow-hidden rounded-control border border-ink-soft">
                {STANCES.map((value) => (
                  <label
                    key={value}
                    htmlFor={`${id}-stance-${value}`}
                    data-stance={value}
                    className={cn(
                      "flex min-h-11 cursor-pointer items-center justify-center border-l border-ink-soft px-2 text-center font-semibold text-ink first:border-l-0",
                      "has-checked:bg-accent has-checked:text-on-accent",
                      "has-focus-visible:outline-2 has-focus-visible:-outline-offset-4 has-focus-visible:outline-on-accent has-focus-visible:not-has-checked:outline-accent",
                    )}
                  >
                    <input
                      id={`${id}-stance-${value}`}
                      type="radio"
                      name={`${id}-stance`}
                      value={value}
                      checked={stance === value}
                      onChange={() => {
                        setStance(value);
                        setStanceError(undefined);
                      }}
                      className="sr-only"
                    />
                    {t(`stance.${value}`)}
                  </label>
                ))}
              </div>
            </fieldset>
            <TextField
              id={`${id}-note`}
              label={t("note")}
              hint={t("noteHint", { count: count.format(Array.from(note).length), max: count.format(NOTE_MAX) })}
              maxLength={NOTE_MAX}
              autoComplete="off"
              value={note}
              error={noteError}
              onChange={(event) => {
                setNote(event.currentTarget.value);
                setNoteError(undefined);
              }}
            />
            {mineSaid ? (
              <Alert key={mineSaid.n} tone={mineSaid.tone}>
                {mineSaid.text}
              </Alert>
            ) : null}
            <div className="flex flex-col gap-3 sm:flex-row sm:justify-end">
              {mine ? (
                <Button variant="secondary" busy={busy !== null} onClick={() => void remove()} data-team-remove="">
                  {busy === "remove" ? t("removing") : t("remove")}
                </Button>
              ) : null}
              <button
                type="submit"
                aria-disabled={busy !== null || undefined}
                className={buttonClass("primary")}
                data-team-save=""
              >
                {busy === "save" ? t("saving") : t("save")}
              </button>
            </div>
          </form>
        ) : null}
      </div>
    );
  }

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onClose={() => props.onClose(changed.current)}
      data-sheet=""
      data-team-sheet=""
      className={cn(sheetClass("lg"), "max-sm:max-h-[92dvh]")}
    >
      <SheetHandle />
      <h2 id={titleId} className="text-lg text-ink">
        {t("title")}
      </h2>
      <p className="mt-1 text-sm text-ink-soft">{t("private")}</p>
      <span aria-live="polite" className="sr-only">
        {busy ? t("working") : ""}
      </span>
      <div className="mt-5">{body}</div>
      <div className="mt-6 flex justify-end border-t border-line pt-4">
        <Button
          variant="secondary"
          onClick={() => ref.current?.close()}
          data-dialog-cancel=""
          className="w-full sm:w-auto"
        >
          {t("close")}
        </Button>
      </div>
    </dialog>
  );
}
