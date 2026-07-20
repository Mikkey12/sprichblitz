"""Smoke-Test gegen ein laufendes Backend.

Aufruf:
    python -m tests.smoke.smoke_test \
        --base-url http://localhost:8000 \
        --token "$(grep BACKEND_AUTH_TOKEN backend/.env | cut -d= -f2)"

Dieser Test ist KEIN pytest-Test, sondern ein eigenständiges CLI-Skript –
gedacht zur manuellen Verifikation von /health und /config gegen das
Live-System (lokal oder über Cloudflare-Tunnel).
"""

from __future__ import annotations

import argparse
import sys

import httpx


def run(base_url: str, token: str | None) -> int:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    timeout = httpx.Timeout(10.0)
    with httpx.Client(base_url=base_url, timeout=timeout) as client:
        print(f"GET {base_url}/health …")
        h = client.get("/health")
        print(f"  status={h.status_code} body={h.json()}")
        if h.status_code != 200:
            return 1

        print(f"GET {base_url}/config …")
        c = client.get("/config", headers=headers)
        print(f"  status={c.status_code}")
        if c.status_code != 200:
            print(f"  body={c.text}")
            return 1

        body = c.json()
        print(f"  modes:    {[m['name'] for m in body['modes']]}")
        print(f"  stt:      {[p['name'] for p in body['stt_providers']]}")
        print(f"  llm:      {[p['name'] for p in body['llm_providers']]}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Sprichblitz smoke test")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--token", default=None)
    args = parser.parse_args()
    sys.exit(run(args.base_url, args.token))


if __name__ == "__main__":
    main()
