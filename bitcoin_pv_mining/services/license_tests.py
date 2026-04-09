import unittest
from unittest.mock import Mock, patch

from bitcoin_pv_mining.services import license as license_service


class LicenseHeartbeatTests(unittest.TestCase):
    def setUp(self):
        self.state = {
            "license_token": "grant-token",
            "premium_enabled": True,
            "install_id": "test-install",
        }

        def _load_state():
            return dict(self.state)

        def _update_state(mutator):
            state = dict(self.state)
            result = mutator(state)
            self.state = state
            return state, result

        self.load_patch = patch.object(license_service, "load_state", side_effect=_load_state)
        self.update_patch = patch.object(license_service, "update_state", side_effect=_update_state)
        self.load_patch.start()
        self.update_patch.start()
        self.addCleanup(self.load_patch.stop)
        self.addCleanup(self.update_patch.stop)

    def _response(self, payload):
        response = Mock()
        response.headers = {"content-type": "application/json"}
        response.text = str(payload)
        response.json.return_value = payload
        return response

    def test_heartbeat_does_not_disable_premium_before_verify_confirms_it(self):
        response = self._response({
            "ok": False,
            "payload": {
                "token": "rotated-token",
                "expires_at": "2030-01-01T00:00:00Z",
            },
        })

        with patch.object(license_service.requests, "post", return_value=response), \
             patch.object(license_service, "verify_license", return_value=True) as verify_mock:
            license_service.heartbeat_once(addon_version="1.2.3")

        self.assertTrue(self.state["premium_enabled"])
        self.assertEqual(self.state["license_token"], "rotated-token")
        self.assertEqual(self.state["token_expires_at"], "2030-01-01T00:00:00Z")
        self.assertIn("last_heartbeat_at", self.state)
        verify_mock.assert_called_once_with()

    def test_heartbeat_without_ok_field_keeps_existing_premium_state(self):
        response = self._response({
            "payload": {
                "token": "rotated-token",
                "expires_at": "2031-01-01T00:00:00Z",
            },
        })

        with patch.object(license_service.requests, "post", return_value=response), \
             patch.object(license_service, "verify_license") as verify_mock:
            license_service.heartbeat_once(addon_version="1.2.3")

        self.assertTrue(self.state["premium_enabled"])
        self.assertEqual(self.state["license_token"], "rotated-token")
        self.assertEqual(self.state["token_expires_at"], "2031-01-01T00:00:00Z")
        verify_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
