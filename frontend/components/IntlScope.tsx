import { NextIntlClientProvider } from "next-intl";
import { getMessages } from "next-intl/server";
import type { ReactNode } from "react";

type Namespace = keyof Awaited<ReturnType<typeof getMessages>>;

/** The given top-level namespaces of the request's messages, and nothing else. */
export async function pickMessages(namespaces: readonly Namespace[]) {
  const messages = await getMessages();
  return Object.fromEntries(namespaces.map((namespace) => [namespace, messages[namespace]]));
}

/**
 * Hands a client subtree only the message namespaces it uses. The provider inlines its messages into the page's
 * HTML, so passing every namespace on every page cost 9-10 KB per page; each page now ships what its forms need.
 */
export async function IntlScope({ namespaces, children }: { namespaces: readonly Namespace[]; children: ReactNode }) {
  return <NextIntlClientProvider messages={await pickMessages(namespaces)}>{children}</NextIntlClientProvider>;
}
