import compile from "icu-minify/compile";
import { describe, expect, it } from "vitest";

import en from "./en.json";
import sw from "./sw.json";

// Every message, _meta included, compiles with the compiler next-intl's plugin runs over the catalogues
// (next.config.ts precompiles them with icu-minify). One message that does not parse ("<kind>" read as an unclosed
// rich-text tag) fails the whole catalogue, and every page answers with an error: this catches it before a build.

type Tree = { [key: string]: string | Tree };

function leaves(tree: Tree, prefix = ""): Array<[string, string]> {
  return Object.entries(tree).flatMap(([key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    return typeof value === "string" ? [[path, value] as [string, string]] : leaves(value, path);
  });
}

describe.each([
  ["en", en],
  ["sw", sw],
])("the %s catalogue", (_, catalogue) => {
  it("compiles message by message", () => {
    const failed: string[] = [];
    for (const [key, message] of leaves(catalogue as Tree)) {
      try {
        compile(message);
      } catch (error) {
        failed.push(`${key}: ${(error as Error).message}`);
      }
    }
    expect(failed).toEqual([]);
  });

  it("would catch a stray angle bracket", () => {
    expect(() => compile("the page reads preference.<kind>")).toThrow();
  });
});
