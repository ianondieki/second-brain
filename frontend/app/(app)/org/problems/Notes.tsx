"use client";

import { useEffect, useRef, type ReactNode } from "react";

import { Alert } from "@/components/ui/Alert";
import { useHydrated } from "@/lib/hooks/useHydrated";

/**
 * "Brief sent for review" after posting (?posted=1): mounted once the page runs in the browser, so its words arrive in
 * a live region (role=status) and are announced, and focused, so the person continues from it rather than from the
 * form that is gone (WCAG 2.4.3, 4.1.3). Nothing in the server HTML: without script the list says it all. Once it has
 * focus, `posted` leaves the address (history.replaceState, which Next's router follows without fetching the page
 * again, so the note stays): a reload or a shared link never says it again.
 */
export function PostedNote({ text }: { text: string }) {
  const hydrated = useHydrated();
  const note = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!hydrated) return;
    note.current?.focus();
    const url = new URL(window.location.href);
    if (!url.searchParams.has("posted")) return;
    url.searchParams.delete("posted");
    window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
  }, [hydrated]);
  if (!hydrated) return null;
  return (
    <Alert ref={note} tone="ok" className="mt-6 focus:outline-none">
      <p data-posted="">{text}</p>
    </Alert>
  );
}

/**
 * A Brief's state note that takes focus when the state it shows changes on the page (Close confirmed: the button that
 * opened the dialog is gone, so focus would fall to <body>). Never on the first load.
 */
export function StateNote({ state, children }: { state: string; children: ReactNode }) {
  const box = useRef<HTMLDivElement>(null);
  const shown = useRef(state);
  useEffect(() => {
    if (shown.current === state) return;
    shown.current = state;
    box.current?.focus();
  }, [state]);
  return (
    <div ref={box} tabIndex={-1} className="focus:outline-none" data-state-focus="">
      {children}
    </div>
  );
}
