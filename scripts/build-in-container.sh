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

log "Installing packages into rootfs"
PKGS=$(sed -e 's/#.*//' -e '/^[[:space:]]*$/d' "$SRC/packages.txt" | tr '\n' ' ')
mkdir -p "$ROOT/proc" "$ROOT/sys" "$ROOT/dev"
mount -t proc proc "$ROOT/proc"
mount --rbind /sys "$ROOT/sys"
mount --rbind /dev "$ROOT/dev"
cleanup() { umount -R "$ROOT/proc" "$ROOT/sys" "$ROOT/dev" 2>/dev/null || true; }
trap cleanup EXIT

# The grub trigger fails inside a container (no real disk to probe) - harmless,
# so tolerate apk's exit code and verify the important bits instead.
# shellcheck disable=SC2086
apk add --root "$ROOT" --initdb --arch x86_64 --cache-dir /cache --update-cache $PKGS || true
for f in boot/vmlinuz-lts usr/bin/openbox usr/bin/Xorg usr/bin/firefox; do
	[ -e "$ROOT/$f" ] || { echo "missing $f - package install failed"; exit 1; }
done
rm -f "$ROOT/etc/apk/cache"

log "Applying Wisp overlay"
cp -a "$SRC/overlay/." "$ROOT/"
chmod 755 "$ROOT"/usr/local/bin/* "$ROOT"/usr/local/sbin/* "$ROOT"/etc/local.d/*.start
chmod 600 "$ROOT/etc/doas.d/wisp.conf"

log "Rendering artwork"
mkdir -p "$ROOT/usr/share/backgrounds/wisp" "$ROOT/usr/share/icons/hicolor/scalable/apps" "$ROOT/usr/share/wisp"
for svg in "$SRC"/art/wallpapers/*.svg; do
	name=$(basename "$svg" .svg)
	rsvg-convert -w 1920 -h 1080 "$svg" -o "$ROOT/usr/share/backgrounds/wisp/$name.png"
done
ln -sf night.png "$ROOT/usr/share/backgrounds/wisp/default.png"
cp "$SRC/art/wisp.svg" "$SRC/art/wisp-start.svg" "$ROOT/usr/share/icons/hicolor/scalable/apps/"
# boot splash (raw PPM for busybox fbsplash)
rsvg-convert "$SRC/art/splash.svg" -o /tmp/splash.png
magick /tmp/splash.png "$ROOT/usr/share/wisp/splash.ppm"
magick identify -format '%w %h\n' /tmp/splash.png > "$ROOT/usr/share/wisp/splash.size"
# boot menu theme
GT="$ISO/boot/grub/themes/wisp"
mkdir -p "$GT"
cp "$SRC/scripts/grub-theme/theme.txt" "$GT/"
rsvg-convert -w 1920 -h 1080 "$SRC/art/grub-bg.svg" -o "$GT/bg.png"
magick -size 8x8 xc:'#24304a' "$GT/sel_c.png"

log "Configuring system"
chroot "$ROOT" /bin/sh -eu <<'EOF'
for s in devfs dmesg udev udev-trigger wisp-splash; do rc-update add $s sysinit; done
for s in modules sysctl hostname bootmisc hwclock zram-init; do rc-update add $s boot; done
for s in dbus elogind polkit networkmanager udisks2 ntpd earlyoom local; do rc-update add $s default; done
for s in mount-ro killprocs savecache; do rc-update add $s shutdown; done

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
# Hide developer/duplicate entries from the app launcher
for d in xfce4-about rofi-theme-selector tint2conf lxshortcut libfm-pref-apps pcmanfm-desktop-pref \
	gcr-prompter gcr-viewer org.gnome.OnlineAccounts.OAuth2 org.gnome.goa-daemon picom compton \
	org.xfce.mousepad-settings openbox rofi feh nm-applet conky nm-connection-editor xsettingsd; do
	f=/usr/share/applications/$d.desktop
	[ -f $f ] && echo 'NoDisplay=true' >> $f
done
rm -f /etc/xdg/autostart/picom.desktop /etc/xdg/autostart/compton.desktop
rename() { f=/usr/share/applications/$1.desktop; [ -f $f ] && sed -i "s/^Name=.*/Name=$2/" $f; }
rename pcmanfm Files
rename lxterminal Terminal
rename gpicview "Image Viewer"
rename galculator Calculator
rename org.xfce.mousepad "Text Editor"
rename mpv "Media Player"
rename atril "Document Viewer"
rename xarchiver Archives
rename org.pulseaudio.pavucontrol "Sound Mixer"
for d in htop; do f=/usr/share/applications/$d.desktop; [ -f $f ] && echo 'NoDisplay=true' >> $f; done
update-desktop-database -q /usr/share/applications 2>/dev/null || true
python3 -m compileall -q /usr/lib/wisp
rm -rf /var/cache/apk/*
EOF

cat > "$ROOT/etc/wisp-release" <<EOF
WISP_VERSION=$VERSION
BUILD_DATE=$(date -u +%Y-%m-%d)
EOF
sed -i "s/@VERSION@/$VERSION/g" "$ROOT/etc/os-release" "$ROOT/etc/issue"

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
