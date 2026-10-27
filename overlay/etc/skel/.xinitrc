#!/bin/sh
[ -f "$HOME/.Xresources" ] && xrdb -merge "$HOME/.Xresources"
export XDG_CURRENT_DESKTOP=Openbox
export XDG_SESSION_TYPE=x11
export MOZ_USE_XINPUT2=1
# No screen reader is installed, so don't start the accessibility bus with every app
export NO_AT_BRIDGE=1
export GTK_A11Y=none
exec dbus-launch --exit-with-session openbox-session
