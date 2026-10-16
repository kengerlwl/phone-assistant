"""Server-local Phone Assistant API client. Uses stdin for RPC, never prints tokens."""
import argparse
import http.client
import json
import os
from pathlib import Path
import sys


def configuration():
    default = Path(__file__).resolve().parents[1] / "deploy" / ".env"
    if not default.is_file():
        default = Path(__file__).with_name("bridge.env")
    path = Path(os.environ.get("PHONE_BRIDGE_ENV", default))
    values = {}
    if path.is_file():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    token = os.environ.get("CONTROL_TOKEN", values.get("CONTROL_TOKEN", ""))
    if len(token) < 32:
        raise RuntimeError("Controller credential missing; run the server setup first")
    port = int(os.environ.get("CONTROL_PORT", values.get("CONTROL_PORT", "18766")))
    if not 1 <= port <= 65535:
        raise RuntimeError("Invalid control port")
    return token, port


def request(path, body=None):
    token, port = configuration()
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=25)
    try:
        connection.request("POST" if body is not None else "GET", path,
                           json.dumps(body) if body is not None else None,
                           {"Authorization": "Bearer " + token, "Content-Type": "application/json"})
        response = connection.getresponse()
        raw = response.read(20 * 1024 * 1024 + 1)
        if len(raw) > 20 * 1024 * 1024:
            raise RuntimeError("Control reply exceeds size limit")
        if response.status != 200:
            return {"status": "error", "error": raw.decode(errors="replace")[:512], "httpStatus": response.status}
        return json.loads(raw)
    finally:
        connection.close()


def dispatch(body):
    if not isinstance(body, dict):
        raise ValueError("RPC requires an object")
    action = body.get("action")
    if action == "status":
        return request("/status")
    if action == "pair":
        return request("/pair-code", {})
    if action == "command" and isinstance(body.get("params", {}), dict) and isinstance(body.get("method"), str):
        return request("/command", {"method": body["method"], "params": body.get("params", {})})
    raise ValueError("Unknown control action")


def main():
    parser = argparse.ArgumentParser(description="Phone Assistant server-local control")
    parser.add_argument("action", choices=["status", "pair", "rpc"])
    args = parser.parse_args()
    if args.action == "rpc":
        raw = sys.stdin.read(65537)
        if len(raw) > 65536:
            raise ValueError("Request too large")
        body = json.loads(raw)
    else:
        body = {"action": args.action}
    result = dispatch(body)
    print(json.dumps(result, ensure_ascii=False))
    if result.get("status") == "error":
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, RuntimeError) as error:
        print(json.dumps({"status": "error", "error": str(error)}))
        sys.exit(1)
