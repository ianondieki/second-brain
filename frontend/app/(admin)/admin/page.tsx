import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { EmptyState } from "@/app/(app)/org/EmptyState";
import { adminSections } from "@/components/AdminNav";
import { homeFor } from "@/lib/auth/routing";

import { AdminShell } from "./AdminShell";
import { staffContext } from "./staff";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("admin");
  return { title: t("pageTitle") };
}

/**
 * The staff console's home (REQ-ADM-01): the first section the staff member's role may open. A role with no section
 * yet (moderators and support until P15) is told so, with the way to their portal.
 */
export default async function StaffConsoleHome() {
  const { me, role } = await staffContext();
  const [first] = adminSections(role);
  if (first) redirect(first.href);
  const t = await getTranslations("admin");
  return (
    <AdminShell role={role}>
      <h1 className="text-xl text-ink lg:text-2xl">{t("title")}</h1>
      <div className="mt-6">
        <EmptyState sentence={t("noSection")} action={t("noSectionAction")} href={homeFor(me.side)} primary />
      </div>
    </AdminShell>
  );
}
