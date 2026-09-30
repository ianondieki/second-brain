# Command guidance

## Workflow questions

Give advice without executing commands; the menu below is only for bare invocations. Consult relevant command references as needed for prerequisites and scope. Link to the [docs](https://impeccable.style/docs/) for the broader workflow guide. If the user also requests execution, follow that request.

## No-argument routing: the context-aware menu

Read this when the user invokes `/impeccable` with no argument. They are asking "what should I do?" Make the menu context-aware instead of static.

Setup step 1 has already read the project context (`CLAUDE.md`, spec 07, spec 04 §4.6). The `impeccable signals` helper is (not available in this copy; do this step by reading the code and screenshots): use what you read, plus the files changed on the branch, then lead with the **2-3 highest-value next commands**, each with a one-line reason, followed by the full menu (the Commands table in SKILL.md, grouped by category). **Never auto-run a command; the recommendation is a suggestion the user confirms.**

Reason over what you read; there is no score to obey:

- The target surface has no critique yet in this session → offering `/impeccable critique <surface>` is a strong default.
- A critique earlier in this session left P0 / P1 issues → `polish`.
- Changed files on the branch point at one surface → scope `audit` or `polish` to those files specifically, naming them.
- Otherwise group by intent (build new / improve what's there), tailored to the current surface.

The bundled `impeccable detect` scan is (not available in this copy; do this step by reading the code and screenshots). Fold what you see into your picks: many quality / contrast problems → `audit` or `polish`; a specific slop family → the matching command (gradient text or eyebrows → `quieter` / `typeset`, flat or gray palette → `colorize`, and so on).

Keep it to 2-3 pointed picks with the exact command to type. The menu stays the fallback; the recommendation is the lede.
