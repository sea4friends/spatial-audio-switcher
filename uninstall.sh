#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Reverts install.sh: stops the virtual surround sink and removes the app, its library and its settings.
# Run without sudo (everything this tweak installs lives in $HOME).
set -euo pipefail
DATA=$HOME/.local/share/spatial-audio-switcher
STATE=$HOME/.config/spatial-audio-switcher/state.json

# 1. Put the default output back on the real device before the virtual sink disappears
if [ -f "$STATE" ]; then
  output=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("output",""))' "$STATE")
  [ -n "$output" ] && pactl set-default-sink "$output" || true
fi

# 2. Stop and remove the sink
systemctl --user disable --now filter-chain.service 2>/dev/null || true
rm -f "$HOME/.config/pipewire/filter-chain.conf.d/sink-virtual-surround.conf" \
      "$HOME/.config/pipewire/hrir/current.wav"
rmdir --ignore-fail-on-non-empty "$HOME/.config/pipewire/filter-chain.conf.d" \
      "$HOME/.config/pipewire/hrir" 2>/dev/null || true

# 3. Remove app, HRIR library, launcher entry, caches and settings
rm -rf "$DATA" "$HOME/.cache/spatial-audio-switcher" "$HOME/.config/spatial-audio-switcher"
rm -f "$HOME/.local/bin/spatial-audio-switcher" \
      "$HOME/.local/share/applications/io.github.sea4friends.SpatialAudioSwitcher.desktop"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
kbuildsycoca6 >/dev/null 2>&1 || true

echo "Removed. Default output is now: $(pactl get-default-sink)"
