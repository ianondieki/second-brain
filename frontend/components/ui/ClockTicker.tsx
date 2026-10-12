// The page's clock ticker (P27; REQ-TRACK-03, REQ-UX-05): one small script in place of a React island per clock.
// Every deadline clock is drawn whole on the server (ClockFigures: the figures, the words for screen readers, the
// <time>'s duration, the warm or past state), and carries what is needed to redraw it: data-until, data-now (the API's
// X-App-Now), data-tone, data-locale, data-past (the screen's word once the instant has passed) and its three messages
// (data-format-days, -hours, -minutes; none on a sentence clock). The script reads only those, so it holds no words of
// any language and no data of the request: constant text.
//
// What it does: the app clock is the browser's clock less a gap taken from the first server instant seen and moved only
// by a later one ahead of it, so a page drawn from a cache is put right at once and a browser clock set wrong changes
// nothing (the rule Countdown's hook had, P23-3). Each run redraws only the clocks whose minute (or state) changed, then
// waits for the next whole minute of the soonest of them (one timer for the page); it pauses while the tab is hidden
// and runs again on visibilitychange, pageshow and focus. A clock the server drew again (a new data-now or data-until:
// a refresh of the page) starts again from what the server drew. Run a second time, the script only runs the clocks
// again. window.__clocks is its run.
//
// How it runs: the page carries it as a data block (<script type="text/x-clock-ticker">, which no browser runs and
// React renders without complaint after a navigation in the app, where a script of its own would be inert and logged as
// an error), and the root layout's CLOCK_BOOT_SCRIPT runs it: once the document is parsed (DOMContentLoaded), and
// whenever a clock is added or drawn again later. The first run anchors the app clock (the gap) at that moment, so the
// time between the server's instant and that run is not counted (by design: the browser's clock is not trusted, as
// the islands anchored at hydration); a full load ticks from the first minute boundary after it.
//
// CSP: inline, like the root layout's and /offline's scripts (security-headers.ts: script-src 'self' 'unsafe-inline',
// report-only). Phase 8's nonce CSP: the layout's head script needs the nonce like the others, and ClockTicker then takes
// a `nonce` prop threaded from the layout (the boot already copies the data block's nonce onto the script it runs).
export const CLOCK_TICKER_SCRIPT =
  "(function(w,d){if(w.__clocks)return w.__clocks();var M=6e4,timer,gap;" +
  'function esc(x){return x.replace(/&/g,"&amp;").replace(/</g,"&lt;")}' +
  "function run(){clearTimeout(timer);if(d.hidden)return;var next=1/0;" +
  'd.querySelectorAll("[data-clock][data-until]").forEach(function(el){' +
  "var s=el.dataset,end=Date.parse(s.until),served=Date.parse(s.now),id=s.now+s.until;" +
  "if(gap==null||served>Date.now()-gap)gap=Date.now()-served;" +
  "var left=end-(Date.now()-gap),m=Math.floor(left/M),k=left>0?m:-1;" +
  // A clock not seen yet, or drawn again by the server (a new data-now or data-until): what the server drew.
  "if(el.__id!==id){el.__id=id;el.__k=end>served?Math.floor((end-served)/M):-1}" +
  "if(left>0)next=Math.min(next,left%M+1);" +
  // The state: past, warm (the viewer's step, under 24 hours) or open; set whenever the element says otherwise (a
  // refresh keeps the element and may leave the state the ticker wrote).
  'var st=k<0?"past":s.tone=="warm"&&left<864e5?"warm":"open";' +
  'if(el.getAttribute("data-clock")!=st)el.setAttribute("data-clock",st);if(k===el.__k)return;el.__k=k;' +
  "if(k<0){el.textContent=s.past;return}" +
  'var D=Math.floor(m/1440),h=Math.floor(m/60)%24,n=m%60,t=el.querySelector("time"),p=[],' +
  'f=s[D?"formatDays":h?"formatHours":"formatMinutes"],v={days:D,hours:h,minutes:n};if(!t)return;' +
  't.setAttribute("datetime","P"+D+"DT"+h+"H"+n+"M");' +
  'function u(x,k){return new Intl.NumberFormat(s.locale,{style:"unit",unit:k,unitDisplay:"long"}).format(x)}' +
  'if(D)p.push(u(D,"day"));if(D||h)p.push(u(h,"hour"));p.push(u(n,"minute"));' +
  // A sentence clock's words wrap between units, never inside one ("15 days" stays together).
  'if(!f){t.textContent=p.map(function(x){return x.replace(/ /g,"\\xa0")}).join(" ");return}' +
  't.firstChild.textContent=p.join(" ");' +
  "t.lastChild.innerHTML=f.replace(/<f>\\{(\\w+)\\}<\\/f>|<u>([^<]*)<\\/u>|([^<]+)/g,function(_,a,b,c){" +
  'return a?\'<span data-figure="">\'+v[a]+"</span>":b!=null?\'<span data-unit="">\'+esc(b)+"</span>"' +
  ':\'<span data-gap="">\'+esc(c)+"</span>"})});' +
  "if(next<1/0)timer=setTimeout(run,next)}" +
  'w.__clocks=run;[[d,"visibilitychange"],[w,"pageshow"],[w,"focus"]].forEach(function(e){' +
  "e[0].addEventListener(e[1],function(){w.__clocks()})});" +
  "run()})(window,document);";

/** The type of the page's data block: not JavaScript, so the browser keeps it as text and React renders it quietly. */
export const CLOCK_TICKER_TYPE = "text/x-clock-ticker";

const BLOCK = `script[type="${CLOCK_TICKER_TYPE}"]`;
const WATCHED = `[data-clock],${BLOCK}`;

// In the root layout's head script (every page, run once per document). Once the document is parsed it runs the page's
// ticker (the first time, a copy of the data block put in the head as a script, which the browser runs at once), and
// from then on it runs it again whenever an element that is or holds a clock or the data block is added (a navigation
// in the app, a part of a page streamed in after its clocks) or a clock's data-now or data-until changes (a refresh of
// the page that keeps the element and rewrites its inside). What the ticker itself writes is neither.
export const CLOCK_BOOT_SCRIPT =
  "(function(w,d){function go(){if(w.__clocks)return w.__clocks();" +
  `var s=d.querySelector('${BLOCK}');if(s){var c=d.createElement("script");c.text=s.text;c.nonce=s.nonce;` +
  'd.head.appendChild(c)}}d.addEventListener("DOMContentLoaded",function(){go();' +
  'new MutationObserver(function(r){for(var i=0;i<r.length;i++){if(r[i].type=="attributes")return go();' +
  "for(var j=0,a=r[i].addedNodes;j<a.length;j++){var n=a[j];" +
  `if(n.nodeType==1&&(n.matches('${WATCHED}')||n.querySelector('${WATCHED}')))return go()}}})` +
  '.observe(d.body,{childList:true,subtree:true,attributes:true,attributeFilter:["data-now","data-until"]})})})' +
  "(window,document);";

/**
 * The page's clock ticker: rendered once by a page that draws deadline clocks (DeadlineClock, DeadlineLine), after them,
 * as a data block the root layout's boot runs (see above). No React at runtime.
 */
export function ClockTicker() {
  return (
    <script type={CLOCK_TICKER_TYPE} data-clock-ticker="" dangerouslySetInnerHTML={{ __html: CLOCK_TICKER_SCRIPT }} />
  );
}
