// The JS budget per route (docs/spec/07 item 5, REQ-UX-05): at most 150 KB of gzipped JavaScript, where
// 1 KB = 1,000 bytes, so 150,000 bytes. Counted: the gzip-compressed bodies of the scripts a first visit downloads
// (the route's <script src> files; nomodule scripts are skipped by modern browsers). Not counted: response headers,
// which depend on the protocol (about 0.4 KB per file over HTTP/1.1, a few bytes with HTTP/2 header compression),
// and chunks that load later on demand (for example two-step setup after "Turn on"). The HTTP/1.1 header bytes are
// printed alongside, since Lighthouse's transfer size includes them (DECISIONS-NEEDED D-28).
//
// Usage, against a production build (the `make dev` web container, or `npm run build && npm run start`):
//   npm run budget                                the default routes: / /login /signup /settings/security
//   npm run budget -- /signup /org --allow-skip   named routes (the leading slash is optional: `signup org`)
// BUDGET_BASE_URL  the web app (default http://localhost:3000; http or https).
// BUDGET_COOKIE    a Cookie header for signed-in routes, e.g. "__Host-bridge_session=<token>" of a test account.
// Exits 1 when a route is over the budget, answers with an error, or is skipped because it redirects (a signed-in
// route without BUDGET_COOKIE) unless --allow-skip is given.
import { get as httpGet } from "node:http";
import { get as httpsGet } from "node:https";
import { gunzipSync, gzipSync } from "node:zlib";

const BUDGET_BYTES = 150_000;
const DEFAULT_ROUTES = ["/", "/login", "/signup", "/settings/security"];

const base = process.env.BUDGET_BASE_URL ?? "http://localhost:3000";
const cookie = process.env.BUDGET_COOKIE;
const args = process.argv.slice(2);
const allowSkip = args.includes("--allow-skip");
const named = args.filter((arg) => arg !== "--allow-skip").map((arg) => (arg.startsWith("/") ? arg : `/${arg}`));
const routes = named.length > 0 ? named : DEFAULT_ROUTES;

function fetchRaw(url, headers = {}) {
  const get = url.protocol === "https:" ? httpsGet : httpGet;
  return new Promise((resolve, reject) => {
    get(url, { headers: { "accept-encoding": "gzip", ...headers } }, (res) => {
      const chunks = [];
      res.on("data", (chunk) => chunks.push(chunk));
      res.on("end", () => {
        // The response head as HTTP/1.1 sends it: status line, header lines, blank line.
        let headerBytes = `HTTP/1.1 ${res.statusCode} ${res.statusMessage}\r\n\r\n`.length;
        for (let i = 0; i < res.rawHeaders.length; i += 2) {
          headerBytes += `${res.rawHeaders[i]}: ${res.rawHeaders[i + 1]}\r\n`.length;
        }
        resolve({ res, body: Buffer.concat(chunks), headerBytes });
      });
    }).on("error", reject);
  });
}

/** The bytes on the wire when the server gzips; otherwise what gzip at its default level would send. */
function gzippedLength({ res, body }) {
  return res.headers["content-encoding"] === "gzip" ? body.length : gzipSync(body).length;
}

async function measure(route) {
  const page = await fetchRaw(new URL(route, base), cookie ? { cookie } : {});
  const status = page.res.statusCode;
  if (status >= 300 && status < 400) return { skipped: `${status} to ${page.res.headers.location ?? "?"}` };
  if (status !== 200) return { failed: `the page answered ${status}` };
  const html = (page.res.headers["content-encoding"] === "gzip" ? gunzipSync(page.body) : page.body).toString();
  const sources = new Set();
  for (const [, attributes] of html.matchAll(/<script\b([^>]*)>/gi)) {
    const src = /\bsrc="([^"]+)"/i.exec(attributes)?.[1];
    if (src && !/\bnomodule\b/i.test(attributes)) sources.add(src.replaceAll("&amp;", "&"));
  }
  let bytes = 0;
  let headerBytes = 0;
  for (const src of sources) {
    const script = await fetchRaw(new URL(src, base));
    if (script.res.statusCode !== 200) return { failed: `${src} answered ${script.res.statusCode}` };
    bytes += gzippedLength(script);
    headerBytes += script.headerBytes;
  }
  return { scripts: sources.size, bytes, headerBytes };
}

let failed = false;
for (const route of routes) {
  const result = await measure(route);
  if (result.failed) {
    failed = true;
    console.log(`${route}: FAILED (${result.failed})`);
  } else if (result.skipped) {
    failed ||= !allowSkip;
    const hint = allowSkip ? "" : "; set BUDGET_COOKIE for signed-in routes, or pass --allow-skip";
    console.log(`${route}: ${allowSkip ? "skipped" : "SKIPPED"} (${result.skipped}${hint})`);
  } else {
    const verdict = result.bytes <= BUDGET_BYTES ? "ok" : "OVER";
    failed ||= verdict === "OVER";
    const withHeaders = result.bytes + result.headerBytes;
    console.log(
      `${route}: ${result.bytes} bytes of gzipped JS in ${result.scripts} scripts (budget ${BUDGET_BYTES}): ` +
        `${verdict}; ${withHeaders} with HTTP/1.1 response headers`,
    );
  }
}
process.exit(failed ? 1 : 0);
