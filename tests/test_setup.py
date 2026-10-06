"""Run the real setup shell against controlled interpreter installations."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SetupTests(unittest.TestCase):
    def prepare(self, tmp, *, fallback=True):
        root = Path(tmp) / "project"
        root.mkdir()
        shutil.copy(ROOT / "setup.sh", root / "setup.sh")
        (root / "requirements.txt").write_text("")
        tools = Path(tmp) / "bin"
        tools.mkdir()
        for command in ["dirname", "mkdir", "ln"]:
            (tools / command).symlink_to(shutil.which(command))
        # Only the version probe is simulated. venv and pip run real Python.
        default = tools / "python3"
        default.write_text(
            '#!/bin/bash\n'
            'if [[ "$1" == "-c" && "$2" == *version_info* ]]; then exit 1; fi\n'
            f'exec "{sys.executable}" "$@"\n'
        )
        default.chmod(0o755)
        if fallback:
            (tools / "python3.12").symlink_to(sys.executable)
        env = os.environ.copy()
        env.pop("OM_PYTHON", None)
        env["PATH"] = str(tools)
        env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        return root, tools, env

    def run_setup(self, root, env):
        return subprocess.run(["/bin/bash", str(root / "setup.sh")], env=env, text=True, capture_output=True, timeout=30)

    def assert_working_environment(self, root):
        result = subprocess.run(
            [str(root / ".venv/bin/python"), "-c", "import sys; print(sys.version_info[:2])"],
            text=True, capture_output=True, check=True,
        )
        self.assertEqual(result.stdout.strip(), str(sys.version_info[:2]))

    def test_unsupported_default_uses_supported_installed_interpreter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _, env = self.prepare(tmp)
            result = self.run_setup(root, env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assert_working_environment(root)
            self.assertFalse((root / ".bootstrap").exists())

    def test_explicit_unsupported_interpreter_gets_actionable_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, tools, env = self.prepare(tmp)
            env["OM_PYTHON"] = str(tools / "python3")
            result = self.run_setup(root, env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("OM_PYTHON", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse((root / ".venv").exists())

    def test_no_installed_candidate_uses_project_managed_interpreter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _, env = self.prepare(tmp, fallback=False)
            # Model the external download boundary only, then create a real venv.
            uv = root / ".bootstrap/bin/uv"
            uv.parent.mkdir(parents=True)
            uv.write_text(
                '#!/bin/bash\n'
                'if [[ "$1" == "python" && "$2" == "install" ]]; then\n'
                '  mkdir -p "$UV_PYTHON_INSTALL_DIR/bin"\n'
                f'  ln -s "{sys.executable}" "$UV_PYTHON_INSTALL_DIR/bin/python3.12"\n'
                'elif [[ "$1" == "python" && "$2" == "find" ]]; then\n'
                '  printf "%s/bin/python3.12\\n" "$UV_PYTHON_INSTALL_DIR"\n'
                'else exit 9; fi\n'
            )
            uv.chmod(0o755)
            result = self.run_setup(root, env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assert_working_environment(root)
            self.assertTrue((root / ".python/bin/python3.12").is_file())


if __name__ == "__main__":
    unittest.main()
