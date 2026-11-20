#!/bin/sh
# Which vstack commit last touched this skill, and how far the checkout sits
# behind origin/main. Prints one line and always exits 0: an installed copy that
# is not a git checkout still says so instead of failing the skill's load.
set -u

dir=$(dirname "$0")

version=$(git -C "$dir" log -1 --format='%cs %h' -- . 2>/dev/null) || version=
if [ -z "$version" ]; then
	echo "unknown (not a git checkout)"
	exit 0
fi

behind=$(git -C "$dir" rev-list --count HEAD..origin/main -- . 2>/dev/null) || behind=
case "$behind" in
'' | *[!0-9]*) behind=0 ;;
esac

if [ "$behind" -eq 0 ]; then
	echo "$version (latest)"
else
	echo "$version ($behind changes behind; the skill-update hook brings the latest)"
fi
exit 0
