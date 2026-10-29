import { getLocale, getTranslations } from "next-intl/server";

import { formatKes, planLines, priceKind, type Plan } from "./plans";

// Plan wording shared by Plan & billing and the checkout, formatted on the server (ICU plurals in `billing.*`).

/** A plan's price: "KES 499 a month", "Free", or "Not available to buy here yet". */
export async function priceText(plan: Plan): Promise<string> {
  const t = await getTranslations("billing");
  const kind = priceKind(plan);
  if (kind === "free" || kind === "notSold") return t(kind);
  return t(kind, { amount: formatKes(plan.price_kes_minor, await getLocale()) });
}

/** The plan's entitlement lines in the request's language. */
export async function lineTexts(plan: Plan): Promise<string[]> {
  const t = await getTranslations("billing");
  return planLines(plan).map((line) =>
    line.count === undefined ? t(`line.${line.key}`) : t(`line.${line.key}`, { count: line.count }),
  );
}
