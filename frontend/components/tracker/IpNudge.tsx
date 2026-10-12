import { getTranslations } from "next-intl/server";

import { Callout } from "@/components/ui/Callout";
import { buttonClass, textLinkClass } from "@/components/ui/Button";

import { PartButton } from "./lazy";
import type { TrackerDetail } from "./model";

/**
 * The one note before a developer first shares a full proposal (REQ-DEV-04; docs/spec/06 6.1 "non-blocking nudge"):
 * under their buttons while the API's `ip_nudge` says so (their next step is sending the NDA, no full-proposal view
 * yet, never dismissed), with KIPI's and KECOBO's sites and Dismiss. Server-rendered; Dismiss loads its call when
 * pressed (components/tracker/lazy.tsx).
 */
export async function IpNudge({ detail }: { detail: TrackerDetail }) {
  if (detail.my_party !== "developer" || !detail.ip_nudge) return null;
  const t = await getTranslations("tracker.ipNudge");
  return (
    <div data-ip-nudge="" className="border-t border-line px-5 py-4 sm:px-7">
      <Callout as="aside" tone="info" aria-label={t("label")}>
        <p className="max-w-[65ch] text-ink">{t("body")}</p>
        <p className="flex flex-wrap gap-x-5">
          <a href="https://kipi.go.ke" target="_blank" rel="noopener noreferrer" className={textLinkClass}>
            {t("kipi")}
            <span className="sr-only"> {t("newTab")}</span>
          </a>
          <a href="https://copyright.go.ke" target="_blank" rel="noopener noreferrer" className={textLinkClass}>
            {t("kecobo")}
            <span className="sr-only"> {t("newTab")}</span>
          </a>
        </p>
        <div className="flex flex-col items-start gap-2">
          <PartButton
            part="nudge"
            props={{ failed: t("failed") }}
            label={t("dismiss")}
            className={buttonClass("secondary")}
          />
        </div>
      </Callout>
    </div>
  );
}
