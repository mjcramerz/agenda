# Fork-owned entry point: upstream Meson/application files stay untouched.
SHELL := /bin/sh
.DEFAULT_GOAL := all
.NOTPARALLEL:

PYTHON ?= python3
BUILD_ROOT ?= /pool/build/mcramer/local/agenda
OUTPUT_DIR ?= $(BUILD_ROOT)/output
PREFIX ?= /usr
BUILD_TYPE ?= release
JOBS ?= 2
export BUILD_ROOT OUTPUT_DIR PREFIX BUILD_TYPE JOBS

.PHONY: all help paths check-deps deps configure build test check check-release stage dist tarball release clean

all: dist

help:
	@printf '%s\n' \
	  'Agenda native Debian build (Meson + Ninja)' \
	  '' \
	  'make / make dist     Build, test, stage and create the binary tarball + SHA-256' \
	  'make check-deps      Check the compiler, tools and GTK 3 / Granite 6 dependencies' \
	  'make deps            Install build dependencies with Debian APT (uses sudo)' \
	  'make configure       Configure an out-of-tree Meson release build' \
	  'make build           Compile the application, translations and upstream tests' \
	  'make test / check    Compile and run upstream tests with private settings' \
	  'make check-release   Run the release helper safety and archive fixture tests' \
	  'make stage           Build, test and stage the installed payload without root' \
	  'make paths           Print the selected workspace and output paths' \
	  'make clean           Remove owned build/stage files; keep output archives' \
	  '' \
	  'Defaults: BUILD_ROOT=/pool/build/mcramer/local/agenda, OUTPUT_DIR=$$BUILD_ROOT/output' \
	  'Overrides: BUILD_ROOT=/absolute/path OUTPUT_DIR=/absolute/path PREFIX=/usr JOBS=2' \
	  'See scripts/release/README.md for archive installation and Debian requirements.'

paths check-deps deps configure build test check stage dist clean:
	@$(PYTHON) -I -B scripts/release/build.py $@

check: check-release

check-release:
	@$(PYTHON) -I -B scripts/release/test_build.py

tarball release: dist
