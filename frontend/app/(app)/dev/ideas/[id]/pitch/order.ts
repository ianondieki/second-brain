// The picker's order when the idea answers an organisation's Problem Brief (REQ-DIR-05): that organisation, chosen
// from the start, is listed first (its group first, its row first in it), so the note that names it and the checkbox
// to untick are together at the top; every other group and row keeps the API's order. No types from the client form
// (this module is the server page's), only the shape it needs.

interface Row {
  id: string;
}
interface Group<R extends Row> {
  rows: R[];
}

/** The groups with the row of `id` (lower case) first in the first group; unchanged when no row has that id. */
export function leadWith<R extends Row, G extends Group<R>>(groups: readonly G[], id: string | undefined): G[] {
  if (!id) return [...groups];
  const at = groups.findIndex((group) => group.rows.some((row) => row.id.toLowerCase() === id));
  if (at < 0) return [...groups];
  const group = groups[at];
  const rows = [...group.rows];
  const index = rows.findIndex((row) => row.id.toLowerCase() === id);
  const [row] = rows.splice(index, 1);
  return [{ ...group, rows: [row, ...rows] }, ...groups.slice(0, at), ...groups.slice(at + 1)];
}
