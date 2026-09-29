import type { Metadata } from "next";
import Link from "next/link";
import { getLocale, getTranslations } from "next-intl/server";

import { HomeSummary } from "@/components/HomeSummary";
import { OrgNav } from "@/components/OrgNav";
import { SignedInShell } from "@/components/SignedInShell";
import { buttonClass } from "@/components/ui/Button";
import { needsMfaSetup } from "@/lib/auth/routing";

import { getInbox, orgContext } from "./data";
import { formatDay } from "./format";
import { inboxHref, type Membership } from "./membership";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("home");
  return { title: t("orgPageTitle") };
}

/**
 * Organisation home: the greeting and two-step sign-in status (owners without it are asked to turn it on, the
 * screen's primary action then), and a short Inbox summary with the way in.
 */
export default async function OrganisationHome() {
  const { me, memberships, org } = await orgContext(undefined);
  const t = await getTranslations("home");
  const setupNeeded = needsMfaSetup(me.mfa);
  return (
    <SignedInShell homeHref="/org" nav={<OrgNav current="home" />}>
      <HomeSummary me={me} lead={org ? t("orgLead", { org: org.org_name }) : t("orgLeadNoName")} />
      {/* The Inbox asks for two-step sign-in first (the API refuses it before then), so it waits for the setup. */}
      {org && !setupNeeded ? <InboxSummary memberships={memberships} org={org} /> : null}
    </SignedInShell>
  );
}

async function InboxSummary({ memberships, org }: { memberships: Membership[]; org: Membership }) {
  const t = await getTranslations("orgHome");
  const ti = await getTranslations("inbox");
  const locale = await getLocale();
  const result = await getInbox(org.org_id, undefined, 1);
  let sentence: string | null = null;
  if (result.kind === "page") {
    const [item] = result.page.items;
    if (item) {
      const title = item.proposal.teaser.title ?? ti("untitled");
      sentence = t("newest", { title, date: formatDay(locale, item.pitched_at) });
    } else if (result.page.held_count > 0) {
      sentence = ti("held", { count: result.page.held_count, org: org.org_name });
    } else {
      const key =
        result.page.verification === "e2"
          ? "emptyE2"
          : result.page.verification === "e1"
            ? "emptyE1"
            : "emptyUnverified";
      sentence = ti(key, { org: org.org_name });
    }
  }
  return (
    <section aria-labelledby="home-inbox" className="mt-10 flex flex-col items-start gap-3 border-t border-line pt-6">
      <h2 id="home-inbox" className="text-lg text-ink">
        {t("inboxTitle")}
      </h2>
      {sentence ? <p className="max-w-[60ch] [overflow-wrap:anywhere] text-ink">{sentence}</p> : null}
      <Link
        href={inboxHref(memberships, org.org_id)}
        data-primary=""
        className={buttonClass("primary", "no-underline")}
      >
        {t("open")}
      </Link>
    </section>
  );
}
