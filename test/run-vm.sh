#!/bin/sh
# Try Wisp OS in a virtual machine - nothing touches your real disk.
#   ./test/run-vm.sh            boot the live ISO with 1 GB RAM
#   ./test/run-vm.sh install    also attach a blank 8 GB virtual disk to test the installer
#   ./test/run-vm.sh disk       boot the installed virtual disk
# Needs QEMU:  brew install qemu
# Note: on Apple Silicon the x86 CPU is emulated, so it is slower than real hardware.
set -eu
cd "$(dirname "$0")/.."

ISO=$(ls -t out/wisp-os-*.iso 2>/dev/null | head -1)
DISK=out/test-disk.qcow2
RAM=${RAM:-1024}

ACCEL="-accel tcg,thread=multi -cpu max"
[ "$(uname -m)" = x86_64 ] && [ "$(uname)" = Darwin ] && ACCEL="-accel hvf -cpu host"
[ "$(uname)" = Linux ] && [ -w /dev/kvm ] && ACCEL="-accel kvm -cpu host"

DISPLAY_OPT="-display cocoa"
[ "$(uname)" = Darwin ] || DISPLAY_OPT="-display gtk"

set -- ${1:-live}
case "$1" in
	live) MEDIA="-cdrom $ISO -boot d" ;;
	install)
		[ -f "$DISK" ] || qemu-img create -f qcow2 "$DISK" 8G
		MEDIA="-cdrom $ISO -boot d -drive file=$DISK,if=virtio" ;;
	disk) MEDIA="-drive file=$DISK,if=virtio -boot c" ;;
	*) echo "usage: $0 [live|install|disk]"; exit 1 ;;
esac

# shellcheck disable=SC2086
exec qemu-system-x86_64 $ACCEL -smp 4 -m "$RAM" \
	-machine q35 -vga std $DISPLAY_OPT \
	-device intel-hda -device hda-output \
	-nic user,model=virtio-net-pci \
	-usb -device usb-tablet \
	$MEDIA
