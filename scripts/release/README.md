# Native Debian release build

This fork keeps its build entry point in `Makefile` and `scripts/release/` so
upstream synchronization can replace the application and Meson sources.
Run these commands from the checkout as your normal user:

```sh
make help
make check-deps
make deps                 # optional: APT installs development packages using sudo
make                      # configure, compile, test, stage, archive, checksum
```

`make deps` uses the system's configured Debian repositories and normal APT
signature verification. It does not change repository configuration or run
`autoremove`. Review APT's proposed transaction before accepting it. On a fresh
machine, update your APT package indexes first. Builds never install packages
automatically and never need root.

## Directories and targets

Default directories:

| Purpose | Directory |
| --- | --- |
| Source | Current checkout (no generated files) |
| Workspace | `/pool/build/mcramer/local/agenda` |
| Meson / Ninja files | `/pool/build/mcramer/local/agenda/build` |
| Installed payload | `/pool/build/mcramer/local/agenda/stage/rootfs/usr` |
| Tarball and checksum | `/pool/build/mcramer/local/agenda/output` |

`make paths` prints the selected paths. For another checkout or machine:

```sh
make BUILD_ROOT=/absolute/writable/path/agenda JOBS=4
make BUILD_ROOT=/absolute/writable/path/agenda OUTPUT_DIR=/absolute/path/releases
```

`BUILD_ROOT` must be an empty directory or a workspace already owned by this
checkout. It must be outside the checkout. The helper locks it against concurrent
builds and refuses to clean a workspace belonging to another checkout.
`make clean` removes only its `build` and `stage` directories and retains archives.
Use separate workspaces for different checkouts/toolchains. Meson reconfiguration
updates `PREFIX` (default `/usr`) and `BUILD_TYPE` (default `release`); clean before
switching compilers. `JOBS` defaults to 2; Make's `-j` does not control Ninja.

Individual targets are `configure`, `build`, `test`, `check`, `stage`, and
`dist` (aliases `tarball`, `release`). Stage and dist run tests before packaging.
`make check-release` runs the helper's safety and archive tests with fixture
payloads; `make check` runs these plus the actual upstream application tests.
Meson uses Ninja and `--wrap-mode=nodownload`: dependencies must already exist.
The test harness compiles the Agenda schema in a private directory and uses the
memory GSettings backend and private XDG directories. It does not modify desktop
settings or task data. The upstream tests do not require a display.

## Build and runtime dependencies

Build dependencies are `build-essential`, `meson` (at least 0.59), `ninja-build`,
`valac`, `pkgconf`, `gettext`, `libglib2.0-dev`, `libgtk-3-dev`, `libgranite-dev`,
`libgee-0.8-dev`, `desktop-file-utils`, `libgtk-3-bin`, Python 3.11 or newer, and Git.
The project uses GTK 3 and Granite 6 (`granite.pc`), including `Granite.Settings`; GTK 4 / Granite 7
development packages do not replace these dependencies.

The archive is a native, dynamically linked Debian binary distribution. It
contains the executable, translations, desktop entry, AppStream metadata, icons,
GSettings schema, upstream license and README, installation script, and build
metadata. It does not bundle system libraries. Build on the oldest Debian release
you intend to support: a Forky build is not guaranteed to run on Trixie/Bookworm.
Only the native host architecture is supported; no cross compilation is implied.

On a compatible Debian system, install runtime dependencies:

```sh
sudo apt-get install libgtk-3-0t64 libgranite6 libgee-0.8-2 \
    gsettings-desktop-schemas libglib2.0-bin libgtk-3-bin desktop-file-utils
```

The desktop privacy schema from `gsettings-desktop-schemas` is required by the
application. Older Debian releases may use the GTK package name `libgtk-3-0`.
APT resolves the remaining shared-library dependencies. A GTK desktop session
(Wayland or X11) is needed to use the app.

## Verify and install the binary tarball

For the current upstream version on amd64, the files are named
`agenda-1.2.1-debian-amd64.tar.gz` and
`agenda-1.2.1-debian-amd64.tar.gz.sha256`. Version and architecture are read from
Meson and dpkg rather than hardcoded by the build. In the output directory:

```sh
sha256sum -c agenda-1.2.1-debian-amd64.tar.gz.sha256
tar -xzf agenda-1.2.1-debian-amd64.tar.gz
sudo sh agenda-1.2.1-debian-amd64/install.sh
com.github.dahenson.agenda
```

The installer copies only `rootfs/<configured-prefix>` and refreshes schema,
icon and desktop caches. For package assembly or inspection, stage it without
touching the system (cache updates are skipped with `DESTDIR`):

```sh
DESTDIR=/absolute/path/inspection sh agenda-1.2.1-debian-amd64/install.sh
```

The compiled prefix is recorded in `prefix.txt`; the binary is not relocatable
because it uses that prefix to locate translations. To use `/usr/local`, build
with `PREFIX=/usr/local` and ensure that prefix's `bin` and `share` directories
are in the desktop session's PATH and XDG_DATA_DIRS. This archive is not a `.deb`
and has no dpkg-managed uninstall/upgrade tracking.

Tar members are sorted and normalized to root ownership and the timestamp in
`SOURCE_DATE_EPOCH` (default: current Git commit time); gzip omits timestamps and
filenames. Identical staged content produces identical archives. This does not
claim identical compiled binaries across different toolchains or source paths.
`BUILD-INFO.json` records the commit, dirty state, architecture, prefix, Vala,
Meson and key dependency versions. C compiler details are included when available
from [Meson 1.2 or newer](https://mesonbuild.com/Release-notes-for-1-2-0.html#more-data-in-introspection-files).
Test processes receive only runtime path,
locale and private settings variables so Meson's test log does not capture the
caller's credentials or full environment. No Git credentials or environment dump is
included. Local archives are replaced only after successful compilation, tests,
staging and archive creation; nothing is uploaded or published by these targets.
