"use client";

import Link from "next/link";
import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode, type Ref } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button, buttonClass, standaloneLinkClass } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { useHydrated } from "@/lib/hooks/useHydrated";

import { pitch as pitchCall } from "./calls";
import {
  heldKey,
  MAX_BATCH,
  pitchesLeft,
  pitchHref,
  selectionMax,
  type PitchReason,
  type PitchResult,
  type TagCap,
} from "./picker";
import type { PitchProblem, PitchRefusal } from "./refusals";

/** One organisation as the picker lists it; its details (type, county, badge, outcome or reason) are drawn on the server. */
export interface PickerRow {
  id: string;
  name: string;
  available: boolean;
  details: ReactNode;
}

export interface PickerGroup {
  key: string;
  parent?: string;
  name: string;
  rows: PickerRow[];
}

export interface PitchFormProps {
  proposalId: string;
  ideaHref: string;
  cap: TagCap;
  groups: PickerGroup[];
  /** Organisations chosen before this page loaded (the URL's `sel`), including ones this page does not list. */
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
type Shown = { problem: Problem; refusal?: PitchRefusal };

/**
 * "Pitch to companies" (REQ-PROP-03, docs/spec/06 6.3): the directory by niche with a checkbox per organisation. One GET
 * form holds the search, the niche, the page and the choices, so choices survive a search or the next page; "Pitch"
 * (the screen's one primary action) sends them all at once, 1 to 20 and within the plan's cap. The API refuses a batch
 * whole, so a refusal means nothing was sent: it is one sentence and at most one action, and a 409's organisations are
 * unticked with their reasons. After a Pitch the form gives way to what was sent now and what is saved.
 */
export function PitchForm({
  proposalId,
  ideaHref,
  cap,
  groups,
  initialSelected,
  filters,
  narrowed,
  cursor,
  nextCursor,
  pitchImpl = pitchCall,
}: PitchFormProps) {
  const t = useStrings("pitch");
  const hydrated = useHydrated();
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set(initialSelected));
  const [blocked, setBlocked] = useState<ReadonlyMap<string, PitchReason>>(() => new Map());
  const [busy, setBusy] = useState(false);
  const [shown, setShown] = useState<Shown | null>(null);
  const [result, setResult] = useState<PitchResult | null>(null);
  const resultHeading = useRef<HTMLHeadingElement>(null);
  const summaryId = useId();

  // What was sent and saved replaces the form: move focus to its heading, so it is read out and the page starts there.
  useEffect(() => {
    if (result) resultHeading.current?.focus();
  }, [result]);

  const max = selectionMax(cap);
  const atMax = selected.size >= max;
  const listed = new Set(groups.flatMap((group) => group.rows.map((row) => row.id)));
  const offPage = [...selected].filter((id) => !listed.has(id));

