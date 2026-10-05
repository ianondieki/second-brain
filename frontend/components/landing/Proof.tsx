import { getTranslations } from "next-intl/server";

import { Seal } from "@/components/brand/Seal";
import { controlClass } from "@/components/ui/Field";
import { CheckIcon, ClockIcon, SendIcon } from "@/components/ui/status-icons";
import { cn } from "@/components/ui/cn";

const PROOF = [
  { key: "when", Icon: ClockIcon },
  { key: "what", Icon: CheckIcon },
  { key: "who", Icon: SendIcon },
] as const;

/**
 * Proof of authorship (D-55), on the night band: the seal, what a certificate records, and a certificate check that
 * works here without an account and without script (a GET form to /verify, which redirects to /verify/<id>).
 */
export async function Proof() {
  const t = await getTranslations("landing.proof");
  return (
    <section aria-labelledby="proof-title" className="on-night relative overflow-hidden bg-night py-20 lg:py-28">
      <div className="mx-auto grid w-full max-w-6xl grid-cols-1 items-start gap-12 px-4 sm:px-6 lg:grid-cols-[auto_minmax(0,1fr)] lg:gap-20">
        <Seal size={200} animate className="mx-auto lg:mx-0 lg:mt-2" />
        <div>
          <h2 id="proof-title" className="max-w-[20ch] text-3xl text-ink lg:text-4xl">
            {t("title")}
          </h2>
          <p className="mt-4 max-w-[60ch] text-lg text-ink-soft">{t("lead")}</p>
          <ul className="mt-10 grid grid-cols-1 gap-8 sm:grid-cols-3 sm:gap-6">
            {PROOF.map(({ key, Icon }) => (
              <li key={key}>
                <span aria-hidden="true" className="flex size-10 items-center justify-center rounded-full bg-flourish text-night">
                  <Icon className="size-5" />
                </span>
                <h3 className="mt-4 text-lg text-ink">{t(`${key}.title`)}</h3>
                <p className="mt-1.5 text-sm text-ink-soft">{t(`${key}.body`)}</p>
              </li>
            ))}
          </ul>
          <form method="get" action="/verify" className="mt-12 flex max-w-xl flex-col gap-3 sm:flex-row sm:items-end">
            <div className="min-w-0 flex-1">
              <label htmlFor="landing-cert" className="font-semibold text-ink">
                {t("checkLabel")}
              </label>
              <p id="landing-cert-hint" className="mt-0.5 text-sm text-ink-soft">
                {t("checkHint")}
              </p>
              <input
                id="landing-cert"
                name="id"
                autoComplete="off"
                autoCapitalize="characters"
                spellCheck={false}
                aria-describedby="landing-cert-hint"
                className={cn(controlClass, "mt-2 font-mono tracking-[0.06em] uppercase")}
              />
            </div>
            <button type="submit" className="btn btn-secondary shrink-0 border-line bg-transparent text-ink hover:bg-accent-wash">
              {t("checkAction")}
            </button>
          </form>
        </div>
      </div>
    </section>
  );
}
