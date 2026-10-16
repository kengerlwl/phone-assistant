"""Attended phone bridge. Public TLS: device/pair only. Control: loopback + token.

No commands are stored or replayed after disconnect. Payloads never enter logs.
AGPL-3.0-or-later; personal companion to the Mobilerun Portal derivative.
"""
import asyncio
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import ssl
import time
import uuid
from aiohttp import web, WSMsgType

ALLOWED = frozenset({"state", "screenshot", "capture", "tap", "swipe", "global", "app", "keyboard/input", "keyboard/clear", "keyboard/key", "version", "time", "packages"})


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Bridge:
    def __init__(self, state_file, control_token):
        self.path = Path(state_file)
        self.control_token = control_token
        self.record = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.ws = None
        self.device_id = None
        self.connected_at = None
        self.pending = {}
        self.busy = False
        self.pairing = None

    def authorized_control(self, request):
        return hmac.compare_digest(request.headers.get("Authorization", ""), "Bearer " + self.control_token)

    def save(self):
        temporary = self.path.with_suffix(".new")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as output:
            json.dump(self.record, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, self.path)

    async def pair_code(self, request):
        if not self.authorized_control(request):
            raise web.HTTPUnauthorized()
        if self.ws is not None and not self.ws.closed:
            raise web.HTTPConflict(text="Disconnect the current phone before pairing")
        code = f"{secrets.randbelow(100000000):08d}"
        self.pairing = {"digest": digest(code), "expires": time.monotonic() + 600, "attempts": 0}
        return web.json_response({"code": code, "expiresIn": 600})

    async def pair(self, request):
        if self.pairing is None or self.pairing["expires"] <= time.monotonic() or self.pairing["attempts"] >= 20:
            raise web.HTTPForbidden(text="Pairing unavailable")
        if self.ws is not None and not self.ws.closed:
            raise web.HTTPConflict(text="Current phone must disconnect first")
        session = self.pairing
        session["attempts"] += 1
        try:
            body = await request.json()
            code, device = body["code"], body["deviceId"]
            valid = isinstance(code, str) and re.fullmatch(r"[0-9]{8}", code) and isinstance(device, str) and re.fullmatch(r"[a-zA-Z0-9-]{8,100}", device)
        except (KeyError, TypeError, ValueError):
            valid = False
        if self.pairing is not session or session["expires"] <= time.monotonic():
            raise web.HTTPForbidden(text="Pairing expired or consumed")
        if not valid or not hmac.compare_digest(digest(code), session["digest"]):
            raise web.HTTPForbidden(text="Invalid pairing")
        token = secrets.token_urlsafe(48)
        self.record = {"deviceId": device, "tokenDigest": digest(token)}
        self.save()
        self.pairing = None
        return web.json_response({"token": token})

    async def device(self, request):
        header = request.headers.get("Authorization", "")
        device = request.headers.get("X-Device-ID", "")
        if not self.record or not header.startswith("Bearer ") or device != self.record.get("deviceId") or not hmac.compare_digest(digest(header[7:]), self.record.get("tokenDigest", "")):
            raise web.HTTPUnauthorized()
        if self.ws is not None and not self.ws.closed:
            raise web.HTTPConflict(text="A device session is already connected")
        ws = web.WebSocketResponse(heartbeat=20, receive_timeout=65, max_msg_size=16 * 1024 * 1024)
        self.ws = ws  # Reserve before prepare yields, so duplicate clients cannot displace it.
        self.device_id = device
        self.connected_at = int(time.time() * 1000)
        try:
            await ws.prepare(request)
            async for message in ws:
                if message.type == WSMsgType.TEXT:
                    try:
                        body = json.loads(message.data)
                        request_id = body.get("id")
                        if not isinstance(request_id, str):
                            continue
                        entry = self.pending.get(request_id)
                        if entry and entry[0] is ws and not entry[1].done():
                            if body.get("status") not in {"success", "error"}:
                                entry[1].set_result({"status": "error", "error": "Invalid device reply"})
                            else:
                                entry[1].set_result(body)
                    except (ValueError, TypeError, AttributeError):
                        continue
                elif message.type in {WSMsgType.ERROR, WSMsgType.CLOSE}:
                    break
        finally:
            for _, (owner, future) in list(self.pending.items()):
                if owner is ws and not future.done():
                    future.set_result({"status": "error", "error": "Device disconnected; outcome unknown, do not replay actions"})
            if self.ws is ws:
                self.ws, self.device_id, self.connected_at = None, None, None
        return ws

    async def status(self, request):
        if not self.authorized_control(request):
            raise web.HTTPUnauthorized()
        return web.json_response({"online": self.ws is not None and not self.ws.closed,
                                  "deviceId": self.device_id, "connectedAt": self.connected_at, "busy": self.busy})

    async def command(self, request):
        if not self.authorized_control(request):
            raise web.HTTPUnauthorized()
        try:
            body = await request.json()
            method, params = body["method"], body.get("params", {})
        except (ValueError, TypeError, KeyError):
            raise web.HTTPBadRequest(text="Invalid request")
        if not isinstance(method, str) or method not in ALLOWED or not isinstance(params, dict):
            raise web.HTTPForbidden(text="Method not enabled")
        ws = self.ws
        if ws is None or ws.closed:
            raise web.HTTPConflict(text="Device offline; no command queued")
        if self.busy:
            raise web.HTTPConflict(text="Device busy; observe before retrying")
        self.busy = True
        request_id = str(uuid.uuid4())
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = (ws, future)
        started = time.monotonic()
        try:
            await ws.send_json({"id": request_id, "method": method, "params": params, "deadline": int(time.time() * 1000) + 12000})
            reply = await asyncio.wait_for(future, 15)
            reply["bridgeElapsedMs"] = round((time.monotonic() - started) * 1000)
            return web.json_response(reply)
        except (asyncio.TimeoutError, ConnectionError, RuntimeError):
            return web.json_response({"status": "error", "error": "Outcome unknown; observe current state before another action", "id": request_id}, status=504)
        finally:
            self.pending.pop(request_id, None)
            self.busy = False

    def apps(self):
        public = web.Application(client_max_size=4096)
        public.add_routes([web.post("/pair", self.pair), web.get("/device", self.device)])
        control = web.Application(client_max_size=65536)
        control.add_routes([web.get("/status", self.status), web.post("/command", self.command), web.post("/pair-code", self.pair_code)])
        return public, control


