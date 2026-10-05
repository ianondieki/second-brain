"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Checkbox } from "@/components/ui/Checkbox";
import { ConfirmDialog, openConfirm } from "@/components/ui/ConfirmDialog";
import { TextField } from "@/components/ui/TextField";

import type { DiscoverQuery } from "./discover";
import { MAX_NAME, nameProblem, saveBody, type SavedProblem, type SavedSearchRow, type SavedView } from "./saved-searches";
import { savedSearchCalls, type SavedSearchCalls } from "./saved-searches-calls";

export interface CurrentSearch {
  /** The view and filters on screen (a list that can be saved: problems or Briefs). */
  query: DiscoverQuery & { view: SavedView };
  /** A name to start from ("Agriculture in Nakuru"), formatted on the server. */
  suggestedName: string;
  /** The same view and filters as a saved row would show and link them. */
  href: string;
  facts: string[];
}

export interface SavedSearchesProps {
  initial: SavedSearchRow[];
  /** How many a developer may keep (the API's `max`). */
  max: number;
  /** What "Save this search" would keep; null on a list that cannot be saved (projects, the gap). */
  current: CurrentSearch | null;
  /** The notification settings, where the email digest is turned on. */
  settingsHref: string;
  calls?: SavedSearchCalls;
}

type Mode = "closed" | "list" | "form";

/**
 * Discover's saved searches (REQ-PERS-03, P21 track C): the strip at the foot of Discover's controls. "Save this search"
 * opens a small form for the name (the current view and filters, alerts on by default); at the cap it stays in view
 * but explains why it cannot be used. "Saved searches (n)" opens the list: each name applies its search (a link), its
 * filters in words, an Alerts switch and Delete (with a confirmation). Without any saved search the strip is the empty
 * state: one sentence and "Save this search".
 */