  function toggle(id: string, on: boolean) {
    setShown(null);
    setSelected((current) => {
      const next = new Set(current);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
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
    setBusy(true);
    setShown(null);
    const outcome = await pitchImpl(proposalId, [...selected]);
    setBusy(false);
    if (outcome.ok) {
      setResult(outcome.value);
      return;
    }
    if (outcome.conflicts.length > 0) {
      const refused = new Map(blocked);
      for (const conflict of outcome.conflicts) refused.set(conflict.orgId, conflict.reason);
      setBlocked(refused);
      setSelected((current) => new Set([...current].filter((id) => !refused.has(id))));
    }
    setShown({ problem: outcome.problem, refusal: outcome });
  }

  if (result) {
    return <PitchDone result={result} ideaHref={ideaHref} againHref={pitchHref(proposalId)} headingRef={resultHeading} />;
  }

  const left = pitchesLeft(cap);
  return (
    <>
      <p className="mt-3 max-w-[62ch] text-ink-soft">{t("lead", { max: MAX_BATCH })}</p>
      <p className="mt-3 text-ink" data-cap="">
        {left === null ? t("capUnlimited") : t("capLeft", { count: left, limit: cap.limit ?? 0 })}
      </p>
      <form method="get" onSubmit={submit} className="mt-6">
        <div role="search" className="max-w-3xl">
          {filters}
          {narrowed ? (
            <p className="mt-2">
              <a href={pitchHref(proposalId, { selected: [...selected] })} className={standaloneLinkClass}>
                {t("clear")}
              </a>
            </p>
          ) : null}
        </div>

        {offPage.map((id) => (
          <input key={id} type="hidden" name="sel" value={id} />
        ))}

        <div className="mt-8">
          {groups.map((group, index) => (
            <section key={group.key} className="mt-10 first:mt-0" aria-labelledby={`pitch-group-${index}`}>
              <h2 id={`pitch-group-${index}`} className="flex flex-col text-lg text-ink">
                {group.parent ? (
                  <span className="text-sm font-medium tracking-normal text-ink-soft">{group.parent}</span>
                ) : null}
                <span>{group.name}</span>
              </h2>
              <ul className="mt-2 grid grid-cols-1 gap-x-10 md:grid-cols-2">
                {group.rows.map((row) => (
                  <Row
                    key={row.id}
                    rowId={`${index}-${row.id}`}
                    row={row}
                    checked={selected.has(row.id)}
                    reason={blocked.get(row.id)}
                    locked={!hydrated || busy || (atMax && !selected.has(row.id))}
                    onToggle={toggle}
                  />
                ))}
              </ul>
            </section>
          ))}
        </div>

        {cursor || nextCursor ? (
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
        ) : null}

        <div
          data-action-bar=""
          className={cn(
            "sticky bottom-[calc(3.5rem+env(safe-area-inset-bottom))] z-[5] -mx-4 mt-8 border-t border-line bg-paper",
            "px-4 pt-3 pb-4 sm:-mx-6 sm:px-6 lg:bottom-0 lg:mx-0 lg:px-0",
          )}
        >
          {shown ? <Refused shown={shown} proposalId={proposalId} ideaHref={ideaHref} /> : null}
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p id={summaryId} aria-live="polite" className="text-ink">
              <span className="font-semibold tabular-nums">{t("chosen", { count: selected.size, max })}</span>
              {atMax && max > 0 ? <span className="block text-sm text-ink-soft">{t("maxReached")}</span> : null}
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
    </>
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
  reason?: PitchReason;
  locked: boolean;
  onToggle: (id: string, on: boolean) => void;
}) {
  const t = useStrings("pitch");
  const refused = reason !== undefined;
  const available = row.available && !refused;
  return (
    <li
      data-org-row={row.id}
      className={cn(
        "relative flex min-w-0 flex-col gap-1 border-t border-line py-4 pr-2 pl-9",
        checked && "bg-jacaranda-wash shadow-[inset_3px_0_0_var(--jacaranda)]",
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
          onChange={(event) => onToggle(row.id, event.target.checked)}
          aria-describedby={`pitch-${rowId}-details`}
          className="absolute top-[1.35rem] left-2 z-[1] size-5 cursor-pointer accent-jacaranda disabled:cursor-not-allowed"
        />
        {row.name}
      </label>
      <div id={`pitch-${rowId}-details`} className="flex flex-col gap-1">
        {refused ? null : row.details}
        {refused ? (
          <p className="text-sm text-error" data-reason={reason}>
            {t(`reason.${reason}`, { name: row.name })}
          </p>
        ) : null}
      </div>
    </li>
  );
}

function Refused({ shown, proposalId, ideaHref }: { shown: Shown; proposalId: string; ideaHref: string }) {
  const t = useStrings("pitch");
  const { problem, refusal } = shown;
  let sentence: string;
  if (problem === "planLimit" && refusal?.limit !== undefined) {
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
    action = <Link href={ideaHref} className={standaloneLinkClass}>{t("back")}</Link>;
  }
  return (
    <Alert tone={problem === "chooseOne" ? "info" : "error"} className="mb-3">
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
          <h3 className="text-lg text-ok">{t("sentTitle", { count: result.sent_count })}</h3>
          <ul className="mt-2 border-t border-line">
            {sent.map((tag) => (
              <li key={tag.id} className="border-b border-line py-3 font-semibold [overflow-wrap:anywhere] text-ink">
                {tag.org?.name ?? t("orgUnlisted")}
              </li>
            ))}
          </ul>
          {result.email_sent ? <p className="mt-3 text-sm text-ink-soft">{t("emailNote")}</p> : null}
        </div>
      ) : null}
      {saved.length > 0 ? (
        <div className="mt-8">
          <h3 className="text-lg text-ink">{t("savedTitle", { count: result.saved_count })}</h3>
          <ul className="mt-2 border-t border-line">
            {saved.map((tag) => {
              const name = tag.org?.name ?? t("orgUnlisted");
              return (
                <li key={tag.id} className="flex flex-col gap-1 border-b border-line py-3">
                  <span className="font-semibold [overflow-wrap:anywhere] text-ink">{name}</span>
                  <span className="text-sm text-ink-soft">{t(heldKey(tag.status)!, { name })}</span>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
      <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-6">
        <Link href={ideaHref} className={buttonClass("primary")} data-primary="">
          {t("back")}
        </Link>
        <a href={againHref} className={standaloneLinkClass}>
          {t("pitchMore")}
        </a>
      </div>
    </section>
  );
}
