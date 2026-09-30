import { useTranslations } from "next-intl";

import { TabNav } from "@/components/ui/TabNav";

export const SETTINGS_TABS = [
  { key: "security", href: "/settings/security" },
  { key: "notifications", href: "/settings/notifications" },
] as const;

export type SettingsTab = (typeof SETTINGS_TABS)[number]["key"];

/**
 * The settings pages as link tabs (P16-A open item 9): Security and Notifications, each its own address, reached from
 * the account menu and from each other.
 */
export function SettingsTabs({ current }: { current: SettingsTab }) {
  const t = useTranslations("settingsNav");
  return (
    <TabNav
      label={t("label")}
      current={current}
      items={SETTINGS_TABS.map(({ key, href }) => ({ key, href, label: t(key) }))}
      className="mb-8"
    />
  );
}
