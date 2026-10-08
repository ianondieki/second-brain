import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { BriefForm } from "./BriefForm";

// P25 (the coordinator's rule for lazy chunks): the live preview is fetched on the first edit; offline, the page's own
// preview stays in its place and the form goes on working.
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }) }));
vi.mock("./BriefPreview", () => {
  throw new Error("offline");
});

afterEach(cleanup);

describe("BriefForm offline", () => {
  it("keeps the page's own preview when the live one cannot be fetched", async () => {
    renderWithIntl(
      <BriefForm
        orgId="o1"
        orgName="Telco A"
        niches={[]}
        counties={[]}
        bands={[]}
        today="2026-10-08"
        planLimit={1}
        planNames={{}}
        doneHref="/org/problems"
        hereHref="/org/problems/new"
        cancelHref="/org/problems"
        preview={<p data-static-preview="">How it reads on Discover</p>}
      />,
    );
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Tower sites go dark" } });
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(document.querySelector("[data-static-preview]")).not.toBeNull();
    expect((screen.getByLabelText("Title") as HTMLInputElement).value).toBe("Tower sites go dark");
  });
});
