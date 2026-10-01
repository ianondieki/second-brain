import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { DevNav } from "@/components/DevNav";
import { SignedInShell } from "@/components/SignedInShell";
import { EngagementRow } from "@/components/tracker/EngagementRow";
import { Badge } from "@/components/ui/Badge";
import { standaloneLinkClass } from "@/components/ui/Button";
import { ButtonLink } from "@/components/ui/ButtonLink";
import { CheckIcon } from "@/components/ui/icons";
import { PageHeader } from "@/components/ui/PageHeader";
import { RowList } from "@/components/ui/RowList";
import { Section } from "@/components/ui/Section";

import { homeGroups } from "@/app/(app)/dev/home";
import { RecommendedForYou } from "@/app/(app)/dev/discover/RecommendedForYou";
import { IdeaRow } from "@/app/(app)/dev/ideas/IdeaRow";
import { NEW_PATH } from "@/app/(app)/dev/ideas/ideas";

import { HOME_ENGAGEMENTS, IDEAS, ME, RECOMMENDATIONS } from "../fixtures";

/** Developer Home as app/(app)/dev/page.tsx composes it, on fixture data (no API). */
export async function HomeScreen() {
  const t = await getTranslations("devHome");
  const th = await getTranslations("home");
  const { waiting, others } = homeGroups(HOME_ENGAGEMENTS);
  const rowHref = (id: string) => `/dev/engagements/${encodeURIComponent(id)}`;
  return (
    <SignedInShell homeHref="/dev" nav={<DevNav current="home" />} wide>
      <div className="max-w-3xl">
        <PageHeader
          title={th("title", { name: ME.user.display_name })}
          lead={t("lead")}
          action={
            <ButtonLink href={NEW_PATH} variant="primary">
              {t("newProposal")}
            </ButtonLink>
          }
        />
      </div>
      <div className="mt-10 flex max-w-3xl flex-col gap-12">
        <Section title={t("needsYou")} headingId="home-needs-you">
          <RowList>
            {waiting.map((item) => (
              <EngagementRow key={item.id} item={item} mine="developer" href={rowHref(item.id)} />
            ))}
          </RowList>
        </Section>
        <RecommendedForYou state={RECOMMENDATIONS} />
        <Section title={t("others")} headingId="home-others" link={{ href: "/dev/engagements", label: t("allEngagements") }}>
          <RowList>
            {others.map((item) => (
              <EngagementRow key={item.id} item={item} mine="developer" href={rowHref(item.id)} />
            ))}
          </RowList>
        </Section>
        <Section title={t("ideasTitle")} headingId="home-ideas" link={{ href: "/dev/ideas", label: t("allIdeas") }}>
          <RowList>
            {IDEAS.map((item) => (
              <IdeaRow key={item.id} item={item} headingLevel={3} />
            ))}
          </RowList>
        </Section>
        <Section title={t("security")} headingId="home-security">
          <div className="flex flex-col items-start gap-1">
            <Badge tone="ok" icon={<CheckIcon />}>
              {th("mfaOn")}
            </Badge>
            <Link href="/settings/security" className={standaloneLinkClass}>
              {th("manage")}
            </Link>
          </div>
        </Section>
      </div>
    </SignedInShell>
  );
}
