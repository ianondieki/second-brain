import { render, type RenderOptions } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactElement } from "react";

import { ClientStrings, type StringTree } from "@/components/ClientStrings";
import en from "@/locales/en.json";

/**
 * Renders a client component with the English messages, as the app provides them: next-intl for the forms under
 * IntlScope, and the server-formatted strings (lib/i18n/client-strings.ts) for the rest. Those namespaces use plain
 * "{name}" arguments only, so the raw English messages are what the server would send.
 */
export function renderWithIntl(ui: ReactElement, options?: RenderOptions) {
  return render(
    <NextIntlClientProvider locale="en" messages={en}>
      <ClientStrings strings={en as unknown as Record<string, StringTree>}>{ui}</ClientStrings>
    </NextIntlClientProvider>,
    options,
  );
}
