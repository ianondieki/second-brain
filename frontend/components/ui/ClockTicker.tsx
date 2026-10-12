// The page's clock ticker (P27; REQ-TRACK-03, REQ-UX-05): one small inline script in place of a React island per
// clock. Every deadline clock is drawn whole on the server (ClockFigures: the figures, the words for screen readers,
// the <time>'s duration, the warm or past state), and carries what is needed to redraw it: data-until, data-now (the
// API's X-App-Now), data-tone, data-locale, data-past (the screen's word once the instant has passed) and its three
// messages (data-format-days, -hours, -minutes; none on a sentence clock). The script reads only those, so it holds
// no words of any language and no data of the request: constant text.
//
// What it does, as useAppClock.ts does for Countdown (whose gap it shares, window.__appGap): the app clock is the
// browser's clock less a gap taken from the first server instant seen and moved only by a later one ahead of it, so a
// page drawn from a cache is put right at once and a browser clock set wrong changes nothing. Each run redraws only the
// clocks whose minute (or state) changed, then waits for the next whole minute of the soonest of them (one timer for
// the page); it pauses while the tab is hidden and runs again on visibilitychange, pageshow and focus. Run a second
// time (the script rendered again), it only runs the clocks again. window.__clocks is its run.
//
// It runs where it is parsed, after the clocks it is rendered under. Scripts that React inserts after a navigation in
// the app are never run by the browser, so the root layout's CLOCK_BOOT_SCRIPT (below) watches for clocks added to the
// page: it runs the ticker again, or the first time from the page's inert copy of this script.
//
// CSP: inline, like the root layout's and /offline's scripts (security-headers.ts: script-src 'self' 'unsafe-inline',
// report-only until the nonce CSP of Phase 8, when these scripts take the nonce; the boot copies a script's nonce).
export const CLOCK_TICKER_SCRIPT =
  "(function(w,d){if(w.__clocks)return w.__clocks();var M=6e4,timer;" +
  'function esc(x){return x.replace(/&/g,"&amp;").replace(/</g,"&lt;")}' +
  "function run(){clearTimeout(timer);if(d.hidden)return;var next=1/0;" +
  'd.querySelectorAll("[data-clock][data-until]").forEach(function(el){' +
  "var s=el.dataset,end=Date.parse(s.until),served=Date.parse(s.now),g=w.__appGap;" +
  "if(g==null||served>Date.now()-g)w.__appGap=g=Date.now()-served;" +
  "var left=end-(Date.now()-g),m=Math.floor(left/M),k=left>0?m:-1;" +
  // A clock not seen yet, or drawn again by the server (a new data-now): what the server drew.
  "if(el.__now!==s.now){el.__now=s.now;el.__k=end>served?Math.floor((end-served)/M):-1}" +
  "if(left>0)next=Math.min(next,left%M+1);if(k===el.__k)return;el.__k=k;" +
  'if(k<0){el.textContent=s.past;el.setAttribute("data-clock","past");return}' +
  'var D=Math.floor(m/1440),h=Math.floor(m/60)%24,n=m%60,t=el.querySelector("time"),p=[],' +
  'f=s[D?"formatDays":h?"formatHours":"formatMinutes"],v={days:D,hours:h,minutes:n};' +
  'el.setAttribute("data-clock",s.tone=="warm"&&left<864e5?"warm":"open");if(!t)return;' +
  't.setAttribute("datetime","P"+D+"DT"+h+"H"+n+"M");' +
  'function u(x,k){return new Intl.NumberFormat(s.locale,{style:"unit",unit:k,unitDisplay:"long"}).format(x)}' +
  'if(D)p.push(u(D,"day"));if(D||h)p.push(u(h,"hour"));p.push(u(n,"minute"));p=p.join(" ");' +
  "if(!f){t.textContent=p;return}t.firstChild.textContent=p;" +
  "t.lastChild.innerHTML=f.replace(/<f>\\{(\\w+)\\}<\\/f>|<u>([^<]*)<\\/u>|([^<]+)/g,function(_,a,b,c){" +
  'return a?\'<span data-figure="">\'+v[a]+"</span>":b!=null?\'<span data-unit="">\'+esc(b)+"</span>"' +
  ':\'<span data-gap="">\'+esc(c)+"</span>"})});' +
  "if(next<1/0)timer=setTimeout(run,next)}" +
  'w.__clocks=run;[[d,"visibilitychange"],[w,"pageshow"],[w,"focus"]].forEach(function(e){' +
  "e[0].addEventListener(e[1],function(){w.__clocks()})});" +
  "run()})(window,document);";

// In the root layout's head script (every page, run once per document): once the document is parsed, the clocks are
// run again (one streamed in after the ticker), and from then on any element added to the page that is or holds a
// clock (a navigation in the app, a refresh of the page) runs the ticker; the first time, a copy of the page's inert
// ticker script, put in the head, is what runs it. Elements the ticker itself writes hold no clock.
export const CLOCK_BOOT_SCRIPT =
  'document.addEventListener("DOMContentLoaded",function(){var w=window,d=document;w.__clocks&&w.__clocks();' +
  "new MutationObserver(function(r){for(var i=0;i<r.length;i++)for(var j=0,a=r[i].addedNodes;j<a.length;j++){var n=a[j];" +
  'if(n.nodeType==1&&(n.matches("[data-clock]")||n.querySelector("[data-clock]"))){if(w.__clocks)return w.__clocks();' +
  'var s=d.querySelector("script[data-clock-ticker]");if(s){var c=d.createElement("script");c.text=s.text;' +
  "c.nonce=s.nonce;d.head.appendChild(c)}return}}}).observe(d.body,{childList:true,subtree:true})});";

/**
 * The page's clock ticker: rendered once by a page that draws deadline clocks (DeadlineClock), after them. No React at
 * runtime: the browser runs it as it parses the page (see CLOCK_TICKER_SCRIPT above).
 */
export function ClockTicker() {
  return <script data-clock-ticker="" dangerouslySetInnerHTML={{ __html: CLOCK_TICKER_SCRIPT }} />;
}
