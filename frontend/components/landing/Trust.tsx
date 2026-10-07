import { getTranslations } from "next-intl/server";

import { FileCheckIcon, FileLockIcon, RouteIcon, ShieldCheckIcon } from "@/components/icons/lucide";

const ITEMS = [
  { key: "timestamped", Icon: FileCheckIcon },
  { key: "nda", Icon: FileLockIcon },
  { key: "verified", Icon: ShieldCheckIcon },
  { key: "tracker", Icon: RouteIcon },
] as const;

/**
 * The strip under the hero (P23-2): four of the product's own truths, each an icon and a few words, restated from what
 * the page already says (landing.lead, the organisations' points, the questions, the tracker). No figures, no names,
 * no logos. Quiet on purpose: the hero above it is the page's one bold place.
 */
export async function Trust() {
  const t = await getTranslations("landing.trust");
  return (
    <div className="border-b border-line bg-field">
      <ul className="mx-auto grid w-full max-w-6xl grid-cols-1 gap-x-8 gap-y-4 px-4 py-8 sm:grid-cols-2 sm:px-6 lg:grid-cols-4 lg:py-9">
        {ITEMS.map(({ key, Icon }) => (
          <li key={key} className="flex items-center gap-3 text-[0.9375rem] leading-snug font-semibold text-ink">
            <Icon className="size-6 shrink-0 text-accent" />
            {t(key)}
          </li>
        ))}
      </ul>
    </div>
  );
}
