#!/bin/sh
# Runs inside an x86_64 Alpine container (see build-package.sh).
set -eu
apk add -q --cache-dir /cache abuild rsvg-convert imagemagick font-inter
# abuild wants a writable source tree; work on a copy
rm -rf /build && mkdir /build
cp -a /src/overlay /src/art /src/keys /src/packages.txt /build/
mkdir -p /build/pkg && cp -a /src/pkg/wisp-desktop /build/pkg/
cp /keys/wisp-os.rsa /tmp/wisp-os.rsa
cp /src/keys/wisp-os.rsa.pub /etc/apk/keys/
cp /src/keys/wisp-os.rsa.pub /tmp/wisp-os.rsa.pub
export PACKAGER="Wisp OS <wisp@users.noreply.github.com>"
export PACKAGER_PRIVKEY=/tmp/wisp-os.rsa
export REPODEST=/tmp/out
cd /build/pkg/wisp-desktop
abuild -F -d -P "$REPODEST" -c 2>&1 | grep -v '^>>> wisp-desktop: Tracing dependencies' || true
ls "$REPODEST"/pkg/x86_64/wisp-desktop-"$WISP_PKGVER"-r0.apk >/dev/null
rm -rf /repo/x86_64
mkdir -p /repo/x86_64
cp "$REPODEST"/pkg/x86_64/* /repo/x86_64/
ls -l /repo/x86_64
