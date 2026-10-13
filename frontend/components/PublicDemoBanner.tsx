import { getTranslations } from "next-intl/server";

import { Icon, type IconProps } from "./ui/status-icons";

// The public demo's banner (REQ-FND-04; docs/platform/tasks/P28.md, track PD): a slim night strip at the very top of
// every page while the mode is on (app/layout.tsx draws it before everything else, so the public pages, the portals,
// the console and the error pages all carry it). In the flow, never fixed: it scrolls away with the page and never
// covers content, at 360 px or anywhere. The night band is the same colour in light and dark (a band on either canvas).
//
// Dismissal costs no JavaScript bundle: DEMO_BANNER_SCRIPT (inline in <head>, as the theme's) hides it before the first
// paint when this browser session has dismissed it, so nothing shifts on hydrate, and handles the button's press by
// delegation. Without script the button is not drawn (the layout's <noscript> style), so it never sits there inert.
//
// The banner's "03:00 EAT" (publicDemo.banner, en and sw) is written into the copy, not fetched: it and the image's
// reset hour (RESET_HOUR_EAT in infra/demo/space/run.py) change together (docs/runbooks/public-demo.md; the locales'
// _meta.reviewP28pd says so too).

/** sessionStorage: the banner was dismissed in this browser session. */
export const DEMO_BANNER_STORAGE_KEY = "wazo-demo-banner";
/** On <html> once dismissed; globals.css hides [data-demo-banner] under it. */
export const DEMO_BANNER_HIDDEN_ATTRIBUTE = "data-demo-banner-hidden";

/**
 * Inline, before paint, no dependencies: hide the banner when this session dismissed it; on a press of the dismiss
 * button, hide it, remember that for the session, and move focus to the page's main region (the pressed button is
 * gone). Storage may be blocked (a private window): the banner then hides for this page only.
 *
 * The focus never scrolls (ux review of P28-PD, MAJOR 2): on a phone #main starts below the top bar, so a plain
 * focus() scrolled the page by the bar's height and hid it. `preventScroll` keeps the page where it is; a browser that
 * ignores the option is put back to the position read just before the focus.
 */
export const DEMO_BANNER_SCRIPT =
  `(function(){var k=${JSON.stringify(DEMO_BANNER_STORAGE_KEY)},a=${JSON.stringify(DEMO_BANNER_HIDDEN_ATTRIBUTE)},` +
  `d=document.documentElement;try{if(sessionStorage.getItem(k)==="1")d.setAttribute(a,"")}catch(e){}` +
  `document.addEventListener("click",function(e){var t=e.target;` +
  `if(!(t instanceof Element)||!t.closest("[data-demo-dismiss]"))return;d.setAttribute(a,"");` +
  `try{sessionStorage.setItem(k,"1")}catch(e){}var m=document.getElementById("main");if(!m)return;` +
  `var x=window.scrollX,y=window.scrollY;m.focus({preventScroll:true});` +
  `if(window.scrollX!==x||window.scrollY!==y)window.scrollTo(x,y)})})();`;

/** What a browser without script reads: no dismiss button (it could do nothing there). */
export const DEMO_BANNER_NOSCRIPT_CSS = "[data-demo-dismiss]{display:none}";

function CloseIcon(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="m5.5 5.5 9 9M14.5 5.5l-9 9" />
    </Icon>
  );
}

export async function PublicDemoBanner() {
  const t = await getTranslations("publicDemo");
  return (
    <section aria-label={t("bannerLabel")} data-demo-banner="" className="border-b border-night-line bg-night text-on-night">
      <div className="mx-auto flex w-full max-w-6xl items-center gap-2 py-1 pr-1 pl-4 sm:pr-3 sm:pl-6">
        <p className="min-w-0 flex-1 py-1.5 text-sm leading-5 text-pretty">
          {t.rich("banner", {
            b: (chunks) => <strong className="font-semibold text-flourish">{chunks}</strong>,
          })}
        </p>
        <button
          type="button"
          data-demo-dismiss=""
          aria-label={t("bannerDismiss")}
          className={
            "inline-flex size-11 shrink-0 items-center justify-center rounded-full text-night-soft " +
            "hover:bg-night-line hover:text-on-night focus-visible:outline-flourish"
          }
        >
          <CloseIcon className="size-5" />
        </button>
      </div>
    </section>
  );
}
