"""Initialize one Linux server without embedding any personal endpoints or credentials."""
import argparse
import os
from pathlib import Path
import secrets
import ssl
from urllib.parse import urlparse


def main():
    parser = argparse.ArgumentParser(description="Initialize Phone Assistant Docker Compose deployment")
    parser.add_argument("--server", required=True, help="Public WSS address, e.g. wss://phone.example.com:8443/device")
    parser.add_argument("--cert", required=True, type=Path, help="Trusted TLS full chain PEM")
    parser.add_argument("--key", required=True, type=Path, help="Matching TLS private key PEM, same directory")
    parser.add_argument("--control-port", type=int, default=18766)
    args = parser.parse_args()
    url = urlparse(args.server)
    if url.scheme != "wss" or not url.hostname or url.username or url.password or url.query or url.fragment or url.path != "/device":
        parser.error("Use wss://hostname[:port]/device without credentials or query")
    try:
        public_port = url.port or 443
    except ValueError:
        parser.error("Invalid public port")
    if not 1024 <= public_port <= 65535:
        parser.error("Use an explicit unprivileged public port, e.g. :8443")
    if not 1024 <= args.control_port <= 65535 or args.control_port == public_port:
        parser.error("Control port must be 1024..65535 and differ from the public port")
    if any(c.isspace() or c in "#$\"'" for c in args.server):
        parser.error("Invalid characters in server address")
    cert, key = args.cert.expanduser().absolute(), args.key.expanduser().absolute()
    if cert.parent != key.parent or not cert.is_file() or not key.is_file():
        parser.error("Certificate and key must exist in the same directory")
    if any(c in str(cert.parent) + cert.name + key.name for c in ["\n", "\r", "$", "#", " ", "\"", "'"]):
        parser.error("Use a TLS directory without spaces, newlines, # or $ characters")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    root = Path(__file__).resolve().parent
    env = root / ".env"
    if env.exists():
        parser.error("Deployment already initialized; keep existing credentials and edit its .env if needed")
    data = root / "data"
    data.mkdir(mode=0o700, exist_ok=True)
    content = {"CONTROL_TOKEN": secrets.token_urlsafe(48), "PUBLIC_PORT": str(public_port),
               "CONTROL_PORT": str(args.control_port), "TLS_DIRECTORY": str(cert.parent),
               "TLS_CERT_NAME": cert.name, "TLS_KEY_NAME": key.name, "PUBLIC_WSS_URL": args.server}
    fd = os.open(env, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        output.write("".join(f"{k}={v}\n" for k, v in content.items()))
    print("Initialized deployment; controller credential stored locally with mode 0600.")
    print("Start: docker compose -f deploy/compose.yaml up -d --build")
    print("Pair: python3 deploy/manage.py pair")


if __name__ == "__main__":
    main()
