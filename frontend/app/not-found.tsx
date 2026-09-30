import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { NotFoundScreen } from "@/components/NotFoundScreen";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("notFound");
  return { title: t("title") };
}

/** Every address with no page (and notFound() anywhere): one static screen, its title, one link home. */
export default function NotFound() {
  return <NotFoundScreen />;
}
