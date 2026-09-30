import Link from "next/link";
import { redirect } from "next/navigation";
import { getTranslations } from "next-intl/server";

import { AuthShell } from "@/components/AuthShell";
import { textLinkClass } from "@/components/ui/Button";
import { ButtonLink } from "@/components/ui/ButtonLink";
import { getSignedIn } from "@/lib/api/server";
import { homeOf } from "@/lib/auth/routing";

/** The landing page for visitors; a signed-in person goes to their own home (a server-side redirect, no script). */
export default async function Landing() {
  const me = await getSignedIn();
  if (me) redirect(homeOf(me));
  const t = await getTranslations("landing");
  return (
    <AuthShell landing>
      <h1 className="text-2xl text-ink lg:text-3xl">{t("title")}</h1>
      <p className="mt-4 max-w-[60ch] text-lg text-ink-soft">{t("lead")}</p>
      <div className="mt-8 flex flex-col items-start gap-4">
        <ButtonLink href="/signup" variant="primary">
          {t("signUp")}
        </ButtonLink>
        <p className="text-ink">
          {t.rich("haveAccount", {
            login: (chunks) => (
              <Link href="/login" className={textLinkClass}>
                {chunks}
              </Link>
            ),
          })}
        </p>
      </div>
    </AuthShell>
  );
}
