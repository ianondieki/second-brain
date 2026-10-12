import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { TopBarBase } from "@/components/TopBarBase";
import { buttonClass, standaloneLinkClass } from "@/components/ui/Button";
import { EmptyStateFrame } from "@/components/ui/EmptyStateFrame";
import { PageHeader } from "@/components/ui/PageHeader";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("offline");
  return { title: t("pageTitle"), robots: { index: false } };
}

/**
 * The page's only script, inline (no build file: offline, the page's own chunks may not be on this device). "Try again"
 * loads the address asked for again (the worker answers /offline at that address). The Engagements line shows only when
 * this device keeps the list of the address's portal (/dev/engagements, or /org/engagements with its ?org=), at most 7
 * days old, so the page never promises a page that is not kept. Constant text: it holds no data of the request.
 */
export const OFFLINE_SCRIPT =
  '(function(){var r=document.querySelector("[data-offline-retry]");if(r)r.setAttribute("href",location.href);' +
  "var m=/^\\/(dev|org)(?:\\/|$)/.exec(location.pathname);if(!m||!self.caches)return;" +
  'var o=new URLSearchParams(location.search).get("org");' +
  'var u="/"+m[1]+"/engagements"+(m[1]==="org"&&o?"?org="+encodeURIComponent(o):"");' +
  "caches.match(u,{ignoreVary:true}).then(function(c){" +
  'var p=document.querySelector("[data-offline-kept]");' +
  'if(!c||!p||!(Date.now()-Date.parse(c.headers.get("date")||"")<6048e5))return;' +
  'p.querySelector("a").setAttribute("href",u);p.hidden=false;},function(){});})();';

/**
 * /offline (P27 track F; REQ-UX-08; D-69): what the service worker answers when a page cannot be loaded and it holds no
 * copy of it. Cached when the worker installs (and again in the person's language), so it reads no session and calls no
 * API: the top bar, the title, one sentence and one action, "Try again" (docs/spec/07 item 4); below it, only where this
 * device keeps it, the way to the portal's Engagements. No photograph.
 */
export default async function OfflinePage() {
  const t = await getTranslations("offline");
  return (
    <>
      <TopBarBase homeHref="/" Anchor="a" />
      <main
        id="main"
        tabIndex={-1}
        className="mx-auto w-full max-w-6xl flex-1 px-4 pt-8 pb-16 focus:outline-none sm:px-6 lg:pt-16"
        data-offline-page=""
      >
        <div className="max-w-md">
          <PageHeader title={t("title")} />
          <EmptyStateFrame
            className="mt-6"
            illustration="waiting"
            sentence={t("body")}
            action={
              // A plain link the inline script points at this address: a full load, which the worker answers.
              // eslint-disable-next-line @next/next/no-html-link-for-pages
              <a href="/" data-primary="" data-offline-retry="" className={buttonClass("primary", "no-underline")}>
                {t("retry")}
              </a>
            }
          />
          <p hidden data-offline-kept="" className="mt-6 max-w-[60ch] text-ink">
            {t.rich("kept", {
              link: (chunks) => (
                // eslint-disable-next-line @next/next/no-html-link-for-pages
                <a href="/" className={standaloneLinkClass}>
                  {chunks}
                </a>
              ),
            })}
          </p>
          <script dangerouslySetInnerHTML={{ __html: OFFLINE_SCRIPT }} />
        </div>
      </main>
    </>
  );
}
