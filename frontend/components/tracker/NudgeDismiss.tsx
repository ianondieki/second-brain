"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api/client";

/**
 * The developer's dismissal of the IP note (REQ-DEV-04), loaded when Dismiss is pressed (components/tracker/lazy.tsx):
 * POST /api/me/profile/ip-nudge/dismiss; then the note is hidden (and gone from the refreshed tracker) and focus moves
 * to the actions' heading. A refusal is said beside the button, which tries again when pressed.
 */
export function NudgeDismiss({ failed, onClose }: { failed: string; onClose: (changed: boolean) => void }) {
  const [refused, setRefused] = useState(false);
  useEffect(() => {
    let live = true;
    void api
      .POST("/api/me/profile/ip-nudge/dismiss")
      .then(
        ({ response }) => response.ok,
        () => false,
      )
      .then((ok) => {
        if (!live) return;
        if (!ok) return setRefused(true);
        document.querySelector("[data-ip-nudge]")?.setAttribute("hidden", "");
        document.getElementById("actions-heading")?.focus();
        onClose(true);
      });
    return () => {
      live = false;
    };
    // Once per press (the button draws this anew each time).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return refused ? (
    <span role="alert" className="text-sm font-medium text-error">
      {failed}
    </span>
  ) : null;
}
