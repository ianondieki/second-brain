import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ButtonLink } from "./ButtonLink";
import { EmptyState } from "./EmptyState";
import { Section } from "./Section";

afterEach(cleanup);

const hintOf = (name: string) => screen.getByRole("link", { name }).querySelector("[data-link-pending]")!;

// P16-C1 fix round 1 (ux MAJOR 3): every in-app link of the system shows the pending hint, at a fixed size inside it.
describe("the pending hint in the system's links", () => {
  it("sits inside a primary ButtonLink in the button's text colour, and in the accent on the others", () => {
    render(
      <>
        <ButtonLink href="/dev/ideas/new" variant="primary">
          New proposal
        </ButtonLink>
        <ButtonLink href="/dev/ideas/1/edit">Edit idea</ButtonLink>
      </>,
    );
    const primary = hintOf("New proposal").className.split(" ");
    expect(primary).toEqual(expect.arrayContaining(["bg-current", "absolute", "h-[3px]", "w-6"]));
    expect(primary).not.toContain("bg-jacaranda");
    expect(screen.getByRole("link", { name: "New proposal" }).className).toContain("relative");
    expect(hintOf("Edit idea").className.split(" ")).toContain("bg-jacaranda");
  });

  it("sits inside a Section's secondary link and an empty state's action (plain and primary)", () => {
    render(
      <>
        <Section title="My ideas" link={{ href: "/dev/ideas", label: "All my ideas" }} />
        <EmptyState sentence="Nothing yet." action="Go to My ideas" href="/dev/ideas" />
        <EmptyState sentence="No ideas yet." action="New idea" href="/dev/ideas/new" primary />
      </>,
    );
    for (const name of ["All my ideas", "Go to My ideas"]) {
      expect(hintOf(name).className.split(" "), name).toEqual(expect.arrayContaining(["absolute", "bg-jacaranda"]));
    }
    expect(hintOf("New idea").className.split(" ")).toContain("bg-current");
  });
});
