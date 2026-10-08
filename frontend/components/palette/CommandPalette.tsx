"use client";

import { useRouter } from "next/navigation";
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent } from "react";

import { withCsrf } from "@/lib/api/csrf";
import { forgetEmail } from "@/lib/auth/remembered-email";
import { applyTheme } from "@/lib/theme";

import { matchParts, paletteGroups, type PaletteOption } from "./model";
import { readRecent } from "./recent";
import { search, SEARCH_DEBOUNCE_MS, searchQuery, type SearchGroup } from "./search";
import type { PaletteData } from "./types";

export interface CommandPaletteProps {
  data: PaletteData;
  /** Closes the palette (the opener puts focus back where it was). */
  onClose: () => void;
}

/** The page is dark now: a choice made here, else the system's. */
function pageIsDark(): boolean {
  const theme = document.documentElement.dataset.theme;
  if (theme) return theme === "dark";
  return typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function Title({ text, query }: { text: string; query: string }) {
  const parts = matchParts(text, query);
  if (!parts) return <>{text}</>;
  return (
    <>
      {parts[0]}
      <mark>{parts[1]}</mark>
      {parts[2]}
    </>
  );
}

function Arrow() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="size-4 shrink-0">
      <path d="M4 10h11M11 5.5 15.5 10 11 14.5" />
    </svg>
  );
}

/**
 * The command palette (D-67, P25): jump to any section, a recent page, your ideas, engagements, problems and listed
 * companies, or run an action (New proposal or Post a Brief, the appearance, Sign out). WAI-ARIA APG: an editable
 * combobox with a grouped listbox, inside a modal dialog (the rest of the page is inert; Escape closes; the opener
 * gets focus back). The active option is the input's aria-activedescendant; arrows, Home and End move it; Enter opens
 * it, Ctrl/⌘ Enter in a new tab; the typed letters are marked in each title.
 */
