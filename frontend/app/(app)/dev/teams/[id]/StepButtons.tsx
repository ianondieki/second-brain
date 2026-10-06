import { buttonClass } from "@/components/ui/Button";

import { Overflow, overflowItemClass } from "../Overflow";

/**
 * The thread's step buttons as plain markup (TeamThread answers their presses by `data-step`): "Add as
 * contributor on an idea" when given, then the overflow menu with "Leave thread" and "Block" when given. Each label
 * is null when the step is not open to the caller. The menu's button keeps to the row's right edge (alone, or wrapped
 * under a long first step), so the menu, opening leftward from it, always stays inside a 360 px screen.
 */
export function StepButtons({ credit, more, leave, block }: { credit: string | null; more: string; leave: string | null; block: string | null }) {
  return (
    <>
      {credit ? (
        <button type="button" className={buttonClass("secondary")} aria-haspopup="dialog" data-step="credit" data-add-contributor="">
          {credit}
        </button>
      ) : null}
      {leave || block ? (
        <div className="ml-auto">
          <Overflow label={more} align="end" data-thread-menu="">
            {leave ? (
              <button type="button" className={overflowItemClass} aria-haspopup="dialog" data-step="leave" data-leave="">
                {leave}
              </button>
            ) : null}
            {block ? (
              <button type="button" className={`${overflowItemClass} text-error`} aria-haspopup="dialog" data-step="block" data-block="">
                {block}
              </button>
            ) : null}
          </Overflow>
        </div>
      ) : null}
    </>
  );
}