async def main():
    os.umask(0o077)
    state = os.environ.get("STATE_FILE", "/data/device.json")
    token = os.environ["CONTROL_TOKEN"]
    if len(token) < 32:
        raise RuntimeError("CONTROL_TOKEN must contain at least 32 characters")
    bridge = Bridge(state, token)
    cert, key = os.environ["TLS_CERT"], os.environ["TLS_KEY"]
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.minimum_version = ssl.TLSVersion.TLSv1_2
    tls.load_cert_chain(cert, key)
    public, control = bridge.apps()
    runners = [web.AppRunner(app, access_log=None) for app in (public, control)]
    for runner in runners:
        await runner.setup()
    await web.TCPSite(runners[0], os.environ.get("PUBLIC_BIND", "0.0.0.0"), int(os.environ.get("PUBLIC_PORT", "8443")), ssl_context=tls).start()
    await web.TCPSite(runners[1], "127.0.0.1", int(os.environ.get("CONTROL_PORT", "18766"))).start()
    previous = (os.stat(cert).st_mtime_ns, os.stat(key).st_mtime_ns)
    try:
        while True:
            await asyncio.sleep(300)
            current = (os.stat(cert).st_mtime_ns, os.stat(key).st_mtime_ns)
            if current != previous:
                try:
                    tls.load_cert_chain(cert, key)
                    previous = current
                except ssl.SSLError:
                    print("Certificate reload failed; existing TLS context retained", flush=True)
    finally:
        for runner in runners:
            await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
