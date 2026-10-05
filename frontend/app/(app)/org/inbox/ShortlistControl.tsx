import { useTranslations } from "next-intl";

import { editsShortlist, type ShortlistProblem } from "../shortlist";
import type { Membership } from "../membership";
import { ShortlistStar } from "./ShortlistStar";
import { StarIcon } from "./StarIcon";

const PROBLEMS: readonly ShortlistProblem[] = ["code", "role", "gone", "network", "failed"];

/**
 * A proposal's place on the shortlist (REQ-REPO-02, P21 B6): the star toggle for the roles that may change the
 * shortlist (a small client island), else a read-only "Shortlisted" mark when it is on it, and nothing when it is not.
 * The mark is a status (icon and words), not one of a row's chips.
 */
export function ShortlistControl({
  org,
  proposalId,
  shortlisted,
  variant = "icon",
}: {
  org: Membership;
  proposalId: string;
  shortlisted: boolean;
  variant?: "icon" | "button";
}) {
  const t = useTranslations("shortlist");
  if (!editsShortlist(org)) {
    return shortlisted ? (
      <span data-shortlisted="" className="inline-flex min-h-11 items-center gap-1.5 text-sm font-semibold text-accent">
        <StarIcon on className="size-5" />
        {t("marked")}
      </span>
    ) : null;
  }
  const problem = Object.fromEntries(PROBLEMS.map((key) => [key, t(`problem.${key}`)])) as Record<
    ShortlistProblem,
    string
  >;
  return (
    <ShortlistStar
      orgId={org.org_id}
      proposalId={proposalId}
      initial={shortlisted}
      variant={variant}
      labels={{ add: t("add"), remove: t("remove"), problem }}
    />
  );
}
