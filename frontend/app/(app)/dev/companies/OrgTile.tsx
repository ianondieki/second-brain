import Link from "next/link";
import { useTranslations } from "next-intl";

import { Avatar } from "@/components/ui/Avatar";
import { cardLinkClass } from "@/components/ui/Card";
import { ClockIcon } from "@/components/ui/icons";
import { LinkPending } from "@/components/ui/LinkPending";
import { NicheBand } from "@/components/ui/NicheBand";
import { placePhotos } from "@/lib/photos/niche";

import type { CardBand } from "./bands";
import { orgHref, type DirectoryFilters, type OrgCard } from "./filters";
import { VerificationBadge } from "./VerificationBadge";

export interface OrgTileProps {
  org: OrgCard;
  filters?: DirectoryFilters;
  /** The niche of the section the card sits in: the band's photograph when the organisation lists none of its own. */
  groupNiche?: string | null;
  /** The band its section chose (bands.ts sectionBands: its county's own photographs in turn, the crop cycling). */
  band?: CardBand;
}

/**
 * One organisation in the directory as a card (P26): the photograph of its place (its HQ county's, else its niche's
 * unless that shows a named organisation's premises, else the lattice; decorative, the county is named in the meta
 * line), its monogram on the band's edge (initials in the display face, never a logo: docs/spec/04 principle 4), its
 * name in Fraunces as the card's one link, the org type and county, the verification badge verbatim as the card's one
 * chip (docs/spec/07 item 2), and the response record when the API sends one (E2 with enough history). A list item of
 * four rows the grid shares (subgrid), so a row of cards lines up its names, meta lines, badges and records.
 */
export function OrgTile({ org, filters = {}, groupNiche, band }: OrgTileProps) {
  const t = useTranslations("companies");
  const kinds = useTranslations("orgKind");
  const kind = kinds(org.kind);
  const titleId = `org-${org.id}-name`;
  // Its section's choice; on its own, the first photograph of its place.
  const photo = band
    ? band.photo
    : (placePhotos({ county: org.county?.code, niche: org.niches[0]?.slug ?? groupNiche })[0]?.slug ?? null);
  return (
    <li className="row-span-4 grid min-w-0 grid-rows-subgrid gap-y-0">
      <article
        data-org={org.slug}
        aria-labelledby={titleId}
        className={
          "relative row-span-4 grid min-w-0 grid-rows-subgrid gap-y-0 rounded-panel border border-line bg-field pb-5 " +
          "transition-[border-color,box-shadow] duration-(--motion-fast) hover:border-accent-line hover:shadow-card " +
          "has-[a:focus-visible]:outline-2 has-[a:focus-visible]:outline-offset-2 has-[a:focus-visible]:outline-accent"
        }
      >
        <div className="min-w-0">
          <NicheBand photo={photo} position={band?.position} className="h-20 rounded-t-[15px] rounded-b-none sm:h-24" />
          {/* Before the link in the document, so the link's cover stays above it: a click on the seal opens the page. */}
          <div className="relative -mt-6 px-5">
            <Avatar name={org.name} kind="org" size="lg" className="font-display ring-4 ring-field" />
          </div>
          <h3
            id={titleId}
            className="mt-2.5 px-5 font-display text-[1.375rem] leading-[1.18] font-[580] [overflow-wrap:anywhere] text-ink"
          >
            <Link href={orgHref(org.id, filters)} className={cardLinkClass}>
              {org.name}
              <LinkPending className="absolute top-2 left-1/2 -translate-x-1/2" />
            </Link>
          </h3>
        </div>
        <p className="mt-1 px-5 text-sm text-ink-soft">
          {org.county ? t("meta", { kind, county: org.county.name }) : kind}
        </p>
        <p className="mt-3.5 px-5">
          <VerificationBadge badge={org.badge} />
        </p>
        {org.responsiveness ? (
          <p
            data-response=""
            className="mx-5 mt-4 flex items-start gap-2 border-t border-line pt-3 text-sm text-ink-soft"
          >
            <ClockIcon className="mt-0.5 size-4 shrink-0" />
            <span className="min-w-0">{org.responsiveness.text}</span>
          </p>
        ) : null}
      </article>
    </li>
  );
}
