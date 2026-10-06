"use client";

import { useEffect, useRef, useState } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";

import type { Blocked } from "@/app/(app)/dev/teams/teams";

import { profileCalls, type ProfileCalls } from "./calls";

/**
 * The developers the caller blocked (REQ-DEV-03), under the peers switch: each handle with "Unblock" (secondary). A
 * lifted block leaves the list and a status line says so (closed threads stay closed); it takes focus.
 */
export function BlockedList({ initial, calls: given }: { initial: readonly Blocked[]; calls?: Partial<ProfileCalls> }) {
  const t = useStrings("profileSettings");
  const [calls] = useState<ProfileCalls>(() => ({ ...profileCalls(), ...given }));
  const [items, setItems] = useState(initial);
  const [busy, setBusy] = useState<string | null>(null);
  const [said, setSaid] = useState<{ ok: boolean; text: string; n: number } | null>(null);
  const status = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (said) status.current?.focus();
  }, [said]);

  async function unblock(item: Blocked) {
    if (busy) return;
    setBusy(item.user_id);
    const ok = await calls.unblock(item.user_id);
    setBusy(null);
    if (ok) setItems((now) => now.filter((other) => other.user_id !== item.user_id));
    setSaid((now) => ({ ok, text: ok ? t("blocked.unblocked", { name: item.handle }) : t("blocked.failed"), n: (now?.n ?? 0) + 1 }));
  }

  return (
    <div className="flex flex-col gap-4">
      {said ? (
        <Alert key={said.n} ref={status} tone={said.ok ? "ok" : "error"}>
          {said.text}
        </Alert>
      ) : null}
      {items.length > 0 ? (
        <ul className="flex flex-col divide-y divide-line border-y border-line" data-blocked-list="">
          {items.map((item) => (
            <li key={item.user_id} className="flex items-center justify-between gap-4 py-2" data-blocked={item.handle}>
              <span id={`blocked-${item.user_id}`} className="min-w-0 font-semibold text-ink [overflow-wrap:anywhere]">
                {item.handle}
              </span>
              <Button busy={busy === item.user_id} aria-describedby={`blocked-${item.user_id}`} onClick={() => void unblock(item)} data-unblock="">
                {busy === item.user_id ? t("blocked.unblocking") : t("blocked.unblock")}
              </Button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
