"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { AlertIcon } from "@/components/ui/status-icons";
import { focusPageTitle } from "@/lib/focus";

import { markAllRead } from "./calls";

export interface MarkAllReadLabels {
  idle: string;
  busy: string;
  done: string;
  failed: string;
}

/**
 * "Mark all as read", the page's one secondary action (never the primary): POST …/read-all, then the page and the
 * top bar's bell are read again (router.refresh), so both show none unread. Disabled when nothing is unread. The
 * outcome is said in a polite status line; a failure in words under the button, with the button there to try again.
 */
export function MarkAllRead({ unread, labels }: { unread: number; labels: MarkAllReadLabels }) {
  const router = useRouter();
  const [state, setState] = useState<"idle" | "busy" | "done" | "failed">("idle");

  async function onClick() {
    setState("busy");
    if (!(await markAllRead())) {
      setState("failed");
      return;
    }
    setState("done");
    // The button turns disabled with the refreshed page: focus goes to the page's title, never to <body>.
    focusPageTitle();
    router.refresh();
  }

  return (
    <div className="flex flex-col items-start gap-1 sm:items-end">
      <Button
        variant="secondary"
        busy={state === "busy"}
        disabled={unread === 0 && state !== "busy"}
        onClick={onClick}
        data-mark-all-read=""
        className="disabled:cursor-not-allowed disabled:border-line disabled:text-ink-soft disabled:hover:bg-transparent"
      >
        {state === "busy" ? labels.busy : labels.idle}
      </Button>
      <p role="status" className={cn("text-sm text-ink-soft sm:text-right", state !== "done" && "sr-only")}>
        {state === "done" ? labels.done : ""}
      </p>
      {state === "failed" ? (
        <p role="alert" className="flex max-w-[18rem] items-start gap-1.5 text-sm font-medium text-error sm:text-right">
          <AlertIcon className="mt-px size-5 shrink-0" />
          <span>{labels.failed}</span>
        </p>
      ) : null}
    </div>
  );
}
