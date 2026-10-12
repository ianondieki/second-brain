"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";

/** The controls a page read offline cannot use; the mark on those this script disabled (globals.css greys them). */
const CONTROLS = "#main :is(button,input,select,textarea)";
const LOCKED = "data-offline-locked";

/**
 * The script of the offline part (P27 track F; REQ-UX-08; D-69), on the pages that carry it (OfflineSlot). It registers
 * the service worker (public/sw.js, `?v=` the build), tells it whose cache it is (the hash the command palette's Recent
 * list uses, and the page's language; with no hash, the cache is cleared) and asks it to keep this page when it was
 * reached inside the app. Offline (the browser says so, or the worker answered this page from its cache) it marks
 * <html data-offline>, which shows the server-drawn banner (OfflineBanner), and disables every button, field and
 * select in <main> (so no form can be sent) until the connection is back. It draws nothing itself, so hydration is
 * unchanged; it is kept small (docs/spec/07 item 5: the trackers sit at the 150 KB budget).
 */
export function Register({ hash, version }: { hash: string | null; version: string }) {
  const pathname = usePathname();

  useEffect(() => {
    const html = document.documentElement;
    // Did the worker answer this page from its cache? Then, back online, the page is loaded again, not unlocked stale.
    let cached = false;
    let watch: MutationObserver | undefined;
    // Read-only offline: every control in <main> the page had not disabled itself is disabled (those added later too,
    // by the observer), and given back online.
    const lock = (down: boolean) => {
      for (const control of document.querySelectorAll<HTMLButtonElement>(CONTROLS)) {
        if (down ? control.disabled : !control.hasAttribute(LOCKED)) continue;
        control.disabled = down;
        control.toggleAttribute(LOCKED, down);
      }
    };
    const offline = (down: boolean) => {
      html.toggleAttribute("data-offline", down);
      lock(down);
      watch?.disconnect();
      // A control a client component enables again is disabled again: "disabled" changes are watched too.
      if (down)
        (watch = new MutationObserver(() => lock(true))).observe(html, {
          childList: true,
          subtree: true,
          attributeFilter: ["disabled"],
        });
    };
    offline(!navigator.onLine);
    const sw = navigator.serviceWorker;
    // The worker handles its messages one at a time, in order: "user" lands before any "status" or "visit".
    if (sw)
      sw
        // The build id is letters, digits, "-" and "_"; the scope is the script's own ("/"); the script itself is
        // never taken from the HTTP cache (updateViaCache "imports", the default, and /sw.js is no-cache).
        .register(`/sw.js?v=${version}`)
        .then(() => sw.ready)
        .then(({ active }) => {
          active?.postMessage(hash ? { type: "user", hash, lang: html.lang } : { type: "clear" });
          // Did the worker answer this page from its cache (the network failed though the browser says online)?
          const channel = new MessageChannel();
          channel.port1.onmessage = ({ data }) => offline((cached = Boolean(data?.cached)) || !navigator.onLine);
          active?.postMessage({ type: "status" }, [channel.port2]);
          // A page reached inside the app loaded no page through the worker: it fetches and keeps it (if it may).
          active?.postMessage({ type: "visit", url: location.href });
        })
        .catch(() => {});
    // The controller is the listeners' options ({signal}): aborting it removes both.
    const listening = new AbortController();
    addEventListener("offline", () => offline(true), listening);
    addEventListener("online", () => (cached ? location.reload() : offline(false)), listening);
    return () => {
      offline(false);
      listening.abort();
    };
    // Run again on every page reached inside the app: a fresh page (fetched now, not the cached copy) starts unlocked,
    // its status asked again (the worker answers "from the cache" once per page load) and its visit sent.
  }, [hash, version, pathname]);

  return null;
}
