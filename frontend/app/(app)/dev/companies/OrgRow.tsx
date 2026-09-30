import { useTranslations } from "next-intl";

import { Row } from "@/components/ui/RowList";

import { orgHref, type DirectoryFilters, type OrgCard } from "./filters";
import { VerificationBadge } from "./VerificationBadge";

/**
 * One organisation in the directory (a Row, the whole row its link): name, org type and county, and the verification
 * badge, which is the row's one badge (docs/spec/07 item 2: at most two). The niche is the section heading above;
 * never a logo (docs/spec/04 principle 4). The response record shows only when the API sends one (E2, enough history).
 */
export function OrgRow({ org, filters = {} }: { org: OrgCard; filters?: DirectoryFilters }) {
  const t = useTranslations("companies");
  const kinds = useTranslations("orgKind");
  const kind = kinds(org.kind);
  return (
    <Row
      data-org={org.slug}
      title={org.name}
      href={orgHref(org.id, filters)}
      meta={org.county ? t("meta", { kind, county: org.county.name }) : kind}
      badges={[<VerificationBadge key="badge" badge={org.badge} />]}
    >
      {org.responsiveness ? <p className="text-sm text-ink">{org.responsiveness.text}</p> : null}
    </Row>
  );
}
