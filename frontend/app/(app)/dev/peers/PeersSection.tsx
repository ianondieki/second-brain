import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { standaloneLinkClass } from "@/components/ui/Button";
import { RowList } from "@/components/ui/RowList";
import { RowBase } from "@/components/ui/RowBase";
import { Section } from "@/components/ui/Section";

import { HOME_PEERS, PEERS_PATH, PROFILE_SETTINGS_PATH, type Peer, type PeersPage } from "../teams/teams";

/**
 * Home's "Peers" (REQ-DEV-03; D-58), after "This week", drawn on the server with no script of its own. Visible to
 * peers: up to three developers in the caller's county or niches (handle, headline, and "Same county" or how many
 * niches they share, as plain text), with "See all" as the section's link; none yet: one sentence and the same link.
 * Not visible: one sentence and the way to turn it on in Settings. When the read failed the section is left out
 * (`peers` null), never the error page.
 */
export async function PeersSection({ peers }: { peers: PeersPage | null }) {
  if (!peers) return null;
  const t = await getTranslations("teams");
  if (!peers.opted_in) {
    return (
      <Section title={t("home.title")} headingId="home-peers" data-home="peers" data-peers="off">
        <p className="max-w-[62ch] text-ink">{t("home.off")}</p>
        <Link href={PROFILE_SETTINGS_PATH} className={standaloneLinkClass} data-peers-turn-on="">
          {t("home.turnOn")}
        </Link>
      </Section>
    );
  }
  const shown = peers.peers.slice(0, HOME_PEERS);
  return (
    <Section
      title={t("home.title")}
      headingId="home-peers"
      data-home="peers"
      data-peers="on"
      link={{ href: PEERS_PATH, label: t("home.seeAll") }}
    >
      {shown.length === 0 ? (
        <p className="text-ink" data-peers-empty="">
          {t("home.empty")}
        </p>
      ) : (
        <div className="rounded-panel border border-line bg-field px-4 sm:px-6">
          <RowList rule={false} aria-label={t("home.listLabel")}>
            {shown.map((peer) => (
              <RowBase
                key={peer.user_id}
                data-peer={peer.handle}
                title={peer.handle}
                meta={<PeerFacts peer={peer} sameCounty={t("facts.sameCounty")} shared={t("facts.sharedNiches", { count: peer.shared_niches.length })} />}
              />
            ))}
          </RowList>
        </div>
      )}
    </Section>
  );
}

/** The headline, then what the two share: the county, and how many liked niches (plain text, no chips). */
function PeerFacts({ peer, sameCounty, shared }: { peer: Peer; sameCounty: string; shared: string }) {
  return (
    <span className="flex flex-col gap-0.5">
      {peer.headline ? <span className="text-ink">{peer.headline}</span> : null}
      <span className="flex flex-wrap gap-x-4">
        {peer.same_county ? <span data-same-county="">{sameCounty}</span> : null}
        {peer.shared_niches.length > 0 ? <span>{shared}</span> : null}
      </span>
    </span>
  );
}
