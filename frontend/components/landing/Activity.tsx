import { getTranslations } from "next-intl/server";

import { publicActivity } from "@/lib/public/public-data";

import { Ticker } from "./Ticker";

/**
 * The landing's "What's happening" (D-66) over GET /api/public/activity: the section is left out when the read fails
 * or the feed is empty. Labelled "Seeded example" when the feed says its rows are the demo seed's. Rendered inside a
 * Suspense boundary (LandingContent), so the page never waits on this read.
 */
export async function Activity() {
  const [t, activity] = await Promise.all([getTranslations("landing.activity"), publicActivity()]);
  if (!activity) return null;
  return (
    <section aria-labelledby="activity-title" data-activity="" className="overflow-hidden pt-4 pb-20 lg:pb-28">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 px-4 sm:px-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="eyebrow">{t("eyebrow")}</p>
          <h2 id="activity-title" className="mt-4 text-3xl text-ink lg:text-4xl">
            {t("title")}
          </h2>
          <p className="mt-4 max-w-[56ch] text-lg text-ink-soft">{t("lead")}</p>
        </div>
        {activity.seeded ? <p className="demo-label self-start lg:self-end">{t("seeded")}</p> : null}
      </div>
      <div className="mt-10">
        <Ticker activity={activity} />
      </div>
    </section>
  );
}
