import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { ScoutScreen } from "../ScoutScreen";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("scoutPage");
  return { title: t("titleNew") };
}

/** Organisation › Inbox › Set up a Scout Agent (REQ-SCOUT-01). */
export default async function NewScoutPage({ searchParams }: PageProps<"/org/inbox/scouts/new">) {
  const query = await searchParams;
  return <ScoutScreen org={query.org} restore={query.restore} />;
}
