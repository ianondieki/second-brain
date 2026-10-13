import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { AuthShell } from "@/components/AuthShell";
import { ClientStrings } from "@/components/ClientStrings";
import { IntlScope } from "@/components/IntlScope";
import { Avatar } from "@/components/ui/Avatar";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { getSignedIn } from "@/lib/api/server";
import { homeOf } from "@/lib/auth/routing";
import { clientStrings } from "@/lib/i18n/client-strings";
import { demoPersonas, personaLine, personaName, type DemoPersona } from "@/lib/public/demo-personas";
import { publicDemoOn } from "@/lib/public-demo";
import { returnPathParam } from "@/lib/return-path";

import { LoginForm } from "./LoginForm";
import { PersonaPicker, type PersonaChoice } from "./PersonaPicker";

export async function generateMetadata(): Promise<Metadata> {
  if (publicDemoOn()) return { title: (await getTranslations("publicDemo"))("pickerTitle") };
  const t = await getTranslations("login");
  return { title: t("title") };
}

/**
 * Log in. `?next=` (set by the proxy for a signed-out visit to a signed-in page) is the page to return to, kept only
 * when it is one of this site's signed-in pages written plainly (lib/return-path.ts). A person already signed in goes
 * there, or to their own home, with a server-side redirect (P16-B review MINOR 3).
 */
export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  const next = returnPathParam((await searchParams).next);
  const me = await getSignedIn();
  if (me) redirect(next ?? homeOf(me));
  if (publicDemoOn()) return <DemoLogin />;
  const t = await getTranslations("login");
  return (
    <AuthShell>
      <PageHeader title={t("title")} lead={t("lead")} />
      <IntlScope namespaces={["login", "fields", "validation", "errors"]}>
        {/* The password field's show/hide words are server-formatted (components/ui/PasswordField.tsx). */}
        <ClientStrings strings={await clientStrings(["fields"])}>
          <LoginForm next={next} />
        </ClientStrings>
      </IntlScope>
    </AuthShell>
  );
}

/**
 * /login in the public demo (REQ-FND-04; docs/platform/tasks/P28.md, track PD): "Try the demo as…" with the API's
 * personas, one press each. Nothing else: password sign-in, the emailed link and sign-up are all switched off in the
 * demo. When no persona could be read, one calm line and "Try again" (the page itself).
 */
async function DemoLogin() {
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
