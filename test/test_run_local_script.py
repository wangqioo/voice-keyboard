import os
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RunLocalScriptTests(unittest.TestCase):
    def test_kill_only_matcher_accepts_homebrew_python_app_process(self):
        script = ROOT / "scripts" / "run-local.sh"
        command = [str(script), "--kill-only"]
        if sys.platform == "win32":
            bash = shutil.which("bash")
            if bash is None:
                self.skipTest("bash is required to run scripts/run-local.sh on Windows")
            command = [bash, str(script), "--kill-only"]

        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            log_path = Path(tmp) / "pgrep.log"
            fake_pgrep = bin_dir / "pgrep"
            fake_pgrep.write_text(
                textwrap.dedent(
                    f"""\
                    #!/usr/bin/env bash
                    printf '%s\\n' "$*" >> "{log_path}"
                    exit 0
                    """
                ),
                encoding="utf-8",
            )
            fake_pgrep.chmod(fake_pgrep.stat().st_mode | stat.S_IXUSR)

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"
            result = subprocess.run(
                command,
                cwd=ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            matcher = log_path.read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[Pp]ython", matcher)
        self.assertIn("agent\\.main", matcher)


if __name__ == "__main__":
    unittest.main()
