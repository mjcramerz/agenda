#!/bin/sh
# Install a compiled release at its configured prefix. No package installation.
set -eu

archive_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)
IFS= read -r prefix < "$archive_dir/prefix.txt"
case "$prefix" in
    /*) ;;
    *) printf '%s\n' 'Invalid archive prefix' >&2; exit 1 ;;
esac
case "$prefix" in
    /|*/../*|*/./*|*/..|*/.) printf '%s\n' 'Unsafe archive prefix' >&2; exit 1 ;;
esac
destination=${DESTDIR:-}
case "$destination" in
    ''|/*) ;;
    *) printf '%s\n' 'DESTDIR must be absolute' >&2; exit 1 ;;
esac
case "$destination" in
    /|*/../*|*/./*|*/..|*/.)
        printf '%s\n' 'DESTDIR must be a staging directory without traversal; omit it for a system install' >&2
        exit 1
        ;;
esac
test -x "$archive_dir/rootfs$prefix/bin/com.github.dahenson.agenda" || {
    printf '%s\n' 'Archive is missing the Agenda binary' >&2
    exit 1
}
mkdir -p -- "${destination}$prefix"
cp -a --no-preserve=ownership -- "$archive_dir/rootfs$prefix/." "${destination}$prefix/"

if test -z "$destination"; then
    glib-compile-schemas "$prefix/share/glib-2.0/schemas"
    gtk-update-icon-cache --ignore-theme-index --force "$prefix/share/icons/hicolor"
    update-desktop-database "$prefix/share/applications"
fi
printf 'Installed Agenda under %s%s\n' "$destination" "$prefix"
