import unittest
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
