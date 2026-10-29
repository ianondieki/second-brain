import { getTranslations } from "next-intl/server";

const KEYS = ["public", "certificate", "verified", "phone", "demo"] as const;

/**
 * Questions (D-55): the five a first-time visitor asks, answered in the product's own rules. Native disclosure
 * (<details>), so it works without script and each question is a button to assistive technology.
 */
export async function Questions() {
  const t = await getTranslations("landing.faq");
  return (
    <section id="faq" aria-labelledby="faq-title" className="py-20 lg:py-28">
      <div className="mx-auto grid w-full max-w-6xl grid-cols-1 gap-10 px-4 sm:px-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)] lg:gap-16">
        <h2 id="faq-title" className="text-3xl text-ink lg:sticky lg:top-10 lg:self-start lg:text-4xl">
          {t("title")}
        </h2>
        <div className="border-t border-line">
          {KEYS.map((key) => (
            <details key={key} className="group border-b border-line">
              <summary className="flex min-h-14 cursor-pointer list-none items-center justify-between gap-6 py-5 text-lg font-semibold text-ink [&::-webkit-details-marker]:hidden">
                {t(`${key}.q`)}
                <span
                  aria-hidden="true"
                  className="relative size-8 shrink-0 rounded-full bg-accent-wash text-accent before:absolute before:top-1/2 before:left-1/2 before:h-0.5 before:w-3.5 before:-translate-1/2 before:rounded-full before:bg-current after:absolute after:top-1/2 after:left-1/2 after:h-3.5 after:w-0.5 after:-translate-1/2 after:rounded-full after:bg-current after:transition-transform group-open:after:scale-y-0"
                />
              </summary>
              <p className="max-w-[62ch] pb-6 text-ink-soft">{t(`${key}.a`)}</p>
            </details>
          ))}
        </div>
      </div>
    </section>
  );
}
