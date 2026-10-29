import { getTranslations } from "next-intl/server";

import { ClientStrings } from "@/components/ClientStrings";
import { OrgNav } from "@/components/OrgNav";
import { SignedInShell } from "@/components/SignedInShell";
import { PageHeader } from "@/components/ui/PageHeader";
import { clientStrings } from "@/lib/i18n/client-strings";

import { FullProposal } from "@/app/(app)/org/inbox/[proposalId]/FullProposal";
import { TeaserDetails } from "@/app/(app)/org/inbox/[proposalId]/TeaserDetails";

import { NDA, TEASER } from "../fixtures";

/** The organisation's proposal page as app/(app)/org/inbox/[proposalId]/page.tsx composes it, at the NDA step. */
export async function ProposalScreen() {
  const t = await getTranslations("orgProposal");
  const title = TEASER.teaser.title!;
  const here = `/org/inbox/${TEASER.id}`;
  return (
    <SignedInShell homeHref="/org" nav={<OrgNav current="inbox" />} wide>
      <article className="flex max-w-3xl flex-col gap-10">
        <div>
          <PageHeader back={{ href: "/org/inbox", label: t("back") }} title={title} lead={TEASER.teaser.niche?.label}>
            <p className="mt-4 max-w-[62ch] text-sm text-ink-soft">{t("teaserNote")}</p>
          </PageHeader>
        </div>
        <TeaserDetails card={TEASER} />
        <ClientStrings strings={await clientStrings(["orgProposal"])}>
          <FullProposal
            orgId="0199b000-0000-7000-8000-00000000c001"
            orgName="Telco A (fixture)"
            proposalId={TEASER.id}
            title={title}
            nda={{ kind: "nda", nda: NDA }}
            viewing={false}
            hrefs={{ here, view: `${here}?view=full`, inbox: "/org/inbox" }}
          />
        </ClientStrings>
      </article>
    </SignedInShell>
  );
}
