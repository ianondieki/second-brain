import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { Wordmark } from "@/components/brand/Logo";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Lattice } from "@/components/ui/Lattice";

const linkClass = "inline-flex min-h-11 items-center text-ink-soft no-underline hover:text-ink hover:underline";

/** The footer (D-55, D-66), on the night band: the wordmark and the prototype's note, three short link lists (with Explore and the photo credits), the theme switch. */
export async function LandingFooter() {
  const t = await getTranslations("landing");
  const columns = [
    { id: "product", links: [["/#how", t("nav.how")], ["/explore", t("footer.explore")], ["/#features", t("footer.features")], ["/#faq", t("footer.faq")]] },
    { id: "start", links: [["/signup", t("footer.signUp")], ["/login", t("footer.logIn")], ["/verify", t("footer.verify")]] },
    { id: "about", links: [["/help", t("footer.help")], ["/legal/terms", t("footer.terms")], ["/credits", t("footer.credits")]] },
  ] as const;
  return (
    <footer className="on-night bg-night">
      <Lattice />
      <div className="mx-auto grid w-full max-w-6xl grid-cols-2 gap-x-6 gap-y-10 px-4 pt-14 pb-12 sm:px-6 lg:grid-cols-[minmax(0,1.6fr)_repeat(3,minmax(0,1fr))]">
        <div className="col-span-2 lg:col-span-1">
          <Wordmark size={30} />
          <p className="mt-4 max-w-[38ch] text-sm text-ink-soft">{t("footer.note")}</p>
          <ThemeToggle className="mt-6" />
        </div>
        {columns.map(({ id, links }) => (
          <nav key={id} aria-labelledby={`footer-${id}`}>
            <h2 id={`footer-${id}`} className="font-sans text-sm font-semibold tracking-normal text-ink">
              {t(`footer.${id}`)}
            </h2>
            <ul className="mt-3 flex flex-col">
              {links.map(([href, label]) => (
                <li key={href}>
                  {href.startsWith("#") ? (
                    <a href={href} className={linkClass}>
                      {label}
                    </a>
                  ) : (
                    <Link href={href} className={linkClass}>
                      {label}
                    </Link>
                  )}
                </li>
              ))}
            </ul>
          </nav>
        ))}
      </div>
    </footer>
  );
}
