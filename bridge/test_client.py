import contextlib
import io
import json
import subprocess
import unittest
from unittest.mock import patch
import phone_client


class ClientTests(unittest.TestCase):
    def test_degraded_snapshot_is_never_actionable(self):
        with patch.object(phone_client, "call", return_value={"result": {"degraded": True, "snapshotAgeMs": 5000}}):
            with self.assertRaises(RuntimeError): phone_client.state()

    def test_node_coordinates_use_device_bounds(self):
        tree = {"isVisibleToUser": True, "isEnabled": True, "isClickable": True, "text": "确定",
                "boundsInScreen": {"left": 20, "top": 40, "right": 100, "bottom": 200}, "children": []}
        node = phone_client.nodes(tree)[0]
        self.assertEqual((node["x"], node["y"]), (60, 120))
        self.assertEqual(node["text"], "确定")

    def test_invisible_nodes_are_not_actionable(self):
        self.assertEqual(phone_client.nodes({"isVisibleToUser": False, "text": "old", "boundsInScreen": {"left": 0,"top": 0,"right": 10,"bottom": 10}}), [])

    def test_animation_offscreen_nodes_are_filtered(self):
        tree = {"isVisibleToUser": True, "text": "moving", "boundsInScreen": {"left": 1200, "top": 0, "right": 1300, "bottom": 100}}
        self.assertEqual(phone_client.nodes(tree, {"width": 1080, "height": 2376}), [])

    def test_readback_error_does_not_lose_completed_action(self):
        with patch.object(phone_client, "state", side_effect=RuntimeError("private screen")):
            result = phone_client.observe_after({"status": "success", "result": "Tap completed"})
        self.assertEqual(result["status"], "success")
        self.assertIn("Do not replay", result["warning"])

    def test_text_child_beats_duplicate_description_container(self):
        common = {"isVisibleToUser": True, "isEnabled": True}
        tree = {"children": [dict(common, text="电池", boundsInScreen={"left": 100,"top": 100,"right": 300,"bottom": 200}), dict(common, contentDescription="电池", boundsInScreen={"left": 0,"top": 100,"right": 1000,"bottom": 200})]}
        self.assertEqual(phone_client.target({"a11y_tree": tree}, "电池"), (200, 150))

    def test_help_and_empty_command_never_touch_device(self):
        with patch.object(phone_client, "tx") as remote, contextlib.redirect_stdout(io.StringIO()):
            phone_client.main([])
            with self.assertRaises(SystemExit) as exit:
                phone_client.main(["--help"])
            self.assertEqual(exit.exception.code, 0)
            remote.assert_not_called()

    def test_removed_commands_fail_without_device_access(self):
        with patch.object(phone_client, "tx") as remote, contextlib.redirect_stderr(io.StringIO()):
            for command in ["capture", "adb", "keyboard", "devices", "open"]:
                with self.assertRaises(SystemExit) as exit:
                    phone_client.main([command])
                self.assertEqual(exit.exception.code, 2)
            remote.assert_not_called()

    def test_ocr_maps_crop_and_nonuniform_scale(self):
        raw = {"width": 100, "height": 50, "lines": [{"text": "价格18.80", "conf": 1, "x": 10, "y": 5, "w": 20, "h": 10}]}
        meta = {"width": 100, "height": 50, "scaleX": 2, "scaleY": 3, "offsetX": 36, "offsetY": 954}
        line = phone_client.ocr_lines(raw, meta, "价格")[0]
        self.assertEqual((line["x"], line["y"]), (76, 984))

    def test_external_image_ocr_keeps_image_coordinates(self):
        raw = {"width": 100, "height": 50, "lines": [{"text": "sample", "conf": 0.8, "x": 10, "y": 5, "w": 20, "h": 10}]}
        line = phone_client.ocr_lines(raw)[0]
        self.assertEqual((line["x"], line["y"]), (20, 10))

    def test_mismatched_ocr_dimensions_are_rejected(self):
        with self.assertRaises(RuntimeError):
            phone_client.ocr_lines({"width": 10, "height": 10}, {"width": 20, "height": 20})

    def test_duplicate_labels_never_guess(self):
        base = {"isVisibleToUser": True, "isEnabled": True, "isClickable": True, "text": "购买"}
        tree = {"children": [dict(base, boundsInScreen={"left": 0,"top": 0,"right": 100,"bottom": 100}), dict(base, boundsInScreen={"left": 0,"top": 200,"right": 100,"bottom": 300})]}
        with self.assertRaises(RuntimeError):
            phone_client.target({"a11y_tree": tree}, "购买")

    def test_id_target_uses_exact_resource_id(self):
        tree = {"isVisibleToUser": True, "isEnabled": True, "resourceId": "app:id/a", "text": "搜索", "boundsInScreen": {"left": 0,"top": 0,"right": 100,"bottom": 100}}
        self.assertEqual(phone_client.target({"a11y_tree": tree}, "app:id/a", "id"), (50, 50))

    def test_password_text_is_not_returned(self):
        tree = {"isVisibleToUser": True, "isPassword": True, "text": "secret", "boundsInScreen": {"left": 0,"top": 0,"right": 100,"bottom": 100}}
        self.assertEqual(phone_client.nodes(tree)[0]["text"], "")

    def test_readback_transport_timeout_keeps_action_success(self):
        with patch.object(phone_client, "state", side_effect=subprocess.TimeoutExpired("read", 1)):
            result = phone_client.observe_after({"status": "success"})
        self.assertEqual(result["status"], "success")
        self.assertIn("Do not replay", result["warning"])

    def test_ui_limits_are_explicit(self):
        current = {"phone_state": {}, "device_context": {}, "a11y_tree": {}}
        with patch.object(phone_client, "state", return_value=current), patch.object(phone_client, "current_nodes", return_value=[{"text": "a", "desc": "", "id": ""}] * 3), contextlib.redirect_stdout(io.StringIO()) as out:
            phone_client.main(["ui", "--limit", "1"])
        result = json.loads(out.getvalue())["data"]
        self.assertEqual(result["matched"], 3)
        self.assertEqual(result["shown"], 1)
        self.assertTrue(result["truncated"])

    def test_ssh_uses_stdin_not_shell_arguments(self):
        body = {"action": "command", "method": "keyboard/input", "params": {"text": "private text"}}
        with patch.object(phone_client, "load_transport", return_value=("phone-server", "/opt/phone assistant/control.py", "python3", False)), patch.object(phone_client.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, '{"status":"success"}')) as run:
            phone_client.tx(body)
        args, kwargs = run.call_args
        self.assertEqual(args[0][:5], ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8"])
        self.assertNotIn("private text", str(args[0]))
        self.assertEqual(json.loads(kwargs["input"]), body)
        self.assertNotIn("shell", kwargs)

    def test_large_ssh_reply_is_not_truncated(self):
        payload = {"result": "x" * 200000}
        with patch.object(phone_client, "load_transport", return_value=("phone-server", "/opt/control.py", "python3", False)), patch.object(phone_client.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, json.dumps(payload))):
            self.assertEqual(phone_client.tx({"action": "status"}), payload)

    def test_invalid_replies_never_retry(self):
        for output in ["partial{", "[]", '{"status":"error","error":"offline"}']:
            with self.subTest(output=output), patch.object(phone_client, "load_transport", return_value=("phone-server", "/opt/control.py", "python3", False)), patch.object(phone_client.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, output)) as run:
                with self.assertRaises(RuntimeError): phone_client.tx({"action": "status"})
                run.assert_called_once()

    def test_timeout_never_retries_action(self):
        with patch.object(phone_client, "load_transport", return_value=("phone-server", "/opt/control.py", "python3", False)), patch.object(phone_client.subprocess, "run", side_effect=subprocess.TimeoutExpired("ssh", 35)) as run:
            with self.assertRaises(subprocess.TimeoutExpired): phone_client.tx({"action": "command", "method": "tap"})
            run.assert_called_once()

    def test_invalid_ssh_host_and_local_flag_rejected(self):
        for config in [{"sshHost": "-oProxyCommand=bad"}, {"sshHost": "host;bad"}, {"local": "false"}, []]:
            with self.subTest(config=config), patch.dict(phone_client.os.environ, {}, clear=True), patch.object(phone_client.Path, "is_file", return_value=True), patch.object(phone_client.Path, "read_text", return_value=json.dumps(config)):
                with self.assertRaises(RuntimeError): phone_client.load_transport()

    def test_local_transport_is_explicit(self):
        with patch.object(phone_client, "load_transport", return_value=("", "/unused", "python3", True)), patch.object(phone_client.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, '{"online":false}')) as run:
            phone_client.tx({"action": "status"})
        self.assertEqual(run.call_args.args[0][0], phone_client.sys.executable)
        self.assertEqual(run.call_args.args[0][-1], "rpc")

    def test_app_null_observation_is_not_confirmed(self):
        with patch.object(phone_client, "call", return_value={"status": "success"}), patch.object(phone_client, "state", return_value={"phone_state": None}), contextlib.redirect_stdout(io.StringIO()) as output:
            phone_client.main(["app", "com.example.app"])
        self.assertIn("not confirmed", json.loads(output.getvalue())["data"]["warning"])


if __name__ == "__main__": unittest.main(verbosity=2)
