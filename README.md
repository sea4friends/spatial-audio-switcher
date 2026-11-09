# Spatial Audio Switcher

HRIR virtual surround for headphones on CachyOS (PipeWire), with a GTK 4
settings window and a CLI.

Games on headphones usually sound flat: a 7.1 mix folded down to stereo keeps
only left/right differences, so "front left" and "rear left" sound the same.
This is what Creative's CMSS-3D / SBX, Dolby Headphone and Windows Sonic fix on
Windows; Linux has no equivalent out of the box.

## How it works

A PipeWire `filter-chain` sink convolves 7.1 audio with an HRIR (a recording of
how a head and ears change sound from each direction) and outputs binaural
stereo. Games send 7.1 to the sink and hear positions all around them.

    game (7.1) -> effect_input.virtual-surround-7.1-hesuvi -> your output device -> headphones

HRIRs come from HeSuVi (MIT, Matt Gore): 57 captures of commercial
virtualizers (Dolby Atmos, DTS Headphone:X, CMSS-3D, SBX, GSX, Razer, Windows
Sonic...) plus 255 research measurements (ARI, CIPIC, IRCAM, KEMAR...).
Which one sounds right is personal, so the app renders a walk-around test clip
through any of them for A/B comparison before applying one.

## Install

CachyOS only. Run as your user, **without** sudo:

```sh
curl -fsSL https://raw.githubusercontent.com/sea4friends/spatial-audio-switcher/main/install.sh | bash
```

or from a clone: `bash install.sh`.

The installer:

1. installs missing packages with `pacman` (asks for your password via sudo):
   `python python-gobject gtk4 libadwaita pipewire pipewire-audio pipewire-pulse
   wireplumber libpulse ffmpeg curl 7zip alsa-utils desktop-file-utils`;
2. downloads HeSuVi 2.0.0.1 (26 MB) from SourceForge, checks its SHA-256 and
   extracts only the HRIR `.wav` files; nothing from that Windows installer is
   executed. `HESUVI_EXE=/path/to.exe` reuses an already downloaded copy;
3. puts the app in `~/.local` and adds a launcher entry.

Re-running is safe: the download is skipped once the library is there, and the
last applied technology is re-applied if
`~/.config/spatial-audio-switcher/state.json` survived.

Removal: `bash uninstall.sh` (restores the previous default output first;
packages are left installed).

## Use

Launcher entry: **Spatial Audio Switcher**. Pick a technology, press *Preview*
to hear the test clip through it without changing anything, then *Apply*.
The output device starts as your system's current default and can be changed
in the window or with `--apply <hrir> <output>`; the choice is remembered.

```sh
spatial-audio-switcher --status          # what is applied
spatial-audio-switcher --list            # all 312 technologies
spatial-audio-switcher --preview dtshx   # hear one; "plain" = no HRIR, for comparison
spatial-audio-switcher --apply atmos     # switch
spatial-audio-switcher --off / --on      # plain stereo (music) / virtual surround (games)
spatial-audio-switcher --outputs         # output devices, for --apply <hrir> <output>
```

In games: choose **7.1 / Surround** output, and turn off any in-game HRTF and
any surround mode of the monitor, receiver or headset, or the sound is
processed twice.

Full runbook, including troubleshooting and how to switch by hand:
[`docs/runbook.html`](docs/runbook.html).

## Installed where

| Path | What |
|---|---|
| `~/.local/share/spatial-audio-switcher/` | app + HRIR library (312 files, ~33 MB) |
| `~/.local/bin/spatial-audio-switcher` | symlink for the CLI |
| `~/.local/share/applications/io.github.sea4friends.SpatialAudioSwitcher.desktop` | launcher entry |
| `~/.config/pipewire/filter-chain.conf.d/sink-virtual-surround.conf` | sink definition, regenerated on every Apply |
| `~/.config/pipewire/hrir/current.wav` | the applied HRIR (always 14-channel) |
| `~/.config/spatial-audio-switcher/state.json` | applied technology + output device |
| `~/.cache/spatial-audio-switcher/` | test clip and rendered previews, safe to delete |

The sink runs as the stock `filter-chain.service` user unit, so applying a
different HRIR restarts only that sink (~1 s) instead of all audio; streams that
follow the default output return to it on their own.

Not KDE-specific: the app is GTK 4 and the launcher entry is freedesktop
standard. Tested with Python 3.14, GTK 4.22, libadwaita 1.9, PipeWire 1.6,
ffmpeg 9.0.

## Checking it works

```sh
spatial-audio-switcher --status                 # sink: active, default: effect_input.virtual-...
pactl list short sinks | grep effect_input      # the virtual sink exists
spatial-audio-switcher --preview plain          # flat stereo, for comparison
spatial-audio-switcher --preview atmos          # same clip, positioned around you
```

While a game plays, `pactl list short sink-inputs` should show **8ch** for it.
If it shows 2ch, the game is still set to stereo.

## What it does not cover

- **Speakers.** HRIR is for headphones; through speakers it sounds worse.
- **Headphone EQ.** No correction for the headphones themselves (an AutoEQ
  profile in EasyEffects does that).
- **Stereo content.** Music through the sink plays from two virtual front
  speakers, which sounds duller than plain stereo; use `--off` for listening.
- **Rear/front confusion.** HRIRs are measured on someone else's head. If no
  preset convincingly places sounds behind you, try the research databases in
  the app ("Include research HRIR databases").
- **Vendor names are best-effort.** HeSuVi ships only file names; the product
  names in the app come from community naming and the `ssc_*` presets could not
  be traced to a product.

## License

GPL-3.0-or-later, see [LICENSE](LICENSE). The HRIR files are downloaded from
HeSuVi at install time (MIT) and are not part of this repository.
