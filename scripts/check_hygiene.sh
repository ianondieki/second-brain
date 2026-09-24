#!/usr/bin/env bash
# Hygiene checks AC-HYG-01..06 (REQ-HYG-01..06), exactly as written in docs/platform/REQUIREMENTS.md §4.
# Used by the pr.yml `hygiene` job; runs locally from the repo root in any POSIX shell (Git Bash on Windows).
# Each check reports PASS/FAIL; the script exits 1 if any check fails. `! cmd` is not used bare because
# `set -e` ignores inverted commands; every negated grep is an explicit `if`.
set -uo pipefail
cd "$(git rev-parse --show-toplevel)"
failed=0

check() {  # check <AC id> <description> <command...>
  local id="$1" what="$2"; shift 2
  if "$@"; then echo "PASS $id $what"; else echo "FAIL $id $what"; failed=1; fi
}
absent() {  # absent <git grep args...>: true when git grep finds nothing
  if git grep "$@"; then return 1; fi
  return 0
}
count_is() {  # count_is <op> <n> <command...>: compare the command's stdout (a number) with n
  local op="$1" n="$2"; shift 2
  local got; got="$("$@" | tr -d '[:space:]')"
  test "${got:-0}" "$op" "$n"
}
env_line() { grep -cE "$1" .env.example | tr -d '\r'; }

check AC-HYG-01 "no Telegram in kept end-user docs" \
  absent -niE "telegram" -- README.md docs ':!docs/spec' ':!docs/platform' ':!legacy'
check AC-HYG-01 "README names WhatsApp" count_is -ge 1 grep -ciE 'whatsapp' README.md
check AC-HYG-01 "README names email" count_is -ge 1 grep -ciE '\bemail\b' README.md
check AC-HYG-02 "no EVOLUTION_ variables" \
  absent -n "EVOLUTION_" -- ':!legacy' ':!docs/spec' ':!docs/platform'
check AC-HYG-03 "no retired Groq model" \
  absent -n "llama-3.3-70b-versatile" -- ':!legacy' ':!docs/spec' ':!docs/platform'
check AC-HYG-03 "GROQ_MODEL example is openai/gpt-oss-20b" \
  count_is -eq 1 env_line '^GROQ_MODEL=openai/gpt-oss-20b\r?$'
check AC-HYG-04 "no Africa/Lagos" \
  absent -n "Africa/Lagos" -- ':!legacy' ':!docs/spec' ':!docs/platform'
check AC-HYG-04 "TZ example is Africa/Nairobi" count_is -eq 1 env_line '^TZ=Africa/Nairobi\r?$'
check AC-HYG-05 "exactly one docs/10-* file" count_is -eq 1 sh -c 'ls docs/10-*.md | wc -l'
check AC-HYG-05 "it is docs/10-project-reminders.md" test -f docs/10-project-reminders.md
check AC-HYG-06 "no tracked *.code-workspace" count_is -eq 0 sh -c "git ls-files | grep -c '\.code-workspace$'"
check AC-HYG-06 "reminder workspace file is gone" test ! -e reminder/second-brain.code-workspace

exit "$failed"
