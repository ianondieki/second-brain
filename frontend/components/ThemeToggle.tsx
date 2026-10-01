"use client";

import { useId, useSyncExternalStore } from "react";

import { applyTheme, readTheme, THEMES, type ThemeChoice } from "@/lib/theme";

import { useStrings } from "./ClientStrings";
import { cn } from "./ui/cn";
import { CheckIcon } from "./ui/status-icons";

// The choice is read from storage on every render after a change (useSyncExternalStore): listeners here, plus the
// "storage" event for a change made in another tab.
const listeners = new Set<() => void>();
function subscribe(listener: () => void) {
  listeners.add(listener);
  window.addEventListener("storage", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

/**
 * Appearance: system, light or dark (D-52). A radio group, not a cycling button, so the current choice is readable and
 * each option is one press. Applies at once and is remembered in this browser (lib/theme.ts).
 */
export function ThemeToggle({ className }: { className?: string }) {
  const t = useStrings("shell");
  const name = useId();
  const choice = useSyncExternalStore(subscribe, () => readTheme(window.localStorage), () => "system" as ThemeChoice);
  function choose(next: ThemeChoice) {
    applyTheme(next, document.documentElement, window.localStorage);
    for (const listener of listeners) listener();
  }
  return (
    <fieldset data-theme-toggle="" className={cn("flex items-center gap-1", className)}>
      <legend className="sr-only">{t("theme.label")}</legend>
      {THEMES.map((option) => (
        <label
          key={option}
          className={cn(
            "inline-flex min-h-11 min-w-11 cursor-pointer items-center gap-1.5 rounded-control px-2.5 text-sm font-medium",
            "has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-accent",
            // The chosen option carries a check, not a colour alone (WCAG 1.4.11).
            choice === option ? "bg-accent-wash font-semibold text-ink" : "text-ink-soft hover:bg-wash-soft hover:text-ink",
          )}
        >
          <input type="radio" name={name} value={option} checked={choice === option} onChange={() => choose(option)} className="sr-only" />
          {choice === option ? <CheckIcon className="size-4 text-accent" /> : null}
          {t(`theme.${option}`)}
        </label>
      ))}
    </fieldset>
  );
}
