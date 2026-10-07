import { readFile } from "node:fs/promises";
import { join } from "node:path";

import { ImageResponse } from "next/og";

// The share cards (P24; REQ-UX-04): 1200 × 630 PNGs drawn with next/og (no new dependency) for the link previews of a
// public teaser and a certificate. The night band with a bloom light, the Wazo mark and wordmark (Bricolage), the
// title in Fraunces, one line under it and the kanga lattice along the foot. Static TrueType instances of the two
// faces (public/fonts/og, LICENCES.md): next/og reads TrueType, not WOFF2.

export const SIZE = { width: 1200, height: 630 } as const;
const NIGHT = "#1E1640";
const ON_NIGHT = "#EEEAF8";
const NIGHT_SOFT = "#B9B0D9";
const BLOOM = "#5A3FC0";
const SAFFRON = "#F4B53F";

let faces: Promise<[Buffer, Buffer]> | null = null;
function loadFaces() {
  const dir = join(process.cwd(), "public", "fonts", "og");
  faces ??= Promise.all([readFile(join(dir, "fraunces-og-v1.ttf")), readFile(join(dir, "bricolage-og-v1.ttf"))]);
  return faces;
}

export interface ShareCardProps {
  /** The big line: the teaser's public title, or the certificate id. */
  title: string;
  /** The line under it: the niche, or "Registered on Wazo". */
  line: string | null;
  /** The title in the figure face (a certificate id), not the serif. */
  code?: boolean;
}

function Mark() {
  return (
    <svg width="64" height="64" viewBox="0 0 32 32">
      <rect x="1" y="1" width="30" height="30" rx="9" fill={BLOOM} />
      <path d="M7.5 11.5 11.75 22.5 16 14.5l4.25 8 4.25-11" fill="none" stroke="#FFFFFF" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="16" cy="8.25" r="2.25" fill={SAFFRON} />
    </svg>
  );
}

/** The card as a PNG response, cached for an hour by browsers and previews. */
export async function shareCard({ title, line, code = false }: ShareCardProps): Promise<ImageResponse> {
  const [fraunces, bricolage] = await loadFaces();
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          backgroundColor: NIGHT,
          backgroundImage: `radial-gradient(circle at 88% 12%, rgba(123, 96, 255, 0.55), rgba(30, 22, 64, 0) 52%)`,
          color: ON_NIGHT,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 18, padding: "64px 80px 0" }}>
          <Mark />
          <span style={{ fontFamily: "Bricolage", fontSize: 54, letterSpacing: "-0.035em" }}>Wazo</span>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 28, padding: "0 80px" }}>
          <div
            style={{
              display: "flex",
              fontFamily: code ? "Bricolage" : "Fraunces",
              fontSize: code ? 84 : title.length > 60 ? 60 : 72,
              lineHeight: 1.08,
              letterSpacing: code ? "0.04em" : "-0.02em",
              maxWidth: 1000,
            }}
          >
            {title.length > 110 ? `${title.slice(0, 107).trimEnd()}…` : title}
          </div>
          {line ? (
            <div style={{ display: "flex" }}>
              <span style={{ display: "flex", borderRadius: 999, backgroundColor: BLOOM, color: "#FFFFFF", fontSize: 30, padding: "8px 24px" }}>
                {line}
              </span>
            </div>
          ) : (
            <div style={{ display: "flex", color: NIGHT_SOFT, fontSize: 30 }} />
          )}
        </div>
        <div style={{ display: "flex", flexDirection: "column" }}>
          <div style={{ display: "flex", height: 56 }} />
          <div
            style={{
              display: "flex",
              height: 14,
              backgroundImage: `linear-gradient(90deg, ${BLOOM} 0%, ${BLOOM} 50%, ${SAFFRON} 50%, ${SAFFRON} 100%)`,
              backgroundSize: "56px 14px",
              backgroundRepeat: "repeat-x",
            }}
          />
        </div>
      </div>
    ),
    {
      ...SIZE,
      fonts: [
        { name: "Fraunces", data: fraunces, weight: 600, style: "normal" },
        { name: "Bricolage", data: bricolage, weight: 700, style: "normal" },
      ],
      headers: { "Cache-Control": "public, max-age=3600" },
    },
  );
}

/** A plain 404 for an id with no public card (a draft, a hidden idea, an unknown certificate). */
export function noCard(): Response {
  return new Response(null, { status: 404, headers: { "Cache-Control": "no-store" } });
}
