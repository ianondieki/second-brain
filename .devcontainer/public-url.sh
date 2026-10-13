#!/usr/bin/env bash
# The demo's address in a codespace (P28 track PD; REQ-FND-04; docs/runbooks/public-demo.md part A).
#
#   bash .devcontainer/public-url.sh             print the address (postAttachCommand); the port stays private
#   bash .devcontainer/public-url.sh --publish   make port 7860 public, so anyone with the address can open it
#   bash .devcontainer/public-url.sh --private   make it private again
#
# Publishing is the owner's choice, made after the runbook's go-live checklist (part D), never automatic. A private
# port opens only for you, signed in to GitHub. devcontainer.json cannot set a port's visibility, so --publish and
# --private ask the GitHub CLI (it uses the codespace's own token). Fallback: the Ports tab, right-click port 7860,
# Port Visibility.
set -uo pipefail

port="${PORT:-7860}"
mode="${1:-}"
case "$mode" in
  ""|--publish|--private) ;;
  *) echo "usage: bash .devcontainer/public-url.sh [--publish|--private]" >&2; exit 2 ;;
esac

if [ -z "${CODESPACE_NAME:-}" ] || [ -z "${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-}" ]; then
  echo "demo: not in a codespace; the demo is at http://localhost:${port}"
  exit 0
fi
url="https://${CODESPACE_NAME}-${port}.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}"

if [ -z "$mode" ]; then
  echo
  echo "demo: the address (private: it opens only for you, signed in to GitHub; ready once ~/demo.log says ready):"
  echo "  ${url}"
  echo "demo: to share it, first work through the go-live checklist (docs/runbooks/public-demo.md, part D), then run:"
  echo "  bash .devcontainer/public-url.sh --publish"
  exit 0
fi

visibility="${mode#--}"
[ "$visibility" = publish ] && visibility=public
for _ in 1 2 3 4 5 6; do
  if gh codespace ports visibility "${port}:${visibility}" -c "$CODESPACE_NAME" >/dev/null 2>&1; then
    if [ "$visibility" = public ]; then
      echo "demo: port ${port} is public. Anyone with this address can open the demo while the codespace runs:"
      echo "  ${url}"
      echo "demo: make it private again with: bash .devcontainer/public-url.sh --private"
    else
      echo "demo: port ${port} is private again: ${url} opens only for you."
    fi
    exit 0
  fi
  sleep 5
done
echo "demo: could not change the port's visibility; in the Ports tab, right-click ${port} > Port Visibility." >&2
exit 1
