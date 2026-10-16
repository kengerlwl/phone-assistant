"""Attended phone control through the paired app. No ADB or camera fallback."""
import argparse
import base64
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / ".private" / "client.json"


def load_transport():
    path = Path(os.environ.get("PHONE_ASSISTANT_CONFIG", DEFAULT_CONFIG)).expanduser()
    config = json.loads(path.read_text()) if path.is_file() else {}
    if not isinstance(config, dict) or not isinstance(config.get("local", False), bool):
        raise RuntimeError("Client configuration must be an object with a boolean local flag")
    host = os.environ.get("PHONE_ASSISTANT_SSH_HOST", config.get("sshHost", ""))
    control = os.environ.get("PHONE_ASSISTANT_CONTROL", config.get("controlPath", "/opt/phone-assistant/bridge/control.py"))
    python = config.get("python", "python3")
    if not isinstance(host, str) or (host and not re.fullmatch(r"[A-Za-z0-9_.@:-]+", host)) or host.startswith("-"):
        raise RuntimeError("Invalid SSH host; use an SSH-config alias or user@hostname")
    if not isinstance(control, str) or not control.startswith("/") or not isinstance(python, str):
        raise RuntimeError("Invalid remote control configuration")
    return host, control, python, config.get("local", False)


def tx(body, timeout=35):
    host, control, python, local = load_transport()
    if local:
        command = [sys.executable, str(Path(__file__).with_name("control.py")), "rpc"]
    else:
        if not host:
            raise RuntimeError("Configure PHONE_ASSISTANT_SSH_HOST or .private/client.json first")
        command = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", host,
                   shlex.join([python, control, "rpc"])]
    response = subprocess.run(command, input=json.dumps(body), capture_output=True, text=True, timeout=timeout)
    if len(response.stdout) > 20 * 1024 * 1024:
        raise RuntimeError("Control reply exceeds size limit")
    try:
        result = json.loads(response.stdout)
    except ValueError:
        raise RuntimeError("Invalid control response; check SSH and server status. No action was retried.")
    if not isinstance(result, dict):
        raise RuntimeError("Control response must be an object; no action was retried")
    if response.returncode or result.get("status") == "error":
        raise RuntimeError(result.get("error", "Remote request failed"))
    return result


def call(method, params=None):
    return tx({"action": "command", "method": method, "params": params or {}})


def state():
    value = call("state", {"filter": False})["result"]
    if isinstance(value, str):
        value = json.loads(value)
    if value.get("degraded"):
        raise RuntimeError("Stale accessibility snapshot; do not click cached coordinates")
    return value


def nodes(tree, screen=None):
    found = []

    def visit(node):
        if isinstance(node, list):
            for child in node:
                visit(child)
            return
        if not isinstance(node, dict):
            return
        bounds = node.get("boundsInScreen", {})
        visible = bounds and bounds.get("right", 0) > bounds.get("left", 0) and bounds.get("bottom", 0) > bounds.get("top", 0)
        if visible:
            x = (bounds["left"] + bounds["right"]) // 2
            y = (bounds["top"] + bounds["bottom"]) // 2
            visible = not screen or (0 <= x < screen["width"] and 0 <= y < screen["height"])
        if visible and node.get("isVisibleToUser") and (node.get("text") or node.get("contentDescription") or node.get("isClickable") or node.get("isEditable") or node.get("isScrollable")):
            found.append({
                "text": "" if node.get("isPassword") else node.get("text", ""),
                "desc": node.get("contentDescription", ""), "id": node.get("resourceId", ""),
                "clickable": node.get("isClickable", False), "editable": node.get("isEditable", False),
                "scrollable": node.get("isScrollable", False), "enabled": node.get("isEnabled", False),
                "password": node.get("isPassword", False), "focused": node.get("isFocused", False),
                "x": x, "y": y,
            })
        for child in node.get("children", []):
            visit(child)

    visit(tree)
    return found


def current_nodes(current):
    return nodes(current["a11y_tree"], current.get("device_context", {}).get("screen_bounds"))


def target(current, label, field="text"):
    matches = [n for n in current_nodes(current) if n["enabled"] and
               (n[field] == label or (field == "text" and n["desc"] == label))]
    clickable = [n for n in matches if n["clickable"]]
    exact = [n for n in matches if n[field] == label]
    points = {(n["x"], n["y"]) for n in (clickable or exact or matches)}
    if len(points) != 1:
        raise RuntimeError(f"Expected one visible target, got {len(points)}; observe again")
    return next(iter(points))


def observe_after(result):
    # Keep completed actions distinct from failed readback; never replay the action.
    try:
        result["after"] = state().get("phone_state")
    except (RuntimeError, subprocess.SubprocessError, OSError) as error:
        result["observationError"] = str(error)
        result["warning"] = "Action accepted/completed; readback unavailable. Do not replay it."
    return result


