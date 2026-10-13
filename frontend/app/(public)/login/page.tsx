import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { AuthShell } from "@/components/AuthShell";
import { ClientStrings } from "@/components/ClientStrings";
import { IntlScope } from "@/components/IntlScope";
import { Avatar } from "@/components/ui/Avatar";
import { InfoIcon } from "@/components/ui/status-icons";
import { ChevronDownIcon } from "@/components/ui/icons";
import { PageHeader } from "@/components/ui/PageHeader";
import { getSignedIn } from "@/lib/api/server";
import { homeOf } from "@/lib/auth/routing";
import { clientStrings } from "@/lib/i18n/client-strings";
import { demoPersonas, type DemoPersona } from "@/lib/public/demo-personas";
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
  if (publicDemoOn()) return <DemoLogin next={next} />;
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
 * personas, one press each, then the email form folded under "Sign in with an account" (native disclosure, open when
 * no persona could be offered), without sign-up or the emailed link (both switched off in the demo).
 */
async function DemoLogin({ next }: { next?: string }) {
  const [t, personas] = await Promise.all([getTranslations("publicDemo"), demoPersonas()]);
  const offered = personas && personas.length > 0 ? personas : null;
  const choice = (persona: DemoPersona): PersonaChoice => ({
    key: persona.key,
    home: persona.home,
    body: (
      <>
        <Avatar name={persona.name} size="lg" />
        <div className="min-w-0">
          <h2 className="font-display text-xl leading-tight tracking-[-0.01em] text-ink [overflow-wrap:anywhere]">
            {persona.name}
          </h2>
          <p className="mt-1 text-sm font-semibold text-ink">{t(`role.${persona.role}`)}</p>
          {persona.detail ? <p className="text-sm text-ink-soft [overflow-wrap:anywhere]">{persona.detail}</p> : null}
        </div>
      </>
    ),
    label: t.rich("continue", {
      name: persona.name,
      hidden: (chunks) => <span className="sr-only">{chunks}</span>,
    }),
  });
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
        <p className="mt-8 flex items-start gap-2 text-ink" data-personas-unavailable="">
          <InfoIcon className="mt-0.5 size-5 shrink-0 text-accent" />
          <span>{t("unavailable")}</span>
        </p>
      )}
      <details className="group mt-8" open={offered ? undefined : true} data-account-sign-in="">
        <summary
          className={
            "inline-flex min-h-11 cursor-pointer list-none items-center gap-1.5 font-semibold text-accent " +
            "[&::-webkit-details-marker]:hidden"
          }
        >
          {t("withAccount")}
          <ChevronDownIcon className="size-5 transition-transform duration-150 group-open:rotate-180" />
        </summary>
        <IntlScope namespaces={["login", "fields", "validation", "errors"]}>
          <ClientStrings strings={await clientStrings(["fields"])}>
            <LoginForm next={next} demo />
          </ClientStrings>
        </IntlScope>
      </details>
    </AuthShell>
  );
}
