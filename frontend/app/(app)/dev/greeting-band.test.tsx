import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { resolveServerTree } from "@/test/server-tree";

import { GreetingBand, PHONE_MEDIA, WIDE_MEDIA } from "./GreetingBand";

// P25 (REQ-UX-05, acceptance 2): the greeting photograph is Home's LCP element on a phone. Below 40 rem it is a strip
// about 380 px wide, so a phone fetches the 480 px file (a 1.75 DPR screen would take 800 px through `sizes`); from
// 40 rem the 800 px file; eager, high priority, decoded with the first paint.

vi.mock("next/headers", () => ({ headers: async () => new Headers() }));

afterEach(cleanup);

async function band() {
  return render(<>{await resolveServerTree(await GreetingBand({ part: "evening", children: <h1>Good evening</h1> }))}</>);
}

describe("Home's greeting photograph", () => {
  it("offers the 480 px files to a phone and the 800 px files from 40 rem, AVIF first", async () => {
    const { container } = await band();
    const sources = [...container.querySelectorAll("source")].map((s) => [s.getAttribute("type"), s.getAttribute("media"), s.getAttribute("srcset")]);
    expect(sources).toEqual([
      ["image/avif", PHONE_MEDIA, "/photos/nairobi-golden-hour-480.avif"],
      ["image/avif", WIDE_MEDIA, "/photos/nairobi-golden-hour-800.avif"],
      ["image/webp", PHONE_MEDIA, "/photos/nairobi-golden-hour-480.webp"],
      ["image/webp", WIDE_MEDIA, "/photos/nairobi-golden-hour-800.webp"],
    ]);
    expect(PHONE_MEDIA).toBe("(width < 40rem)"); // the CSS breakpoint of .greeting-photo (globals.css)
  });

  it("is the one eager, high-priority image, not decoded asynchronously, and decorative", async () => {
    const { container } = await band();
    const img = container.querySelector("img")!;
    expect(img.getAttribute("loading")).toBe("eager");
    expect(img.getAttribute("fetchpriority")).toBe("high");
    expect(img.hasAttribute("decoding")).toBe(false);
    expect(img.getAttribute("alt")).toBe("");
    expect(container.querySelector(".greeting-photo")!.getAttribute("aria-hidden")).toBe("true");
  });
});
