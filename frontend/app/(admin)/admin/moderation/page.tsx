import type { Metadata } from "next";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { EmptyState } from "@/components/ui/EmptyState";
import { first } from "@/app/(app)/org/membership";
import { ClientStrings } from "@/components/ClientStrings";
import { buttonClass } from "@/components/ui/Button";

import { AdminShell } from "../AdminShell";
import { PageStepUp } from "../research/PageStepUp";
import { staffContext } from "../staff";
import { stepUpStrings } from "../strings";
import { ViewTabs } from "../ViewTabs";
import { CaseRow } from "./CaseRow";
import { getQueue } from "./data";
import { caseHref, moderationView, viewHref } from "./moderation";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("adminModeration");
  return { title: t("pageTitle") };
}

/** The staff roles the API admits to the moderation queue (bridge/admin/deps.py StaffModerator). */
const ROLES = new Set(["admin", "moderator"]);

/**
 * Moderation (REQ-MOD-01, REQ-ADM-01; docs/spec/06 6.12; M2 walkthrough step 6): the cases the pre-screen held or
 * queued, oldest first, and the decided ones, newest decision first. "Review the oldest case" (the oldest this
 * moderator can decide) is the screen's one primary action. Staff admins and moderators; a stale second factor asks for
 * a fresh code first.
 */
export default async function ModerationPage({ searchParams }: PageProps<"/admin/moderation">) {
  const { role } = await staffContext();
  const view = moderationView(first((await searchParams).view));
  const t = await getTranslations("adminModeration");
  const header = (
    <header>
      <h1 tabIndex={-1} className="text-xl text-ink focus:outline-none lg:text-2xl">
        {t("title")}
      </h1>
      <p className="mt-2 max-w-[60ch] text-ink-soft">{t("lead")}</p>
    </header>
  );
  const shell = (children: React.ReactNode) => (
    <AdminShell role={role} current="moderation" wide>
      <div className="flex max-w-3xl flex-col gap-8">
        {header}
        {children}
      </div>
    </AdminShell>
  );
  const notAllowed = () =>
    shell(<EmptyState sentence={t("notAllowed")} action={t("notAllowedAction")} href="/admin" />);
  if (!ROLES.has(role)) return notAllowed();

  const loaded = await getQueue(view);
  if (loaded.kind === "forbidden") return notAllowed();
  if (loaded.kind === "stepUp") {
    return shell(
      <ClientStrings strings={await stepUpStrings()}>
        <PageStepUp />
      </ClientStrings>,
    );
  }

  const items = loaded.data;
  const oldest = view === "open" ? items.find((item) => item.actions.length > 0) : undefined;
  const tabs = [
    { key: "open", label: t("tabs.open"), href: viewHref("open") },
    { key: "decided", label: t("tabs.decided"), href: viewHref("decided") },
  ];
  return shell(
    <div>
      <ViewTabs label={t("tabsLabel")} tabs={tabs} current={view} />
      <div className="mt-6 flex flex-col gap-6">
        {oldest ? (
          <Link
            href={caseHref(oldest.id)}
            data-primary=""
            className={buttonClass("primary", "self-start no-underline")}
          >
            {t("reviewOldest")}
          </Link>
        ) : null}
        {items.length > 0 ? (
          <ol aria-label={view === "open" ? t("listOpen") : t("listDecided")} className="flex flex-col">
            {items.map((item) => (
              <CaseRow key={item.id} item={item} />
            ))}
          </ol>
        ) : view === "open" ? (
          <EmptyState sentence={t("emptyOpen")} action={t("emptyOpenAction")} href={viewHref("decided")} />
        ) : (
          <EmptyState sentence={t("emptyDecided")} action={t("emptyDecidedAction")} href={viewHref("open")} />
        )}
      </div>
    </div>,
  );
}
