// The JS budget per route (docs/spec/07 item 5, REQ-UX-05): at most 150 KB of gzipped JavaScript, where
// 1 KB = 1,000 bytes, so 150,000 bytes. Counted: the gzip-compressed bodies of the scripts a first visit downloads
// (the route's <script src> files; nomodule scripts are skipped by modern browsers). Not counted: response headers,
// which depend on the protocol (about 0.4 KB per file over HTTP/1.1, a few bytes with HTTP/2 header compression),
// and chunks that load later on demand (for example two-step setup after "Turn on").
// Usage, against a production build (the `make dev` web container, or `npm run build && npm run start`):
//   npm run budget -- /signup /login        BUDGET_BASE_URL defaults to http://localhost:3000
// The leading slash is optional (`signup login`), which spares Git Bash its path conversion of "/signup".
// Exits 1 when a route is over the budget. Routes that redirect (signed-in pages without a session) are skipped.
import { get } from "node:http";
import { gunzipSync, gzipSync } from "node:zlib";

const BUDGET_BYTES = 150_000;

const base = process.env.BUDGET_BASE_URL ?? "http://localhost:3000";
const routes = process.argv.slice(2).map((route) => (route.startsWith("/") ? route : `/${route}`));

function fetchRaw(url) {
  return new Promise((resolve, reject) => {
    get(url, { headers: { "accept-encoding": "gzip" } }, (res) => {
      const chunks = [];
      res.on("data", (chunk) => chunks.push(chunk));
      res.on("end", () => resolve({ res, body: Buffer.concat(chunks) }));
    }).on("error", reject);
  });
}

/** The bytes on the wire when the server gzips; otherwise what gzip at its default level would send. */
function gzippedLength({ res, body }) {
  return res.headers["content-encoding"] === "gzip" ? body.length : gzipSync(body).length;
}

async function measure(route) {
  const page = await fetchRaw(new URL(route, base));
  if (page.res.statusCode !== 200) {
    return { route, skipped: `${page.res.statusCode} ${page.res.headers.location ?? ""}`.trim() };
  }
  const html = (page.res.headers["content-encoding"] === "gzip" ? gunzipSync(page.body) : page.body).toString();
  const sources = new Set();
  for (const [, attributes] of html.matchAll(/<script\b([^>]*)>/gi)) {
    const src = /\bsrc="([^"]+)"/i.exec(attributes)?.[1];
    if (src && !/\bnomodule\b/i.test(attributes)) sources.add(src.replaceAll("&amp;", "&"));
  }
  let bytes = 0;
  for (const src of sources) bytes += gzippedLength(await fetchRaw(new URL(src, base)));
  return { route, scripts: sources.size, bytes };
}

if (routes.length === 0) {
  console.error("Name the routes to measure, for example: npm run budget -- /signup /login");
  process.exit(2);
}

let over = false;
for (const route of routes) {
  const result = await measure(route);
  if (result.skipped) {
    console.log(`${route}: skipped (${result.skipped})`);
    continue;
  }
  const verdict = result.bytes <= BUDGET_BYTES ? "ok" : "OVER";
  over ||= verdict === "OVER";
  const summary = `${result.bytes} bytes of gzipped JS in ${result.scripts} scripts (budget ${BUDGET_BYTES})`;
  console.log(`${route}: ${summary}: ${verdict}`);
}
process.exit(over ? 1 : 0);
