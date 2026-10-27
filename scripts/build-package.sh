#!/bin/sh
# Build and sign the wisp-desktop package and its repository index.
#   scripts/build-package.sh KEY_DIR OUT_REPO
# KEY_DIR holds the private signing key wisp-os.rsa (never commit it).
# OUT_REPO receives x86_64/APKINDEX.tar.gz and x86_64/wisp-desktop-*.apk.
# The version is 0.1.<number of commits>, so every push is a newer version.
set -eu
cd "$(dirname "$0")/.."
KEYS=$(cd "${1:?key dir}" && pwd)
mkdir -p "${2:?output repo dir}"
OUTREPO=$(cd "$2" && pwd)
[ -f "$KEYS/wisp-os.rsa" ] || { echo "missing $KEYS/wisp-os.rsa" >&2; exit 1; }
BASE=$(cat VERSION)
COUNT=$(git rev-list --count HEAD 2>/dev/null || echo 0)
PKGVER=${WISP_PKGVER:-$BASE.$COUNT}
echo "Building wisp-desktop $PKGVER"
mkdir -p .cache/apk
docker run --rm --platform linux/amd64 \
	-v "$PWD":/src:ro -v "$KEYS":/keys:ro -v "$OUTREPO":/repo -v "$PWD/.cache/apk":/cache \
	-e WISP_PKGVER="$PKGVER" \
	alpine:3.24 /bin/sh /src/scripts/package-in-container.sh
