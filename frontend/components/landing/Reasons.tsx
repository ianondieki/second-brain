import { getTranslations } from "next-intl/server";

import { CheckIcon } from "@/components/ui/status-icons";

// The why-panel's lines: the Discover ranker's own words for one seeded card (backend bridge/matching/ranker.py:
// the pursuit decision and its reason, three Why chips and the Why-not chip, as the API returns them).
const LINES = [
  { key: "card", value: "card" },
  { key: "decision", value: "decision" },
  { key: "reason", value: "reason" },
  { key: "why", value: "why1" },
  { key: "why", value: "why2" },
  { key: "why", value: "why3" },
  { key: "whyNot", value: "whyNot" },
] as const;

/**
 * The night band (D-66, after Basix's reasoning panel): every recommendation names its reason. The text on the left;
 * on the right a terminal-style panel with the ranker's real reason texts for one seeded card, labelled "Seeded
 * example". A list of key and value pairs, so it reads in order to assistive technology.
 */
export async function Reasons() {
  const t = await getTranslations("landing.reasons");
  return (
    <section aria-labelledby="reasons-title" className="on-night bg-night py-20 lg:py-28">
      <div className="mx-auto grid w-full max-w-6xl grid-cols-1 items-center gap-12 px-4 sm:px-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] lg:gap-16">
        <div>
          <p className="eyebrow">{t("eyebrow")}</p>
          <h2 id="reasons-title" className="mt-4 max-w-[18ch] text-3xl text-ink lg:text-4xl">
            {t("title")}
          </h2>
          <p className="mt-5 max-w-[52ch] text-lg text-ink-soft">{t("lead")}</p>
          <ul className="mt-8 flex flex-col gap-3.5">
            {(["point1", "point2", "point3"] as const).map((key) => (
              <li key={key} className="flex gap-3 text-ink">
                <CheckIcon aria-hidden="true" className="mt-0.5 size-5 shrink-0 text-flourish" />
                {t(key)}
              </li>
            ))}
          </ul>
        </div>
        <figure className="terminal">
          <figcaption className="flex items-center justify-between gap-4 border-b border-night-line px-5 py-3.5">
            <span className="flex items-center gap-3">
              <span aria-hidden="true" className="flex gap-1.5">
                <i className="size-2.5 rounded-full bg-night-line" />
                <i className="size-2.5 rounded-full bg-night-line" />
                <i className="size-2.5 rounded-full bg-night-line" />
              </span>
              <span className="font-mono text-xs text-ink-soft">{t("panelTitle")}</span>
            </span>
            <span className="demo-label">{t("seeded")}</span>
          </figcaption>
          <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-5 gap-y-2.5 px-5 py-5 font-mono text-[0.8125rem] leading-relaxed sm:text-sm">
            {LINES.map(({ key, value }) => (
              <div key={value} className="contents">
                <dt className={key === "whyNot" ? "text-flourish" : "text-accent"}>{t(`keys.${key}`)}</dt>
                <dd className={value === "card" ? "font-semibold text-ink" : "text-ink"}>{t(`values.${value}`)}</dd>
              </div>
            ))}
          </dl>
          <p className="mx-3 mb-3 flex items-center gap-2 rounded-xl bg-accent-wash px-4 py-3 font-mono text-[0.8125rem] text-ink">
            <span aria-hidden="true" className="text-flourish">
              ⇒
            </span>
            {t("values.fit")}
          </p>
          <p className="border-t border-night-line px-5 py-3 text-xs text-ink-soft">{t("footer")}</p>
        </figure>
      </div>
    </section>
  );
}
