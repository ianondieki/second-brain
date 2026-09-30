import Link from "next/link";
import { useTranslations } from "next-intl";
import type { ComponentType, SVGProps } from "react";

import type { components } from "@/lib/api/schema";

import { ClaimsIcon, ModerationIcon, ResearchIcon } from "./admin-icons";
import { cn } from "./ui/cn";

export type StaffRole = components["schemas"]["StaffRole"];

/**
 * The staff console's sections (REQ-ADM-01; docs/spec/07 item 1: "Admin is a separate console", at most five), each
 * with the staff roles the API admits to it (docs/spec/03; bridge/admin/deps.py): a section is listed only for those
 * roles. Research and Claims are the staff admin's; Moderation is the staff admin's and the moderator's. Support has
 * no section yet (the console home tells them so).
 */
export const ADMIN_SECTIONS = [
  { key: "research", href: "/admin/research", Icon: ResearchIcon, roles: ["admin"] },
  { key: "moderation", href: "/admin/moderation", Icon: ModerationIcon, roles: ["admin", "moderator"] },
  { key: "claims", href: "/admin/claims", Icon: ClaimsIcon, roles: ["admin"] },
] as const satisfies ReadonlyArray<{
  key: string;
  href: string;
  Icon: ComponentType<SVGProps<SVGSVGElement>>;
  roles: readonly StaffRole[];
}>;

export type AdminSection = (typeof ADMIN_SECTIONS)[number]["key"];

/** The sections a staff role may open, in the console's order. */
export function adminSections(role: StaffRole) {
  return ADMIN_SECTIONS.filter((section) => (section.roles as readonly StaffRole[]).includes(role));
}

/**
 * Bottom tabs under 1024 px, a left rail from 1024 px (one <nav>, restyled like DevNav and OrgNav). The current
 * section carries aria-current="page" and is marked by colour, weight and a bar, not colour alone. With a single
 * section there is no tab bar below 1024 px (the console home opens that section).
 */
export function AdminNav({ current, role }: { current?: AdminSection; role: StaffRole }) {
  const t = useTranslations("admin");
  const sections = adminSections(role);
  if (sections.length === 0) return null;
  // A bottom tab bar with one tab only takes room on a phone: below 1024 px the bar appears from two sections on.
  const tabs = sections.length > 1;
  return (
    <nav
      aria-label={t("navLabel")}
      data-tab-bar={tabs ? "" : undefined}
      className={cn(
        tabs
          ? "fixed inset-x-0 bottom-0 z-10 border-t border-line bg-paper pb-[env(safe-area-inset-bottom)] lg:static lg:z-auto lg:border-0 lg:bg-transparent lg:pb-0"
          : "hidden lg:block",
        "lg:w-52 lg:shrink-0 lg:pt-16",
      )}
    >
      <p className="hidden px-3 pb-3 text-sm font-medium text-ink-soft lg:block">{t("navLabel")}</p>
      <ul className="mx-auto flex max-w-md lg:max-w-none lg:flex-col lg:gap-1">
        {sections.map(({ key, href, Icon }) => {
          const active = key === current;
          return (
            <li key={key} className="flex-1 lg:flex-none">
              <Link
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "relative flex min-h-14 flex-col items-center justify-center gap-0.5 px-2 text-sm whitespace-nowrap no-underline",
                  "lg:min-h-11 lg:flex-row lg:justify-start lg:gap-3 lg:rounded-control lg:px-3 lg:text-base",
                  active
                    ? "font-semibold text-jacaranda lg:bg-jacaranda-wash"
                    : "font-medium text-ink-soft hover:text-ink lg:hover:bg-wash-soft",
                )}
              >
                {active ? (
                  <span
                    aria-hidden="true"
                    className="absolute inset-x-6 top-0 h-0.5 rounded-b bg-jacaranda lg:inset-x-auto lg:inset-y-2 lg:left-0 lg:h-auto lg:w-0.5 lg:rounded-none lg:rounded-r"
                  />
                ) : null}
                <Icon className="size-5 shrink-0" />
                <span>{t(`nav.${key}`)}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
