import hashlib
import os
import platform
import re
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/install-bun"
VERSION = re.search(r"^BUN_VERSION=(\S+)$", SCRIPT.read_text(), re.M).group(1)
ASSETS = {"x86_64": "bun-linux-x64.zip", "amd64": "bun-linux-x64.zip",
          "aarch64": "bun-linux-aarch64.zip", "arm64": "bun-linux-aarch64.zip"}
ASSET = ASSETS.get(platform.machine())

FAKE_CURL = """#!/bin/sh
out=; url=
while [ "$#" -gt 0 ]; do
  case "$1" in
    -o) out=$2; shift 2 ;;
    -*) shift ;;
    *) url=$1; shift ;;
  esac
done
[ -z "$FAKE_CURL_MARK" ] || : > "$FAKE_CURL_MARK"
copy=$FAKE_CURL_RELEASE/${url##*/}
[ -f "$copy" ] || { echo "curl: (22) fake download failed" >&2; exit 22; }
cp "$copy" "$out"
"""


def bun_binary(version=VERSION):
    return f"#!/bin/sh\necho {version}\n"


class InstallBun(unittest.TestCase):
    def setUp(self):
        if ASSET is None:
            self.skipTest(f"no bun release for {platform.machine()}")
        self.tmp = Path(tempfile.mkdtemp(prefix="install-bun-"))
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.tmp)])
        self.home = self.tmp / "home"
        self.release = self.tmp / "release"
        self.bin = self.tmp / "bin"
        for path in (self.home, self.release, self.bin):
            path.mkdir(parents=True)
        curl = self.bin / "curl"
        curl.write_text(FAKE_CURL)
        curl.chmod(0o755)
        self.mark = self.tmp / "curl-called"

    def env(self):
        return {**os.environ, "HOME": str(self.home),
                "PATH": f"{self.bin}:{os.environ['PATH']}",
                "FAKE_CURL_RELEASE": str(self.release), "FAKE_CURL_MARK": str(self.mark)}

    def run_script(self):
        return subprocess.run(["bash", str(SCRIPT)], env=self.env(), text=True,
                              capture_output=True, timeout=120)

    def publish(self, payload="bun", sha=None):
        archive = self.release / ASSET
        with zipfile.ZipFile(archive, "w") as bundle:
            info = zipfile.ZipInfo(f"{ASSET[:-4]}/bun")
            info.external_attr = 0o755 << 16
            bundle.writestr(info, payload)
        digest = sha or hashlib.sha256(archive.read_bytes()).hexdigest()
        (self.release / "SHASUMS256.txt").write_text(
            f"{'0' * 64}  bun-darwin-x64.zip\n{digest}  {ASSET}\n")

    def assert_warned(self, result, needle):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        lines = result.stderr.splitlines()
        self.assertEqual(len(lines), 1, result.stderr)
        self.assertTrue(lines[0].startswith("vstack install: "), lines[0])
        self.assertIn(needle, lines[0])

    def test_skips_when_pinned_bun_is_present(self):
        target = self.home / ".bun/bin/bun"
        target.parent.mkdir(parents=True)
        target.write_text(bun_binary())
        target.chmod(0o755)

        result = self.run_script()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((result.stdout, result.stderr), ("", ""))
        self.assertFalse(self.mark.exists(), "a present bun must not be downloaded again")
        link = self.home / ".local/bin/bun"
        self.assertTrue(link.is_symlink())
        self.assertEqual(Path(os.path.realpath(link)), Path(os.path.realpath(target)))

    def test_installs_the_pinned_release_then_skips(self):
        self.publish()

        result = self.run_script()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"bun {VERSION}", result.stdout)
        target = self.home / ".bun/bin/bun"
        self.assertEqual(subprocess.run([str(target), "--version"], text=True,
                                        capture_output=True, check=True).stdout.strip(), VERSION)
        self.assertEqual(Path(os.path.realpath(self.home / ".local/bin/bun")),
                         Path(os.path.realpath(target)))

        self.mark.unlink()
        for leftover in self.release.iterdir():
            leftover.unlink()
        again = self.run_script()
        self.assertEqual((again.returncode, again.stdout, again.stderr), (0, "", ""))
        self.assertFalse(self.mark.exists(), "the second run must not download")

    def test_failed_download_warns_once_and_leaves_no_bun(self):
        result = self.run_script()

        self.assert_warned(result, "could not download bun")
        self.assertFalse((self.home / ".bun/bin/bun").exists())

    def test_checksum_mismatch_installs_nothing(self):
        self.publish(sha="1" * 64)

        result = self.run_script()

        self.assert_warned(result, "does not match its published checksum")
        self.assertFalse((self.home / ".bun/bin/bun").exists())

    def test_a_real_file_on_the_path_is_not_replaced(self):
        self.publish()
        link = self.home / ".local/bin/bun"
        link.parent.mkdir(parents=True)
        link.write_text("someone else's bun\n")

        result = self.run_script()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("is a real file", result.stderr)
        self.assertEqual(link.read_text(), "someone else's bun\n")


if __name__ == "__main__":
    unittest.main()
