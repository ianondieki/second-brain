import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { ClientStrings } from "@/components/ClientStrings";
import { OrgNav } from "@/components/OrgNav";
import { SignedInShell } from "@/components/SignedInShell";
import { PageHeader } from "@/components/ui/PageHeader";
import { clientStrings } from "@/lib/i18n/client-strings";

import { getNda, getTeaser, orgContext } from "../../data";
import { EmptyState } from "@/components/ui/EmptyState";
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
  const { memberships, org, missing, query: orgParam } = await orgContext(query.org);
  const t = await getTranslations("orgProposal");
  const ti = await getTranslations("inbox");
  // Not a member of the organisation asked for: nothing is read, and nothing can be accepted in another's name.
  const card = org ? await getTeaser(proposalId) : null;
  const nav = <OrgNav current="inbox" query={orgParam} />;
  const inbox = org ? inboxHref(memberships, org.org_id) : "/org/inbox";

  const back = { href: inbox, label: t("back") };

  if (!org || !card) {
    return (
      <SignedInShell homeHref={`/org${orgParam}`} nav={nav}>
        <PageHeader back={back} title={t("pageTitle")} />
        <div className="mt-6">
          {org ? (
            <EmptyState
              sentence={t("refusal.not_found", { org: org.org_name })}
              action={t("action.inbox")}
              href={inbox}
            />
          ) : missing === "notMember" ? (
            <EmptyState sentence={ti("notMember")} action={ti("openOwnInbox")} href="/org/inbox" />
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
    <SignedInShell homeHref={`/org${orgParam}`} nav={nav} wide>
      <article className="flex max-w-3xl flex-col gap-10">
        <PageHeader back={back} title={title} lead={card.teaser.niche?.label}>
          <p className="mt-4 max-w-[62ch] text-sm text-ink-soft">{t("teaserNote")}</p>
        </PageHeader>
        <TeaserDetails card={card} />
        <ClientStrings strings={await clientStrings(["orgProposal"])}>
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
        </ClientStrings>
      </article>
    </SignedInShell>
  );
}
