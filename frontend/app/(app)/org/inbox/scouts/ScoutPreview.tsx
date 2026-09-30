"use client";

import type { Ref } from "react";

import { useStrings } from "@/components/ClientStrings";
import { Alert } from "@/components/ui/Alert";
// RowBase, not Row: these rows have no page, and RowBase's module leaves next/link out of the scout form's bundle.
import { RowBase, RowList } from "@/components/ui/RowBase";

import type { Preview } from "../../scout-draft";
import { FitBar } from "../matches/FitBar";

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
          <RowList ordered aria-label={t("previewLabel")}>
            {preview.items.map((item) => (
              <RowBase
                key={item.proposal_id}
                title={item.teaser.title ?? t("untitled")}
                meta={
                  <span className="flex flex-wrap gap-x-4 gap-y-1">
                    {item.owner_handle ? <span>{t("by", { name: item.owner_handle })}</span> : null}
                    {item.teaser.niche ? <span>{item.teaser.niche.label}</span> : null}
                  </span>
                }
                badges={[
                  <FitBar
                    key="fit"
                    value={item.score}
                    short={t("fit", { value: item.score })}
                    long={t("fitLong", { value: item.score })}
                  />,
                ]}
              >
                <p className="max-w-[64ch] text-sm text-ink [overflow-wrap:anywhere]">{item.why}</p>
              </RowBase>
            ))}
          </RowList>
        </>
      )}
    </section>
  );
}
