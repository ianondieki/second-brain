import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { PublicFrame } from "@/components/landing/PublicFrame";
import { publicExplore } from "@/lib/public/public-data";

import { ExploreContent } from "./ExploreContent";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("explore");
  return { title: t("pageTitle"), description: t("lead") };
}

/** Public /explore (D-66; P24): GET /api/public/explore on the server, drawn by ExploreContent. No script of its own. */
export default async function ExplorePage() {
  const explore = await publicExplore();
  return (
    <PublicFrame>
      <ExploreContent explore={explore} />
    </PublicFrame>
  );
}
