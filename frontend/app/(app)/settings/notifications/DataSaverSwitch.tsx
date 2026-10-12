"use client";

import { useState } from "react";

import { useStrings } from "@/components/ClientStrings";
import { dataSaverCookie } from "@/lib/data-saver";

/**
 * The data-saver switch (P27 track F; REQ-UX-08; docs/spec/07 item 5): on this device, no photographs and the smallest
 * images, as the browser's `Save-Data: on` asks. It takes effect at once (a cookie, lib/data-saver.ts; nothing to
 * save, nothing stored on the account): the next page the server draws reads it. `initial` is the cookie as the
 * server read it, so hydration is unchanged.
 */
export function DataSaverSwitch({ initial }: { initial: boolean }) {
  const t = useStrings("profileSettings");
  const [on, setOn] = useState(initial);

  function toggle() {
    const next = !on;
    document.cookie = dataSaverCookie(next, location.protocol === "https:");
    setOn(next);
  }

  return (
    <div className="flex flex-col gap-1" data-data-saver={on ? "on" : "off"}>
      <span className="inline-flex items-center gap-3">
        <button
          type="button"
          role="switch"
          aria-checked={on}
          aria-describedby="data-saver-explain"
          onClick={toggle}
          className="group inline-flex min-h-11 items-center gap-3 font-semibold text-ink"
        >
          <span
            aria-hidden="true"
            className="relative h-6 w-10 shrink-0 rounded-full border border-ink-soft bg-field transition-colors group-aria-checked:border-accent group-aria-checked:bg-accent motion-reduce:transition-none"
          >
            <span className="absolute top-0.5 left-0.5 size-4 rounded-full bg-ink-soft transition-transform group-aria-checked:translate-x-4 group-aria-checked:bg-on-accent motion-reduce:transition-none" />
          </span>
          {t("dataSaver")}
        </button>
        <span aria-hidden="true" className="text-sm text-ink-soft">
          {on ? t("on") : t("off")}
        </span>
      </span>
      <p id="data-saver-explain" className="max-w-[60ch] text-sm text-ink-soft">
        {t("dataSaverExplain")}
      </p>
    </div>
  );
}
