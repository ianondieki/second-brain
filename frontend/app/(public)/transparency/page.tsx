import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { PublicFrame } from "@/components/landing/PublicFrame";

import { readTransparency } from "./transparency";
import { TransparencyContent } from "./TransparencyContent";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("transparency");
  return { title: t("pageTitle"), description: t("description") };
}

/**
 * Public /transparency (REQ-AUD-01; P28 track D): GET /api/transparency and the published keys on the server, drawn
 * by TransparencyContent. No script of its own; indexable, like the other public pages beside the landing.
 */
export default async function TransparencyPage() {
  const read = await readTransparency();
  return (
    <PublicFrame>
      <TransparencyContent {...read} />
    </PublicFrame>
  );
}
