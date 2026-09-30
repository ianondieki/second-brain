import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { ScoutScreen } from "../ScoutScreen";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("scoutPage");
  return { title: t("titleEdit") };
}

/** Organisation › Inbox › Change a Scout Agent: its form, Preview, and pause or resume (REQ-SCOUT-01). */
export default async function EditScoutPage({ params, searchParams }: PageProps<"/org/inbox/scouts/[scoutId]">) {
  const [{ scoutId }, query] = await Promise.all([params, searchParams]);
  return <ScoutScreen scoutId={scoutId} org={query.org} />;
}
