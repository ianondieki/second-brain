#!/usr/bin/env bash
# postAttachCommand (P28 track PD; REQ-FND-04): make the demo's port public and print the address to share.
# devcontainer.json cannot set a port's visibility, so this asks the GitHub CLI (it uses the codespace's own token).
# Fallback when it fails: the Ports tab, right-click port 7860, Port Visibility, Public.
set -uo pipefail

port="${PORT:-7860}"
if [ -z "${CODESPACE_NAME:-}" ] || [ -z "${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-}" ]; then
  echo "demo: not in a codespace; the demo is at http://localhost:${port}"
  exit 0
fi

url="https://${CODESPACE_NAME}-${port}.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}"
made_public=false
for _ in 1 2 3 4 5 6; do
  if gh codespace ports visibility "${port}:public" -c "$CODESPACE_NAME" >/dev/null 2>&1; then
    made_public=true
    break
  fi
  sleep 5
done

echo
if [ "$made_public" = true ]; then
  echo "demo: port ${port} is public. Share this address (it answers once ~/demo.log says ready):"
else
  echo "demo: could not make port ${port} public; in the Ports tab, right-click ${port} > Port Visibility > Public."
  echo "demo: then share this address:"
fi
echo "  ${url}"
echo "demo: it works only while this codespace runs (it stops when idle). Log: tail -f ~/demo.log"
