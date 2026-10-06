import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { getCounties } from "@/app/(app)/org/scout-data";
import { ClientStrings } from "@/components/ClientStrings";
import { EventForm } from "@/components/events/EventForm";
import { BackLink } from "@/components/ui/BackLink";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { clientStrings } from "@/lib/i18n/client-strings";

import { AdminShell } from "../../AdminShell";
import { staffContext } from "../../staff";
import { ADMIN_EVENTS_PATH } from "../events";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("adminEvents");
  return { title: t("newTitle") };
}

/**
 * Events › Post a platform event (REQ-DEV-02; D-60): the organisations' form, posted as "Platform" by a staff admin;
 * it waits on the queue like any other. A moderator reads one sentence and the way back.
 */
export default async function NewPlatformEventPage() {
  const { role } = await staffContext();
  const t = await getTranslations("adminEvents");
  const shell = (children: ReactNode, lead?: string) => (
    <AdminShell role={role} current={role === "admin" || role === "moderator" ? "events" : undefined} wide>
      <div className="max-w-3xl">
        <BackLink href={ADMIN_EVENTS_PATH}>{t("back")}</BackLink>
        <PageHeader title={t("newTitle")} lead={lead} focusable />
        <div className="mt-8">{children}</div>
      </div>
    </AdminShell>
  );
  if (role !== "admin") return shell(<EmptyState sentence={t("notAdmin")} action={t("notAdminAction")} href={ADMIN_EVENTS_PATH} />);
  const counties = await getCounties();
  return shell(
    <ClientStrings strings={await clientStrings(["eventForm"])}>
      <EventForm
        counties={counties.map((c) => ({ id: c.code, label: c.name }))}
        poster={t("platform")}
        target={{ kind: "staff" }}
        doneBase={ADMIN_EVENTS_PATH}
        cancelHref={ADMIN_EVENTS_PATH}
      />
    </ClientStrings>,
    t("newLead"),
  );
}