def take_shot(args):
    suffix = ".png" if args.format == "png" else ".jpg"
    folder = ROOT / "output"
    if not args.out:
        folder.mkdir(mode=0o700, exist_ok=True)
    out = Path(args.out) if args.out else folder / ("screen-" + str(time.time_ns()) + suffix)
    out = out.expanduser().resolve()
    if not out.is_relative_to(ROOT) or not out.parent.is_dir():
        raise RuntimeError("Screenshot output must be inside this project and parent must exist")
    if out.exists() or out.with_suffix(out.suffix + ".json").exists():
        raise RuntimeError("Screenshot output already exists; choose a new path")
    params = {"maxEdge": args.max_edge, "format": args.format}
    if args.crop:
        params["crop"] = dict(zip(["x", "y", "width", "height"], args.crop))
    result = call("capture", params)["result"]
    data = base64.b64decode(result.pop("image"), validate=True)
    if len(data) != result["bytes"]:
        raise RuntimeError("Screenshot length mismatch")
    fd = os.open(out, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as image:
        image.write(data)
    result["path"] = str(out)
    result["sha256"] = hashlib.sha256(data).hexdigest()
    result["metadataPath"] = str(out.with_suffix(out.suffix + ".json"))
    fd = os.open(result["metadataPath"], os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as metadata:
        metadata.write(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def image_metadata(path):
    sidecar = path.with_suffix(path.suffix + ".json")
    if not sidecar.is_file():
        return None
    meta = json.loads(sidecar.read_text())
    if hashlib.sha256(path.read_bytes()).hexdigest() != meta.get("sha256"):
        raise RuntimeError("Image metadata does not match this screenshot")
    if any(not isinstance(meta.get(k), (int, float)) or not math.isfinite(meta[k]) for k in ("scaleX", "scaleY", "offsetX", "offsetY")):
        raise RuntimeError("Invalid screenshot coordinate metadata")
    if meta["scaleX"] <= 0 or meta["scaleY"] <= 0 or meta["offsetX"] < 0 or meta["offsetY"] < 0:
        raise RuntimeError("Invalid screenshot coordinate transform")
    return meta


def ocr_lines(raw, meta=None, keyword=""):
    if meta and (raw["width"] != meta["width"] or raw["height"] != meta["height"]):
        raise RuntimeError("OCR image dimensions disagree with screenshot metadata")
    sx, sy = (meta["scaleX"], meta["scaleY"]) if meta else (1, 1)
    ox, oy = (meta["offsetX"], meta["offsetY"]) if meta else (0, 0)
    return [{"text": line["text"], "confidence": line["conf"],
             "x": round(ox + (line["x"] + line["w"] / 2) * sx),
             "y": round(oy + (line["y"] + line["h"] / 2) * sy)}
            for line in raw["lines"] if keyword.lower() in line["text"].lower()]


def run_ocr(args):
    binary = Path(os.environ.get("PHONE_OCR_BINARY", ""))
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise RuntimeError("Configure an executable PHONE_OCR_BINARY before OCR")
    meta = None
    if args.path:
        image = Path(args.path).expanduser().resolve()
        meta = image_metadata(image)
    else:
        meta = take_shot(args)
        image = Path(meta["path"])
    response = subprocess.run([str(binary), str(image), str(args.min_confidence)], capture_output=True, text=True, timeout=60)
    if response.returncode:
        raise RuntimeError("OCR failed; inspect the screenshot instead")
    raw = json.loads(response.stdout)
    lines = ocr_lines(raw, meta, args.filter)
    return {"path": str(image), "coordinateSpace": "device" if meta else "image", "lines": lines,
            "count": len(lines), "capturedAt": meta.get("capturedAt") if meta else None,
            "note": "Coordinates describe this image, not necessarily the current UI; observe again after navigation."}


def numbers(value, count):
    try:
        result = tuple(map(int, value.split(",")))
    except ValueError:
        raise argparse.ArgumentTypeError("Use comma-separated integers")
    if len(result) != count:
        raise argparse.ArgumentTypeError(f"Expected {count} integers")
    return result


def parser():
    result = argparse.ArgumentParser(description="手机助手：只通过手机主动连接的加密通道操作；无参数仅显示帮助。")
    commands = result.add_subparsers(dest="action")
    commands.add_parser("status", help="读取当前连接状态")
    commands.add_parser("pair", help="首次接入或凭据失效时生成一次性配对码")
    commands.add_parser("fg", help="读取前台应用和屏幕信息")
    ui = commands.add_parser("ui", help="读取新鲜控件及设备坐标")
    ui.add_argument("--filter", default="")
    ui.add_argument("--limit", type=int, default=80, help="0 表示全部")
    for action in ("shot", "ocr"):
        image = commands.add_parser(action, help="截取屏幕" if action == "shot" else "读取图片文字并保留坐标映射")
        image.add_argument("--out")
        image.add_argument("--max-edge", type=int, default=1600)
        image.add_argument("--format", choices=["jpeg", "png"], default="jpeg")
        image.add_argument("--crop", type=lambda v: numbers(v, 4), help="设备坐标 x,y,width,height")
        if action == "ocr":
            image.add_argument("--path", help="读取已有图片；无匹配元数据时只返回图片坐标")
            image.add_argument("--filter", default="")
            image.add_argument("--min-confidence", type=float, default=0.3)
    tap = commands.add_parser("tap", help="选择唯一控件或已观察到的设备坐标")
    locator = tap.add_mutually_exclusive_group(required=True)
    for field in ("text", "desc", "id"):
        locator.add_argument("--" + field)
    locator.add_argument("--xy", type=lambda v: numbers(v, 2))
    text = commands.add_parser("text", help="写入当前焦点的非密码输入框，不自动发送")
    text.add_argument("value")
    text.add_argument("--append", action="store_true", help="默认替换，指定后插入/追加")
    swipe = commands.add_parser("swipe", help="按设备坐标滑动")
    swipe.add_argument("--xy", required=True, type=lambda v: numbers(v, 2))
    swipe.add_argument("--to", required=True, type=lambda v: numbers(v, 2))
    scroll = commands.add_parser("scroll", help="按内容方向滚动，down 表示看更下方")
    scroll.add_argument("--dir", required=True, choices=["up", "down", "left", "right"])
    key = commands.add_parser("key", help="执行返回、主页等全局动作")
    key.add_argument("value", choices=["back", "home", "recent", "notifications"])
    app = commands.add_parser("app", help="请求启动应用并回读，不冒称已切到前台")
    app.add_argument("value", help="包名")
    return result


def main(argv=None):
    cli = parser()
    args = cli.parse_args(argv)
    if args.action is None:
        cli.print_help()
        return
    started = time.monotonic()
    if args.action in {"status", "pair"}:
        result = tx({"action": args.action})
    elif args.action in {"fg", "ui"}:
        current = state()
        result = {"phone": current.get("phone_state"), "device": current.get("device_context")}
        if args.action == "ui":
            if args.limit < 0:
                cli.error("--limit must be >= 0")
            items = [n for n in current_nodes(current) if args.filter.lower() in (n["text"] + n["desc"] + n["id"]).lower()]
            shown = items[:args.limit] if args.limit else items
            result.update(nodes=shown, matched=len(items), shown=len(shown), truncated=len(shown) < len(items))
    elif args.action == "shot":
        result = take_shot(args)
    elif args.action == "ocr":
        if not 0 <= args.min_confidence <= 1:
            cli.error("--min-confidence must be between 0 and 1")
        result = run_ocr(args)
    elif args.action == "tap":
        if args.xy:
            x, y = args.xy
        else:
            field = next(name for name in ("text", "desc", "id") if getattr(args, name) is not None)
            x, y = target(state(), getattr(args, field), field)
        result = observe_after(call("tap", {"x": x, "y": y}))
    elif args.action == "text":
        if not args.value:
            cli.error("Text is required")
        focused = [n for n in current_nodes(state()) if n["editable"] and n["focused"]]
        if len(focused) != 1 or focused[0]["password"]:
            raise RuntimeError("Focus one non-password field first")
        result = observe_after(call("keyboard/input", {"base64_text": base64.b64encode(args.value.encode()).decode(), "clear": not args.append}))
    elif args.action in {"swipe", "scroll"}:
        if args.action == "swipe":
            x1, y1 = args.xy
            x2, y2 = args.to
        else:
            bounds = state()["device_context"]["screen_bounds"]
            w, h = bounds["width"], bounds["height"]
            positions = {"down": (0.5, 0.72, 0.5, 0.3), "up": (0.5, 0.3, 0.5, 0.72),
                         "right": (0.75, 0.5, 0.25, 0.5), "left": (0.25, 0.5, 0.75, 0.5)}
            a, b, c, d = positions[args.dir]
            x1, y1, x2, y2 = round(w*a), round(h*b), round(w*c), round(h*d)
        result = observe_after(call("swipe", {"startX": x1, "startY": y1, "endX": x2, "endY": y2, "duration": 350}))
    elif args.action == "key":
        result = observe_after(call("global", {"action": {"back": 1, "home": 2, "recent": 3, "notifications": 4}[args.value]}))
    else:
        result = observe_after(call("app", {"package": args.value}))
        if (result.get("after") or {}).get("packageName") != args.value:
            result["warning"] = "Launch requested but target foreground not confirmed; inspect screen before acting."
    print(json.dumps({"ok": True, "elapsedMs": round((time.monotonic()-started)*1000), "data": result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        sys.exit(1)
