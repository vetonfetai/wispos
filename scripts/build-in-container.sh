#!/bin/sh
# Runs inside an x86_64 Alpine container (see ../build.sh).
set -eu

SRC=/src
OUT=/out
WORK=/work
ROOT=$WORK/rootfs
ISO=$WORK/iso
VERSION=${WISP_VERSION:-0.1}
LABEL=WISP_LIVE
ALPINE_REL=v3.24

log() { printf '\033[1;35m==> %s\033[0m\n' "$*"; }

STAGE=${1:-rootfs}

# Stage 2 runs in a native (fast) container: squashfs is architecture-independent.
if [ "$STAGE" = squash ]; then
	apk add -q squashfs-tools
	log "Compressing root filesystem (squashfs/zstd)"
	rm -f "$ISO/wisp/rootfs.sfs"
	mksquashfs "$ROOT" "$ISO/wisp/rootfs.sfs" -comp zstd -Xcompression-level 19 -b 1M -noappend -no-progress -quiet
	ls -lh "$ISO/wisp/rootfs.sfs"
	exit 0
fi

if [ "$STAGE" = iso ]; then
	apk add -q grub grub-bios grub-efi xorriso mtools
	log "Building hybrid BIOS+UEFI ISO"
	sed "s/@LABEL@/$LABEL/g; s/@VERSION@/$VERSION/g" "$SRC/scripts/grub.cfg" > "$ISO/boot/grub/grub.cfg"
	NAME="wisp-os-$VERSION-x86_64.iso"
	grub-mkrescue -o "$OUT/$NAME" "$ISO" -- -volid "$LABEL" 2>&1 | grep -v -e '^xorriso' -e '^Drive current' -e '^Media' || true
	(cd "$OUT" && sha256sum "$NAME" > "$NAME.sha256")
	log "Done: $NAME"
	exit 0
fi

log "Installing build tools"
apk add -q rsvg-convert imagemagick font-inter

rm -rf "${WORK:?}"/*
mkdir -p "$ROOT/etc/apk" "$ISO/boot/grub" "$ISO/wisp"

cat > "$ROOT/etc/apk/repositories" <<EOF
https://dl-cdn.alpinelinux.org/alpine/$ALPINE_REL/main
https://dl-cdn.alpinelinux.org/alpine/$ALPINE_REL/community
EOF
cp -r /etc/apk/keys "$ROOT/etc/apk/"
cp "$SRC/keys/wisp-os.rsa.pub" "$ROOT/etc/apk/keys/"

log "Installing packages into rootfs"
# wisp-desktop (built by scripts/build-package.sh into out/repo) depends on everything
# in packages.txt, so installing it pulls in the whole system.
[ -f "$OUT"/repo/x86_64/APKINDEX.tar.gz ] || { echo "out/repo missing - run scripts/build-package.sh first"; exit 1; }
mkdir -p "$ROOT/proc" "$ROOT/sys" "$ROOT/dev"
mount -t proc proc "$ROOT/proc"
mount --rbind /sys "$ROOT/sys"
mount --rbind /dev "$ROOT/dev"
cleanup() { umount -R "$ROOT/proc" "$ROOT/sys" "$ROOT/dev" 2>/dev/null || true; }
trap cleanup EXIT

# The grub trigger fails inside a container (no real disk to probe) - harmless,
# so tolerate apk's exit code and verify the important bits instead.
apk add --root "$ROOT" --initdb --arch x86_64 --cache-dir /cache --update-cache \
	--repository "$OUT/repo" wisp-desktop || true
apk --root "$ROOT" info -e wisp-desktop >/dev/null || { echo "wisp-desktop not installed"; exit 1; }
for f in boot/vmlinuz-lts usr/bin/openbox usr/bin/Xorg usr/bin/firefox; do
	[ -e "$ROOT/$f" ] || { echo "missing $f - package install failed"; exit 1; }
done
rm -f "$ROOT/etc/apk/cache"

# Files only for a fresh install (later updates must not overwrite them)
cp -a "$SRC/image/." "$ROOT/"

log "Rendering boot menu theme"
GT="$ISO/boot/grub/themes/wisp"
mkdir -p "$GT"
cp "$SRC/scripts/grub-theme/theme.txt" "$GT/"
rsvg-convert -w 1920 -h 1080 "$SRC/art/grub-bg.svg" -o "$GT/bg.png"
magick -size 8x8 xc:'#24304a' "$GT/sel_c.png"

log "Configuring system"
chroot "$ROOT" /bin/sh -eu <<'EOF'
# services, system files and launcher names (the same script runs on every update)
/usr/lib/wisp/system-fixup all

adduser -D -s /bin/sh -g "Wisp User" wisp
for g in wheel video audio input netdev plugdev; do addgroup wisp $g 2>/dev/null || true; done
echo 'wisp:wisp' | chpasswd
passwd -l root

mkdir -p /home/wisp/Desktop /home/wisp/Documents /home/wisp/Downloads /home/wisp/Pictures /home/wisp/Music /home/wisp/Videos
chown -R wisp:wisp /home/wisp

# Trim: docs, headers, static libs, extra icon variants and sizes
rm -rf /usr/share/doc /usr/share/man /usr/share/info /usr/share/gtk-doc /usr/include
find /usr/lib -name '*.a' -delete
rm -rf /usr/share/icons/ePapirus /usr/share/icons/ePapirus-Dark /usr/share/icons/Papirus-Light
for t in Papirus Papirus-Dark; do
	rm -rf /usr/share/icons/$t/18x18 /usr/share/icons/$t/64x64 /usr/share/icons/$t/84x84
	sed -i -e 's#18x18/[a-z@x0-9]*,##g' -e 's#64x64/[a-z@x0-9]*,##g' -e 's#84x84/[a-z@x0-9]*,##g' /usr/share/icons/$t/index.theme
done
find /usr/share/locale -mindepth 1 -maxdepth 1 ! -name 'en*' -exec rm -rf {} +
for t in hicolor Papirus Papirus-Dark Adwaita; do gtk-update-icon-cache -q -f /usr/share/icons/$t 2>/dev/null || true; done
fc-cache -f >/dev/null
update-mime-database /usr/share/mime >/dev/null 2>&1 || true
rm -rf /var/cache/apk/*
EOF

log "Building live initramfs"
KVER=$(ls "$ROOT/lib/modules" | head -1)
cp "$SRC/scripts/live-init" "$ROOT/tmp/live-init"
chroot "$ROOT" mkinitfs -F "base ata cdrom ext4 mmc nvme scsi usb virtio squashfs wisplive" \
	-i /tmp/live-init -o /tmp/initramfs-live "$KVER"
mv "$ROOT/tmp/initramfs-live" "$ISO/boot/initramfs"
rm -f "$ROOT/tmp/live-init"
cp "$ROOT/boot/vmlinuz-lts" "$ISO/boot/vmlinuz"

cleanup
trap - EXIT
log "Root filesystem ready"
