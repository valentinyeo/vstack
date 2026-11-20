#!/bin/sh
# The valentin-mode version is a plain count: how many commits touched this
# folder on HEAD, and the same count on origin/main. Prints one line and always
# exits 0: an installed copy that is not a git checkout still says so instead of
# failing the skill's load.
set -u

dir=$(dirname "$0")

count=$(git -C "$dir" rev-list --count HEAD -- . 2>/dev/null) || count=
case "$count" in
'' | *[!0-9]*)
	echo "valentin-mode version unknown"
	exit 0
	;;
esac

latest=$(git -C "$dir" rev-list --count origin/main -- . 2>/dev/null) || latest=
case "$latest" in
'' | *[!0-9]*) latest=$count ;;
esac

if [ "$count" -ge "$latest" ]; then
	echo "valentin-mode v$count (latest)"
else
	echo "valentin-mode v$count, latest is v$latest (updates itself within 10 minutes)"
fi
exit 0
