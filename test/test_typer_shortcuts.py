import unittest
import plistlib
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from pynput.keyboard import Key

from agent import app_launcher
from agent import macos_window_actions
from agent import typer


class TyperShortcutTests(unittest.TestCase):
    def test_init_loads_custom_shortcuts_from_config(self):
        with patch.object(typer, "register_shortcut") as register:
            typer.init({
                "shortcuts": {
                    "打开设置": "cmd+,",
                    "刷新": ["cmd", "r"],
                }
            })

        register.assert_any_call("打开设置", [Key.cmd, typer.KeyCode.from_char(",")])
        register.assert_any_call("刷新", [Key.cmd, typer.KeyCode.from_char("r")])

    def test_init_loads_app_shortcuts_from_config(self):
        with patch.dict(typer._APP_SHORTCUTS, {}, clear=True):
            typer.init({
                "application_shortcuts": {
                    "com.openai.codex": {
                        "发送": "cmd+enter",
                    },
                },
            })

            self.assertEqual(
                typer._APP_SHORTCUTS["com.openai.codex"]["发送"],
                [Key.cmd, Key.enter],
            )

    def test_init_loads_legacy_experimental_app_shortcuts_from_config(self):
        with patch.dict(typer._APP_SHORTCUTS, {}, clear=True):
            typer.init({
                "experimental_app_shortcuts": {
                    "com.openai.codex": {
                        "发送": "cmd+enter",
                    },
                },
            })

            self.assertEqual(
                typer._APP_SHORTCUTS["com.openai.codex"]["发送"],
                [Key.cmd, Key.enter],
            )

    def test_init_merges_legacy_and_current_app_shortcut_fields_by_action(self):
        with patch.dict(typer._APP_SHORTCUTS, {}, clear=True):
            typer.init({
                "experimental_app_shortcuts": {
                    "com.openai.codex": {
                        "发送": "cmd+enter",
                    },
                },
                "application_shortcuts": {
                    "com.openai.codex": {
                        "新建会话": "cmd+n",
                    },
                },
            })

            self.assertEqual(
                typer._APP_SHORTCUTS["com.openai.codex"],
                {
                    "发送": [Key.cmd, Key.enter],
                    "新建会话": [Key.cmd, typer.KeyCode.from_char("n")],
                },
            )

    def test_send_shortcut_prefers_active_application_shortcut(self):
        app = typer.ActiveApplication("Codex", "com.openai.codex", 42)
        with (
            patch.dict(typer._APP_SHORTCUTS, {
                "com.openai.codex": {"发送": [Key.cmd, Key.enter]},
            }, clear=True),
            patch.object(typer, "current_application", return_value=app),
            patch.object(typer, "_press_keys") as press_keys,
        ):
            self.assertTrue(typer.send_shortcut("发送"))

        press_keys.assert_called_once_with([Key.cmd, Key.enter])

    def test_send_shortcut_does_not_use_builtin_app_preset(self):
        app = typer.ActiveApplication("Feishu", "com.bytedance.macos.feishu", 42)
        with (
            patch.object(typer, "_OS", "Darwin"),
            patch.dict(typer._APP_SHORTCUTS, {}, clear=True),
            patch.object(typer, "current_application", return_value=app),
            patch.object(typer, "_press_keys") as press_keys,
        ):
            self.assertFalse(typer.send_shortcut("发送"))

        press_keys.assert_not_called()

    def test_custom_app_shortcut_overrides_builtin_preset(self):
        app = typer.ActiveApplication("Feishu", "com.bytedance.macos.feishu", 42)
        with (
            patch.object(typer, "_OS", "Darwin"),
            patch.dict(typer._APP_SHORTCUTS, {
                "com.bytedance.macos.feishu": {"发送": [Key.cmd, Key.enter]},
            }, clear=True),
            patch.object(typer, "current_application", return_value=app),
            patch.object(typer, "_press_keys") as press_keys,
        ):
            self.assertTrue(typer.send_shortcut("发送"))

        press_keys.assert_called_once_with([Key.cmd, Key.enter])

    def test_list_shortcuts_includes_active_application_shortcuts(self):
        app = typer.ActiveApplication("Codex", "com.openai.codex", 42)
        with (
            patch.dict(typer._APP_SHORTCUTS, {
                "com.openai.codex": {"发送": [Key.cmd, Key.enter]},
            }, clear=True),
            patch.object(typer, "current_application", return_value=app),
        ):
            self.assertIn("发送", typer.list_shortcuts())

    def test_shortcut_catalog_prefers_application_entries_and_keeps_metadata(self):
        app = typer.ActiveApplication("Codex", "com.openai.codex", 42)
        with (
            patch.dict(typer._APP_SHORTCUTS, {
                "com.openai.codex": {"保存": [Key.cmd, Key.shift, typer.KeyCode.from_char("s")]},
            }, clear=True),
            patch.object(typer, "current_application", return_value=app),
        ):
            catalog = typer.shortcut_catalog()

        save = next(entry for entry in catalog if entry.name == "保存")
        self.assertEqual(save.source, "application")
        self.assertEqual(save.kind, "shortcut")
        self.assertEqual(save.application, "Codex (com.openai.codex)")
        self.assertEqual(save.risk, "normal")
        self.assertEqual([entry.name for entry in catalog].count("保存"), 1)

    def test_shortcut_catalog_marks_high_risk_named_actions(self):
        app = typer.ActiveApplication("Codex", "com.openai.codex", 42)
        with (
            patch.dict(typer._APP_SHORTCUTS, {
                "com.openai.codex": {"发送": [Key.cmd, Key.enter]},
            }, clear=True),
            patch.object(typer, "current_application", return_value=app),
        ):
            catalog = typer.shortcut_catalog()

        send = next(entry for entry in catalog if entry.name == "发送")
        self.assertEqual(send.source, "application")
        self.assertEqual(send.risk, "high")

    def test_universal_core_shortcuts_are_global_without_application_presets(self):
        app = typer.ActiveApplication("Microsoft Word", "com.microsoft.Word", 42)
        with (
            patch.object(typer, "_OS", "Darwin"),
            patch.dict(typer._APP_SHORTCUTS, {}, clear=True),
            patch.object(typer, "current_application", return_value=app),
        ):
            catalog = typer.shortcut_catalog()

        bold = next(entry for entry in catalog if entry.name == "加粗")
        self.assertEqual(bold.source, "global")
        self.assertEqual(bold.application, "")
        self.assertNotIn("插入批注", [entry.name for entry in catalog])

    def test_macos_builtin_presets_are_empty_by_default(self):
        cases = [
            typer.ActiveApplication("Chrome", "com.google.Chrome", 42),
            typer.ActiveApplication("Codex", "com.openai.codex", 42),
            typer.ActiveApplication("微信", "com.tencent.xinwechat", 42),
            typer.ActiveApplication("Microsoft Word", "com.microsoft.Word", 42),
            typer.ActiveApplication("Microsoft Excel", "com.microsoft.Excel", 42),
            typer.ActiveApplication("Microsoft PowerPoint", "com.microsoft.Powerpoint", 42),
            typer.ActiveApplication("WPS Office", "com.kingsoft.wpsoffice.mac", 42),
            typer.ActiveApplication("飞书", "com.bytedance.macos.feishu", 42),
        ]
        for app in cases:
            with self.subTest(app=app.label):
                with (
                    patch.object(typer, "_OS", "Darwin"),
                    patch.dict(typer._APP_SHORTCUTS, {}, clear=True),
                    patch.object(typer, "current_application", return_value=app),
                ):
                    catalog = typer.shortcut_catalog()

                self.assertFalse([
                    entry for entry in catalog
                    if entry.source == "application"
                ])

    def test_send_shortcut_uses_global_formatting_in_feishu(self):
        app = typer.ActiveApplication("飞书", "com.bytedance.macos.feishu", 42)
        with (
            patch.object(typer, "_OS", "Darwin"),
            patch.dict(typer._APP_SHORTCUTS, {}, clear=True),
            patch.object(typer, "current_application", return_value=app),
            patch.object(typer, "_press_keys") as press_keys,
        ):
            self.assertTrue(typer.send_shortcut("加粗"))

        press_keys.assert_called_once_with([Key.cmd, typer.KeyCode.from_char("b")])

    def test_blocked_shortcut_name_is_removed_from_catalog_and_execution(self):
        app = typer.ActiveApplication("飞书", "com.bytedance.macos.feishu", 42)
        with (
            patch.object(typer, "_OS", "Darwin"),
            patch.object(typer, "current_application", return_value=app),
            patch.object(typer, "_BLOCKED_SHORTCUT_NAMES", set()),
            patch.object(typer, "_BLOCKED_SHORTCUT_KEY_SEQUENCES", set()),
            patch.object(typer, "_press_keys") as press_keys,
        ):
            typer.init({"blocked_shortcuts": ["加粗"]})
            self.assertNotIn("加粗", typer.list_shortcuts())
            self.assertFalse(typer.send_shortcut("加粗"))

        press_keys.assert_not_called()

    def test_blocked_shortcut_keys_are_removed_from_catalog_and_execution(self):
        app = typer.ActiveApplication("飞书", "com.bytedance.macos.feishu", 42)
        with (
            patch.object(typer, "_OS", "Darwin"),
            patch.object(typer, "current_application", return_value=app),
            patch.object(typer, "_BLOCKED_SHORTCUT_NAMES", set()),
            patch.object(typer, "_BLOCKED_SHORTCUT_KEY_SEQUENCES", set()),
            patch.object(typer, "_press_keys") as press_keys,
        ):
            typer.init({"blocked_shortcut_keys": ["cmd+shift+z"]})
            self.assertNotIn("重做", typer.list_shortcuts())
            self.assertFalse(typer.send_shortcut("重做"))

        press_keys.assert_not_called()

    def test_macos_builtin_app_preset_is_not_used_on_other_platforms(self):
        app = typer.ActiveApplication("Microsoft Word", "com.microsoft.Word", 42)
        with (
            patch.object(typer, "_OS", "Windows"),
            patch.dict(typer._APP_SHORTCUTS, {}, clear=True),
            patch.object(typer, "current_application", return_value=app),
        ):
            application_names = {
                entry.name for entry in typer.shortcut_catalog()
                if entry.source == "application"
            }
            self.assertNotIn("加粗", application_names)

    def test_shortcut_policy_blocks_missing_shortcut_before_adapter_execution(self):
        app = typer.ActiveApplication("Codex", "com.openai.codex", 42)
        with (
            patch.dict(typer._APP_SHORTCUTS, {}, clear=True),
            patch.object(typer, "current_application", return_value=app),
            patch.object(typer, "_press_keys") as press_keys,
        ):
            decision = typer.shortcut_policy_for_invocation("provider invented")
            result = typer.send_shortcut("provider invented")

        self.assertEqual(
            decision,
            typer.ShortcutPolicyDecision.missing("provider invented"),
        )
        self.assertFalse(result)
        press_keys.assert_not_called()

    def test_shortcut_policy_blocks_high_risk_shortcut_in_atomic_stack(self):
        app = typer.ActiveApplication("Codex", "com.openai.codex", 42)
        with (
            patch.dict(typer._APP_SHORTCUTS, {
                "com.openai.codex": {"发送": [Key.cmd, Key.enter]},
            }, clear=True),
            patch.object(typer, "current_application", return_value=app),
        ):
            decision = typer.shortcut_policy_for_invocation("发送", in_atomic_stack=True)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "high_risk_requires_confirmation")
        self.assertEqual(decision.risk, "high")

    def test_open_settings_is_global_system_action(self):
        with patch.object(typer, "_run_system_action", return_value=True) as run:
            self.assertTrue(typer.send_shortcut("打开系统设置"))

        run.assert_called_once_with("open_system_settings")

    def test_macos_window_actions_are_system_actions_without_key_chords(self):
        with (
            patch.object(typer, "_OS", "Darwin"),
            patch.object(typer, "current_application", return_value=typer.ActiveApplication()),
            patch.object(typer, "_run_system_action", return_value=True) as run,
            patch.object(typer, "_press_keys") as press_keys,
        ):
            names = set(typer.list_shortcuts())
            self.assertIn("窗口左半屏", names)
            self.assertIn("窗口右半屏", names)
            self.assertIn("窗口最大化", names)
            self.assertIn("窗口居中", names)
            left_half = next(entry for entry in typer.shortcut_catalog() if entry.name == "窗口左半屏")
            self.assertEqual(left_half.kind, "system_window_action")
            self.assertTrue(typer.send_shortcut("窗口左半屏"))

        run.assert_called_once_with("macos_window_left_half")
        press_keys.assert_not_called()

    def test_macos_window_actions_are_not_exposed_on_other_platforms(self):
        with (
            patch.object(typer, "_OS", "Windows"),
            patch.object(typer, "current_application", return_value=typer.ActiveApplication()),
        ):
            self.assertNotIn("窗口左半屏", typer.list_shortcuts())

    def test_macos_window_target_rects_keep_slice_small_and_predictable(self):
        screen = macos_window_actions.MacWindowRect(0, 24, 1440, 876)
        current = macos_window_actions.MacWindowRect(200, 120, 800, 600)

        self.assertEqual(
            macos_window_actions.target_window_rect("left_half", current, screen),
            macos_window_actions.MacWindowRect(0, 24, 720, 876),
        )
        self.assertEqual(
            macos_window_actions.target_window_rect("right_half", current, screen),
            macos_window_actions.MacWindowRect(720, 24, 720, 876),
        )
        self.assertEqual(
            macos_window_actions.target_window_rect("maximize", current, screen),
            macos_window_actions.MacWindowRect(0, 24, 1440, 876),
        )
        self.assertEqual(
            macos_window_actions.target_window_rect("center", current, screen),
            macos_window_actions.MacWindowRect(320, 162, 800, 600),
        )

    def test_macos_window_action_sets_accessibility_frame(self):
        window = object()
        current = macos_window_actions.MacWindowRect(200, 120, 800, 600)
        screen = macos_window_actions.MacWindowRect(0, 24, 1440, 876)
        with (
            patch.object(typer, "_OS", "Darwin"),
            patch.object(macos_window_actions, "frontmost_window", return_value=window),
            patch.object(macos_window_actions, "is_fullscreen_window", return_value=False),
            patch.object(macos_window_actions, "window_rect", return_value=current),
            patch.object(macos_window_actions, "screen_for_window", return_value=screen),
            patch.object(macos_window_actions, "set_window_rect", return_value=True) as set_rect,
        ):
            self.assertTrue(typer._run_macos_window_action("right_half"))

        set_rect.assert_called_once_with(
            window,
            macos_window_actions.MacWindowRect(720, 24, 720, 876),
            typer.ApplicationServices,
            current_rect=current,
        )

    def test_macos_window_action_exits_fullscreen_before_setting_frame(self):
        window = object()
        current = macos_window_actions.MacWindowRect(200, 120, 800, 600)
        screen = macos_window_actions.MacWindowRect(0, 24, 1440, 876)
        fullscreen_checks = [True, False]

        class AX:
            @staticmethod
            def AXUIElementSetAttributeValue(_window, _attr, _value):
                return 0

        with (
            patch.object(macos_window_actions, "frontmost_window", return_value=window),
            patch.object(
                macos_window_actions,
                "is_fullscreen_window",
                side_effect=lambda *_args: fullscreen_checks.pop(0) if fullscreen_checks else False,
            ),
            patch.object(macos_window_actions, "window_rect", return_value=current),
            patch.object(macos_window_actions, "screen_for_window", return_value=screen),
            patch.object(macos_window_actions, "set_window_rect", return_value=True) as set_rect,
        ):
            self.assertTrue(
                macos_window_actions.run_window_action(
                    "left_half",
                    typer.ActiveApplication("Notes", "com.apple.Notes", 42),
                    AX,
                    MagicMock(),
                )
            )

        set_rect.assert_called_once_with(
            window,
            macos_window_actions.MacWindowRect(0, 24, 720, 876),
            AX,
            current_rect=current,
        )

    def test_macos_window_action_reacquires_window_after_fullscreen_exit(self):
        fullscreen_window = object()
        regular_window = object()
        current = macos_window_actions.MacWindowRect(200, 120, 800, 600)
        screen = macos_window_actions.MacWindowRect(0, 24, 1440, 876)

        class AX:
            @staticmethod
            def AXUIElementSetAttributeValue(_window, _attr, _value):
                return 0

        with (
            patch.object(
                macos_window_actions,
                "frontmost_window",
                side_effect=[fullscreen_window, regular_window],
            ) as frontmost,
            patch.object(
                macos_window_actions,
                "is_fullscreen_window",
                side_effect=lambda window, _ax: window is fullscreen_window,
            ),
            patch.object(macos_window_actions, "window_rect", return_value=current) as window_rect,
            patch.object(macos_window_actions, "screen_for_window", return_value=screen),
            patch.object(macos_window_actions, "set_window_rect", return_value=True) as set_rect,
        ):
            self.assertTrue(
                macos_window_actions.run_window_action(
                    "left_half",
                    typer.ActiveApplication("Notes", "com.apple.Notes", 42),
                    AX,
                    MagicMock(),
                )
            )

        self.assertEqual(frontmost.call_count, 2)
        window_rect.assert_called_once_with(regular_window, AX)
        set_rect.assert_called_once_with(
            regular_window,
            macos_window_actions.MacWindowRect(0, 24, 720, 876),
            AX,
            current_rect=current,
        )

    def test_macos_window_action_stops_when_fullscreen_exit_fails(self):
        window = object()

        class AX:
            @staticmethod
            def AXUIElementSetAttributeValue(_window, _attr, _value):
                return -25200

        with (
            patch.object(macos_window_actions, "frontmost_window", return_value=window),
            patch.object(macos_window_actions, "is_fullscreen_window", return_value=True),
            patch.object(macos_window_actions, "window_rect") as window_rect,
            patch.object(macos_window_actions, "set_window_rect") as set_rect,
        ):
            self.assertFalse(
                macos_window_actions.run_window_action(
                    "left_half",
                    typer.ActiveApplication("Notes", "com.apple.Notes", 42),
                    AX,
                    MagicMock(),
                )
            )

        window_rect.assert_not_called()
        set_rect.assert_not_called()

    def test_macos_window_frame_sets_size_before_position(self):
        window = object()
        rect = macos_window_actions.MacWindowRect(0, 24, 720, 876)
        calls = []

        class AX:
            kAXValueCGSizeType = "size"
            kAXValueCGPointType = "point"

            @staticmethod
            def CGSizeMake(width, height):
                return ("size", width, height)

            @staticmethod
            def CGPointMake(x, y):
                return ("point", x, y)

            @staticmethod
            def AXValueCreate(value_type, value):
                return (value_type, value)

            @staticmethod
            def AXValueGetValue(_value, _value_type, _default):
                return False, None

            @staticmethod
            def AXUIElementCopyAttributeValue(_window, _attr, _default):
                return 1, None

            @staticmethod
            def AXUIElementSetAttributeValue(_window, attr, _value):
                calls.append(attr)
                return 0

        with patch.object(macos_window_actions.time, "sleep"):
            self.assertTrue(
                macos_window_actions.set_window_rect(
                    window,
                    rect,
                    AX,
                    current_rect=macos_window_actions.MacWindowRect(200, 120, 900, 900),
                )
            )
        self.assertEqual(calls[:2], ["AXSize", "AXPosition"])

    def test_macos_window_frame_moves_small_window_then_expands_and_realigned(self):
        window = object()
        rect = macos_window_actions.MacWindowRect(0, 24, 720, 876)
        calls = []

        class AX:
            kAXValueCGSizeType = "size"
            kAXValueCGPointType = "point"

            @staticmethod
            def CGSizeMake(width, height):
                return ("size", width, height)

            @staticmethod
            def CGPointMake(x, y):
                return ("point", x, y)

            @staticmethod
            def AXValueCreate(value_type, value):
                return (value_type, value)

            @staticmethod
            def AXValueGetValue(_value, _value_type, _default):
                return False, None

            @staticmethod
            def AXUIElementCopyAttributeValue(_window, _attr, _default):
                return 1, None

            @staticmethod
            def AXUIElementSetAttributeValue(_window, attr, _value):
                calls.append(attr)
                return 0

        with patch.object(macos_window_actions.time, "sleep"):
            self.assertTrue(
                macos_window_actions.set_window_rect(
                    window,
                    rect,
                    AX,
                    current_rect=macos_window_actions.MacWindowRect(200, 120, 500, 400),
                )
            )

        self.assertEqual(calls[:3], ["AXPosition", "AXSize", "AXPosition"])

    def test_macos_window_frame_shrinks_before_moving_left_edge(self):
        window = object()
        current = macos_window_actions.MacWindowRect(500, 80, 1800, 900)
        screen = macos_window_actions.MacWindowRect(0, 24, 1440, 876)
        calls = []

        class AX:
            kAXValueCGSizeType = "size"
            kAXValueCGPointType = "point"

            @staticmethod
            def CGSizeMake(width, height):
                return ("size", width, height)

            @staticmethod
            def CGPointMake(x, y):
                return ("point", x, y)

            @staticmethod
            def AXValueCreate(value_type, value):
                return (value_type, value)

            @staticmethod
            def AXValueGetValue(_value, _value_type, _default):
                return False, None

            @staticmethod
            def AXUIElementCopyAttributeValue(_window, _attr, _default):
                return 1, None

            @staticmethod
            def AXUIElementSetAttributeValue(_window, attr, value):
                calls.append((attr, value))
                return 0

        def window_rect_probe(*_args):
            if calls:
                return macos_window_actions.MacWindowRect(0, 24, 720, 876)
            return current

        with (
            patch.object(macos_window_actions, "frontmost_window", return_value=window),
            patch.object(macos_window_actions, "is_fullscreen_window", return_value=False),
            patch.object(macos_window_actions, "window_rect", side_effect=window_rect_probe),
            patch.object(macos_window_actions, "screen_for_window", return_value=screen),
            patch.object(macos_window_actions.time, "sleep"),
        ):
            self.assertTrue(
                macos_window_actions.run_window_action(
                    "left_half",
                    typer.ActiveApplication("Notes", "com.apple.Notes", 42),
                    AX,
                    MagicMock(),
                )
            )

        self.assertEqual(calls[:2], [
            ("AXSize", ("size", ("size", 720, 876))),
            ("AXPosition", ("point", ("point", 0, 24))),
        ])

    def test_macos_window_frame_keeps_size_before_position_when_position_fails(self):
        window = object()
        rect = macos_window_actions.MacWindowRect(0, 24, 720, 876)
        calls = []

        class AX:
            kAXValueCGSizeType = "size"
            kAXValueCGPointType = "point"

            @staticmethod
            def CGSizeMake(width, height):
                return ("size", width, height)

            @staticmethod
            def CGPointMake(x, y):
                return ("point", x, y)

            @staticmethod
            def AXValueCreate(value_type, value):
                return (value_type, value)

            @staticmethod
            def AXValueGetValue(_value, _value_type, _default):
                return False, None

            @staticmethod
            def AXUIElementCopyAttributeValue(_window, _attr, _default):
                return 1, None

            @staticmethod
            def AXUIElementSetAttributeValue(_window, attr, _value):
                calls.append(attr)
                if calls == ["AXSize", "AXPosition"]:
                    return -25200
                return 0

        with patch.object(macos_window_actions.time, "sleep"):
            self.assertTrue(
                macos_window_actions.set_window_rect(
                    window,
                    rect,
                    AX,
                    current_rect=macos_window_actions.MacWindowRect(200, 120, 900, 900),
                )
            )
        self.assertEqual(calls[:2], ["AXSize", "AXPosition"])

    def test_macos_window_frame_reapplies_when_readback_is_not_target(self):
        window = object()
        rect = macos_window_actions.MacWindowRect(0, 24, 720, 876)
        reads = [
            macos_window_actions.MacWindowRect(-1200, 24, 1800, 876),
            macos_window_actions.MacWindowRect(0, 24, 720, 876),
        ]
        calls = []

        class AX:
            kAXValueCGSizeType = "size"
            kAXValueCGPointType = "point"

            @staticmethod
            def CGSizeMake(width, height):
                return ("size", width, height)

            @staticmethod
            def CGPointMake(x, y):
                return ("point", x, y)

            @staticmethod
            def AXValueCreate(value_type, value):
                return (value_type, value)

            @staticmethod
            def AXUIElementSetAttributeValue(_window, attr, _value):
                calls.append(attr)
                return 0

        with (
            patch.object(macos_window_actions, "window_rect", side_effect=lambda *_args: reads.pop(0)),
            patch.object(macos_window_actions.time, "sleep"),
        ):
            self.assertTrue(
                macos_window_actions.set_window_rect(
                    window,
                    rect,
                    AX,
                    current_rect=macos_window_actions.MacWindowRect(200, 120, 900, 900),
                )
            )

        self.assertEqual(calls, ["AXSize", "AXPosition", "AXSize", "AXPosition"])

    def test_macos_window_frame_accepts_app_constrained_half_screen(self):
        target = macos_window_actions.MacWindowRect(745, -1440, 1280, 1440)
        current = macos_window_actions.MacWindowRect(745, -1410, 1280, 1296)

        self.assertTrue(macos_window_actions.rect_satisfies_window_action(current, target))

    def test_macos_window_rect_reads_pyobjc_axvalue_return_tuple(self):
        position = typer.ApplicationServices.AXValueCreate(
            typer.ApplicationServices.kAXValueCGPointType,
            typer.ApplicationServices.CGPointMake(12, 34),
        )
        size = typer.ApplicationServices.AXValueCreate(
            typer.ApplicationServices.kAXValueCGSizeType,
            typer.ApplicationServices.CGSizeMake(640, 480),
        )

        def copy_attr(_window, attr, _default):
            if attr == "AXPosition":
                return 0, position
            if attr == "AXSize":
                return 0, size
            return 1, None

        with (
            patch.object(typer, "_OS", "Darwin"),
            patch.object(
                typer.ApplicationServices,
                "AXUIElementCopyAttributeValue",
                side_effect=copy_attr,
            ),
        ):
            rect = macos_window_actions.window_rect(object(), typer.ApplicationServices)

        self.assertEqual(rect, macos_window_actions.MacWindowRect(12, 34, 640, 480))

    def test_macos_visible_screens_convert_from_main_screen_top(self):
        class Point:
            def __init__(self, x, y):
                self.x = x
                self.y = y

        class Size:
            def __init__(self, width, height):
                self.width = width
                self.height = height

        class Rect:
            def __init__(self, x, y, width, height):
                self.origin = Point(x, y)
                self.size = Size(width, height)

        class Screen:
            def __init__(self, frame, visible):
                self._frame = frame
                self._visible = visible

            def frame(self):
                return self._frame

            def visibleFrame(self):
                return self._visible

        main = Screen(Rect(0, 0, 1512, 982), Rect(0, 53, 1512, 896))
        above = Screen(Rect(745, 982, 2560, 1440), Rect(745, 982, 2560, 1440))
        left_above = Screen(Rect(-1815, 982, 2560, 1440), Rect(-1815, 982, 2560, 1440))

        class Screens:
            @staticmethod
            def screens():
                return [main, above, left_above]

            @staticmethod
            def mainScreen():
                return main

        self.assertEqual(
            macos_window_actions.visible_screens(Screens),
            [
                macos_window_actions.MacWindowRect(0, 33, 1512, 896),
                macos_window_actions.MacWindowRect(745, -1440, 2560, 1440),
                macos_window_actions.MacWindowRect(-1815, -1440, 2560, 1440),
            ],
        )

    def test_macos_visible_screens_ignore_dynamic_main_screen_when_converting(self):
        class Point:
            def __init__(self, x, y):
                self.x = x
                self.y = y

        class Size:
            def __init__(self, width, height):
                self.width = width
                self.height = height

        class Rect:
            def __init__(self, x, y, width, height):
                self.origin = Point(x, y)
                self.size = Size(width, height)

        class Screen:
            def __init__(self, frame, visible):
                self._frame = frame
                self._visible = visible

            def frame(self):
                return self._frame

            def visibleFrame(self):
                return self._visible

        primary = Screen(Rect(0, 0, 1512, 982), Rect(0, 53, 1512, 896))
        upper = Screen(Rect(745, 982, 2560, 1440), Rect(745, 982, 2560, 1440))

        class Screens:
            @staticmethod
            def screens():
                return [primary, upper]

            @staticmethod
            def mainScreen():
                return upper

        self.assertEqual(
            macos_window_actions.visible_screens(Screens)[0],
            macos_window_actions.MacWindowRect(0, 33, 1512, 896),
        )

    def test_builtin_open_app_actions_cover_current_launch_slice(self):
        with (
            patch.object(typer, "_OS", "Darwin"),
            patch.object(typer, "current_application", return_value=typer.ActiveApplication()),
        ):
            names = set(typer.list_shortcuts())

        self.assertIn("打开飞书", names)
        self.assertIn("打开Word", names)
        self.assertIn("打开Excel", names)
        self.assertIn("打开PowerPoint", names)
        self.assertIn("打开WPS", names)
        self.assertIn("打开谷歌浏览器", names)
        self.assertIn("打开Chrome", names)
        feishu = next(entry for entry in typer.shortcut_catalog() if entry.name == "打开飞书")
        self.assertEqual(feishu.kind, "app_launch")

    def test_macos_discovers_installed_app_launch_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "Obsidian.app"
            contents = app / "Contents"
            contents.mkdir(parents=True)
            (contents / "Info.plist").write_bytes(plistlib.dumps({
                "CFBundleIdentifier": "md.obsidian",
                "CFBundleName": "Obsidian",
            }))

            with (
                patch.object(typer, "_OS", "Darwin"),
                patch.object(app_launcher, "MACOS_APP_SEARCH_DIRS", (tmp,)),
                patch.object(app_launcher, "DYNAMIC_APP_LAUNCH_CACHE", None),
                patch.object(typer, "current_application", return_value=typer.ActiveApplication()),
            ):
                self.assertIn("打开Obsidian", typer.list_shortcuts())

    def test_macos_discovered_app_launches_can_use_common_chinese_aliases(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "NeteaseMusic.app"
            contents = app / "Contents"
            contents.mkdir(parents=True)
            (contents / "Info.plist").write_bytes(plistlib.dumps({
                "CFBundleIdentifier": "com.netease.163music",
                "CFBundleName": "NeteaseMusic",
            }))

            with (
                patch.object(typer, "_OS", "Darwin"),
                patch.object(app_launcher, "MACOS_APP_SEARCH_DIRS", (tmp,)),
                patch.object(app_launcher, "DYNAMIC_APP_LAUNCH_CACHE", None),
                patch.object(typer, "current_application", return_value=typer.ActiveApplication()),
            ):
                names = set(typer.list_shortcuts())

        self.assertIn("打开网易云音乐", names)
        self.assertIn("打开网易云", names)

    def test_macos_discovered_terminal_can_use_chinese_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "Terminal.app"
            contents = app / "Contents"
            contents.mkdir(parents=True)
            (contents / "Info.plist").write_bytes(plistlib.dumps({
                "CFBundleIdentifier": "com.apple.Terminal",
                "CFBundleName": "Terminal",
            }))

            with (
                patch.object(typer, "_OS", "Darwin"),
                patch.object(app_launcher, "MACOS_APP_SEARCH_DIRS", (tmp,)),
                patch.object(app_launcher, "DYNAMIC_APP_LAUNCH_CACHE", None),
                patch.object(typer, "current_application", return_value=typer.ActiveApplication()),
            ):
                self.assertIn("打开终端", typer.list_shortcuts())

    def test_macos_discovered_stocks_app_has_chinese_aliases(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "Stocks.app"
            contents = app / "Contents"
            contents.mkdir(parents=True)
            (contents / "Info.plist").write_bytes(plistlib.dumps({
                "CFBundleIdentifier": "com.apple.stocks",
                "CFBundleName": "Stocks",
            }))

            with (
                patch.object(typer, "_OS", "Darwin"),
                patch.object(app_launcher, "MACOS_APP_SEARCH_DIRS", (tmp,)),
                patch.object(app_launcher, "DYNAMIC_APP_LAUNCH_CACHE", None),
                patch.object(typer, "current_application", return_value=typer.ActiveApplication()),
            ):
                names = set(typer.list_shortcuts())

        self.assertIn("打开股市", names)
        self.assertIn("打开股票", names)

    def test_send_shortcut_opens_builtin_macos_application_by_bundle_id(self):
        with (
            patch.object(typer, "_OS", "Darwin"),
            patch.object(typer, "current_application", return_value=typer.ActiveApplication()),
            patch.object(app_launcher.subprocess, "Popen") as popen,
        ):
            self.assertTrue(typer.send_shortcut("打开飞书"))

        popen.assert_called_once_with(["open", "-b", "com.bytedance.macos.feishu"])

    def test_send_shortcut_opens_builtin_chrome_application_by_bundle_id(self):
        with (
            patch.object(typer, "_OS", "Darwin"),
            patch.object(typer, "current_application", return_value=typer.ActiveApplication()),
            patch.object(app_launcher.subprocess, "Popen") as popen,
        ):
            self.assertTrue(typer.send_shortcut("打开谷歌浏览器"))

        popen.assert_called_once_with(["open", "-b", "com.google.Chrome"])

    def test_send_shortcut_opens_discovered_macos_application_by_bundle_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "Obsidian.app"
            contents = app / "Contents"
            contents.mkdir(parents=True)
            (contents / "Info.plist").write_bytes(plistlib.dumps({
                "CFBundleIdentifier": "md.obsidian",
                "CFBundleName": "Obsidian",
            }))

            with (
                patch.object(typer, "_OS", "Darwin"),
                patch.object(app_launcher, "MACOS_APP_SEARCH_DIRS", (tmp,)),
                patch.object(app_launcher, "DYNAMIC_APP_LAUNCH_CACHE", None),
                patch.object(typer, "current_application", return_value=typer.ActiveApplication()),
                patch.object(app_launcher.subprocess, "Popen") as popen,
            ):
                self.assertTrue(typer.send_shortcut("打开Obsidian"))

        popen.assert_called_once_with(["open", "-b", "md.obsidian"])

    def test_send_shortcut_opens_discovered_app_case_insensitively(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp) / "Stocks.app"
            contents = app / "Contents"
            contents.mkdir(parents=True)
            (contents / "Info.plist").write_bytes(plistlib.dumps({
                "CFBundleIdentifier": "com.apple.stocks",
                "CFBundleName": "Stocks",
            }))

            with (
                patch.object(typer, "_OS", "Darwin"),
                patch.object(app_launcher, "MACOS_APP_SEARCH_DIRS", (tmp,)),
                patch.object(app_launcher, "DYNAMIC_APP_LAUNCH_CACHE", None),
                patch.object(typer, "current_application", return_value=typer.ActiveApplication()),
                patch.object(app_launcher.subprocess, "Popen") as popen,
            ):
                self.assertTrue(typer.send_shortcut("打开stocks"))

        popen.assert_called_once_with(["open", "-b", "com.apple.stocks"])

    def test_init_loads_custom_app_launch_actions_from_config(self):
        with (
            patch.object(typer, "_OS", "Darwin"),
            patch.dict(app_launcher.CUSTOM_APP_LAUNCHES, {}, clear=True),
            patch.object(typer, "current_application", return_value=typer.ActiveApplication()),
            patch.object(app_launcher.subprocess, "Popen") as popen,
        ):
            typer.init({
                "app_launches": {
                    "打开Obsidian": {
                        "macos_bundle_id": "md.obsidian",
                        "macos_name": "Obsidian",
                    },
                },
            })

            self.assertIn("打开Obsidian", typer.list_shortcuts())
            self.assertTrue(typer.send_shortcut("打开Obsidian"))

        popen.assert_called_once_with(["open", "-b", "md.obsidian"])

    def test_builtin_shortcuts_include_system_actions(self):
        self.assertIn("打开系统设置", typer.list_shortcuts())
        self.assertNotIn("打开设置", typer.list_shortcuts())

    def test_global_shortcuts_are_limited_to_common_keyboard_actions(self):
        with patch.object(typer, "current_application", return_value=typer.ActiveApplication()):
            names = set(typer.list_shortcuts())

        self.assertIn("保存", names)
        self.assertIn("重做", names)
        self.assertIn("加粗", names)
        self.assertIn("斜体", names)
        self.assertIn("下划线", names)
        self.assertIn("查找", names)
        self.assertNotIn("居中", names)
        self.assertNotIn("替换", names)
        self.assertNotIn("截图", names)
        self.assertNotIn("新标签", names)
        self.assertNotIn("关闭标签", names)

    def test_macos_clip_method_types_via_clipboard(self):
        with (
            patch.object(typer, "_OS", "Darwin"),
            patch.object(typer, "_use_clipboard_mode", True),
            patch.object(typer, "replace_selection") as replace_selection,
            patch.object(typer, "_type_via_quartz") as type_via_quartz,
        ):
            typer.type_text("hello")

        replace_selection.assert_called_once_with("hello")
        type_via_quartz.assert_not_called()

    def test_macos_focus_probe_blocks_insertion_when_accessibility_is_uncertain(self):
        class Workspace:
            @staticmethod
            def sharedWorkspace():
                return Workspace()

            def frontmostApplication(self):
                app = MagicMock()
                app.processIdentifier.return_value = 42
                return app

        class AX:
            @staticmethod
            def AXUIElementCreateApplication(pid):
                return object()

            @staticmethod
            def AXUIElementCopyAttributeValue(elem, attr, default):
                return 1, None

        with (
            patch.object(typer, "_OS", "Darwin"),
            patch.object(typer, "NSWorkspace", Workspace),
            patch.object(typer, "ApplicationServices", AX),
        ):
            self.assertFalse(typer.has_focused_text_input())

    def test_macos_focus_probe_allows_settable_text_focus(self):
        class Workspace:
            @staticmethod
            def sharedWorkspace():
                return Workspace()

            def frontmostApplication(self):
                app = MagicMock()
                app.processIdentifier.return_value = 42
                app.localizedName.return_value = "TextEdit"
                app.bundleIdentifier.return_value = "com.apple.TextEdit"
                return app

        class AX:
            @staticmethod
            def AXUIElementCreateApplication(pid):
                return object()

            @staticmethod
            def AXUIElementCopyAttributeValue(elem, attr, default):
                values = {
                    "AXFocusedUIElement": object(),
                    "AXRole": "AXTextArea",
                }
                return 0, values.get(attr)

            @staticmethod
            def AXUIElementIsAttributeSettable(elem, attr, default):
                return 0, attr in {"AXValue", "AXSelectedTextRange"}

        with (
            patch.object(typer, "_OS", "Darwin"),
            patch.object(typer, "NSWorkspace", Workspace),
            patch.object(typer, "ApplicationServices", AX),
        ):
            self.assertTrue(typer.has_focused_text_input())

    def test_macos_focus_probe_blocks_feishu_without_focused_element(self):
        class Workspace:
            @staticmethod
            def sharedWorkspace():
                return Workspace()

            def frontmostApplication(self):
                app = MagicMock()
                app.processIdentifier.return_value = 42
                app.localizedName.return_value = "飞书"
                app.bundleIdentifier.return_value = "com.bytedance.lark"
                return app

        class AX:
            @staticmethod
            def AXUIElementCreateApplication(pid):
                return object()

            @staticmethod
            def AXUIElementCopyAttributeValue(elem, attr, default):
                return -25212, None

        with (
            patch.object(typer, "_OS", "Darwin"),
            patch.object(typer, "NSWorkspace", Workspace),
            patch.object(typer, "ApplicationServices", AX),
        ):
            self.assertFalse(typer.has_focused_text_input())

    def test_macos_clip_mode_allows_uncertain_non_desktop_frontmost_app(self):
        class Workspace:
            @staticmethod
            def sharedWorkspace():
                return Workspace()

            def frontmostApplication(self):
                app = MagicMock()
                app.processIdentifier.return_value = 42
                app.localizedName.return_value = "微信"
                app.bundleIdentifier.return_value = "com.tencent.xinWeChat"
                return app

        class AX:
            @staticmethod
            def AXUIElementCreateApplication(pid):
                return object()

            @staticmethod
            def AXUIElementCopyAttributeValue(elem, attr, default):
                return -25212, None

        with (
            patch.object(typer, "_OS", "Darwin"),
            patch.object(typer, "_use_clipboard_mode", True),
            patch.object(typer, "NSWorkspace", Workspace),
            patch.object(typer, "ApplicationServices", AX),
        ):
            self.assertTrue(typer.has_focused_text_input())

    def test_macos_clip_mode_still_blocks_finder_desktop(self):
        class Workspace:
            @staticmethod
            def sharedWorkspace():
                return Workspace()

            def frontmostApplication(self):
                app = MagicMock()
                app.processIdentifier.return_value = 42
                app.localizedName.return_value = "访达"
                app.bundleIdentifier.return_value = "com.apple.finder"
                return app

        class AX:
            @staticmethod
            def AXUIElementCreateApplication(pid):
                return object()

            @staticmethod
            def AXUIElementCopyAttributeValue(elem, attr, default):
                values = {
                    "AXFocusedUIElement": object(),
                    "AXRole": "AXGroup",
                    "AXSubrole": "",
                    "AXDescription": "桌面",
                }
                return 0, values.get(attr)

            @staticmethod
            def AXUIElementIsAttributeSettable(elem, attr, default):
                return 0, False

        with (
            patch.object(typer, "_OS", "Darwin"),
            patch.object(typer, "_use_clipboard_mode", True),
            patch.object(typer, "NSWorkspace", Workspace),
            patch.object(typer, "ApplicationServices", AX),
        ):
            self.assertFalse(typer.has_focused_text_input())

    def test_macos_focus_fallback_logs_once_per_frontmost_app(self):
        class Workspace:
            @staticmethod
            def sharedWorkspace():
                return Workspace()

            def frontmostApplication(self):
                app = MagicMock()
                app.processIdentifier.return_value = 42
                app.localizedName.return_value = "Codex"
                app.bundleIdentifier.return_value = "com.openai.codex"
                return app

        class AX:
            @staticmethod
            def AXUIElementCreateApplication(pid):
                return object()

            @staticmethod
            def AXUIElementCopyAttributeValue(elem, attr, default):
                return -25212, None

        with (
            patch.object(typer, "_OS", "Darwin"),
            patch.object(typer, "NSWorkspace", Workspace),
            patch.object(typer, "ApplicationServices", AX),
            patch.object(typer, "_last_focus_fallback_log", None),
            patch("builtins.print") as print_fn,
        ):
            self.assertTrue(typer.has_focused_text_input())
            self.assertTrue(typer.has_focused_text_input())

        print_fn.assert_called_once()

    def test_macos_focus_probe_allows_developer_app_fallback_in_clipboard_mode(self):
        class Workspace:
            @staticmethod
            def sharedWorkspace():
                return Workspace()

            def frontmostApplication(self):
                app = MagicMock()
                app.processIdentifier.return_value = 42
                app.localizedName.return_value = "Codex"
                app.bundleIdentifier.return_value = "com.openai.codex"
                return app

        class AX:
            @staticmethod
            def AXUIElementCreateApplication(pid):
                return object()

            @staticmethod
            def AXUIElementCopyAttributeValue(elem, attr, default):
                return -25212, None

        with (
            patch.object(typer, "_OS", "Darwin"),
            patch.object(typer, "_use_clipboard_mode", True),
            patch.object(typer, "NSWorkspace", Workspace),
            patch.object(typer, "ApplicationServices", AX),
        ):
            self.assertTrue(typer.has_focused_text_input())

    def test_macos_focus_probe_allows_developer_apps_without_focused_element(self):
        cases = [
            ("Cursor", "com.todesktop.230313mzl4w4u92"),
            ("Codex", "com.openai.codex"),
        ]

        for app_name, bundle_id in cases:
            with self.subTest(app_name=app_name):
                self.assertTrue(
                    typer._allows_typing_without_focused_element(bundle_id, app_name)
                )

    def test_macos_focus_probe_blocks_chat_apps_without_focused_element(self):
        cases = [
            ("微信", "com.tencent.xinWeChat"),
            ("企业微信", "com.tencent.WeWorkMac"),
            ("飞书", "com.bytedance.lark"),
            ("Slack", "com.tinyspeck.slackmacgap"),
        ]

        for app_name, bundle_id in cases:
            with self.subTest(app_name=app_name):
                self.assertFalse(
                    typer._allows_typing_without_focused_element(bundle_id, app_name)
                )

    def test_macos_focus_probe_blocks_unknown_apps_without_focused_element(self):
        self.assertFalse(
            typer._allows_typing_without_focused_element(
                "com.example.notes", "Example Notes"
            )
        )

    def test_macos_focus_probe_does_not_allow_finder_without_focused_element(self):
        self.assertFalse(
            typer._allows_typing_without_focused_element("com.apple.finder", "访达")
        )

    def test_get_selection_prefers_accessibility_selection(self):
        with (
            patch.object(typer, "_get_accessibility_selection", return_value="选中的文字"),
            patch.object(typer, "_copy_selection") as copy_selection,
        ):
            self.assertEqual(typer.get_selection(), "选中的文字")

        copy_selection.assert_not_called()

    def test_slice_caret_text_window_prefers_current_text_when_small(self):
        text = "第一句。第二句需要修改。第三句。"

        window = typer._slice_caret_text_window(text, text.index("需要"))

        self.assertIsNotNone(window)
        self.assertEqual(window.text, text)
        self.assertEqual(window.source, "text_field")

    def test_slice_caret_text_window_limits_long_sentence(self):
        text = "a" * 20

        window = typer._slice_caret_text_window(text, 10, max_chars=8)

        self.assertIsNotNone(window)
        self.assertEqual(window.text, "aaaaaaaa")

    def test_get_caret_text_window_reads_accessibility_value_and_range(self):
        focused = object()
        text = "第一句。第二句需要修改。第三句。"

        with (
            patch.object(typer, "_OS", "Darwin"),
            patch.object(typer, "_focused_accessibility_element", return_value=focused),
            patch.object(typer, "_get_accessibility_selected_range", return_value=(8, 0)),
            patch.object(typer, "ApplicationServices") as ax,
        ):
            ax.AXUIElementCopyAttributeValue.return_value = (0, text)

            window = typer.get_caret_text_window()

        self.assertIsNotNone(window)
        self.assertEqual(window.text, text)
        self.assertEqual(window.source, "text_field")

    def test_accessibility_selected_range_reads_pyobjc_return_tuple(self):
        app_services = typer.ApplicationServices
        selected_range = app_services.AXValueCreate(
            app_services.kAXValueCFRangeType,
            app_services.CFRangeMake(3, 4),
        )
        with (
            patch.object(typer, "_OS", "Darwin"),
            patch.object(typer, "ApplicationServices") as ax,
        ):
            ax.AXUIElementCopyAttributeValue.return_value = (0, selected_range)
            ax.kAXValueCFRangeType = app_services.kAXValueCFRangeType
            ax.AXValueGetValue = app_services.AXValueGetValue

            self.assertEqual(typer._get_accessibility_selected_range(object()), (3, 4))

    def test_accessibility_replacement_uses_value_range(self):
        focused = object()
        state = {
            "value": "hello world",
            "range": (6, 5),
            "set_range": None,
        }

        with (
            patch.object(typer, "_OS", "Darwin"),
            patch.object(typer, "_frontmost_app_is_codex", return_value=True),
            patch.object(typer, "_focused_accessibility_element", return_value=focused),
            patch.object(typer, "_get_accessibility_selected_range", return_value=state["range"]),
            patch.object(typer, "_set_accessibility_selected_range") as set_range,
            patch.object(typer, "ApplicationServices") as ax,
            patch.object(typer, "_set_clipboard") as set_clipboard,
        ):
            ax.AXUIElementCopyAttributeValue.return_value = (0, state["value"])

            def set_attr(element, attr, value):
                state[attr] = value
                return 0

            ax.AXUIElementSetAttributeValue.side_effect = set_attr

            typer.replace_selection("earth")

        self.assertEqual(state["AXValue"], "hello earth")
        set_range.assert_called_once_with(focused, 11, 0)
        set_clipboard.assert_not_called()

    def test_accessibility_delete_uses_value_range(self):
        focused = object()
        state = {"value": "hello world"}

        with (
            patch.object(typer, "_OS", "Darwin"),
            patch.object(typer, "_frontmost_app_is_codex", return_value=True),
            patch.object(typer, "_focused_accessibility_element", return_value=focused),
            patch.object(typer, "_get_accessibility_selected_range", return_value=(6, 5)),
            patch.object(typer, "_set_accessibility_selected_range"),
            patch.object(typer, "ApplicationServices") as ax,
            patch.object(typer, "_press_key") as press_key,
        ):
            ax.AXUIElementCopyAttributeValue.return_value = (0, state["value"])

            def set_attr(element, attr, value):
                state[attr] = value
                return 0

            ax.AXUIElementSetAttributeValue.side_effect = set_attr

            typer.delete_selection()

        self.assertEqual(state["AXValue"], "hello ")
        press_key.assert_not_called()

    def test_accessibility_replacement_falls_back_to_original_when_selection_range_is_lost(self):
        focused = object()
        state = {"value": "hello world"}

        with (
            patch.object(typer, "_OS", "Darwin"),
            patch.object(typer, "_frontmost_app_is_codex", return_value=True),
            patch.object(typer, "_focused_accessibility_element", return_value=focused),
            patch.object(typer, "_get_accessibility_selected_range", return_value=(11, 0)),
            patch.object(typer, "_set_accessibility_selected_range") as set_range,
            patch.object(typer, "ApplicationServices") as ax,
            patch.object(typer, "_set_clipboard") as set_clipboard,
        ):
            ax.AXUIElementCopyAttributeValue.return_value = (0, state["value"])

            def set_attr(element, attr, value):
                state[attr] = value
                return 0

            ax.AXUIElementSetAttributeValue.side_effect = set_attr

            typer.replace_selection("earth", original="world")

        self.assertEqual(state["AXValue"], "hello earth")
        set_range.assert_called_once_with(focused, 11, 0)
        set_clipboard.assert_not_called()

    def test_replace_text_window_requires_original_adjacent_to_caret(self):
        focused = object()
        state = {"value": "same text. other words. same text.", "range": (18, 0)}

        with (
            patch.object(typer, "_OS", "Darwin"),
            patch.object(typer, "_focused_accessibility_element", return_value=focused),
            patch.object(typer, "_get_accessibility_selected_range", return_value=state["range"]),
            patch.object(typer, "ApplicationServices") as ax,
        ):
            ax.AXUIElementCopyAttributeValue.return_value = (0, state["value"])

            result = typer.replace_text_window("same text.", "changed.")

        self.assertFalse(result)
        ax.AXUIElementSetAttributeValue.assert_not_called()

    def test_replace_text_window_applies_when_original_contains_caret(self):
        focused = object()
        state = {"value": "First sentence. Second sentence here.", "range": (23, 0)}

        with (
            patch.object(typer, "_OS", "Darwin"),
            patch.object(typer, "_focused_accessibility_element", return_value=focused),
            patch.object(typer, "_get_accessibility_selected_range", return_value=state["range"]),
            patch.object(typer, "_set_accessibility_selected_range") as set_range,
            patch.object(typer, "ApplicationServices") as ax,
        ):
            ax.AXUIElementCopyAttributeValue.return_value = (0, state["value"])

            def set_attr(element, attr, value):
                state[attr] = value
                return 0

            ax.AXUIElementSetAttributeValue.side_effect = set_attr

            result = typer.replace_text_window("Second sentence here.", "Changed sentence.")

        self.assertTrue(result)
        self.assertEqual(state["AXValue"], "First sentence. Changed sentence.")
        set_range.assert_called_once_with(focused, 33, 0)

    def test_replace_text_window_applies_when_original_starts_at_caret(self):
        focused = object()
        state = {"value": "same text. other words. same text.", "range": (24, 0)}

        with (
            patch.object(typer, "_OS", "Darwin"),
            patch.object(typer, "_focused_accessibility_element", return_value=focused),
            patch.object(typer, "_get_accessibility_selected_range", return_value=state["range"]),
            patch.object(typer, "_set_accessibility_selected_range") as set_range,
            patch.object(typer, "ApplicationServices") as ax,
        ):
            ax.AXUIElementCopyAttributeValue.return_value = (0, state["value"])

            def set_attr(element, attr, value):
                state[attr] = value
                return 0

            ax.AXUIElementSetAttributeValue.side_effect = set_attr

            result = typer.replace_text_window("same text.", "changed.")

        self.assertTrue(result)
        self.assertEqual(state["AXValue"], "same text. other words. changed.")
        set_range.assert_called_once_with(focused, 32, 0)

    def test_replace_text_window_has_no_clipboard_fallback(self):
        with (
            patch.object(typer, "_replace_accessibility_selection", return_value=False),
            patch.object(typer, "_set_clipboard") as set_clipboard,
        ):
            result = typer.replace_text_window("world", "earth")

        self.assertFalse(result)
        set_clipboard.assert_not_called()

    def test_accessibility_delete_falls_back_to_original_when_selection_range_is_lost(self):
        focused = object()
        state = {"value": "hello world"}

        with (
            patch.object(typer, "_OS", "Darwin"),
            patch.object(typer, "_frontmost_app_is_codex", return_value=True),
            patch.object(typer, "_focused_accessibility_element", return_value=focused),
            patch.object(typer, "_get_accessibility_selected_range", return_value=(11, 0)),
            patch.object(typer, "_set_accessibility_selected_range") as set_range,
            patch.object(typer, "ApplicationServices") as ax,
            patch.object(typer, "_press_key") as press_key,
        ):
            ax.AXUIElementCopyAttributeValue.return_value = (0, state["value"])

            def set_attr(element, attr, value):
                state[attr] = value
                return 0

            ax.AXUIElementSetAttributeValue.side_effect = set_attr

            typer.delete_selection(original="world")

        self.assertEqual(state["AXValue"], "hello ")
        set_range.assert_called_once_with(focused, 6, 0)
        press_key.assert_not_called()

    def test_accessibility_value_failure_restores_selection_before_clipboard_fallback(self):
        focused = object()
        state = {"value": "hello world"}

        with (
            patch.object(typer, "_OS", "Darwin"),
            patch.object(typer, "_focused_accessibility_element", return_value=focused),
            patch.object(typer, "_get_accessibility_selected_range", return_value=(11, 0)),
            patch.object(typer, "_set_accessibility_selected_range", return_value=True) as set_range,
            patch.object(typer, "ApplicationServices") as ax,
            patch.object(typer, "_set_clipboard") as set_clipboard,
            patch.object(typer, "_kb"),
            patch.object(typer, "_press_key"),
        ):
            ax.AXUIElementCopyAttributeValue.return_value = (0, state["value"])
            ax.AXUIElementSetAttributeValue.return_value = 1

            typer.replace_selection("earth", original="world")

        set_range.assert_called_once_with(focused, 6, 5)
        set_clipboard.assert_called_once_with("earth")


if __name__ == "__main__":
    unittest.main()
