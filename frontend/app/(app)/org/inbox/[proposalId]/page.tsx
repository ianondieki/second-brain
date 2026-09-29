import type { Metadata } from "next";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { OrgNav } from "@/components/OrgNav";
import { SignedInShell } from "@/components/SignedInShell";
import { standaloneLinkClass } from "@/components/ui/Button";

import { getNda, getTeaser, orgContext } from "../../data";
import { EmptyState } from "../../EmptyState";
import { first, inboxHref, proposalHref } from "../../membership";
import { FullProposal } from "./FullProposal";
import { TeaserDetails } from "./TeaserDetails";

export async function generateMetadata({ params }: PageProps<"/org/inbox/[proposalId]">): Promise<Metadata> {
  const t = await getTranslations("orgProposal");
  const card = await getTeaser((await params).proposalId);
  return { title: card?.teaser.title ?? t("pageTitle"), robots: { index: false } };
}

/**
 * Organisation › Inbox › a proposal (REQ-REPO-01, REQ-PROV-03, REQ-SEC-01): the public teaser (Tier 1), then the
 * full proposal behind the Evaluation NDA. Rendered on the server; the only browser code is the "Accept and view"
 * and step-up forms. Tier 2 exists only as the API's marked HTML page, shown in a sandboxed frame when opened.
 */
export default async function OrgProposalScreen({ params, searchParams }: PageProps<"/org/inbox/[proposalId]">) {
  const [{ proposalId }, query] = await Promise.all([params, searchParams]);
  const { memberships, org } = await orgContext(query.org);
  const t = await getTranslations("orgProposal");
  const ti = await getTranslations("inbox");
  const card = await getTeaser(proposalId);
  const inbox = org ? inboxHref(memberships, org.org_id) : "/org/inbox";

  const back = (
    <Link href={inbox} className={standaloneLinkClass}>
      {t("back")}
    </Link>
  );

  if (!org || !card) {
    return (
      <SignedInShell homeHref="/org" nav={<OrgNav current="inbox" />}>
        {back}
        <h1 className="mt-4 text-xl text-ink lg:text-2xl">{t("pageTitle")}</h1>
        <div className="mt-6">
          {org ? (
            <EmptyState
              sentence={t("refusal.not_found", { org: org.org_name })}
              action={t("action.inbox")}
              href={inbox}
            />
          ) : (
            <EmptyState sentence={ti("noOrg")} action={ti("emptyAction")} href="/org" />
          )}
        </div>
      </SignedInShell>
    );
  }

  const nda = await getNda(org.org_id, card.id);
  const title = card.teaser.title ?? ti("untitled");
  return (
    <SignedInShell homeHref="/org" nav={<OrgNav current="inbox" />} wide>
      <article className="max-w-4xl">
        {back}
        <header className="mt-4 max-w-3xl">
          <h1 className="text-xl [overflow-wrap:anywhere] text-ink lg:text-2xl">{title}</h1>
          {card.teaser.niche ? <p className="mt-2 text-ink-soft">{card.teaser.niche.label}</p> : null}
          <p className="mt-4 max-w-[62ch] text-sm text-ink-soft">{t("teaserNote")}</p>
        </header>
        <div className="max-w-3xl">
          <TeaserDetails card={card} />
        </div>
        <FullProposal
          orgId={org.org_id}
          orgName={org.org_name}
          proposalId={card.id}
          title={title}
          nda={nda}
          viewing={first(query.view) === "full"}
          hrefs={{
            here: proposalHref(memberships, org.org_id, card.id),
            view: proposalHref(memberships, org.org_id, card.id, { view: true }),
            inbox,
          }}
        />
      </article>
    </SignedInShell>
  );
}
