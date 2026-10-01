"use client";

import Link from "next/link";
import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode, type Ref } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button, standaloneLinkClass } from "@/components/ui/Button";
import { ButtonLink } from "@/components/ui/ButtonLink";
import { cn } from "@/components/ui/cn";
import { ClockIcon, SendIcon } from "@/components/ui/status-icons";
import { upgradeHref } from "@/lib/billing/upgrade";
import { useHydrated } from "@/lib/hooks/useHydrated";

import { pitch as pitchCall } from "./calls";
import {
  capBinds,
  heldKey,
  orgKey,
  pitchesLeft,
  pitchHref,
  selectionMax,
  type PitchReason,
  type PitchResult,
  type TagCap,
} from "./picker";
import type { PitchProblem, PitchRefusal } from "./refusals";
import { StandaloneLink } from "@/components/ui/StandaloneLink";

/**
 * One organisation as the picker lists it. `about` (type, county, badge) and `outcome` (sent now, or saved until it
 * verifies, or why it cannot be pitched) are drawn on the server.
 */
export interface PickerRow {
  id: string;
  name: string;
  available: boolean;
  about: ReactNode;
  outcome: ReactNode;
}

export interface PickerGroup {
  key: string;
  /** The niche's two-level name ("ICT › Networks & Telecommunications"), one line: no label above the heading. */
  name: string;
  rows: PickerRow[];
}

export interface PitchFormProps {
  proposalId: string;
  ideaHref: string;
  cap: TagCap;
  groups: PickerGroup[];
  /** Organisations chosen on another page or search, resolved by id on the server: shown first, by name. */
  chosen?: PickerRow[];
  /** The URL's `sel`. Only ids shown on this page as available rows (here or under "chosen") become choices. */
  initialSelected: string[];
  /** The search and niche fields, drawn on the server; submitted with the form as a GET, choices included. */
  filters: ReactNode;
  /** A search or a niche narrows the list: offer to clear it (keeping the choices). */
  narrowed: boolean;
  cursor?: string;
  nextCursor?: string | null;
  pitchImpl?: typeof pitchCall;
}

type Problem = PitchProblem | "chooseOne";
type Shown = { problem: Problem; refusal?: PitchRefusal; local?: { count: number; limit: number } };
type Blocked = PitchReason | "gone";

/**
 * The choices a page starts with: the URL's ids that this page shows as available rows, by name and with their
 * outcome, up to what one Pitch may hold. Anything else (an id on no row, an unavailable one, one over the cap) is
 * dropped, so the Pitch never sends an organisation the developer has not seen.
 */
export function initialChoices(ids: readonly string[], rows: readonly PickerRow[], cap: TagCap): Set<string> {
  const shown = new Set(rows.filter((row) => row.available).map((row) => orgKey(row.id)));
  const out = new Set<string>();
  for (const id of ids) {
    if (out.size >= selectionMax(cap)) break;
    if (shown.has(orgKey(id))) out.add(orgKey(id));
  }
  return out;
}

/**
 * "Pitch to companies" (REQ-PROP-03, docs/spec/06 6.3): the directory by niche with a checkbox per organisation. One GET
 * form holds the search, the niche, the page and the choices; choices made on another page or search come back as
 * their own group, first, each by name with its outcome, and can be unticked there. "Pitch" (the screen's one primary
 * action) sends them all at once, within the batch of 20 and the plan's cap. The API refuses a batch whole, so a
 * refusal means nothing was sent: one sentence and at most one action above the list (the sticky bar stays the
 * summary and Pitch), and a 409's organisations are unticked with their reasons. After a Pitch the form gives way to
 * what was sent now and what is saved.
 */
