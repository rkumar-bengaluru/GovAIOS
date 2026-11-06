#!/bin/bash
# seed-apps.sh SRC_REPO DEST_APPS: copy flows/*.yaml and pages/*.yaml, never overwriting.
# Run as the user (install.sh uses sudo -u). A symlinked DEST/flows/pages is refused; symlinked entries are skipped.
set -euo pipefail
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
umask 077 # every dir we create (parents too) is 0700
[ $# -eq 2 ] || { echo "usage: seed-apps.sh SRC_REPO DEST_APPS" >&2; exit 2; }
SRC=$1; DEST=$2
[ ! -L "$DEST" ] || { echo "refusing: $DEST is a symlink" >&2; exit 1; }
mkdir -p "$DEST"; chmod 0700 "$DEST"
for d in flows pages; do
  [ ! -L "$DEST/$d" ] || { echo "refusing: $DEST/$d is a symlink" >&2; exit 1; }
  mkdir -p "$DEST/$d"; chmod 0700 "$DEST/$d"
  [ -d "$SRC/$d" ] || continue
  for f in "$SRC/$d"/*.yaml; do
    [ -f "$f" ] && [ ! -L "$f" ] || continue
    n=$(basename "$f"); t="$DEST/$d/$n"
    if [ -L "$t" ]; then echo "not updated: $d/$n"
    elif [ -e "$t" ]; then cmp -s "$f" "$t" || echo "not updated: $d/$n"
    # exclusive, no-follow create (0600): a path that appeared since the check is skipped, never written through
    elif ! /usr/bin/python3 -I -c 'import os,sys
data=open(sys.argv[1],"rb").read()
fd=os.open(sys.argv[2],os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
try:
  with os.fdopen(fd,"wb") as o: o.write(data)
except BaseException:
  os.unlink(sys.argv[2]); raise' "$f" "$t" 2>/dev/null; then echo "not updated: $d/$n"; fi
  done
done
