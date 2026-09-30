"use client";

import type { Ref } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";

import type { Preview } from "../../scout";

/**
 * Preview matches (docs/spec/06 6.8; AC-SCOUT-5: the Preview equals the first digest): what these settings would have
 * matched over the last 30 days by the rules alone, nothing saved. An on_new scout never runs over that window (it
 * sends each new proposal as it is published), so its preview says so first. Proposals appear by pseudonymous handle.
 */
export function ScoutPreview({ preview, headingRef }: { preview: Preview; headingRef?: Ref<HTMLHeadingElement> }) {
  const t = useStrings("scoutForm");
  return (
    <section aria-labelledby="preview-heading" data-preview="" className="flex flex-col gap-3">
      <h2 id="preview-heading" ref={headingRef} tabIndex={-1} className="text-lg text-ink focus:outline-none">
        {t("previewTitle")}
      </h2>
      {preview.note ? (
        <Alert tone="info" className="w-full">
          <p data-preview-note="">{t("previewOnNew", { count: preview.window_days })}</p>
        </Alert>
      ) : null}
      {preview.items.length === 0 ? (
        <p className="text-ink">{t("previewEmpty", { count: preview.window_days })}</p>
      ) : (
        <>
          <div className="text-ink">
            <p data-preview-total={preview.total}>
              {t("previewTotal", { count: preview.window_days, total: preview.total })}
            </p>
            {preview.total > preview.digest_size ? <p>{t("previewDigest", { max: preview.digest_size })}</p> : null}
          </div>
          <ol aria-label={t("previewLabel")} className="flex flex-col">
            {preview.items.map((item) => (
              <li key={item.proposal_id} className="flex min-w-0 flex-col gap-1 border-t border-line py-4">
                <p className="text-sm font-semibold text-jacaranda tabular-nums">{t("fit", { value: item.score })}</p>
                <p className="font-semibold [overflow-wrap:anywhere] text-ink">{item.teaser.title ?? t("untitled")}</p>
                <p className="text-sm text-ink-soft [overflow-wrap:anywhere]">
                  {item.owner_handle ? <span className="block">{t("by", { name: item.owner_handle })}</span> : null}
                  {item.teaser.niche ? <span className="block">{item.teaser.niche.label}</span> : null}
                </p>
                <p className="max-w-[64ch] border-l-2 border-line pl-3 text-sm text-ink [overflow-wrap:anywhere]">
                  {item.why}
                </p>
              </li>
            ))}
          </ol>
        </>
      )}
    </section>
  );
}