export function PitchForm({
  proposalId,
  ideaHref,
  cap,
  groups,
  chosen = [],
  initialSelected,
  filters,
  narrowed,
  cursor,
  nextCursor,
  pitchImpl = pitchCall,
}: PitchFormProps) {
  const t = useStrings("pitch");
  const hydrated = useHydrated();
  const rows = [...chosen, ...groups.flatMap((group) => group.rows)];
  const [capNow, setCapNow] = useState(cap);
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => initialChoices(initialSelected, rows, cap));
  const [blocked, setBlocked] = useState<ReadonlyMap<string, Blocked>>(() => new Map());
  const [busy, setBusy] = useState(false);
  const [shown, setShown] = useState<Shown | null>(null);
  const [result, setResult] = useState<PitchResult | null>(null);
  const resultHeading = useRef<HTMLHeadingElement>(null);
  const notice = useRef<HTMLDivElement>(null);
  const summaryId = useId();

  // What was sent and saved replaces the form: its heading takes focus, so it is read out and the page starts there.
  useEffect(() => {
    if (result) resultHeading.current?.focus();
  }, [result]);
  // A refusal sits above the list, in the page's flow: it takes focus, so it is in view and read out.
  useEffect(() => {
    if (shown) notice.current?.focus();
  }, [shown]);

  const max = selectionMax(capNow);
  const atMax = selected.size >= max;
  const locked = !hydrated || busy;

  function toggle(id: string, on: boolean) {
    setShown(null);
    setSelected((current) => {
      const next = new Set(current);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  function refuse(ids: Iterable<[string, Blocked]>) {
    const next = new Map(blocked);
    for (const [id, why] of ids) next.set(id, why);
    setBlocked(next);
    setSelected((current) => new Set([...current].filter((id) => !next.has(id))));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    const submitter = (event.nativeEvent as SubmitEvent).submitter;
    if (!(submitter instanceof HTMLElement) || submitter.dataset.intent !== "pitch") return; // search or paging: a GET
    event.preventDefault();
    if (busy) return;
    if (selected.size === 0) {
      setShown({ problem: "chooseOne" });
      return;
    }
    if (selected.size > max) {
      // The cap fell (a 402 said so): nothing goes out until the choices fit.
      setShown({ problem: "planLimit", local: { count: max, limit: capNow.limit ?? max } });
      return;
    }
    setBusy(true);
    setShown(null);
    const outcome = await pitchImpl(proposalId, [...selected]);
    setBusy(false);
    if (outcome.ok) {
      setResult(outcome.value);
      return;
    }
    if (outcome.conflicts.length > 0) refuse(outcome.conflicts.map((c) => [c.orgId, c.reason] as [string, Blocked]));
    if (outcome.gone?.length) refuse(outcome.gone.map((id) => [id, "gone"] as [string, Blocked]));
    if (outcome.problem === "planLimit" && outcome.limit !== undefined && outcome.used !== undefined) {
      setCapNow({ ...capNow, limit: outcome.limit, used: outcome.used });
    }
    setShown({ problem: outcome.problem, refusal: outcome });
  }

  if (result) {
    return <PitchDone result={result} ideaHref={ideaHref} againHref={pitchHref(proposalId)} headingRef={resultHeading} />;
  }

  const left = pitchesLeft(capNow);
  const rowProps = (row: PickerRow, rowId: string) => ({
    rowId,
    row,
    checked: selected.has(orgKey(row.id)),
    reason: blocked.get(orgKey(row.id)),
    locked: locked || (atMax && !selected.has(orgKey(row.id))),
    onToggle: toggle,
  });
  return (
    // The form starts at the lead, not at the search field: a sticky element stays inside its containing block, so a
    // form that began lower held the Pitch bar under the tab bar at 360 x 640 (P16-C1 fix round 1, ux item 11).
    <form method="get" onSubmit={submit}>
      <p className="mt-3 max-w-[62ch] text-ink-soft">{t("lead", { max })}</p>
      <p className="mt-3 text-ink" data-cap="">
        {left === null ? t("capUnlimited") : t("capLeft", { count: left, limit: capNow.limit ?? 0 })}
      </p>
        {/* Nothing changes the list while a Pitch is under way. */}
        <fieldset disabled={busy} className="m-0 mt-6 max-w-3xl min-w-0 border-0 p-0">
          <div role="search">{filters}</div>
          {narrowed ? (
            <p className="mt-2">
              <a
                href={busy ? undefined : pitchHref(proposalId, { selected: [...selected] })}
                aria-disabled={busy || undefined}
                className={standaloneLinkClass}
              >
                {t("clear")}
              </a>
            </p>
          ) : null}
        </fieldset>

        <div className="mt-6 flex flex-col gap-2 empty:hidden">
          {shown ? <Refused shown={shown} proposalId={proposalId} ideaHref={ideaHref} alertRef={notice} /> : null}
          {atMax && max > 0 ? (
            <p role="status" className="text-ink" data-max-reached="">
              {capBinds(capNow) ? t("maxReachedPlan") : t("maxReachedBatch")}
            </p>
          ) : null}
        </div>

        <div className="mt-8">
          {chosen.length > 0 ? (
            <section className="mb-10" aria-labelledby="pitch-chosen" data-chosen-group="">
              <h2 id="pitch-chosen" className="text-lg text-ink">
                {t("chosenTitle")}
              </h2>
              <ul className="mt-2 grid grid-cols-1 gap-x-10 md:grid-cols-2">
                {chosen.map((row) => (
                  <Row {...rowProps(row, `c-${row.id}`)} key={row.id} />
                ))}
              </ul>
            </section>
          ) : null}
          {groups.map((group, index) => (
            <section key={group.key} className="mt-10 first:mt-0" aria-labelledby={`pitch-group-${index}`}>
              <h2 id={`pitch-group-${index}`} className="text-lg text-ink">
                {group.name}
              </h2>
              <ul className="mt-2 grid grid-cols-1 gap-x-10 md:grid-cols-2">
                {group.rows.map((row) => (
                  <Row {...rowProps(row, `${index}-${row.id}`)} key={row.id} />
                ))}
              </ul>
            </section>
          ))}
        </div>

        {cursor || nextCursor ? (
          <fieldset disabled={busy} className="m-0 min-w-0 border-0 p-0">
            <nav aria-label={t("pages")} className="mt-10 flex flex-wrap items-center justify-between gap-x-8 gap-y-2">
              {cursor ? (
                <button type="submit" name="cursor" value="" className={standaloneLinkClass}>
                  {t("firstPage")}
                </button>
              ) : (
                <span />
              )}
              {nextCursor ? (
                <button type="submit" name="cursor" value={nextCursor} className={standaloneLinkClass}>
                  {t("nextPage")}
                </button>
              ) : null}
            </nav>
          </fieldset>
        ) : null}

        {/* The summary and Pitch only: its height stays within the scroll padding of globals.css. */}
        <div
          data-action-bar=""
          className={cn(
            // Above the tab bar: its 56 px tabs, its 1 px top border and the safe area.
            "sticky bottom-[calc(3.5rem+1px+env(safe-area-inset-bottom))] z-[5] -mx-4 mt-8 border-t border-line bg-paper",
            "px-4 pt-3 pb-4 sm:-mx-6 sm:px-6 lg:bottom-0 lg:mx-0 lg:px-0",
          )}
        >
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p id={summaryId} aria-live="polite" className="font-semibold text-ink tabular-nums">
              {t("chosen", { count: selected.size, max })}
            </p>
            <Button
              type="submit"
              variant="primary"
              data-intent="pitch"
              aria-describedby={summaryId}
              busy={busy}
              disabled={!hydrated}
              className="shrink-0"
            >
              {busy ? t("submitting") : t("submit")}
            </Button>
          </div>
        </div>
    </form>
  );
}

function Row({
  rowId,
  row,
  checked,
  reason,
  locked,
  onToggle,
}: {
  rowId: string;
  row: PickerRow;
  checked: boolean;
  reason?: Blocked;
  locked: boolean;
  onToggle: (id: string, on: boolean) => void;
}) {
  const t = useStrings("pitch");
  const available = row.available && reason === undefined;
  return (
    <li
      data-org-row={row.id}
      className={cn(
        "relative flex min-w-0 flex-col gap-1 border-t border-line py-4 pr-2 pl-9",
        checked && "bg-accent-wash shadow-[inset_3px_0_0_var(--accent)]",
      )}
    >
      <label
        htmlFor={`pitch-${rowId}`}
        className={cn(
          "-my-2 flex min-h-11 items-center py-2 font-semibold [overflow-wrap:anywhere] text-ink",
          // The whole row toggles the box (a 44 px target at least; docs/spec/07 item 6).
          available && "cursor-pointer after:absolute after:inset-0",
          !available && "text-ink-soft",
        )}
      >
        <input
          id={`pitch-${rowId}`}
          type="checkbox"
          name="sel"
          value={row.id}
          checked={checked}
          disabled={!available || (locked && !checked)}
          onChange={(event) => {
            if (available) onToggle(orgKey(row.id), event.target.checked); // an unavailable row never joins the Pitch
          }}
          aria-describedby={`pitch-${rowId}-details`}
          className="absolute top-[1.35rem] left-2 z-[1] size-5 cursor-pointer accent-accent disabled:cursor-not-allowed"
        />
        {row.name}
      </label>
      <div id={`pitch-${rowId}-details`} className="flex flex-col gap-1">
        {row.about}
        {reason === undefined ? (
          row.outcome
        ) : (
          <p className="text-sm text-error" data-reason={reason}>
            {reason === "gone" ? t("gone", { name: row.name }) : t(`reason.${reason}`, { name: row.name })}
          </p>
        )}
      </div>
    </li>
  );
}

function Refused({
  shown,
  proposalId,
  ideaHref,
  alertRef,
}: {
  shown: Shown;
  proposalId: string;
  ideaHref: string;
  alertRef: Ref<HTMLDivElement>;
}) {
  const t = useStrings("pitch");
  const { problem, refusal, local } = shown;
  let sentence: string;
  if (problem === "planLimit" && local) {
    sentence = t("problem.planLimit", local);
  } else if (problem === "planLimit" && refusal?.limit !== undefined) {
    sentence = t("problem.planLimit", {
      count: Math.max(0, refusal.limit - (refusal.used ?? 0)),
      limit: refusal.limit,
    });
  } else if (problem === "conflict") {
    sentence = t("problem.conflict", { count: refusal?.conflicts.length ?? 0 });
  } else if (problem === "chooseOne") {
    sentence = t("chooseOne");
  } else {
    sentence = t(`problem.${problem}`);
  }
  let action: ReactNode = null;
  if (problem === "signedOut" || problem === "mfaRequired") {
    action = <Link href="/login" className={standaloneLinkClass}>{t("logIn")}</Link>;
  } else if (problem === "orgsGone" || problem === "changed") {
    action = <a href={pitchHref(proposalId)} className={standaloneLinkClass}>{t("reload")}</a>;
  } else if (problem === "notPublic" || problem === "notFound") {
    action = <StandaloneLink href={ideaHref}>{t("back")}</StandaloneLink>;
  } else if ((problem === "planLimit" || problem === "planLimitUnknown") && refusal?.upgrade) {
    // The next plan up, and back to this picker once it is paid for (REQ-BIL-08).
    const href = upgradeHref(refusal.upgrade, { next: pitchHref(proposalId) });
    action = <StandaloneLink href={href}>{t("problem.planLimitUpgrade")}</StandaloneLink>;
  }
  return (
    <Alert tone={problem === "chooseOne" ? "info" : "error"} ref={alertRef}>
      <p>{sentence}</p>
      {action}
    </Alert>
  );
}

function PitchDone({
  result,
  ideaHref,
  againHref,
  headingRef,
}: {
  result: PitchResult;
  ideaHref: string;
  againHref: string;
  headingRef: Ref<HTMLHeadingElement>;
}) {
  const t = useStrings("pitch");
  const sent = result.tags.filter((tag) => tag.status === "delivered");
  const saved = result.tags.filter((tag) => heldKey(tag.status) !== null);
  const left = pitchesLeft(result.cap);
  return (
    <section aria-labelledby="pitch-result" className="mt-8 max-w-3xl" data-pitch-result="">
      <h2 id="pitch-result" ref={headingRef} tabIndex={-1} className="text-lg text-ink focus:outline-none">
        {t("resultTitle")}
      </h2>
      <p className="mt-2 text-ink" data-cap="">
        {left === null ? t("capUnlimited") : t("capLeft", { count: left, limit: result.cap.limit ?? 0 })}
      </p>
      {sent.length > 0 ? (
        <div className="mt-6">
          <h3 className="flex items-center gap-2 text-lg text-ink">
            <SendIcon className="size-5 shrink-0 text-ok" />
            {t("sentTitle", { count: result.sent_count })}
          </h3>
          <ul className="mt-2">
            {sent.map((tag) => (
              <li key={tag.id} className="border-t border-line py-3 font-semibold [overflow-wrap:anywhere] text-ink">
                {tag.org?.name ?? t("orgUnlisted")}
              </li>
            ))}
          </ul>
          {result.email_sent ? <p className="mt-3 text-sm text-ink-soft">{t("emailNote")}</p> : null}
        </div>
      ) : null}
      {saved.length > 0 ? (
        <div className="mt-8">
          <h3 className="flex items-center gap-2 text-lg text-ink">
            <ClockIcon className="size-5 shrink-0 text-ink-soft" />
            {t("savedTitle", { count: result.saved_count })}
          </h3>
          <ul className="mt-2">
            {saved.map((tag) => {
              const name = tag.org?.name ?? t("orgUnlisted");
              return (
                <li key={tag.id} className="flex flex-col gap-1 border-t border-line py-3">
                  <span className="font-semibold [overflow-wrap:anywhere] text-ink">{name}</span>
                  <span className="text-sm text-ink-soft">{t(heldKey(tag.status)!, { name })}</span>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
      <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-6">
        <ButtonLink href={ideaHref} variant="primary">
          {t("back")}
        </ButtonLink>
        <a href={againHref} className={standaloneLinkClass}>
          {t("pitchMore")}
        </a>
      </div>
    </section>
  );
}
