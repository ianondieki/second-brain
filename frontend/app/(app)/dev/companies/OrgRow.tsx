import Link from "next/link";
import { useTranslations } from "next-intl";

import { orgHref, type DirectoryFilters, type OrgCard } from "./filters";
import { VerificationBadge } from "./VerificationBadge";

/**
 * One organisation in the directory: name (a link to its page), org type and county, and the verification badge,
 * which is the card's one chip (docs/spec/07 item 2: at most two). The niche is the group heading above; never a
 * logo (docs/spec/04 principle 4). The response record shows only when the API sends one (E2, enough history).
 */
export function OrgRow({ org, filters = {} }: { org: OrgCard; filters?: DirectoryFilters }) {
  const t = useTranslations("companies");
  const kinds = useTranslations("orgKind");
  const kind = kinds(org.kind);
  return (
    <article className="flex min-w-0 flex-col gap-1 border-t border-line py-4" data-org={org.slug}>
      <h3 className="text-base leading-snug">
        <Link
          href={orgHref(org.id, filters)}
          className={
            "-my-2 inline-flex min-h-11 items-center py-2 font-semibold [overflow-wrap:anywhere] text-ink " +
            "underline decoration-transparent decoration-1 underline-offset-[0.2em] hover:decoration-jacaranda"
          }
        >
          {org.name}
        </Link>
      </h3>
      <p className="text-sm text-ink-soft">{org.county ? t("meta", { kind, county: org.county.name }) : kind}</p>
      <VerificationBadge badge={org.badge} className="mt-1" />
      {org.responsiveness ? <p className="text-sm text-ink">{org.responsiveness.text}</p> : null}
    </article>
  );
}
