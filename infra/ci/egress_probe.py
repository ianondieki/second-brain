"""Egress probe (AC-SEC-5): prove that the current process cannot reach real providers.

Run it inside the egress lock (infra/ci/sandboxed.sh python infra/ci/egress_probe.py). It exits 0 only when
every provider endpoint below is unreachable. Stdlib only, so it runs before any project dependency is installed.
"""

from __future__ import annotations

import socket
import sys

# LLM, email, WhatsApp, payment and SMS providers named in docs/spec/08 and ADR-004..006.
PROVIDERS = (
    ("api.anthropic.com", 443),
    ("api.postmarkapp.com", 443),
    ("graph.facebook.com", 443),
    ("api.safaricom.co.ke", 443),
    ("sandbox.safaricom.co.ke", 443),
    ("api.paystack.co", 443),
    ("api.africastalking.com", 443),
    ("api.groq.com", 443),
    ("smtp.gmail.com", 587),
)
TIMEOUT_S = 5.0


def reachable(host: str, port: int) -> str | None:
    """Return the address connected to, or None when the connection is refused, unreachable or not resolvable."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        return None
    for family, kind, proto, _, addr in infos:
        with socket.socket(family, kind, proto) as sock:
            sock.settimeout(TIMEOUT_S)
            try:
                sock.connect(addr)
            except OSError:
                continue
            return str(addr[0])
    return None


def main() -> int:
    leaks = []
    for host, port in PROVIDERS:
        addr = reachable(host, port)
        status = f"REACHABLE via {addr}" if addr else "blocked"
        print(f"{host}:{port} {status}")
        if addr:
            leaks.append(host)
    if leaks:
        print(f"FAIL: egress is open to {', '.join(leaks)}", file=sys.stderr)
        return 1
    print("PASS: no provider endpoint is reachable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
