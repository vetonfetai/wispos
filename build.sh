#!/bin/sh
# Build the Wisp OS live/installer ISO.
# Works on macOS (Apple Silicon or Intel) and Linux - only needs Docker.
# Output: out/wisp-os-<version>-x86_64.iso
set -eu

cd "$(dirname "$0")"
mkdir -p out .cache/apk

run() {
	platform=$1; shift
	docker run --rm --privileged --platform "$platform" \
		-v "$PWD":/src:ro \
		-v "$PWD/out":/out \
		-v "$PWD/.cache/apk":/cache \
		-v wisp-work:/work \
		-e WISP_VERSION="${WISP_VERSION:-0.1}" \
		alpine:3.24 /bin/sh /src/scripts/build-in-container.sh "$@"
}

# 1. root filesystem (x86_64 packages) - skip with SKIP_ROOTFS=1 to only re-pack
[ "${SKIP_ROOTFS:-0}" = 1 ] || run linux/amd64 rootfs
# 2. compress natively on the build machine's own architecture (much faster)
run "linux/$(uname -m | sed 's/x86_64/amd64/; s/aarch64/arm64/')" squash
# 3. bootable ISO (x86 GRUB)
run linux/amd64 iso

ls -lh out/*.iso
