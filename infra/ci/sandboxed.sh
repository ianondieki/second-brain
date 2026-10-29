#!/usr/bin/env bash
# Run a command as the egress-locked user created by infra/ci/egress-lock.sh, keeping the job's
# environment and PATH (sudo resets PATH to secure_path otherwise). Usage: infra/ci/sandboxed.sh make check
set -euo pipefail
user_name="${EGRESS_LOCK_USER:-sandbox}"
exec sudo --preserve-env -u "$user_name" env "PATH=$PATH" "HOME=/home/$user_name" "$@"
