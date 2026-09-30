import { useTranslations } from "next-intl";

/**
 * A route's loading state (loading.tsx): still blocks where the page header, its lead and three rows will be, and a
 * hidden sentence for screen readers (docs/platform/design/p16-design-system.md, Loading). A server component: no
 * client JavaScript, no shimmer or animation (low bandwidth, reduced motion), nothing to announce twice.
 */
export function PageSkeleton() {
  const t = useTranslations("common");
  return (
    <div role="status" data-skeleton="">
      <span className="sr-only">{t("loading")}</span>
      <div aria-hidden="true">
        <div className="h-7 w-3/4 max-w-sm bg-jacaranda-wash lg:h-9" />
        <div className="mt-3 h-5 w-full max-w-md bg-wash-soft" />
        <ul className="mt-10">
          {[0, 1, 2].map((row) => (
            <li key={row} className="border-t border-line py-5">
              <div className="h-5 w-2/3 max-w-xs bg-jacaranda-wash" />
              <div className="mt-3 h-4 w-1/2 max-w-[14rem] bg-wash-soft" />
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
