#!/usr/bin/env python3
"""Fork-owned native Debian build; never install dependencies implicitly."""

from __future__ import annotations

import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

REPO = Path(__file__).resolve().parents[2]
APP_ID = "com.github.dahenson.agenda"
PACKAGES = (
    "build-essential", "meson", "ninja-build", "valac", "pkgconf", "gettext",
    "libglib2.0-dev", "libgtk-3-dev", "libgranite-dev", "libgee-0.8-dev",
    "desktop-file-utils", "libgtk-3-bin", "python3", "git",
)
TOOLS = (
    "meson", "ninja", "valac", "cc", "pkg-config", "msgfmt", "git",
    "glib-compile-resources", "glib-compile-schemas", "desktop-file-validate",
    "dpkg", "gtk-update-icon-cache", "update-desktop-database",
)


def run(args: list[str], *, capture: bool = False, timeout: int = 1800,
        env: dict[str, str] | None = None) -> str:
    result = subprocess.run(args, cwd=REPO, check=True, timeout=timeout,
                            env=env, encoding="utf-8", stdout=subprocess.PIPE if capture else None)
    return result.stdout.strip() if capture else ""


def fail(message: str) -> None:
    raise ValueError(message)


def absolute_path(value: str, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or path == Path("/"):
        fail(f"{label} must be an absolute directory other than /, without '..'")
    return path.resolve()


class Build:
    def __init__(self) -> None:
        self.root = absolute_path(os.environ.get("BUILD_ROOT", "/pool/build/mcramer/local/agenda"), "BUILD_ROOT")
        self.output = absolute_path(os.environ.get("OUTPUT_DIR", str(self.root / "output")), "OUTPUT_DIR")
        self.prefix = os.environ.get("PREFIX", "/usr")
        if not re.fullmatch(r"/(?:[A-Za-z0-9_+.-]+/)*[A-Za-z0-9_+.-]+", self.prefix):
            fail("PREFIX must be an absolute path without spaces or trailing slash")
        if any(part in (".", "..") for part in Path(self.prefix).parts):
            fail("PREFIX must not contain '.' or '..'")
        self.build_type = os.environ.get("BUILD_TYPE", "release")
        if self.build_type not in ("release", "debug", "debugoptimized", "minsize", "plain"):
            fail("Unsupported BUILD_TYPE")
        jobs = os.environ.get("JOBS", "2")
        if not jobs.isdecimal() or not 1 <= int(jobs) <= 1024:
            fail("JOBS must be an integer between 1 and 1024")
        self.jobs = jobs
        for path in (self.root, self.output):
            if path == REPO or path.is_relative_to(REPO) or REPO.is_relative_to(path):
                fail("Build/output paths must be outside the checkout and its ancestors")
        self.build = self.root / "build"
        self.stage = self.root / "stage"
        for path in (self.build, self.stage):
            if path.is_symlink() or self.output == path or self.output.is_relative_to(path):
                fail("Build/stage directories must not be symlinks or contain OUTPUT_DIR")
        if self.root.is_relative_to(self.output) and self.root != self.output:
            fail("OUTPUT_DIR must not be an ancestor of BUILD_ROOT")
        self.identity = json.dumps({"repository": str(REPO), "format": 1}, sort_keys=True) + "\n"

    def paths(self) -> None:
        for key, value in (("SOURCE_DIR", REPO), ("BUILD_ROOT", self.root),
                           ("BUILD_DIR", self.build), ("STAGE_DIR", self.stage),
                           ("OUTPUT_DIR", self.output), ("PREFIX", self.prefix)):
            print(f"{key}={value}")

    def dependencies(self) -> None:
        missing = [tool for tool in TOOLS if shutil.which(tool) is None]
        if missing:
            fail("Missing tools: " + ", ".join(missing) + ". Run make deps on Debian.")
        for requirement in ("glib-2.0", "gtk+-3.0 >= 3.22", "granite >= 6.0", "gee-0.8"):
            try:
                run(["pkg-config", "--print-errors", "--exists", requirement], timeout=30)
            except subprocess.CalledProcessError as exc:
                raise ValueError(f"Missing development dependency: {requirement}. Run make deps.") from exc
        print("Debian build dependencies are available.")

    def claim(self) -> None:
        if os.geteuid() == 0:
            fail("Run builds as your normal user. Use make deps for dependency installation.")
        self.root.mkdir(parents=True, exist_ok=True)
        marker = self.root / ".agenda-build-owner.json"
        if marker.is_symlink():
            fail("Workspace ownership marker must not be a symlink")
        if marker.exists():
            if marker.read_text(encoding="utf-8") != self.identity:
                fail("BUILD_ROOT belongs to another checkout; choose a separate BUILD_ROOT")
        else:
            if any(self.root.iterdir()):
                fail("Refusing to use a nonempty, unowned BUILD_ROOT")
            with marker.open("x", encoding="utf-8") as handle:
                handle.write(self.identity)

    def configure(self) -> None:
        args = ["meson", "setup"]
        if (self.build / "meson-private/coredata.dat").is_file():
            args.append("--reconfigure")
        args += [str(self.build), str(REPO), "--backend=ninja", f"--prefix={self.prefix}",
                 "--bindir=bin", "--datadir=share", f"--buildtype={self.build_type}",
                 "--wrap-mode=nodownload"]
        run(args)

    def compile(self) -> None:
        self.configure()
        run(["meson", "compile", "-C", str(self.build), "-j", self.jobs])

    def test(self) -> None:
        # The upstream tests construct GLib.Settings but do not initialize GTK.
        # Use a private schema directory and memory backend; never touch user data.
        with tempfile.TemporaryDirectory(prefix="test-", dir=self.root) as directory:
            private = Path(directory)
            shutil.copy2(REPO / f"data/{APP_ID}.gschema.xml", private)
            run(["glib-compile-schemas", "--strict", directory])
            # Meson records its inherited environment in testlog.txt. Pass only
            # the runtime search path and locale; never forward credentials.
            env = {key: os.environ[key] for key in ("PATH", "LD_LIBRARY_PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ")
                   if key in os.environ}
            env.update(GSETTINGS_SCHEMA_DIR=directory, GSETTINGS_BACKEND="memory",
                       HOME=str(private), XDG_STATE_HOME=str(private / "state"),
                       XDG_CONFIG_HOME=str(private / "config"), XDG_DATA_HOME=str(private / "data"),
                       XDG_CACHE_HOME=str(private / "cache"))
            run(["meson", "test", "-C", str(self.build), "--no-rebuild", "--print-errorlogs"], env=env)

    def stage_files(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage-", dir=self.root) as directory:
            package = Path(directory)
            rootfs = package / "rootfs"
            # DESTDIR makes Meson's GNOME post-install hooks skip global caches.
            run(["meson", "install", "-C", str(self.build), "--no-rebuild", "--destdir", str(rootfs)])
            installed = rootfs / self.prefix.lstrip("/")
            if not (installed / f"bin/{APP_ID}").is_file():
                fail("Meson did not install the Agenda executable")
            run(["desktop-file-validate", str(installed / f"share/applications/{APP_ID}.desktop")])
            run(["glib-compile-schemas", "--strict", "--dry-run", str(installed / "share/glib-2.0/schemas")])
            docs = installed / "share/doc/agenda"
            docs.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / "LICENSE", docs / "copyright")
            shutil.copy2(REPO / "README.md", docs / "README.upstream.md")
            shutil.copy2(REPO / "scripts/release/install.sh", package / "install.sh")
            shutil.copy2(REPO / "scripts/release/README.md", package / "README.md")
            (package / "prefix.txt").write_text(self.prefix + "\n", encoding="utf-8")
            info = json.loads(run(["meson", "introspect", str(self.build), "--projectinfo"], capture=True))
            self.version = info["version"]
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+~-]*", self.version):
                fail("Meson project version is not safe for an archive filename")
            self.arch = run(["dpkg", "--print-architecture"], capture=True, timeout=30)
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", self.arch):
                fail("Invalid Debian architecture")
            # Compiler introspection was added in Meson 1.2; retain the
            # upstream minimum of 0.59 instead of requiring the newer command.
            compilers = self.build / "meson-info/intro-compilers.json"
            info = {"application": APP_ID, "version": self.version, "architecture": self.arch,
                    "prefix": self.prefix, "build_type": self.build_type,
                    "commit": run(["git", "rev-parse", "HEAD"], capture=True, timeout=30),
                    "working_tree_modified": bool(run(["git", "status", "--porcelain", "--untracked-files=normal"], capture=True, timeout=30)),
                    "compilers": json.loads(compilers.read_text(encoding="utf-8")) if compilers.is_file() else None,
                    "meson": run(["meson", "--version"], capture=True, timeout=30),
                    "valac": run(["valac", "--version"], capture=True, timeout=30),
                    "libraries": {name: run(["pkg-config", "--modversion", name], capture=True, timeout=30)
                                  for name in ("glib-2.0", "gtk+-3.0", "granite", "gee-0.8")}}
            (package / "BUILD-INFO.json").write_text(json.dumps(info, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            if self.stage.exists():
                shutil.rmtree(self.stage)
            package.rename(self.stage)
        print(f"Staged payload: {self.stage}")

    def archive(self) -> None:
        epoch = os.environ.get("SOURCE_DATE_EPOCH")
        if epoch is None:
            epoch = run(["git", "log", "-1", "--format=%ct"], capture=True, timeout=30)
        if not epoch.isdecimal():
            fail("SOURCE_DATE_EPOCH must be a nonnegative integer")
        timestamp = int(epoch)
        self.output.mkdir(parents=True, exist_ok=True)
        name = f"agenda-{self.version}-debian-{self.arch}"
        final = self.output / f"{name}.tar.gz"

        def normalize(member: tarfile.TarInfo) -> tarfile.TarInfo:
            member.uid = member.gid = 0
            member.uname = member.gname = "root"
            member.mtime = timestamp
            member.mode = 0o755 if member.isdir() or member.mode & 0o111 else 0o644
            return member

        # Publish only a complete archive; previous releases survive build failures.
        with tempfile.TemporaryDirectory(prefix=".agenda-archive-", dir=self.output) as directory:
            temporary = Path(directory) / final.name
            with temporary.open("wb") as raw:
                with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
                    with tarfile.open(fileobj=compressed, mode="w", format=tarfile.GNU_FORMAT) as archive:
                        archive.add(self.stage, arcname=name, filter=normalize)
            with temporary.open("rb") as handle:
                digest = hashlib.file_digest(handle, "sha256").hexdigest()
            checksum = Path(directory) / (final.name + ".sha256")
            checksum.write_text(f"{digest}  {final.name}\n", encoding="ascii")
            temporary.replace(final)
            checksum.replace(self.output / checksum.name)
        print(f"Archive: {final}\nSHA-256: {final}.sha256")


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in {
        "paths", "check-deps", "deps", "configure", "build", "test", "check", "stage", "dist", "clean"
    }:
        fail("Expected a Makefile target; run make help")
    action = sys.argv[1]
    build = Build()
    if action == "paths":
        build.paths()
        return
    if action == "deps":
        command = ["apt-get", "install", "--no-install-recommends", *PACKAGES]
        if os.geteuid() != 0:
            command.insert(0, "sudo")
        run(command)
        return
    if action == "check-deps":
        build.dependencies()
        return
    if action != "clean":
        build.dependencies()
    build.claim()
    lock_path = build.root / ".agenda-build.lock"
    if lock_path.is_symlink():
        fail("Workspace lock must not be a symlink")
    with lock_path.open("a", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("Another Agenda build is using BUILD_ROOT") from exc
        if action == "clean":
            for path in (build.build, build.stage):
                if path.exists():
                    shutil.rmtree(path)
            print("Removed owned build and stage directories; output archives retained.")
        elif action == "configure":
            build.configure()
        else:
            build.compile()
            if action in {"test", "check", "stage", "dist"}:
                build.test()
            if action in {"stage", "dist"}:
                build.stage_files()
            if action == "dist":
                build.archive()


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"agenda-build: {error}", file=sys.stderr)
        sys.exit(1)
