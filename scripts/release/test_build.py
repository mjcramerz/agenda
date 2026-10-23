#!/usr/bin/env python3
"""Focused safety and archive tests; fixture payloads are not app builds."""

from __future__ import annotations

import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

HELPER = Path(__file__).with_name("build.py")
SPEC = importlib.util.spec_from_file_location("agenda_release_build", HELPER)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="agenda-release-test-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.environment = patch.dict(os.environ, {
            "BUILD_ROOT": str(self.base / "workspace"),
            "OUTPUT_DIR": str(self.base / "workspace/output"),
            "PREFIX": "/usr", "BUILD_TYPE": "release", "JOBS": "2",
            "SOURCE_DATE_EPOCH": "1700000000",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def clean_command(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["python3", "-I", "-B", str(HELPER), "clean"],
                              capture_output=True, encoding="utf-8", timeout=10)

    def test_paths_reject_checkout_root_and_ancestors(self) -> None:
        for value in ("/", str(MODULE.REPO), str(MODULE.REPO.parent), "relative/path", "/tmp/../usr"):
            with self.subTest(value=value), patch.dict(os.environ, {"BUILD_ROOT": value}):
                with self.assertRaises(ValueError):
                    MODULE.Build()

    def test_output_must_survive_clean(self) -> None:
        root = Path(os.environ["BUILD_ROOT"])
        for value in (root / "build", root / "build/output", root / "stage", self.base):
            with self.subTest(value=value), patch.dict(os.environ, {"OUTPUT_DIR": str(value)}):
                with self.assertRaises(ValueError):
                    MODULE.Build()

    def test_refuse_nonempty_unowned_workspace(self) -> None:
        build = MODULE.Build()
        build.root.mkdir()
        sentinel = build.root / "keep"
        sentinel.write_text("user-owned", encoding="utf-8")
        result = self.clean_command()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unowned", result.stderr)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "user-owned")

    def test_refuse_another_checkouts_workspace(self) -> None:
        build = MODULE.Build()
        build.root.mkdir()
        (build.root / ".agenda-build-owner.json").write_text(
            json.dumps({"repository": "/different/checkout", "format": 1}), encoding="utf-8")
        result = self.clean_command()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("another checkout", result.stderr)

    def test_clean_retains_archives_and_other_workspace_files(self) -> None:
        build = MODULE.Build()
        build.claim()
        for path in (build.build, build.stage, build.output):
            path.mkdir()
            (path / "keep-or-remove").write_text("content", encoding="utf-8")
        result = self.clean_command()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(build.build.exists())
        self.assertFalse(build.stage.exists())
        self.assertTrue((build.output / "keep-or-remove").exists())
        self.assertTrue((build.root / ".agenda-build-owner.json").exists())

    def test_clean_refuses_symlink(self) -> None:
        build = MODULE.Build()
        build.claim()
        target = self.base / "precious"
        target.mkdir()
        sentinel = target / "keep"
        sentinel.write_text("user-owned", encoding="utf-8")
        build.stage.symlink_to(target, target_is_directory=True)
        result = self.clean_command()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("symlink", result.stderr)
        self.assertTrue(sentinel.exists())

    def test_concurrent_build_lock_blocks_clean(self) -> None:
        build = MODULE.Build()
        build.claim()
        with (build.root / ".agenda-build.lock").open("a", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.clean_command()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Another Agenda build", result.stderr)

    def test_test_environment_excludes_credentials(self) -> None:
        build = MODULE.Build()
        build.claim()
        with patch.dict(os.environ, {"PRIVATE_TOKEN": "do-not-forward"}), patch.object(MODULE, "run") as run:
            build.test()
        environment = run.call_args.kwargs["env"]
        self.assertNotIn("PRIVATE_TOKEN", environment)
        self.assertEqual(environment["GSETTINGS_BACKEND"], "memory")
        for name in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
            self.assertTrue(Path(environment[name]).is_relative_to(build.root))

    def test_archive_reproducibility_permissions_and_checksum(self) -> None:
        build = MODULE.Build()
        build.claim()
        build.stage.mkdir(mode=0o700)
        (build.stage / "README").write_text("fixture", encoding="utf-8")
        (build.stage / "README").chmod(0o600)
        (build.stage / "install.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        (build.stage / "install.sh").chmod(0o700)
        build.version, build.arch = "1.2.3", "amd64"
        build.archive()
        archive = build.output / "agenda-1.2.3-debian-amd64.tar.gz"
        initial = archive.read_bytes()
        os.utime(build.stage / "README", (1800000000, 1800000000))
        build.archive()
        self.assertEqual(initial, archive.read_bytes())
        digest = hashlib.sha256(initial).hexdigest()
        self.assertEqual(Path(str(archive) + ".sha256").read_text(encoding="ascii"), f"{digest}  {archive.name}\n")
        with tarfile.open(archive) as contents:
            members = contents.getmembers()
        self.assertEqual([member.name for member in members], sorted(member.name for member in members))
        for member in members:
            self.assertEqual((member.uid, member.gid, member.mtime), (0, 0, 1700000000))
            self.assertEqual(member.mode, 0o755 if member.isdir() or member.name.endswith("install.sh") else 0o644)


if __name__ == "__main__":
    unittest.main(verbosity=2)
