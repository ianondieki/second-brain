"use client";

import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";

import { forgetOffline } from "@/components/offline/clear";
import { Button } from "@/components/ui/Button";
import { AlertIcon } from "@/components/ui/status-icons";
import { settle } from "@/lib/api/call";
import { api } from "@/lib/api/client";

/** One persona as the page drew it: the server renders the words (and checked `home` is a path on this site). */
export interface PersonaChoice {
  key: string;
  home: string;
  /** The avatar and the words (name, role, detail): two cells of the row, server-rendered. */
  body: ReactNode;
  /** The button's words: "Continue", with "as {name}" for screen readers (its accessible name names the persona). */
  label: ReactNode;
}

export interface PersonaPickerProps {
  personas: PersonaChoice[];
  /** The list's accessible name. */
  label: string;
  strings: { signingIn: string; tooMany: string; failed: string };
}

/**
 * The public demo's persona picker (REQ-FND-04; docs/platform/tasks/P28.md, track PD): one row per persona, its whole
 * row the button's target. A press POSTs /api/auth/demo/sign-in with the persona's key through the typed client (the
 * double-submit CSRF header, as the email form's sign-in), then goes to the persona's Home. A refusal is one line in
 * that row: 429 says to wait a minute, anything else a calm generic line. Small on purpose: /login is near its 150 KB.
 */
export function PersonaPicker({ personas, label, strings }: PersonaPickerProps) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [refused, setRefused] = useState<{ key: string; line: string } | null>(null);

  async function signIn({ key, home }: PersonaChoice) {
    if (busy) return;
    setBusy(key);
    setRefused(null);
    const outcome = await settle(api.POST("/api/auth/demo/sign-in", { body: { persona: key } }));
    if (outcome.ok) {
      // As every sign-in: no other person's offline copies stay on this device (P27, D-69), then the persona's Home.
      await forgetOffline();
      router.replace(outcome.data.mfa_required ? "/auth/mfa" : home);
      return;
    }
    setBusy(null);
    setRefused({ key, line: outcome.status === 429 ? strings.tooMany : strings.failed });
  }

  return (
    <ul aria-label={label} className="mt-8 flex flex-col border-t border-line" data-personas="">
      {personas.map((persona) => (
        <li
          key={persona.key}
          data-persona={persona.key}
          className={
            "relative grid grid-cols-[auto_minmax(0,1fr)] items-start gap-x-4 gap-y-2.5 border-b border-line py-4 " +
            "sm:grid-cols-[auto_minmax(0,1fr)_auto] sm:items-center"
          }
        >
          {persona.body}
          <Button
            busy={busy === persona.key}
            onClick={() => void signIn(persona)}
            // The row is the target: the button's ::after covers it (the button stays the one control, and its hover
            // shows wherever the row is pointed at).
            className="col-start-2 justify-self-start after:absolute after:inset-0 sm:col-start-3"
          >
            {busy === persona.key ? strings.signingIn : persona.label}
          </Button>
          {refused?.key === persona.key ? (
            <p role="alert" className="col-start-2 flex items-start gap-1.5 text-sm font-medium text-error sm:col-span-2">
              <AlertIcon className="mt-px size-5 shrink-0" />
              <span>{refused.line}</span>
            </p>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
