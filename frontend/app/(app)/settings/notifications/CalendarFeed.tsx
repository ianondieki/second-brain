"use client";

import { useId, useRef, useState } from "react";

import { useStrings } from "@/components/ClientStrings";
import { api, type ApiClient } from "@/lib/api/client";
import { buttonClass } from "@/components/ui/Button";
import { controlClass } from "@/components/ui/Field";
import { cn } from "@/components/ui/cn";

/** What the feed section shows: no feed, a live one (its link not shown again), a new link shown once, or removed. */
export type FeedState = { kind: "none" } | { kind: "live" } | { kind: "shown"; url: string } | { kind: "removed" };

type Busy = null | "create" | "rotate" | "remove";

/** The feed's address for subscribing: the URL as the API answered it, made absolute against this site if need be. */
export function feedLinks(url: string, origin: string): { https: string; webcal: string; google: string } {
  const https = new URL(url, origin).href;
  const webcal = https.replace(/^https?:/, "webcal:");
  return { https, webcal, google: `https://calendar.google.com/calendar/render?cid=${encodeURIComponent(webcal)}` };
}

/** POST (create or rotate) or DELETE the caller's feed, or the organisation's for them; null on any failure. */
export async function changeFeed(
  action: "create" | "remove",
  orgId: string | undefined,
  client: ApiClient = api,
): Promise<{ url: string } | true | null> {
  try {
    if (action === "remove") {
      const { response } = orgId
        ? await client.DELETE("/api/orgs/{org_id}/calendar-feed", { params: { path: { org_id: orgId } } })
        : await client.DELETE("/api/me/calendar-feed");
      return response.ok ? true : null;
    }
    const { data } = orgId
      ? await client.POST("/api/orgs/{org_id}/calendar-feed", { params: { path: { org_id: orgId } } })
      : await client.POST("/api/me/calendar-feed");
    return data ?? null;
  } catch {
    return null;
  }
}

/**
 * Settings › Notifications › Calendar feed (P27 track A; REQ-ENG-13; D-70), the page's one client part for it: create
 * the private feed link, see it once in a read-only field with Copy and the two ways to subscribe (Google Calendar,
 * and Apple Calendar or any app through webcal://), make a new link (the old one stops working at once) or remove the
 * feed. The link is never shown again after the page is left: the API keeps only its hash. `lastRead` is the time a
 * calendar app last fetched it, formatted by the server.
 */
export function CalendarFeed({
  initial,
  orgId,
  lastRead,
}: {
  initial: "none" | "live";
  orgId?: string;
  lastRead: string | null;
}) {
  const t = useStrings("calendarFeed");
  const [state, setState] = useState<FeedState>({ kind: initial });
  const [busy, setBusy] = useState<Busy>(null);
  const [notice, setNotice] = useState<"" | "copied" | "copyFailed" | "failed" | "removed">("");
  const field = useRef<HTMLInputElement>(null);
  const createButton = useRef<HTMLButtonElement>(null);
  const fieldId = useId();
  const noteId = useId();

  async function run(kind: Exclude<Busy, null>) {
    if (busy) return;
    setBusy(kind);
    setNotice("");
    const result = await changeFeed(kind === "remove" ? "remove" : "create", orgId);
    setBusy(null);
    if (result === null) return setNotice("failed");
    if (result === true) {
      setState({ kind: "removed" });
      setNotice("removed");
      // The button pressed is gone: focus goes to the one that takes its place, never to the page's start.
      requestAnimationFrame(() => createButton.current?.focus());
      return;
    }
    setState({ kind: "shown", url: result.url });
    // The new link has the focus's attention: the field it is in, selected for copying.
    requestAnimationFrame(() => {
      field.current?.focus();
      field.current?.select();
    });
  }

  async function copy(url: string) {
    try {
      await navigator.clipboard.writeText(url);
      setNotice("copied");
    } catch {
      field.current?.select();
      setNotice("copyFailed");
    }
  }

  const links = state.kind === "shown" ? feedLinks(state.url, location.origin) : null;
  const actionClass = buttonClass("secondary");
  return (
    <div className="flex flex-col gap-4" data-calendar-feed={state.kind}>
      {state.kind === "none" || state.kind === "removed" ? (
        <>
          {state.kind === "none" ? <p className="text-ink-soft">{t("none")}</p> : null}
          <p>
            <button
              ref={createButton}
              type="button"
              className={actionClass}
              aria-disabled={busy !== null || undefined}
              onClick={() => run("create")}
            >
              {busy === "create" ? t("creating") : t("create")}
            </button>
          </p>
        </>
      ) : null}
      {links && state.kind === "shown" ? (
        <div className="flex flex-col gap-3">
          <label htmlFor={fieldId} className="font-semibold text-ink">
            {t("urlLabel")}
          </label>
          <div className="flex flex-col gap-2 sm:flex-row">
            <input
              ref={field}
              id={fieldId}
              type="text"
              readOnly
              value={links.https}
              aria-describedby={noteId}
              onFocus={(event) => event.currentTarget.select()}
              className={cn(controlClass, "min-w-0 flex-1 font-mono text-sm")}
              data-feed-url=""
            />
            <button type="button" className={actionClass} onClick={() => copy(links.https)} data-feed-copy="">
              {t("copy")}
            </button>
          </div>
          <p id={noteId} className="text-sm text-ink-soft">
            {t("shownOnce")}
          </p>
          <p className="flex flex-wrap gap-x-6">
            <a
              href={links.google}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex min-h-11 items-center font-semibold text-accent underline decoration-1 hover:decoration-2"
              data-feed-google=""
            >
              {t("google")}
            </a>
            <a
              href={links.webcal}
              className="inline-flex min-h-11 items-center font-semibold text-accent underline decoration-1 hover:decoration-2"
              data-feed-webcal=""
            >
              {t("apple")}
            </a>
          </p>
        </div>
      ) : null}
      {state.kind === "live" ? (
        <p className="text-ink">{lastRead ? t("live", { date: lastRead }) : t("liveUnread")}</p>
      ) : null}
      {state.kind === "live" || state.kind === "shown" ? (
        <p className="flex flex-wrap gap-3">
          <button
            type="button"
            className={actionClass}
            aria-disabled={busy !== null || undefined}
            onClick={() => run("rotate")}
            data-feed-rotate=""
          >
            {busy === "rotate" ? t("rotating") : t("rotate")}
          </button>
          <button
            type="button"
            className={buttonClass("danger")}
            aria-disabled={busy !== null || undefined}
            onClick={() => run("remove")}
            data-feed-remove=""
          >
            {busy === "remove" ? t("removing") : t("remove")}
          </button>
        </p>
      ) : null}
      <p role="status" className="text-sm font-semibold text-ink empty:hidden" data-feed-notice={notice || undefined}>
        {notice ? t(notice) : ""}
      </p>
    </div>
  );
}
