"use client";

import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { formatMoment } from "@/lib/format";

import { useStrings } from "../ClientStrings";
import { cn } from "../ui/cn";
import { noticeBox, noticeTone } from "../ui/notice";
import { Icon } from "../ui/status-icons";

import { dropInstallOffer, keepInstallOffer } from "./install";
import { tellWorker } from "./worker";

/** The controls a page held offline cannot use: every one in <main> but the banner's (it has none). */
const CONTROLS = "button, input, select, textarea";
const LOCKED = "data-offline-locked";

function OfflineIcon() {
  return (
    <Icon className="mt-0.5 size-5 shrink-0 text-accent">
      <path d="M2.5 7.5a11 11 0 0 1 4.2-2.6M17.5 7.5A11 11 0 0 0 10 4.5" />
      <path d="M5.25 10.6a6.6 6.6 0 0 1 2.2-1.35M14.75 10.6A6.6 6.6 0 0 0 11.8 9" />
      <path d="M10 14.5v.05" strokeWidth="2.25" />
      <path d="m3 3 14 14" />
    </Icon>
  );
}

/** Disables every control in <main> (and holds any form's submission) until `release` is called; new ones too. */
function readOnly(main: HTMLElement): () => void {
  const lock = () => {
    for (const control of main.querySelectorAll<HTMLButtonElement>(CONTROLS)) {
      if (control.disabled) continue;
      control.disabled = true;
      control.setAttribute(LOCKED, "");
    }
  };
  const hold = (event: Event) => event.preventDefault();
  lock();
  const watch = new MutationObserver(lock);
  watch.observe(main, { childList: true, subtree: true });
  main.addEventListener("submit", hold, true);
  return () => {
    watch.disconnect();
    main.removeEventListener("submit", hold, true);
    for (const control of main.querySelectorAll<HTMLButtonElement>(`[${LOCKED}]`)) {
      control.disabled = false;
      control.removeAttribute(LOCKED);
    }
  };
}

/**
 * The signed-in shell's offline part (P27 track F; REQ-UX-08; D-69), drawn in <main> above the page. It registers the
 * service worker (public/sw.js, `?v=` the build), tells it whose cache it is (the hash the command palette's Recent list
 * uses; with none, the cache is cleared), asks it to keep a tracker reached inside the app, and keeps the browser's
 * install offer for the account menu. Offline (the browser says so, or this page came from the worker's cache) it shows
 * the banner, "as of" the copy's Date in Nairobi time, and makes the page read-only: every button, field and form in
 * <main> disabled until the connection is back. Nothing is drawn until it has mounted, so hydration is unchanged.
 */
export function Register({ hash, version }: { hash: string | null; version: string }) {
  const t = useStrings("shell");
  const pathname = usePathname();
  const [offline, setOffline] = useState(false);
  const [asOf, setAsOf] = useState<string | null>(null);
  const [page, setPage] = useState("");
  const worker = useRef<Promise<ServiceWorker | null> | null>(null);

  useEffect(() => {
    addEventListener("beforeinstallprompt", keepInstallOffer);
    addEventListener("appinstalled", dropInstallOffer);
    const sw = navigator.serviceWorker;
    worker.current =
      sw && !location.pathname.startsWith("/admin")
        ? sw
            .register(`/sw.js?v=${encodeURIComponent(version)}`, { scope: "/", updateViaCache: "none" })
            .then(() => sw.ready)
            .then(async ({ active }) => {
              await tellWorker(active, hash ? { type: "user", hash } : { type: "clear" });
              return active;
            })
            .catch(() => null)
        : Promise.resolve(null);

    let alive = true;
    async function check(fromCache: boolean) {
      const down = fromCache || !navigator.onLine;
      if (down) {
        const copy = await globalThis.caches?.match(location.href, { ignoreVary: true }).catch(() => undefined);
        const date = Date.parse(copy?.headers.get("date") ?? "");
        if (!alive) return;
        // The one date format (lib/format.ts): "12 Oct 2026, 14:05", in Nairobi; the message adds "EAT".
        setAsOf(
          Number.isNaN(date) ? null : formatMoment(document.documentElement.lang || "en", new Date(date).toISOString()),
        );
        setPage(document.querySelector("main h1")?.textContent?.trim() || document.title);
      }
      if (alive) setOffline(down);
    }
    const goneOffline = () => void check(false);
    const backOnline = () => setOffline(false);
    void worker.current
      .then((active) => tellWorker(active, { type: "status" }))
      .then((status) => check(Boolean((status as { cached?: boolean } | null)?.cached)));
    addEventListener("offline", goneOffline);
    addEventListener("online", backOnline);
    return () => {
      alive = false;
      removeEventListener("beforeinstallprompt", keepInstallOffer);
      removeEventListener("appinstalled", dropInstallOffer);
      removeEventListener("offline", goneOffline);
      removeEventListener("online", backOnline);
    };
  }, [hash, version]);

  // A tracker reached inside the app loaded no page through the worker: it fetches and keeps it (if it may).
  useEffect(() => {
    void worker.current?.then((active) => active?.postMessage({ type: "visit", url: location.href }));
  }, [pathname]);

  useEffect(() => {
    const main = document.getElementById("main");
    return offline && main ? readOnly(main) : undefined;
  }, [offline]);

  if (!offline) return null;
  return (
    <div role="status" data-offline-banner="" className={cn(noticeBox, noticeTone.info, "mb-6")}>
      <OfflineIcon />
      <p className="min-w-0 flex-1">
        {asOf ? t("offline.banner", { page, time: asOf }) : t("offline.bannerUndated", { page })}
      </p>
    </div>
  );
}
