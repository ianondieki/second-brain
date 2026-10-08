import { ALL_PHOTOS, photo, type Photo } from "./photos";

export type DayPart = "morning" | "afternoon" | "evening";

/** Until P25-A's Nairobi morning: the P24 skyline serves the morning and the afternoon, golden hour the evening. */
const INTERIM: Record<DayPart, string> = {
  morning: "nairobi-skyline",
  afternoon: "nairobi-skyline",
  evening: "nairobi-golden-hour",
};

/** Home's greeting photograph for the time of day in Nairobi: the index's `greeting-<part>` role first (P25-A). */
export function greetingPhoto(part: DayPart): Photo {
  return ALL_PHOTOS.find((p) => p.role === `greeting-${part}`) ?? photo(INTERIM[part]);
}
