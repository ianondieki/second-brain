import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";

import { SHORTLIST_HEADING_ID } from "../../shortlist";
import { RemoveEntry } from "./RemoveEntry";

// REQ-REPO-02 (P21 B1): Remove on the Shortlist. Once its row leaves, focus stays on the list, or on the Shortlist's
// heading when it was the last entry (the list then gives way to the empty state).

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh }) }));

afterEach(() => {
  cleanup();
  refresh.mockClear();
});

const labels = (title: string) => ({
  remove: en.shortlist.removeEntry,
  name: `Remove ${title} from the shortlist`,
  busy: en.shortlist.removing,
  problem: en.shortlist.problem,
});

function renderList(titles: string[]) {
  const setImpl = vi.fn(async () => ({ ok: true as const }));
  render(
    <>
      <h2 id={SHORTLIST_HEADING_ID} tabIndex={-1}>
        Shortlist
      </h2>
      <ul data-shortlist-list="" tabIndex={-1} aria-label="Shortlist of Telco A">
        {titles.map((title, i) => (
          <li key={title}>
            <article data-shortlist-entry={`p${i}`}>
              {title}
              <RemoveEntry orgId="o1" proposalId={`p${i}`} labels={labels(title)} setImpl={setImpl} />
            </article>
          </li>
        ))}
      </ul>
    </>,
  );
  return setImpl;
}

describe("Remove on the Shortlist", () => {
  it("leaves focus on the list after removing a middle entry, then reads the list again", async () => {
    const setImpl = renderList(["First", "Middle", "Last"]);
    const button = screen.getByRole("button", { name: "Remove Middle from the shortlist" });
    button.focus();
    await act(async () => fireEvent.click(button));
    expect(setImpl).toHaveBeenCalledWith("o1", "p1", false);
    expect(document.activeElement).toBe(screen.getByRole("list", { name: "Shortlist of Telco A" }));
    expect(refresh).toHaveBeenCalledOnce();
  });

  it("moves focus to the Shortlist's heading after removing the last entry", async () => {
    renderList(["Only"]);
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Remove Only from the shortlist" })));
    expect(document.activeElement).toBe(screen.getByRole("heading", { name: "Shortlist" }));
    expect(refresh).toHaveBeenCalledOnce();
  });
});
