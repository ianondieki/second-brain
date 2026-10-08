import { getTranslations } from "next-intl/server";

import type { AdminSection } from "@/components/AdminNav";

/** A console screen's eyebrow (PageHero, D-67): "Staff console / Moderation", where you are, never the title again. */
export async function StaffEyebrow({ section }: { section: AdminSection }) {
  const [t, admin] = await Promise.all([getTranslations("portal"), getTranslations("admin")]);
  return <>{t("eyebrow.staff", { section: admin(`nav.${section}`) })}</>;
}
