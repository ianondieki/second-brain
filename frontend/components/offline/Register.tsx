"use client";

import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";

/** The controls a page read offline cannot use; the mark on those this script disabled (globals.css greys them). */
const CONTROLS = "#main :is(button, input, select, textarea)";
const LOCKED = "data-offline-locked";

/**
 * The script of the offline part (P27 track F; REQ-UX-08; D-69), on the pages that carry it (OfflineSlot). It registers
 * the service worker (public/sw.js, `?v=` the build), tells it whose cache it is (the hash the command palette's Recent
 * list uses; with none, the cache is cleared) and asks it to keep this page when it was reached inside the app. Offline (the browser says so, or the worker answered this page from
 * its cache) it marks <html data-offline>, which shows the server-drawn banner (OfflineBanner), and disables every
 * button, field and select in <main> (so no form can be sent) until the connection is back. It draws nothing itself, so hydration is unchanged; it is kept small (docs/spec/07 item 5: the trackers sit
 * near the 150 KB budget).
 */
export function Register({ hash, version }: { hash: string | null; version: string }) {
  const pathname = usePathname();
  const worker = useRef<Promise<ServiceWorker | null | undefined> | null>(null);

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
      if (down) (watch = new MutationObserver(() => lock(true))).observe(html, { childList: true, subtree: true });
    };
    const goneOffline = () => offline(true);
    const backOnline = () => (cached ? location.reload() : offline(false));
    offline(!navigator.onLine);
    const sw = navigator.serviceWorker;
    // The worker handles its messages one at a time, in order: "user" lands before any "status" or "visit".
    worker.current = sw
      ? sw
          // The build id is letters, digits, "-" and "_"; the scope is the script's own ("/"); the script itself is
          // never taken from the HTTP cache (updateViaCache "imports", the default, and /sw.js is no-cache).
          .register(`/sw.js?v=${version}`)
          .then(() => sw.ready)
          .then(({ active }) => {
            active?.postMessage(hash ? { type: "user", hash } : { type: "clear" });
            // Did the worker answer this page from its cache (the network failed though the browser says online)?
            const channel = new MessageChannel();
            channel.port1.onmessage = ({ data }) => offline((cached = Boolean(data?.cached)) || !navigator.onLine);
            active?.postMessage({ type: "status" }, [channel.port2]);
            return active;
          })
          .catch(() => null)
      : Promise.resolve(null);
    addEventListener("offline", goneOffline);
    addEventListener("online", backOnline);
    return () => {
      offline(false);
      removeEventListener("offline", goneOffline);
      removeEventListener("online", backOnline);
    };
  }, [hash, version]);

  // A page reached inside the app loaded no page through the worker: it fetches and keeps it (if it may).
  useEffect(() => {
    void worker.current?.then((active) => active?.postMessage({ type: "visit", url: location.href }));
  }, [pathname]);

  return null;
}
