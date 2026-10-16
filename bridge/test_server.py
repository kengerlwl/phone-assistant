import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from aiohttp import ClientSession, WSServerHandshakeError
from aiohttp.test_utils import TestServer
from server import Bridge


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.bridge = Bridge(Path(self.temp.name) / "device.json", "control-test-secret")
        public, control = self.bridge.apps()
        self.public, self.control = TestServer(public), TestServer(control)
        await self.public.start_server()
        await self.control.start_server()
        self.client = ClientSession()
        self.headers = {"Authorization": "Bearer control-test-secret"}

    async def asyncTearDown(self):
        if self.bridge.ws is not None:
            await self.bridge.ws.close()
        await self.client.close()
        await self.public.close()
        await self.control.close()
        for p in Path(self.temp.name).iterdir():
            p.unlink()
        # Do not recursively remove directories; the empty test directory remains.
        self.temp._finalizer.detach()

    async def pair(self):
        response = await self.client.post(self.control.make_url("/pair-code"), headers=self.headers)
        self.assertEqual(response.status, 200)
        code = (await response.json())["code"]
        response = await self.client.post(self.public.make_url("/pair"), json={"code": code, "deviceId": "test-device-001"})
        self.assertEqual(response.status, 200)
        token = (await response.json())["token"]
        return code, token

    async def test_pairing_is_one_time_and_only_hash_is_stored(self):
        code, token = await self.pair()
        self.assertNotIn(token, self.bridge.path.read_text())
        response = await self.client.post(self.public.make_url("/pair"), json={"code": code, "deviceId": "test-device-001"})
        self.assertEqual(response.status, 403)

    async def test_control_is_not_public_and_requires_auth(self):
        self.assertEqual((await self.client.get(self.public.make_url("/status"))).status, 404)
        self.assertEqual((await self.client.get(self.control.make_url("/status"))).status, 401)
        self.assertEqual((await self.client.post(self.control.make_url("/pair-code"))).status, 401)
        self.assertEqual((await self.client.post(self.control.make_url("/command"), headers=self.headers, json={"method": "install"})).status, 403)

    async def test_offline_commands_are_rejected_not_queued(self):
        response = await self.client.post(self.control.make_url("/command"), headers=self.headers, json={"method": "tap", "params": {"x": 1, "y": 2}})
        self.assertEqual(response.status, 409)
        self.assertEqual(len(self.bridge.pending), 0)

    async def test_request_reply_and_duplicate_session_rejection(self):
        _, token = await self.pair()
        headers = {"Authorization": "Bearer " + token, "X-Device-ID": "test-device-001"}
        async with self.client.ws_connect(self.public.make_url("/device"), headers=headers) as ws:
            with self.assertRaises(WSServerHandshakeError):
                await self.client.ws_connect(self.public.make_url("/device"), headers=headers)
            pending = asyncio.create_task(self.client.post(self.control.make_url("/command"), headers=self.headers, json={"method": "state"}))
            request = await asyncio.wait_for(ws.receive_json(), 2)
            self.assertEqual(request["method"], "state")
            self.assertIn("deadline", request)
            await ws.send_json({"id": request["id"], "status": "success", "result": {"visible": True}})
            response = await pending
            self.assertTrue((await response.json())["result"]["visible"])

    async def test_disconnect_releases_pending_and_never_replays(self):
        _, token = await self.pair()
        headers = {"Authorization": "Bearer " + token, "X-Device-ID": "test-device-001"}
        ws = await self.client.ws_connect(self.public.make_url("/device"), headers=headers)
        pending = asyncio.create_task(self.client.post(self.control.make_url("/command"), headers=self.headers, json={"method": "tap", "params": {"x": 1, "y": 2}}))
        await asyncio.wait_for(ws.receive_json(), 2)
        await ws.close()
        response = await pending
        self.assertIn("outcome unknown", (await response.json())["error"])
        self.assertEqual(self.bridge.pending, {})
        self.assertFalse(self.bridge.busy)


if __name__ == "__main__":
    unittest.main(verbosity=2)
