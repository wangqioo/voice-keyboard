import unittest
from unittest.mock import MagicMock, patch

from pynput.keyboard import Key

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

    def test_init_keeps_legacy_app_shortcuts_as_experimental_alias(self):
        with patch.dict(typer._APP_SHORTCUTS, {}, clear=True):
            typer.init({
                "app_shortcuts": {
                    "com.openai.codex": {
                        "发送": "cmd+enter",
                    },
                },
            })

            self.assertIn("发送", typer._APP_SHORTCUTS["com.openai.codex"])

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

    def test_list_shortcuts_includes_active_application_shortcuts(self):
        app = typer.ActiveApplication("Codex", "com.openai.codex", 42)
        with (
            patch.dict(typer._APP_SHORTCUTS, {
                "com.openai.codex": {"发送": [Key.cmd, Key.enter]},
            }, clear=True),
            patch.object(typer, "current_application", return_value=app),
        ):
            self.assertIn("发送", typer.list_shortcuts())

    def test_open_settings_is_global_system_action(self):
        with patch.object(typer, "_run_system_action", return_value=True) as run:
            self.assertTrue(typer.send_shortcut("打开系统设置"))

        run.assert_called_once_with("open_system_settings")

    def test_builtin_shortcuts_include_system_actions(self):
        self.assertIn("打开系统设置", typer.list_shortcuts())

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

    def test_macos_focus_probe_allows_feishu_without_focused_element(self):
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
            self.assertTrue(typer.has_focused_text_input())

    def test_macos_focus_probe_allows_common_rich_input_apps_without_focused_element(self):
        cases = [
            ("微信", "com.tencent.xinWeChat"),
            ("企业微信", "com.tencent.WeWorkMac"),
            ("钉钉", "com.alibaba.DingTalk"),
            ("Slack", "com.tinyspeck.slackmacgap"),
            ("Notion", "notion.id"),
            ("Cursor", "com.todesktop.230313mzl4w4u92"),
            ("Codex", "com.openai.codex"),
        ]

        for app_name, bundle_id in cases:
            with self.subTest(app_name=app_name):
                self.assertTrue(
                    typer._allows_typing_without_focused_element(bundle_id, app_name)
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

    def test_slice_caret_text_window_prefers_current_sentence(self):
        text = "第一句。第二句需要修改。第三句。"

        window = typer._slice_caret_text_window(text, text.index("需要"))

        self.assertIsNotNone(window)
        self.assertEqual(window.text, "第二句需要修改。")
        self.assertEqual(window.source, "caret_sentence")

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
        self.assertEqual(window.text, "第二句需要修改。")
        self.assertEqual(window.source, "caret_sentence")

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
