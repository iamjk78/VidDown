#!/bin/sh
# Spustí VidDown pod uživatelem PUID:PGID, aby stažené soubory nepatřily rootovi.
set -e
if [ "$(id -u)" = "0" ]; then
  PUID="${PUID:-1000}"
  PGID="${PGID:-1000}"
  getent group "$PGID" >/dev/null 2>&1 || groupadd -o -g "$PGID" viddown
  getent passwd "$PUID" >/dev/null 2>&1 || useradd -o -u "$PUID" -g "$PGID" -d /data -s /bin/sh viddown
  mkdir -p /data /downloads
  chown "$PUID:$PGID" /data /downloads
  chown -R "$PUID:$PGID" /data
  export HOME=/data
  exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups viddown "$@"
fi
exec viddown "$@"