export function SavedSearches({ initial, max, current, settingsHref, calls: given }: SavedSearchesProps) {
  const t = useStrings("savedSearches");
  const calls = useRef(given ?? savedSearchCalls()).current;
  const [rows, setRows] = useState(initial);
  const [mode, setMode] = useState<Mode>("closed");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<SavedProblem | null>(null);
  const [alerts, setAlerts] = useState(true);
  const [status, setStatus] = useState("");
  const [rowProblem, setRowProblem] = useState<{ id: string; text: string } | null>(null);
  const [deleting, setDeleting] = useState<SavedSearchRow | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteProblem, setDeleteProblem] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const toggle = useRef<HTMLButtonElement>(null);
  const saveButton = useRef<HTMLButtonElement>(null);
  const focusAfter = useRef<"toggle" | "save" | null>(null);

  const full = rows.length >= max;

  // Focus goes to a control that is still there once the form closes or a row leaves.
  useEffect(() => {
    const target = focusAfter.current === "toggle" ? toggle.current : focusAfter.current === "save" ? saveButton.current : null;
    focusAfter.current = null;
    target?.focus();
  }, [mode, rows]);

  if (rows.length === 0 && !current) return null;

  function openForm() {
    if (full) return;
    setProblem(null);
    setStatus("");
    setAlerts(true);
    setMode(mode === "form" ? "closed" : "form");
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy || !current) return;
    const name = String(new FormData(event.currentTarget).get("name") ?? "");
    const wrong = nameProblem(name);
    if (wrong) {
      setProblem(wrong);
      return;
    }
    setBusy(true);
    setProblem(null);
    const outcome = await calls.save(saveBody(current.query, name, alerts));
    setBusy(false);
    if (!outcome.ok) {
      setProblem(outcome.problem);
      return;
    }
    const saved = outcome.value;
    focusAfter.current = "toggle";
    setRows([{ id: saved.id, name: saved.name, alerts: saved.alerts, href: current.href, facts: current.facts }, ...rows]);
    setMode("list");
    setStatus(t("saved", { name: saved.name }));
  }

  async function flipAlerts(row: SavedSearchRow) {
    const next = !row.alerts;
    const set = (value: boolean) =>
      setRows((list) => list.map((item) => (item.id === row.id ? { ...item, alerts: value } : item)));
    set(next);
    setRowProblem(null);
    setStatus("");
    const outcome = await calls.setAlerts(row.id, next);
    if (!outcome.ok) {
      set(!next);
      setRowProblem({ id: row.id, text: t("alertsProblem") });
    }
  }

  async function confirmDelete() {
    if (!deleting || deleteBusy) return;
    setDeleteBusy(true);
    setDeleteProblem(false);
    const outcome = await calls.remove(deleting.id);
    setDeleteBusy(false);
    if (!outcome.ok) {
      setDeleteProblem(true);
      return;
    }
    const left = rows.filter((row) => row.id !== deleting.id);
    focusAfter.current = left.length > 0 ? "toggle" : "save";
    setStatus(t("deleted", { name: deleting.name }));
    setRows(left);
    if (left.length === 0) setMode("closed");
    dialog.current?.close();
  }

  return (
    <div data-saved-searches="" className="border-t border-line px-4 py-2 sm:px-5">
      <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between sm:gap-x-6">
        {rows.length > 0 ? (
          <button
            ref={toggle}
            type="button"
            aria-expanded={mode === "list"}
            aria-controls="saved-list"
            onClick={() => setMode(mode === "list" ? "closed" : "list")}
            className="group inline-flex min-h-11 items-center gap-1.5 self-start font-semibold text-accent"
          >
            {t("toggle", { count: rows.length })}
            <svg aria-hidden="true" viewBox="0 0 20 20" className="size-5 transition-transform group-aria-expanded:rotate-180 motion-reduce:transition-none">
              <path d="M5 7.5l5 5 5-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        ) : (
          <p className="max-w-[52ch] py-2 text-sm text-ink" data-saved-empty="">
            {t("empty")}
          </p>
        )}
        {current ? (
          <button
            ref={saveButton}
            type="button"
            onClick={openForm}
            aria-expanded={mode === "form"}
            aria-controls="save-search"
            aria-disabled={full || undefined}
            aria-describedby={full ? "saved-limit" : undefined}
            data-save-search=""
            className="btn btn-secondary mb-2 self-start sm:mb-0 aria-disabled:cursor-not-allowed aria-disabled:text-ink-soft"
          >
            {t("save")}
          </button>
        ) : null}
      </div>
      {full && current ? (
        <p id="saved-limit" className="pb-2 text-sm text-ink-soft" data-saved-limit="">
          {t("limit", { max })}
        </p>
      ) : null}

      {mode === "form" && current ? (
        <form id="save-search" noValidate onSubmit={save} className="flex flex-col gap-4 border-t border-line pt-4 pb-3">
          <TextField
            id="saved-name"
            name="name"
            label={t("nameLabel")}
            hint={t("nameHint", { max: MAX_NAME })}
            defaultValue={current.suggestedName}
            maxLength={MAX_NAME}
            autoComplete="off"
            autoFocus
            error={problem === "nameMissing" || problem === "nameLong" ? t(`problem.${problem}`) : undefined}
          />
          <div>
            <p className="text-sm text-ink-soft">{t("keeps")}</p>
            <Facts facts={current.facts} />
          </div>
          <Checkbox
            id="saved-alerts"
            label={t("alertsLabel")}
            checked={alerts}
            onChange={(event) => setAlerts(event.currentTarget.checked)}
          />
          {problem && problem !== "nameMissing" && problem !== "nameLong" ? (
            <Alert>{t(`problem.${problem}`, { max })}</Alert>
          ) : null}
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <button type="submit" aria-disabled={busy || undefined} className="btn btn-secondary">
              {busy ? t("saving") : t("submit")}
            </button>
            <button
              type="button"
              onClick={() => {
                focusAfter.current = "save";
                setMode("closed");
              }}
              className="btn btn-link self-start"
            >
              {t("cancel")}
            </button>
          </div>
        </form>
      ) : null}

      {mode === "list" && rows.length > 0 ? (
        <div id="saved-list" className="border-t border-line pt-1 pb-2">
          <p className="max-w-[62ch] pt-3 text-sm text-ink-soft">
            {t("lead")}{" "}
            <Link href={settingsHref} className="font-semibold text-accent underline">
              {t("settingsLink")}
            </Link>
          </p>
          <ul aria-label={t("listLabel")} className="flex flex-col">
            {rows.map((row) => (
              <li
                key={row.id}
                data-saved-search={row.id}
                className="flex flex-col gap-1 border-t border-line py-3 first:border-t-0 sm:flex-row sm:items-center sm:justify-between sm:gap-6"
              >
                <div className="min-w-0">
                  <Link
                    href={row.href}
                    id={`saved-name-${row.id}`}
                    className="inline-flex min-h-11 items-center font-semibold [overflow-wrap:anywhere] text-ink underline decoration-line underline-offset-4 hover:decoration-accent"
                  >
                    {row.name}
                  </Link>
                  <Facts facts={row.facts} />
                  {rowProblem?.id === row.id ? (
                    <p role="alert" className="text-sm text-error">
                      {rowProblem.text}
                    </p>
                  ) : null}
                </div>
                <div className="flex shrink-0 items-center gap-6">
                  <span className="inline-flex items-center gap-2">
                    <button
                      type="button"
                      role="switch"
                      aria-checked={row.alerts}
                      aria-labelledby={`saved-alerts-${row.id} saved-name-${row.id}`}
                      onClick={() => flipAlerts(row)}
                      data-alerts={row.alerts ? "on" : "off"}
                      className="group inline-flex min-h-11 items-center gap-2"
                    >
                      <span
                        aria-hidden="true"
                        className="relative h-6 w-10 rounded-full border border-ink-soft bg-field transition-colors group-aria-checked:border-accent group-aria-checked:bg-accent motion-reduce:transition-none"
                      >
                        <span className="absolute top-0.5 left-0.5 size-4 rounded-full bg-ink-soft transition-transform group-aria-checked:translate-x-4 group-aria-checked:bg-on-accent motion-reduce:transition-none" />
                      </span>
                      <span id={`saved-alerts-${row.id}`} className="text-sm font-semibold text-ink">
                        {t("alerts")}
                      </span>
                    </button>
                    <span aria-hidden="true" className="w-8 text-sm text-ink-soft">
                      {row.alerts ? t("on") : t("off")}
                    </span>
                  </span>
                  <button
                    type="button"
                    onClick={() => {
                      setDeleting(row);
                      setDeleteProblem(false);
                      openConfirm(dialog.current);
                    }}
                    aria-label={t("deleteNamed", { name: row.name })}
                    className="btn btn-link"
                  >
                    {t("delete")}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <p role="status" className="text-sm text-ok empty:hidden">
        {status}
      </p>

      <ConfirmDialog
        ref={dialog}
        title={t("confirmTitle")}
        confirmLabel={t("delete")}
        busyLabel={t("deleting")}
        busy={deleteBusy}
        onConfirm={confirmDelete}
        tone="danger"
        cancelLabel={t("cancel")}
        problem={deleteProblem ? <Alert>{t("deleteProblem")}</Alert> : undefined}
        onClose={() => setDeleting(null)}
      >
        <p>{t("confirmBody", { name: deleting?.name ?? "" })}</p>
      </ConfirmDialog>
    </div>
  );
}

/** The view and filters in words, each a quiet fact (no separators: the gap is the separator). */
function Facts({ facts }: { facts: string[] }) {
  return (
    <p className="flex flex-wrap gap-x-3 gap-y-0.5 text-sm text-ink-soft" data-facts="">
      {facts.map((fact, index) => (
        <span key={index} className="[overflow-wrap:anywhere]">
          {fact}
        </span>
      ))}
    </p>
  );
}
