import { useTranslations } from "next-intl";

import { buttonClass } from "@/components/ui/Button";
import { controlClass } from "@/components/ui/Field";
import { cn } from "@/components/ui/cn";

import type { Membership } from "./membership";

/**
 * The organisation picker, shown only to members of several organisations: a GET form, so it works before the
 * page's JavaScript has loaded. The choice travels as ?org=<id>; the server acts only for a membership of the person's.
 */
export function OrgPicker({
  memberships,
  current,
  action,
}: {
  memberships: Membership[];
  current: string;
  action: string;
}) {
  const t = useTranslations("inbox");
  if (memberships.length < 2) return null;
  return (
    <form method="get" action={action} className="flex flex-wrap items-end gap-3">
      <div className="flex min-w-0 flex-1 flex-col gap-1.5 sm:max-w-sm">
        <label htmlFor="org-picker" className="font-semibold text-ink">
          {t("pickerLabel")}
        </label>
        <select id="org-picker" name="org" defaultValue={current} className={cn(controlClass, "w-full")}>
          {memberships.map((m) => (
            <option key={m.org_id} value={m.org_id}>
              {m.org_name}
            </option>
          ))}
        </select>
      </div>
      <button type="submit" className={buttonClass("secondary")}>
        {t("pickerSubmit")}
      </button>
    </form>
  );
}
