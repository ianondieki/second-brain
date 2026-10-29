#!/usr/bin/env bash
# Egress lock for CI test steps (AC-SEC-5, REQ-FND-03). Linux runners only; needs passwordless sudo
# (GitHub-hosted ubuntu runners have it).
#
# Run it AFTER dependencies are installed and container images are pulled. From then on, test commands run
# as the unprivileged user `sandbox` through infra/ci/sandboxed.sh. That user may reach loopback and private
# (Docker/runner-internal) networks only; every other outbound packet is rejected, so no test can call an LLM,
# email, WhatsApp or payment provider. Containers started by the Docker daemon get the same limit through the
# DOCKER-USER chain. The GitHub runner agent itself (user `runner`) is not affected, so logs keep streaming.
set -euo pipefail

user_name="${EGRESS_LOCK_USER:-sandbox}"
private_v4=(127.0.0.0/8 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16)

if ! id "$user_name" >/dev/null 2>&1; then
  sudo useradd --create-home --shell /bin/bash "$user_name"
fi
if getent group docker >/dev/null; then
  sudo usermod -aG docker "$user_name"
fi

# Test user: allow private destinations, reject the rest (IPv4 and IPv6).
for net in "${private_v4[@]}"; do
  sudo iptables -A OUTPUT -m owner --uid-owner "$user_name" -d "$net" -j ACCEPT
done
sudo iptables -A OUTPUT -m owner --uid-owner "$user_name" -j REJECT
sudo ip6tables -A OUTPUT -m owner --uid-owner "$user_name" -o lo -j ACCEPT
sudo ip6tables -A OUTPUT -m owner --uid-owner "$user_name" -j REJECT

# Containers: replies and private destinations pass, new connections to public addresses are rejected.
if sudo iptables -L DOCKER-USER -n >/dev/null 2>&1; then
  sudo iptables -I DOCKER-USER 1 -j REJECT
  for net in "${private_v4[@]}"; do
    sudo iptables -I DOCKER-USER 1 -d "$net" -j RETURN
  done
  sudo iptables -I DOCKER-USER 1 -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
fi

# The sandbox user must reach the checkout and the runner's temp dir (the runner's home is mode 750) and be
# able to write caches inside the checkout.
workspace="${GITHUB_WORKSPACE:-$PWD}"
for target in "$workspace" "${RUNNER_TEMP:-}"; do
  [ -n "$target" ] || continue
  dir="$target"
  while [ "$dir" != "/" ]; do
    sudo chmod o+x "$dir"
    dir="$(dirname "$dir")"
  done
done
sudo chmod -R a+rwX "$workspace"
if [ -n "${RUNNER_TEMP:-}" ]; then
  sudo chmod -R a+rX "$RUNNER_TEMP"
fi
echo "egress lock active for user '$user_name' and for containers"
