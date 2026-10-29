import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { DataCell, DataRow, DataTable } from "./DataTable";

afterEach(cleanup);

// D-52, the staff console's tables: named, with their roles written out so the stacked phone layout keeps them.
describe("DataTable", () => {
  it("is a named table with column headers, row headers and cells", () => {
    render(
      <DataTable aria-label="Claims waiting for review" columns={["Organisation", "Level", "Filed"]}>
        <DataRow data-claim="c1">
          <DataCell head label="Organisation">
            Telco A
          </DataCell>
          <DataCell label="Level">E1</DataCell>
          <DataCell label="Filed" figure nowrap>
            1 Oct 2026
          </DataCell>
        </DataRow>
      </DataTable>,
    );
    const table = screen.getByRole("table", { name: "Claims waiting for review" });
    expect(table.getAttribute("role")).toBe("table");
    expect(within(table).getAllByRole("columnheader").map((th) => th.textContent)).toEqual(["Organisation", "Level", "Filed"]);
    expect(within(table).getAllByRole("rowgroup")).toHaveLength(2);
    const row = within(table).getAllByRole("row")[1]!;
    expect(row.getAttribute("role")).toBe("row");
    expect(within(row).getByRole("rowheader").textContent).toBe("Telco A");
    expect(within(row).getAllByRole("cell").map((td) => td.getAttribute("data-label"))).toEqual(["Level", "Filed"]);
  });

  it("prefixes stacked cells with their column's name, never the row's title", () => {
    const { container } = render(
      <DataTable aria-label="Cases" columns={["Case", "Status"]}>
        <DataRow>
          <DataCell head label="Case">
            A case
          </DataCell>
          <DataCell label="Status">Open</DataCell>
        </DataRow>
      </DataTable>,
    );
    const [head, cell] = container.querySelectorAll("th[scope=row], td");
    expect(head!.className).not.toContain("before:content-[attr(data-label)]");
    expect(cell!.className).toContain("before:content-[attr(data-label)]");
    expect(container.querySelector("thead")!.className).toContain("max-sm:hidden");
  });
});
