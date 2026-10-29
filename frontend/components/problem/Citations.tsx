import { getLocale, getTranslations } from "next-intl/server";

import { CheckIcon } from "@/components/ui/icons";

import { formatDate, safeHttpsUrl, sourceType, type Citation } from "./problem";

/**
 * A problem card's cited sources (REQ-RES-02; docs/spec/06 6.5 evidence): each quote verbatim, as the publisher wrote
 * it, with who published it, what kind of source it is, when, and a link to read it there. Shared by the signed-in
 * problem page and the staff review screen, so staff approve exactly what people will read.
 */
export async function Citations({ sources, labelledBy }: { sources: readonly Citation[]; labelledBy: string }) {
  const t = await getTranslations("problem");
  const locale = await getLocale();
  return (
    <ol aria-labelledby={labelledBy} className="flex flex-col gap-8">
      {sources.map((source, index) => {
        const href = safeHttpsUrl(source.url);
        const publisher = source.publisher?.trim() || t("unknownPublisher");
        const type = sourceType(source.source_type);
        return (
          <li key={`${source.url}-${index}`} data-citation="" className="flex min-w-0 flex-col gap-3">
            <p className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className="font-semibold [overflow-wrap:anywhere] text-ink">{publisher}</span>
              <span className="inline-flex items-center gap-1 text-sm font-medium text-ink-soft">
                {type === "official" ? <CheckIcon className="size-4 text-ok" /> : null}
                {t(`sourceType.${type}`)}
              </span>
              <span className="text-sm text-ink-soft">
                {source.published_date
                  ? t("publishedOn", { date: formatDate(locale, source.published_date) })
                  : t("noDate")}
              </span>
            </p>
            {source.quote ? (
              <blockquote
                cite={href ?? undefined}
                className="max-w-[62ch] border-l-2 border-line pl-4 text-ink [overflow-wrap:anywhere]"
              >
                <p>{source.quote}</p>
              </blockquote>
            ) : null}
            {href ? (
              <a
                href={href}
                rel="noopener noreferrer"
                className="inline-flex min-h-11 max-w-full items-center self-start font-semibold [overflow-wrap:anywhere] text-accent underline decoration-1 hover:decoration-2"
              >
                <span>
                  {t("open", { publisher })} <span className="sr-only">{t("external")}</span>
                </span>
              </a>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}
