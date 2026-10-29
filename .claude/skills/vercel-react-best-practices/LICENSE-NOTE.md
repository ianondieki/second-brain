# Licence note (Bridge)

Added by Bridge on 2026-09-30. Not part of the upstream skill.

- Upstream: https://github.com/vercel-labs/agent-skills, folder `skills/react-best-practices`
- Commit: `063bee94c3f4df8453406c830b0a7df0f2860278` (committed 2026-08-28T15:36:07+02:00)
- Licence as stated upstream: MIT

At this commit the upstream repository has **no LICENSE file and no copyright line** (none at the repository
root and none in this skill's folder). The licence is stated only in the two places quoted verbatim below. No
copyright holder is named upstream, so none is named here.

The repository README (`README.md`), section "## License", verbatim:

```
## License

MIT
```

This skill's `SKILL.md` frontmatter, verbatim:

```
license: MIT
metadata:
  author: vercel
  version: "1.0.0"
```

Local changes (full list in `docs/platform/research/design-skills.md`): the folder is named
`vercel-react-best-practices` to match the frontmatter `name`; the skill's contributor `README.md` was not copied
(it tells the reader to run `pnpm install` and build scripts that are not vendored); the `npx svgo` command in
`rules/rendering-svg-precision.md` and the same section of `AGENTS.md` was replaced with a note. Everything else
is unchanged.
