import { getTranslations } from "next-intl/server";

import { Picture } from "@/components/landing/Picture";
import { savesData } from "@/components/ui/NicheBand";
import { DAY_PHOTOS, type DayPart } from "@/lib/photos/photos";

/**
 * Home's greeting band (D-67, P25): the Nairobi photograph for the time of day of the app clock, as a window beside the
 * greeting from a wide hero column (PageHero's aside) and a narrow band under it on a phone, never the page's largest
 * element. Decorative (`alt=""`): its caption names the place and the time ("Nairobi, this afternoon"); credited on
 * /credits. None under `Save-Data: on`. A server component: no script. Both Homes use it (the developer's and the
 * organisation's), so the greeting reads the same on either side.
 */
export async function GreetingPhoto({ part }: { part: DayPart }) {
  if (await savesData()) return null;
  const t = await getTranslations("portal");
  return (
    <figure className="greeting-photo" data-greeting-photo={part}>
      <Picture photo={DAY_PHOTOS[part]} sizes="(min-width: 1024px) 18rem, 100vw" />
      <figcaption className="greeting-photo-caption">{t(`greeting.${part}`)}</figcaption>
    </figure>
  );
}
