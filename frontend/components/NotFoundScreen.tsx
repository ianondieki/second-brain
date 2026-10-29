import { getTranslations } from "next-intl/server";

import { TopBarBase } from "./TopBarBase";
import { buttonClass } from "./ui/Button";
import { EmptyStateFrame } from "./ui/EmptyStateFrame";
import { PageHeader } from "./ui/PageHeader";

/**
 * An address with no page (app/not-found.tsx): the top bar, the title, one sentence and one link home (docs/spec/07
 * item 4). Fully static on purpose: Next.js embeds the not-found tree in every page's payload, so it reads no session
 * and holds no client component (no account menu, plain links); anything more would ship on every route and call the
 * API on every render. The same answer for every unknown address and for anyone, the staff console's included for
 * those who are not staff (proxy.ts).
 */
export async function NotFoundScreen() {
  const t = await getTranslations("notFound");
  return (
    <>
      <TopBarBase homeHref="/" Anchor="a" />
      <main id="main" tabIndex={-1} className="mx-auto w-full max-w-6xl flex-1 px-4 pt-8 pb-16 focus:outline-none sm:px-6 lg:pt-16">
        <div className="max-w-md">
          <PageHeader title={t("title")} />
          <EmptyStateFrame
            className="mt-6"
            sentence={t("body")}
            action={
              // A plain link on purpose: this tree ships in every page's payload, so it holds no client component.
              // eslint-disable-next-line @next/next/no-html-link-for-pages
              <a href="/" data-primary="" className={buttonClass("primary", "no-underline")}>
                {t("home")}
              </a>
            }
          />
        </div>
      </main>
    </>
  );
}
