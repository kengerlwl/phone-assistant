import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch, MagicMock
import control

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("deploy_setup", ROOT / "deploy/setup.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class ControlTests(unittest.TestCase):
    def test_rpc_dispatch_keeps_params(self):
        with patch.object(control, "request", return_value={"status": "success"}) as request:
            control.dispatch({"action": "command", "method": "tap", "params": {"x": 2, "y": 3}})
        request.assert_called_once_with("/command", {"method": "tap", "params": {"x": 2, "y": 3}})

    def test_invalid_rpc_never_reaches_network(self):
        with patch.object(control, "request") as request:
            for value in [[], {}, {"action": "delete"}, {"action": "command", "method": "tap", "params": []}]:
                with self.assertRaises(ValueError): control.dispatch(value)
            request.assert_not_called()

    def test_status_and_pair_routes(self):
        with patch.object(control, "request") as request:
            control.dispatch({"action": "status"})
            request.assert_called_with("/status")
            control.dispatch({"action": "pair"})
            request.assert_called_with("/pair-code", {})

    def test_rpc_input_limit(self):
        with patch.object(control.sys, "argv", ["control.py", "rpc"]), patch.object(control.sys, "stdin", io.StringIO("x" * 65537)), patch.object(control, "request") as request:
            with self.assertRaises(ValueError): control.main()
            request.assert_not_called()

    def test_configuration_does_not_accept_short_token(self):
        with patch.dict(os.environ, {"CONTROL_TOKEN": "short"}, clear=True), patch.object(Path, "is_file", return_value=False):
            with self.assertRaises(RuntimeError): control.configuration()

    def test_reply_size_limit_and_connection_closed(self):
        connection = MagicMock()
        connection.getresponse.return_value.read.return_value = b"x" * (20 * 1024 * 1024 + 1)
        with patch.object(control, "configuration", return_value=("t" * 48, 18766)), patch.object(control.http.client, "HTTPConnection", return_value=connection) as factory:
            with self.assertRaises(RuntimeError): control.request("/status")
        factory.assert_called_once_with("127.0.0.1", 18766, timeout=25)
        connection.close.assert_called_once()

    def test_deploy_rejects_unsafe_url_and_port_collision(self):
        for server, port in [("ws://example.com:8443/device", "18766"), ("wss://example.com:18766/device", "18766"), ("wss://example.com:99999/device", "18766"), ("wss://example.com/device", "18766"), ("wss://user@example.com:8443/device", "18766")]:
            with self.subTest(server=server), patch.object(sys, "argv", ["setup.py", "--server", server, "--cert", "missing.pem", "--key", "missing.key", "--control-port", port]), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit): setup.main()

    def test_setup_writes_private_config_and_refuses_overwrite(self):
        folder = Path(tempfile.mkdtemp(prefix="tmp-deploy-", dir=ROOT / "bridge"))
        cert, key = folder / "fullchain.pem", folder / "privkey.pem"
        cert.write_text("test-only certificate placeholder")
        key.write_text("test-only key placeholder")
        argv = ["setup.py", "--server", "wss://phone.example.com:8443/device", "--cert", str(cert), "--key", str(key)]
        try:
            with patch.object(setup, "__file__", str(folder / "setup.py")), patch.object(sys, "argv", argv), patch.object(setup.ssl, "SSLContext") as tls, contextlib.redirect_stdout(io.StringIO()) as output:
                setup.main()
                config = (folder / ".env").read_text()
                token = dict(line.split("=", 1) for line in config.splitlines())["CONTROL_TOKEN"]
                self.assertGreaterEqual(len(token), 32)
                self.assertNotIn(token, output.getvalue())
                self.assertEqual((folder / ".env").stat().st_mode & 0o777, 0o600)
                tls.return_value.load_cert_chain.assert_called_with(cert, key)
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit): setup.main()
                self.assertEqual((folder / ".env").read_text(), config)
        finally:
            for path in [folder / ".env", cert, key]:
                if path.is_file(): path.unlink()
            # Preserve empty test directories; no recursive deletion.


if __name__ == "__main__":
    unittest.main(verbosity=2)
