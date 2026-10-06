// What the team thread's page loads on first use, as one module (one chunk to fetch): the team calls (the first Send,
// earlier messages, Report) and the steps' dialogs (the first press of a step). docs/spec/07 item 5: the route shares
// the Messages route's thread parts and sits near 150 KB, so none of this ships with the page.
export { teamThreadCalls } from "./thread-calls";
export { ThreadSheets } from "./ThreadSheets";
