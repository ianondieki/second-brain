"use client";

import { usePathname } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type ComponentType } from "react";

import type { CommandPaletteProps } from "./CommandPalette";
import { loadPalette } from "./load";
import { DETAIL, rememberVisit } from "./remember";
import type { PaletteData } from "./types";

/** A key press inside a text field types; "/" opens the palette only outside one. */
function inField(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName);
}

function SearchIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" aria-hidden="true" focusable="false" className="size-5 shrink-0">
      <circle cx="11" cy="11" r="6.5" />
      <path d="m16 16 4 4" />
    </svg>
  );
}

/**
 * The top bar's Search (D-67, P25): a field-like pill from 640 px ("Search or jump to" and the shortcut), an icon
 * button with the same name on phones. It opens the command palette, whose code loads on first use; Ctrl/⌘ K anywhere
 * and "/" outside a text field open it too. It also remembers the detail pages this browser opens, for the palette's
 * Recent group (their address and the title on their screen, in this browser only).
 */
export function PaletteTrigger({ data }: { data: PaletteData }) {
  const [Palette, setPalette] = useState<ComponentType<CommandPaletteProps> | null>(null);
  const [open, setOpen] = useState(false);
  const opener = useRef<HTMLElement | null>(null);
  const pathname = usePathname();

  const button = useRef<HTMLButtonElement>(null);

  const show = useCallback(() => {
    const from = document.activeElement;
    if (from instanceof HTMLElement && from.closest("[data-palette]")) return; // already open
    // Focus goes back where it was on closing: the focused control, or the Search button (a click in Safari, which
    // does not focus buttons, or a shortcut pressed with nothing focused).
    opener.current = from instanceof HTMLElement && from !== document.body ? from : button.current;
    loadPalette().then(
      (module) => {
        setPalette(() => module.CommandPalette);
        setOpen(true);
      },
      () => {}, // offline: nothing opens; the next press tries again
    );
  }, []);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.altKey || event.defaultPrevented) return;
      const shortcut = (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k";
      const slash = event.key === "/" && !event.ctrlKey && !event.metaKey && !inField(event.target);
      if (!shortcut && !slash) return;
      event.preventDefault();
      show();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [show]);

  useEffect(() => {
    if (!pathname || !DETAIL.test(pathname)) return;
    // After the page has painted its title (the same h1 RouteFocus moves focus to).
    const frame = requestAnimationFrame(() => {
      const title = document.querySelector("main h1")?.textContent ?? "";
      const org = new URLSearchParams(window.location.search).get("org");
      rememberVisit(org ? `${pathname}?org=${encodeURIComponent(org)}` : pathname, title);
    });
    return () => cancelAnimationFrame(frame);
  }, [pathname]);

  return (
    <>
      <button
        ref={button}
        type="button"
        onClick={show}
        onPointerEnter={() => void loadPalette().catch(() => {})}
        onFocus={() => void loadPalette().catch(() => {})}
        aria-haspopup="dialog"
        aria-keyshortcuts="Control+K Meta+K /"
        className="search-pill"
        data-search-trigger=""
      >
        <SearchIcon />
        <span className="sr-only sm:not-sr-only sm:truncate">{data.strings.trigger}</span>
        {/* The shortcut as this computer writes it (the server reads the browser's platform: no script for it). */}
        <kbd aria-hidden="true" className="kbd ml-auto max-sm:hidden">
          {data.shortcut}
        </kbd>
      </button>
      {/* Mounted while open, so each opening starts from an empty field and the latest recent pages. */}
      {Palette && open ? (
        <Palette
          data={data}
          onClose={() => {
            setOpen(false);
            opener.current?.focus();
          }}
        />
      ) : null}
    </>
  );
}
