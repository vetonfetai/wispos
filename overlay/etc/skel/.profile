export EDITOR=nano
export PATH="$HOME/.local/bin:$PATH"

# Start the desktop automatically on the first console.
if [ -z "$DISPLAY" ] && [ "$(tty)" = /dev/tty1 ]; then
	mkdir -p "$HOME/.cache"
	startx >"$HOME/.cache/xsession.log" 2>&1
	echo
	echo "  The desktop has exited. Type 'startx' to start it again."
	echo "  If graphics failed, see ~/.cache/xsession.log or boot with 'safe graphics'."
	echo
fi
