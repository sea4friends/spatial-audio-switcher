#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Spatial Audio Switcher installer for CachyOS. Run as your user, not with sudo:
#   bash install.sh
#   curl -fsSL https://raw.githubusercontent.com/sea4friends/spatial-audio-switcher/main/install.sh | bash
# Installs missing packages with pacman (asks for your password via sudo), downloads the HeSuVi
# HRIR collection and puts the app in ~/.local. Re-running is safe.
set -euo pipefail
REPO=https://github.com/sea4friends/spatial-audio-switcher
SRC_TARBALL=${SAS_SRC:-$REPO/archive/refs/heads/main.tar.gz}
HESUVI_URL=https://sourceforge.net/projects/hesuvi/files/HeSuVi_2.0.0.1.exe/download
HESUVI_SHA256=a31774714d8f7a87ae4fd5bdbaa4bfa294a808296bdcc9e9935da4b427a601ba
PACKAGES=(python python-gobject gtk4 libadwaita pipewire pipewire-audio pipewire-pulse wireplumber
          libpulse ffmpeg curl 7zip alsa-utils desktop-file-utils)
DATA=$HOME/.local/share/spatial-audio-switcher
BIN=$HOME/.local/bin
APPS=$HOME/.local/share/applications
die() { echo "$*" >&2; exit 1; }

[ "$EUID" -ne 0 ] || die "Run without sudo: everything goes to your home folder; sudo is asked only for pacman."
ID=$(. /etc/os-release && echo "$ID")
[ "$ID" = cachyos ] || die "This installer is for CachyOS only (found: $ID)."
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

# 1. Packages
missing=$(pacman -T "${PACKAGES[@]}" || true)
if [ -n "$missing" ]; then
  echo "Installing packages: $missing"
  # shellcheck disable=SC2086  # one word per package
  sudo pacman -S --needed $missing </dev/tty
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

# 4. App + launcher entry
install -Dm755 "$HERE/spatial_audio_switcher.py" "$DATA/spatial_audio_switcher.py"
mkdir -p "$BIN" "$APPS"
ln -sf "$DATA/spatial_audio_switcher.py" "$BIN/spatial-audio-switcher"
sed "s|^Exec=.*|Exec=$BIN/spatial-audio-switcher|" "$HERE/spatial-audio-switcher.desktop" \
  > "$APPS/io.github.sea4friends.SpatialAudioSwitcher.desktop"
update-desktop-database "$APPS" 2>/dev/null || true
kbuildsycoca6 >/dev/null 2>&1 || true

# 5. Re-apply the last used technology when settings from an earlier install are still around
STATE=$HOME/.config/spatial-audio-switcher/state.json
if [ -f "$STATE" ]; then
  hrir=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("hrir",""))' "$STATE")
  [ -n "$hrir" ] && "$BIN/spatial-audio-switcher" --apply "$hrir"
fi
echo "Done. Open 'Spatial Audio Switcher' from the launcher, or run: spatial-audio-switcher --help"
