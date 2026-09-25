import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { needsMfaSetup, type Me } from "@/lib/auth/routing";

import { ButtonLink, textLinkClass } from "./ui/Button";
import { cn } from "./ui/cn";
import { AlertIcon, CheckIcon, InfoIcon } from "./ui/icons";

/**
 * Phase 1 home placeholder body: greeting, one sentence, two-step sign-in status (icon + text + colour) and one
 * action. An account whose role requires two-step sign-in and lacks it gets "Turn on" as the primary action.
 */
export async function HomeSummary({ me, lead }: { me: Me; lead: string }) {
  const t = await getTranslations("home");
  const setupNeeded = needsMfaSetup(me.mfa);
  const status = me.mfa.enrolled ? "on" : setupNeeded ? "required" : "off";
  const Icon = status === "on" ? CheckIcon : status === "required" ? AlertIcon : InfoIcon;
  return (
    <>
      <h1 className="text-xl [overflow-wrap:anywhere] text-ink lg:text-2xl">
        {t("title", { name: me.user.display_name })}
      </h1>
      <p className="mt-3 text-ink-soft">{lead}</p>
      <div className="mt-8 flex flex-col items-start gap-4 border-t border-line pt-6">
        <p
          className={cn(
            "flex items-start gap-2 font-medium",
            status === "on" && "text-ok",
            status === "required" && "text-error",
            status === "off" && "text-ink",
          )}
        >
          <Icon className="mt-0.5 size-5 shrink-0" />
          <span>{status === "on" ? t("mfaOn") : status === "required" ? t("mfaRequired") : t("mfaOff")}</span>
        </p>
        {setupNeeded ? (
          <ButtonLink href="/settings/security" variant="primary">
            {t("turnOn")}
          </ButtonLink>
        ) : (
          <Link href="/settings/security" className={textLinkClass}>
            {me.mfa.enrolled ? t("manage") : t("setUp")}
          </Link>
        )}
      </div>
    </>
  );
}
