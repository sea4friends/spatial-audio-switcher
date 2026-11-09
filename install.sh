#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Spatial Audio Switcher installer for CachyOS and Bazzite. Run as your user, not with sudo:
#   bash install.sh
#   curl -fsSL https://raw.githubusercontent.com/sea4friends/spatial-audio-switcher/main/install.sh | bash
# On CachyOS installs missing packages with pacman (asks for your password via sudo); on Bazzite
# installs nothing system-wide and only checks that what it needs is there. Downloads the HeSuVi
# HRIR collection and puts the app in ~/.local. Re-running is safe.
set -euo pipefail
REPO=https://github.com/sea4friends/spatial-audio-switcher
SRC_TARBALL=${SAS_SRC:-$REPO/archive/refs/heads/main.tar.gz}
HESUVI_URL=https://sourceforge.net/projects/hesuvi/files/HeSuVi_2.0.0.1.exe/download
HESUVI_SHA256=a31774714d8f7a87ae4fd5bdbaa4bfa294a808296bdcc9e9935da4b427a601ba
PACKAGES=(python python-gobject gtk4 libadwaita pipewire pipewire-audio pipewire-pulse wireplumber
          libpulse ffmpeg curl 7zip alsa-utils desktop-file-utils)
# Bazzite already ships all of these; checked instead of installed (command names, then files)
BAZZITE_CMDS=(python3 pactl pw-play ffmpeg ffprobe 7z curl sha256sum tar update-desktop-database)
BAZZITE_FILES=(/usr/share/pipewire/filter-chain/sink-virtual-surround-7.1-hesuvi.conf
               /usr/lib/systemd/user/filter-chain.service /usr/share/sounds/alsa/Front_Left.wav)
DATA=$HOME/.local/share/spatial-audio-switcher
BIN=$HOME/.local/bin
APPS=$HOME/.local/share/applications
die() { echo "$*" >&2; exit 1; }

[ "$EUID" -ne 0 ] || die "Run without sudo: everything goes to your home folder; sudo is asked only for pacman on CachyOS."
# shellcheck source=/dev/null
ID=$(. "${SAS_OS_RELEASE:-/etc/os-release}" && echo "$ID")  # SAS_OS_RELEASE: for tests only
case $ID in cachyos|bazzite) ;; *) die "This installer is for CachyOS and Bazzite only (found: $ID)." ;; esac
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

# 1. Packages
if [ "$ID" = bazzite ]; then
  missing=
  for c in "${BAZZITE_CMDS[@]}"; do command -v "$c" >/dev/null || missing="$missing $c"; done
  python3 -c 'import gi; gi.require_version("Gtk","4.0"); gi.require_version("Adw","1")' 2>/dev/null \
    || missing="$missing python3-gobject/GTK4/libadwaita"
  for f in "${BAZZITE_FILES[@]}"; do [ -e "$f" ] || missing="$missing $f"; done
  [ -z "$missing" ] || die "Missing on this system:$missing
Bazzite normally ships these; nothing was installed. Update Bazzite and run this again."
else
  missing=$(pacman -T "${PACKAGES[@]}" || true)
  if [ -n "$missing" ]; then
    echo "Installing packages: $missing"
    # shellcheck disable=SC2086  # one word per package
    sudo pacman -S --needed $missing </dev/tty
  fi
fi

# 2. App sources: next to this script, or downloaded when run as curl | bash
HERE=$(cd "$(dirname "${BASH_SOURCE[0]:-.}")" && pwd)
if [ ! -f "$HERE/spatial_audio_switcher.py" ]; then
  echo "Downloading Spatial Audio Switcher..."
  mkdir "$tmp/src"
  curl -fsSL "$SRC_TARBALL" | tar xz -C "$tmp/src" --strip-components=1
  HERE=$tmp/src
fi

# 3. HRIR library (HeSuVi's presets + research databases), extracted from its installer - nothing is run
if [ ! -f "$DATA/hrir/atmos.wav" ]; then
  # HESUVI_EXE=/path/to/HeSuVi_2.0.0.1.exe skips the download
  if [ -n "${HESUVI_EXE:-}" ]; then cp "$HESUVI_EXE" "$tmp/hesuvi.exe"
  else
    echo "Downloading HeSuVi HRIR collection (26 MB)..."
    curl -fsSL -o "$tmp/hesuvi.exe" "$HESUVI_URL"
  fi
  echo "$HESUVI_SHA256  $tmp/hesuvi.exe" | sha256sum -c --quiet - \
    || die "HeSuVi download has an unexpected checksum; not using it."
  7z x -y -o"$tmp/x" "$tmp/hesuvi.exe" >/dev/null
  src=$(find "$tmp/x" -type d -path '*HeSuVi/hrir' | head -1)
  [ -n "$src" ] || die "hrir folder not found in the HeSuVi installer"
  mkdir -p "$DATA/hrir/more"
  cp "$src"/*.wav "$DATA/hrir/"
  cp "$src"/more/*.wav "$src"/more/info.csv "$DATA/hrir/more/"
fi
echo "HRIR library: $(find "$DATA/hrir" -name '*.wav' | wc -l) files in $DATA/hrir"

# 4. App: install, or update an installed copy that differs (asks first)
APP=$DATA/spatial_audio_switcher.py
if [ ! -f "$APP" ]; then
  install -Dm755 "$HERE/spatial_audio_switcher.py" "$APP"
elif cmp -s "$HERE/spatial_audio_switcher.py" "$APP"; then
  echo "Spatial Audio Switcher is already up to date."
else
  answer=y
  if (exec </dev/tty) 2>/dev/null; then  # no terminal (e.g. a script): update without asking
    read -rp "Another version of Spatial Audio Switcher is installed. Update it? [Y/n] " answer </dev/tty
  fi
  case $answer in
    [nN]*) echo "Kept the installed version."; exit 0 ;;
  esac
  install -Dm755 "$HERE/spatial_audio_switcher.py" "$APP"
  echo "Updated."
  pgrep -f "$BIN/spatial-audio-switcher" >/dev/null \
    && echo "The app is open: close and reopen its window to use the new version."
fi

# 5. Launcher entry (and removal of entries left by earlier app IDs)
DESKTOP=$APPS/io.github.sea4friends.SpatialAudioSwitcher.desktop
mkdir -p "$BIN" "$APPS"
ln -sf "$APP" "$BIN/spatial-audio-switcher"
for old in "$APPS"/*.SpatialAudioSwitcher.desktop; do
  [ "$old" = "$DESKTOP" ] || rm -f "$old"
done
sed "s|^Exec=.*|Exec=$BIN/spatial-audio-switcher|" "$HERE/spatial-audio-switcher.desktop" > "$DESKTOP"
update-desktop-database "$APPS" 2>/dev/null || true
kbuildsycoca6 >/dev/null 2>&1 || true

# 6. Bring the sink back after a reinstall (settings survived, sink not running); never restarts a running one
STATE=$HOME/.config/spatial-audio-switcher/state.json
if [ -f "$STATE" ] && ! systemctl --user is-active -q filter-chain.service; then
  hrir=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("hrir",""))' "$STATE")
  [ -n "$hrir" ] && "$BIN/spatial-audio-switcher" --apply "$hrir"
fi
echo "Done. Open 'Spatial Audio Switcher' from the launcher, or run: spatial-audio-switcher --help"
