import { useTranslations } from "next-intl";

import { MessageIcon } from "./icons";

/**
 * A list row's unread messages (REQ-ENG-11): the count in words beside a speech bubble, in the accent; nothing when
 * there are none. Plain text, not a chip (docs/spec/07 item 2 keeps a row to the stage and "Your turn").
 */
export function UnreadLine({ count }: { count: number | undefined }) {
  const t = useTranslations("tracker");
  if (!count) return null;
  return (
    <span data-unread-messages={count} className="inline-flex items-center gap-1.5 text-sm font-semibold text-accent tabular-nums">
      <MessageIcon className="size-4 shrink-0" />
      {t("unread", { count })}
    </span>
  );
}
