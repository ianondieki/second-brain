import { useTranslations } from "next-intl";

import { TabNav } from "@/components/ui/TabNav";

export const SETTINGS_TABS = [
  { key: "security", href: "/settings/security" },
  { key: "notifications", href: "/settings/notifications" },
  { key: "profile", href: "/settings/profile" },
] as const;

export type SettingsTab = (typeof SETTINGS_TABS)[number]["key"];

/**
 * The settings pages as link tabs (P16-A open item 9): Security and Notifications, each its own address, reached from
 * the account menu and from each other; for a developer, Profile too (REQ-DEV-03: the headline, the county and
 * "Visible to peers"). They close the page's hero (PageHero `tabs`, D-67).
 */
export function SettingsTabs({ current, developer = false }: { current: SettingsTab; developer?: boolean }) {
  const t = useTranslations("settingsNav");
  return (
    <TabNav
      label={t("label")}
      current={current}
      items={SETTINGS_TABS.filter(({ key }) => developer || key !== "profile").map(({ key, href }) => ({ key, href, label: t(key) }))}
    />
  );
}
