import unittest
from unittest.mock import patch


class PermissionRequestTests(unittest.TestCase):
    def test_request_helpers_are_noop_off_macos(self):
        from agent import permissions

        with patch.object(permissions, "_DARWIN", False):
            self.assertEqual(permissions.request_accessibility(), "granted")
            self.assertEqual(permissions.request_input_monitoring(), "granted")
            self.assertEqual(permissions.request_microphone_sync(timeout=0.01), "granted")

    def test_input_monitoring_request_maps_iokit_status(self):
        from agent import permissions

        def fake_request(_request_type):
            return 0

        with (
            patch.object(permissions, "_DARWIN", True),
            patch.object(permissions, "activate_app_for_permission_prompt"),
            patch.object(permissions, "_load_iokit_request", return_value=fake_request),
        ):
            self.assertEqual(permissions.request_input_monitoring(), "granted")


if __name__ == "__main__":
    unittest.main()
