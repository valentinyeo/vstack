#!/bin/sh
# The valentin-mode version is a plain count: how many commits touched this
# folder on HEAD, and the same count on origin/main. Prints one line and always
# exits 0.
#
# An installed copy is not a git checkout: vstack install assembles it from
# symlinks, so its own folder has no history. Install writes those counts into
# a VERSION stamp next to this script (VSTA-203). Read git first, the stamp
# second, and say "unknown" only when neither has a number.
set -u

dir=$(dirname "$0")

count=$(git -C "$dir" rev-list --count HEAD -- . 2>/dev/null) || count=
latest=
case "$count" in
'' | *[!0-9]*)
	stamp="$dir/VERSION"
	count=
	if [ -f "$stamp" ]; then
		count=$(sed -n 's/^count=\([0-9][0-9]*\)$/\1/p' "$stamp" | head -n 1)
		latest=$(sed -n 's/^latest=\([0-9][0-9]*\)$/\1/p' "$stamp" | head -n 1)
	fi
	;;
esac

case "$count" in
'' | *[!0-9]*)
	echo "valentin-mode version unknown"
	exit 0
	;;
esac

case "$latest" in
'' | *[!0-9]*)
	latest=$(git -C "$dir" rev-list --count origin/main -- . 2>/dev/null) || latest=
	;;
esac
case "$latest" in
'' | *[!0-9]*) latest=$count ;;
esac

if [ "$count" -ge "$latest" ]; then
	echo "valentin-mode v$count (latest)"
else
	echo "valentin-mode v$count, latest is v$latest (update the shared checkout)"
fi
exit 0
