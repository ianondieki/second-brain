"use client";

import Link from "next/link";
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
import { standaloneLinkClass } from "@/components/ui/Button";

import { threadHref } from "./teams";

export type Said = { kind: "accepted"; name: string; threadId: string } | { kind: "declined" | "withdrawn" | "gone" | "failed" };

const Say = createContext<(said: Said) => void>(() => {});

/** The status line's setter of the page's StatusHost. */
export function useSay() {
  return useContext(Say);
}

/**
 * /dev/teams' status line (REQ-DEV-03), above the page's sections: what an answer to an invitation did, taking focus.
 * It sits outside the sections so reading the page again after an answer (the card leaves, a new thread appears under
 * Threads, or the page has nothing left) keeps it.
 */
export function StatusHost({ children }: { children: ReactNode }) {
  const t = useStrings("teamUp");
  const [said, setSaid] = useState<(Said & { n: number }) | null>(null);
  const status = useRef<HTMLDivElement>(null);
  const say = useCallback((next: Said) => setSaid((now) => ({ ...next, n: (now?.n ?? 0) + 1 })), []);

  useEffect(() => {
    if (said) status.current?.focus();
  }, [said]);

  return (
    <Say value={say}>
      {said ? (
        <Alert key={said.n} ref={status} tone={said.kind === "failed" || said.kind === "gone" ? "error" : "ok"} className="-mt-4">
          {said.kind === "accepted" ? (
            <span className="flex flex-col items-start">
              {t("invitation.accepted", { name: said.name })}
              <Link href={threadHref(said.threadId)} className={standaloneLinkClass} data-open-thread="">
                {t("invitation.openThread")}
              </Link>
            </span>
          ) : (
            t(`invitation.${said.kind}`)
          )}
        </Alert>
      ) : null}
      {children}
    </Say>
  );
}
