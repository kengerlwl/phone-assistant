"""Run on the deployment host: status, one-time pairing link, or local health check."""
import argparse
import json
import os
from pathlib import Path
import socket
import ssl
import sys
from urllib.parse import urlencode, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bridge"))
from control import request


def main():
    parser = argparse.ArgumentParser(description="Manage Phone Assistant on its server")
    parser.add_argument("action", choices=["status", "pair", "doctor"])
    args = parser.parse_args()
    result = request("/pair-code", {}) if args.action == "pair" else request("/status")
    if result.get("status") == "error":
        print(json.dumps(result)); raise SystemExit(1)
    if args.action in {"pair", "doctor"}:
        env = Path(os.environ.get("PHONE_BRIDGE_ENV", ROOT / "deploy/.env"))
        values = dict(line.split("=", 1) for line in env.read_text().splitlines() if "=" in line and not line.startswith("#"))
        address = values["PUBLIC_WSS_URL"]
        if args.action == "pair":
            result["server"] = address
            result["pairingLink"] = "phoneassistant://pair?" + urlencode({"server": address, "code": result["code"]})
            result["note"] = "Open or paste this private one-time link on the phone, review the server, then tap Connect."
        else:
            url = urlparse(address)
            with socket.create_connection((url.hostname, url.port or 443), timeout=8) as connection:
                with ssl.create_default_context().wrap_socket(connection, server_hostname=url.hostname) as secure:
                    result["tls"] = secure.version()
                    result["certificateExpires"] = secure.getpeercert().get("notAfter")
            result["note"] = "TLS and local control checked; verify the control port is not reachable from another host."
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        print(json.dumps({"ok": False, "error": str(error)})); raise SystemExit(1)
