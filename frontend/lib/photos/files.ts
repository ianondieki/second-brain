import { existsSync } from "node:fs";
import { join } from "node:path";

import type { Photo } from "./photos";

// Which sizes of a photograph are vendored (server only: it looks at public/photos). P24 shipped 800 and 1600 px;
// P25-A adds a 480 px pair for card bands, which then joins the srcset with no code change. Read once per photograph.

const CANDIDATES = [480, 800, 1600] as const;
const known = new Map<string, readonly number[]>();

export function photoWidths(photo: Photo, root: string = join(process.cwd(), "public")): readonly number[] {
  const key = `${root}|${photo.slug}`;
  const cached = known.get(key);
  if (cached) return cached;
  const found = CANDIDATES.filter((w) => existsSync(join(root, photo.dir, `${photo.slug}-${w}.avif`)) && existsSync(join(root, photo.dir, `${photo.slug}-${w}.webp`)));
  const widths = found.includes(800) ? found : [800, 1600];
  known.set(key, widths);
  return widths;
}