export function CommandPalette({ data, onClose }: CommandPaletteProps) {
  const s = data.strings;
  const router = useRouter();
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const id = useId();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [answer, setAnswer] = useState<{ q: string; groups: SearchGroup[] }>({ q: "", groups: [] });
  const [recent] = useState(() => readRecent());
  const [dark] = useState(pageIsDark);
  const [signOutFailed, setSignOutFailed] = useState(false);
  const [mod] = useState(() => (/Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent) ? "⌘" : "Ctrl"));

  const q = searchQuery(query);
  const searching = q !== null && answer.q !== q;
  const groups = useMemo(
    () => paletteGroups({ data, query, recent, results: q !== null && answer.q === q ? answer.groups : [], dark }),
    [data, query, recent, answer, q, dark],
  );
  const options = groups.flatMap((group) => group.options);
  // Each group's first option's place in the whole list (the listbox's options are numbered across groups).
  const starts = groups.map((_, g) => groups.slice(0, g).reduce((sum, group) => sum + group.options.length, 0));
  const current = options.length > 0 ? Math.min(active, options.length - 1) : -1;
  const optionId = (index: number) => `${id}-o${index}`;

  // Opened as a modal at once (the rest of the page inert), with focus in the field.
  useEffect(() => {
    const box = dialog.current;
    if (box && !box.open) box.showModal();
    input.current?.focus();
  }, []);

  // The API's groups: after a pause in typing (180 ms), the previous call aborted by the next keystroke.
  useEffect(() => {
    if (q === null) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void search(q, controller.signal).then((found) => {
        if (!controller.signal.aborted) setAnswer({ q, groups: found });
      });
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [q]);

  // The active option stays in view as the arrows move it.
  useEffect(() => {
    if (current >= 0) document.getElementById(`${id}-o${current}`)?.scrollIntoView?.({ block: "nearest" });
  }, [current, id]);

  async function signOut() {
    const status = await withCsrf()("/api/auth/logout", { method: "POST", credentials: "same-origin" }).then(
      (response) => response.status,
      () => 0,
    );
    if (status === 204 || status === 401) {
      forgetEmail(); // the next person on this device should not see this address offered back
      router.replace("/login");
      router.refresh();
      return;
    }
    setSignOutFailed(true);
  }

  function run(option: PaletteOption, newTab: boolean) {
    if (option.action === "theme") {
      applyTheme(dark ? "light" : "dark", document.documentElement, window.localStorage);
      onClose();
    } else if (option.action === "signout") {
      void signOut();
    } else if (newTab) {
      window.open(option.href, "_blank", "noopener,noreferrer");
      onClose();
    } else {
      onClose();
      router.push(option.href);
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    const last = options.length - 1;
    let next: number | null = null;
    if (event.key === "ArrowDown") next = current >= last ? 0 : current + 1;
    else if (event.key === "ArrowUp") next = current <= 0 ? last : current - 1;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = last;
    else if (event.key === "Escape") {
      event.preventDefault(); // handled here, so the dialog's own close request does not follow
      onClose();
      return;
    } else if (event.key === "Enter") {
      event.preventDefault();
      const option = options[current];
      if (option) run(option, event.ctrlKey || event.metaKey);
      return;
    }
    if (next === null || last < 0) return;
    event.preventDefault();
    setActive(next);
  }

  function onPick(event: MouseEvent, option: PaletteOption) {
    run(option, event.ctrlKey || event.metaKey);
  }

  return (
    <dialog
      ref={dialog}
      aria-label={s.dialog}
      className="palette"
      data-palette=""
      onCancel={(event) => {
        event.preventDefault(); // Escape: closed by the opener, which puts focus back
        onClose();
      }}
      onClick={(event) => {
        if (event.target === dialog.current) onClose(); // a press on the backdrop
      }}
    >
      <div className="flex items-center gap-2 border-b border-line px-3 sm:px-4">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" aria-hidden="true" className="size-5 shrink-0 text-ink-soft">
          <circle cx="11" cy="11" r="6.5" />
          <path d="m16 16 4 4" />
        </svg>
        <label htmlFor={`${id}-input`} className="sr-only">
          {s.input}
        </label>
        <input
          ref={input}
          id={`${id}-input`}
          type="text"
          role="combobox"
          aria-expanded="true"
          aria-controls={`${id}-list`}
          aria-autocomplete="list"
          aria-activedescendant={current >= 0 ? optionId(current) : undefined}
          autoComplete="off"
          autoCorrect="off"
          spellCheck={false}
          enterKeyHint="go"
          maxLength={80}
          placeholder={s.trigger}
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setActive(0);
          }}
          onKeyDown={onKeyDown}
          className="min-h-14 min-w-0 flex-1 bg-transparent text-base text-ink placeholder:text-ink-soft focus:outline-none"
        />
        <button
          type="button"
          onClick={onClose}
          className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-control px-2 text-sm font-semibold text-accent hover:bg-paper-deep"
        >
          <span className="sm:sr-only">{s.close}</span>
          <kbd aria-hidden="true" className="kbd max-sm:hidden">
            Esc
          </kbd>
        </button>
      </div>

      <div id={`${id}-list`} role="listbox" aria-label={s.dialog} className="palette-list">
        {groups.map((group, g) => (
          <div key={group.id} role="group" aria-label={group.label} className="pt-2" data-palette-group={group.id}>
            <div aria-hidden="true" className="px-2.5 pt-1 pb-1.5 text-xs font-semibold text-ink-soft">
              {group.label}
            </div>
            {group.options.map((option, o) => {
              const at = starts[g] + o;
              return (
                <div
                  key={option.id}
                  id={optionId(at)}
                  role="option"
                  aria-selected={at === current}
                  className="palette-option"
                  onMouseMove={() => {
                    if (at !== current) setActive(at);
                  }}
                  onClick={(event) => onPick(event, option)}
                >
                  <span className="min-w-0">
                    <span className="block truncate font-medium text-ink">
                      <Title text={option.title} query={query} />
                    </span>
                    {option.subtitle ? <span className="block truncate text-sm text-ink-soft">{option.subtitle}</span> : null}
                  </span>
                  <span className="palette-go">
                    <Arrow />
                  </span>
                </div>
              );
            })}
          </div>
        ))}
      </div>

      {/* What the list holds now, said once it settles; the empty state is one sentence. */}
      <div className="px-4 pb-3 text-sm text-ink-soft" role="status">
        {signOutFailed ? (
          <span className="font-medium text-error">{s.signOutFailed}</span>
        ) : searching ? (
          s.searching
        ) : options.length === 0 ? (
          <span className="block py-4 text-center text-base text-ink">{s.empty.replace("{q}", query.trim())}</span>
        ) : query.trim() ? (
          <span className="sr-only">{s.results.replace("{count}", String(options.length))}</span>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 border-t border-line px-4 py-2.5 text-xs text-ink-soft max-sm:hidden" aria-hidden="true">
        <span className="inline-flex items-center gap-1.5">
          <kbd className="kbd">↑</kbd>
          <kbd className="kbd">↓</kbd>
          {s.keyMove}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <kbd className="kbd">Enter</kbd>
          {s.keyOpen}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <kbd className="kbd">{mod} Enter</kbd>
          {s.keyNewTab}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <kbd className="kbd">Esc</kbd>
          {s.keyClose}
        </span>
      </div>
    </dialog>
  );
}
