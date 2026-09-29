import { useTranslations } from "next-intl";

import { cn } from "@/components/ui/cn";

import { ChipMark } from "./Chip";
import { endorsementRows, type Detail, type Endorsement, type Party } from "./model";
import { Eat } from "./When";

const PARTIES: readonly Party[] = ["developer", "org"];

/**
 * The current stage's dual endorsement (docs/spec/06 6.9; AC-TRACK-3): one labelled row per party, "Endorsement by
 * Developer" and "Endorsement by Enterprise", each with its status, name, role, time (EAT) and method.
 */
export function Endorsements({ detail }: { detail: Pick<Detail, "endorsements" | "state"> }) {
  const t = useTranslations("tracker");
  const rows = endorsementRows(detail);
  return (
    <section aria-labelledby="endorsements-heading">
      <h2 id="endorsements-heading" className="text-lg text-ink">
        {t("endorsements.title")}
      </h2>
      <ul className="mt-3 grid gap-3 sm:grid-cols-2">
        {PARTIES.map((party) => (
          <li key={party}>
            <EndorsementRow party={party} endorsement={rows[party]} />
          </li>
        ))}
      </ul>
    </section>
  );
}

function EndorsementRow({ party, endorsement }: { party: Party; endorsement: Endorsement | null }) {
  const t = useTranslations("tracker");
  const done = endorsement !== null;
  return (
    <article
      data-endorsement={party}
      data-endorsed={done ? "true" : "false"}
      className={cn("h-full border-t-2 pt-3", done ? "border-ok" : "border-line")}
    >
      <h3 className="font-semibold text-ink">{t(`endorsements.by.${party}`)}</h3>
      <p className={cn("mt-1 flex items-center gap-1.5 text-sm font-semibold", done ? "text-ok" : "text-ink-soft")}>
        <ChipMark kind={done ? "completed" : "pending"} className="size-4" />
        {done ? t("endorsements.endorsed") : t("endorsements.notYet")}
      </p>
      {endorsement ? (
        <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
          <dt className="text-ink-soft">{t("endorsements.name")}</dt>
          <dd className="min-w-0 [overflow-wrap:anywhere] text-ink">{endorsement.name ?? t("endorsements.platform")}</dd>
          <dt className="text-ink-soft">{t("endorsements.role")}</dt>
          <dd className="text-ink">{t(`role.${endorsement.role}`)}</dd>
          <dt className="text-ink-soft">{t("endorsements.time")}</dt>
          <dd className="text-ink">
            <Eat iso={endorsement.endorsed_at} />
          </dd>
          <dt className="text-ink-soft">{t("endorsements.method")}</dt>
          <dd className="text-ink">{t(`method.${endorsement.method}`)}</dd>
        </dl>
      ) : null}
    </article>
  );
}
