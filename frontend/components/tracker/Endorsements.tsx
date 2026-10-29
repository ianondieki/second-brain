import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/Badge";
import { Description, DescriptionList } from "@/components/ui/DescriptionList";
import { Section } from "@/components/ui/Section";

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
    <Section title={t("endorsements.title")} headingId="endorsements-heading">
      <ul className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
        {PARTIES.map((party) => (
          <li key={party}>
            <EndorsementRow party={party} endorsement={rows[party]} />
          </li>
        ))}
      </ul>
    </Section>
  );
}

function EndorsementRow({ party, endorsement }: { party: Party; endorsement: Endorsement | null }) {
  const t = useTranslations("tracker");
  const done = endorsement !== null;
  return (
    <article
      data-endorsement={party}
      data-endorsed={done ? "true" : "false"}
      className="h-full border-t border-line pt-3"
    >
      <h3 className="font-semibold text-ink">{t(`endorsements.by.${party}`)}</h3>
      <p className="mt-1">
        <Badge tone={done ? "ok" : "neutral"} icon={<ChipMark kind={done ? "completed" : "pending"} />}>
          {done ? t("endorsements.endorsed") : t("endorsements.notYet")}
        </Badge>
      </p>
      {endorsement ? (
        <DescriptionList dense className="mt-2">
          <Description label={t("endorsements.name")}>{endorsement.name ?? t("endorsements.platform")}</Description>
          <Description label={t("endorsements.role")}>{t(`role.${endorsement.role}`)}</Description>
          <Description label={t("endorsements.time")}>
            <Eat iso={endorsement.endorsed_at} />
          </Description>
          <Description label={t("endorsements.method")}>{t(`method.${endorsement.method}`)}</Description>
        </DescriptionList>
      ) : null}
    </article>
  );
}
