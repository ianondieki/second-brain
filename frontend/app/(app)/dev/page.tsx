import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { DevNav } from "@/components/DevNav";
import { SignedInShell } from "@/components/SignedInShell";
import { myEngagements } from "@/components/tracker/data";
import { EngagementRow } from "@/components/tracker/EngagementRow";
import { standaloneLinkClass } from "@/components/ui/Button";
import { ButtonLink } from "@/components/ui/ButtonLink";
import { cn } from "@/components/ui/cn";
import { AlertIcon, CheckIcon, InfoIcon } from "@/components/ui/icons";
import { EmptyState } from "@/components/ui/EmptyState";
import { requireMe } from "@/lib/api/server";
import { homeFor, needsMfaSetup } from "@/lib/auth/routing";

import { recommendations } from "./discover/data";
import { RecommendedForYou } from "./discover/RecommendedForYou";
import { recommendationsState } from "./discover/recommendations";
import { homeGroups } from "./home";
import { myIdeas } from "./ideas/data";
import { IdeaRow } from "./ideas/IdeaRow";
import { NEW_PATH } from "./ideas/ideas";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("home");
  return { title: t("devPageTitle") };
}

/** How many of the engagements not waiting on the developer, and of their ideas, Home lists before "All …". */
const OTHERS_SHOWN = 5;
const IDEAS_SHOWN = 3;
const ENGAGEMENTS_PATH = "/dev/engagements";

/**
 * Developer Home (docs/spec/07 item 1, prototype part): the engagements waiting on the developer, each linking to its
 * tracker, then the others; then their latest ideas. "New proposal" is the screen's one primary action (a button, not
 * a nav item); with no engagements yet, an empty state points to My ideas. The two-step sign-in status stays, since
 * signing and payments need it. "Recommended for you" (P12) follows what needs the developer; the reminder summary
 * comes with P6's in-app route.
 */
export default async function DeveloperHome() {
  const me = await requireMe();
  const home = homeFor(me.side);
  if (home !== "/dev") redirect(home);
  const t = await getTranslations("devHome");
  const th = await getTranslations("home");
  const [engagements, ideas, recommended] = await Promise.all([myEngagements(), myIdeas(), recommendations()]);
  const { waiting, others } = homeGroups(engagements);
  const mfa = me.mfa.enrolled ? "on" : needsMfaSetup(me.mfa) ? "required" : "off";
  const MfaIcon = mfa === "on" ? CheckIcon : mfa === "required" ? AlertIcon : InfoIcon;

  return (
    <SignedInShell homeHref={home} nav={<DevNav current="home" />} wide>
      <div className="flex max-w-3xl flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-xl [overflow-wrap:anywhere] text-ink lg:text-2xl">
            {th("title", { name: me.user.display_name })}
          </h1>
          <p className="mt-2 text-ink-soft">{t("lead")}</p>
        </div>
        <ButtonLink href={NEW_PATH} variant="primary" className="shrink-0">
          <PlusIcon />
          {t("newProposal")}
        </ButtonLink>
      </div>

      <div className="mt-10 flex max-w-3xl flex-col gap-10">
        {engagements.length === 0 ? (
          <EmptyState sentence={t("empty")} action={t("emptyAction")} href="/dev/ideas" />
        ) : null}

        {waiting.length > 0 ? (
          <section aria-labelledby="home-needs-you" data-home="needs-you">
            <h2 id="home-needs-you" className="text-lg text-ink">
              {t("needsYou")}
            </h2>
            <ul className="mt-2 border-b border-line">
              {waiting.map((item) => (
                <li key={item.id}>
                  <EngagementRow item={item} mine="developer" href={`${ENGAGEMENTS_PATH}/${encodeURIComponent(item.id)}`} />
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        <RecommendedForYou state={recommendationsState(recommended)} />

        {others.length > 0 ? (
          <section aria-labelledby="home-others" data-home="others">
            <h2 id="home-others" className="text-lg text-ink">
              {t("others")}
            </h2>
            <ul className="mt-2 border-b border-line">
              {others.slice(0, OTHERS_SHOWN).map((item) => (
                <li key={item.id}>
                  <EngagementRow item={item} mine="developer" href={`${ENGAGEMENTS_PATH}/${encodeURIComponent(item.id)}`} />
                </li>
              ))}
            </ul>
            <Link href={ENGAGEMENTS_PATH} className={cn(standaloneLinkClass, "mt-2")}>
              {t("allEngagements")}
            </Link>
          </section>
        ) : null}

        {ideas.length > 0 ? (
          <section aria-labelledby="home-ideas" data-home="ideas">
            <h2 id="home-ideas" className="text-lg text-ink">
              {t("ideasTitle")}
            </h2>
            <ul className="mt-2 border-b border-line">
              {ideas.slice(0, IDEAS_SHOWN).map((item) => (
                <li key={item.id}>
                  <IdeaRow item={item} headingLevel={3} />
                </li>
              ))}
            </ul>
            <Link href="/dev/ideas" className={cn(standaloneLinkClass, "mt-2")}>
              {t("allIdeas")}
            </Link>
          </section>
        ) : null}

        <section aria-labelledby="home-security" className="border-t border-line pt-6">
          <h2 id="home-security" className="text-base font-semibold text-ink">
            {t("security")}
          </h2>
          <p
            className={cn(
              "mt-2 flex items-start gap-2",
              mfa === "on" && "text-ok",
              mfa === "required" && "text-error",
              mfa === "off" && "text-ink",
            )}
          >
            <MfaIcon className="mt-0.5 size-5 shrink-0" />
            <span>{mfa === "on" ? th("mfaOn") : mfa === "required" ? th("mfaRequired") : th("mfaOff")}</span>
          </p>
          <Link href="/settings/security" className={standaloneLinkClass}>
            {me.mfa.enrolled ? th("manage") : th("setUp")}
          </Link>
        </section>
      </div>
    </SignedInShell>
  );
}

function PlusIcon() {
  return (
    <svg aria-hidden="true" focusable="false" width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="size-5 shrink-0">
      <path d="M10 4.5v11M4.5 10h11" />
    </svg>
  );
}
