import type { Metadata } from "next";
import { notFound, redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { AuthShell } from "@/components/AuthShell";
import { Avatar } from "@/components/ui/Avatar";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { getSignedIn } from "@/lib/api/server";
import { homeOf } from "@/lib/auth/routing";
import { demoPersonas, personaLine, personaName, type DemoPersona } from "@/lib/public/demo-personas";
import { publicDemoOn } from "@/lib/public-demo";
import { returnPathParam } from "@/lib/return-path";

import { PersonaPicker, type PersonaChoice } from "../PersonaPicker";

// /login in the public demo, as its own route (REQ-FND-04, AC-UX-3). While the mode is on, the proxy rewrites /login
// here (the address stays /login); with it off this route does not exist. Its own route because Next puts the client
// components of one page into one chunk: inside /login's page, the picker was part of every visitor's download, and
// the email form part of every demo visitor's. Nothing may import this page or the picker from /login's own page
// (demo-login.test.tsx checks it).

export async function generateMetadata(): Promise<Metadata> {
  if (!publicDemoOn()) notFound(); // the unknown address's title too, not the picker's
  return { title: (await getTranslations("publicDemo"))("pickerTitle") };
}

/**
 * "Try the demo as…" with the API's personas, one press each (docs/platform/tasks/P28.md, track PD). Nothing else:
 * password sign-in, the emailed link and sign-up are all switched off in the demo. When no persona could be read, one
 * calm line and "Try again" (/login itself). A person already signed in goes on as at /login.
 */
export default async function DemoLoginPage({ searchParams }: PageProps<"/login/demo">) {
  if (!publicDemoOn()) notFound();
  const next = returnPathParam((await searchParams).next);
  const me = await getSignedIn();
  if (me) redirect(next ?? homeOf(me));
  const [t, personas] = await Promise.all([getTranslations("publicDemo"), demoPersonas()]);
  const offered = personas && personas.length > 0 ? personas : null;
  // All of it is drawn here, on the server: the client island (PersonaPicker) gets finished nodes, nothing to format.
  const choice = (persona: DemoPersona): PersonaChoice => {
    const name = personaName(persona.name);
    const line = personaLine(persona, (role, org) => t(`about.${role}`, { org }));
    return {
      key: persona.key,
      home: persona.home,
      body: (
        <>
          <Avatar name={name} size="lg" />
          <div className="min-w-0">
            <h2 className="font-display text-xl leading-tight tracking-[-0.01em] text-ink [overflow-wrap:anywhere]">
              {name}
            </h2>
            <p className="mt-1 text-sm font-semibold text-ink">{t(`role.${persona.role}`)}</p>
            {line ? <p className="text-sm text-ink-soft [overflow-wrap:anywhere]">{line}</p> : null}
          </div>
        </>
      ),
      label: t.rich("continue", {
        name,
        hidden: (chunks) => <span className="sr-only">{chunks}</span>,
      }),
    };
  };
  return (
    <AuthShell>
      <PageHeader title={t("pickerTitle")} lead={t("pickerLead")} />
      {offered ? (
        <PersonaPicker
          personas={offered.map(choice)}
          label={t("personasLabel")}
          strings={{ signingIn: t("signingIn"), tooMany: t("tooMany"), failed: t("failed") }}
        />
      ) : (
        <EmptyState
          className="mt-8"
          sentence={t("unavailable")}
          action={t("retry")}
          href="/login"
          data-personas-unavailable=""
        />
      )}
    </AuthShell>
  );
}
