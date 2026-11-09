# Headphone Surround Runbook

*Operator runbook · PipeWire HRIR virtual surround*

How to choose, preview and switch the virtual-surround technology that games play through, and how to recover when audio goes wrong.

OS **CachyOS** and **Bazzite** · Audio **PipeWire** + WirePlumber

## Quick start

1. Install (as your user, not with sudo):

   ```sh
   curl -fsSL https://raw.githubusercontent.com/sea4friends/spatial-audio-switcher/main/install.sh | bash
   ```

2. Open **Spatial Audio Switcher** from the launcher.
3. Pick a technology (start with *Dolby Atmos for Headphones*), press **Preview** to hear footsteps walk around you, try a few, then **Apply**.
4. In your game, set audio to **7.1 / Surround** and turn off in-game HRTF.
5. Music sounds dull through surround: play it, then turn on the **Exclude** switch next to the player in the **Apps** section. It is remembered.
6. To update, run the install command again. To remove: `curl -fsSL https://raw.githubusercontent.com/sea4friends/spatial-audio-switcher/main/uninstall.sh | bash`

Details for each step are below; problems are under [Troubleshooting](#troubleshooting).

## Signal path

Games send 7.1 audio to a virtual sink. The sink turns it into binaural stereo using an HRIR (a set of recorded ear responses) and sends it to your real output device: a headphone jack, a USB headset, or an HDMI monitor or receiver with headphones attached.

```
game (7.1) -> Virtual Surround 7.1 (effect_input.virtual-surround-7.1-hesuvi) -> Output device -> Headphones
```

- **Game / app**: 7.1 PCM, 48 kHz
- **Virtual Surround 7.1**: effect_input.virtual-surround-7.1-hesuvi · filter-chain.service
- **Output device**: chosen in the app; the system default at first
- **Headphones**: binaural stereo

All spatial processing happens in PipeWire, so any surround mode of the monitor, receiver or headset must stay **off**.

## Quick commands

The launcher entry **Spatial Audio Switcher** does the same things with a dropdown and Preview / Apply buttons. For the terminal, `spatial-audio-switcher` is in `~/.local/bin`.

**Show what is applied**

```sh
spatial-audio-switcher --status
```

**List every technology**

```sh
spatial-audio-switcher --list
```

**Hear one before applying**

```sh
spatial-audio-switcher --preview dtshx
spatial-audio-switcher --preview plain   # no HRIR, for comparison
```

**Switch technology**

```sh
spatial-audio-switcher --apply atmos
```

**Plain stereo (music, video)**

```sh
spatial-audio-switcher --off
```

**Back to virtual surround**

```sh
spatial-audio-switcher --on
```

**Keep an app in plain stereo (music player, browser)**

```sh
spatial-audio-switcher --apps                # apps playing sound right now
spatial-audio-switcher --exclude Spotify     # plain stereo, remembered
spatial-audio-switcher --include Spotify     # back to virtual surround
```

**Send to another output**

```sh
spatial-audio-switcher --outputs
spatial-audio-switcher --apply atmos <output-name>
```

**Open the settings window**

```sh
spatial-audio-switcher
```

## Technologies

Each code is a HeSuVi HRIR name; pass it to `--apply` or `--preview`. Suffixes `+` / `-` are alternative captures of the same product (HeSuVi does not document them; compare by ear). Codes marked † are 7-channel symmetric files: the app mirrors their left side to make the right side, so both ears match exactly.

| Product | Codes |
| --- | --- |
| Dolby Atmos for Headphones | `atmos-`† `atmos` |
| Creative CMSS-3D Entertainment | `cmss_ent-`† `cmss_ent` |
| Creative CMSS-3D Game | `cmss_game-`† `cmss_game` |
| Creative CMSS-3D (rx) | `cmss_rx+` `cmss_rx`† |
| Dolby Headphone | `dh++` `dh+` `dh-`† |
| Dolby Home Theater v4 | `dht-` `dht` |
| DirectSound3D | `ds3d+++` `ds3d++` `ds3d+` `ds3d`† |
| DTS Headphone:X | `dtshx-`† `dtshx` |
| Dolby Virtual Speaker | `dvs+` `dvs` |
| Sennheiser GSX | `gsx++` `gsx+` `gsx-`† `gsx` |
| Hear | `hear`† |
| Nahimic | `nahimic-`† `nahimic` |
| No virtualization (reference) | `none`† |
| OpenAL Soft | `oal+++` `oal++` `oal+` `oal_cia0`† `oal_cia1`† `oal_dflt`† |
| Out Of Your Head | `ooyh0` `ooyh1` |
| Razer Surround | `razer`† `razer_fix`† |
| Creative SBX Pro Studio | `sbx100-`† `sbx100` `sbx33-`† `sbx33` `sbx67-`† `sbx67` |
| Windows Sonic for Headphones | `sonic+` `sonic-`† `sonic` |
| SSC room presets (source unverified) | `ssc_dub` `ssc_hù+` `ssc_hù` `ssc_ny+` `ssc_ny` `ssc_syd+` `ssc_syd` |
| Waves Nx | `waves-`† `waves` |

> **Names are best-effort.** HeSuVi ships only file names. The product names come from the community naming for these captures; the SSC presets could not be traced to a product.

### Research HRIR databases

Measurements of real people and dummy heads. Enable **Include research HRIR databases** in the app to list them. Try them if none of the products above sounds convincing; one person's head may match yours better.

| Database | Sets | Example code |
| --- | ---: | --- |
| ARI database | 140 | `more/ari002` |
| ARI dummy head | 2 | `more/aria169` |
| Club Fritz (Neumann KU 100) | 12 | `more/cf01` |
| CIAIR | 1 | `more/ciair` |
| CIPIC database | 45 | `more/cipic003` |
| IRCAM Listen | 51 | `more/irc02` |
| MIT KEMAR | 1 | `more/mit` |
| SCUT | 1 | `more/scut` |
| TU Berlin | 1 | `more/tub` |
| TU Chemnitz | 1 | `more/tuc` |

## Procedures

### Switch technology in the app

1. Open **Spatial Audio Switcher** from the launcher.
2. Pick a technology in **HRIR**. The dropdown has search: type `dts`, `sbx` or `gsx`.
3. Press **Preview**. A voice names seven positions around you, each followed by footsteps. Nothing on the system changes. Press **Plain stereo** to hear the same clip without an HRIR.
4. Press **Apply**. Only the virtual sink restarts (about a second); other audio keeps playing, and games return to the sink on their own.
5. Press **Test applied sink** to hear the clip through the live sink.

### Set up a game

1. In the game's audio settings, choose **7.1** or **Surround**, not Headphones or Stereo.
2. Turn off in-game HRTF / "3D headphone" options, or the sound is processed twice.
3. Check that the game really sends 8 channels while it plays:

```sh
pactl list short sink-inputs   # the game's line should say 8ch
```

### Keep music in plain stereo

Music through the virtual sink plays from two virtual front speakers and sounds duller than plain stereo. Exclude the player once and it always plays straight to the output device, while games keep the surround.

1. Start the music so the player is playing sound.
2. In the app's **Apps** section, turn on the **Exclude** switch next to it. The list updates by itself every second.
3. Turning the switch off sends it back to virtual surround.

The choice is stored by WirePlumber per app name, the same as moving the app to another device in the desktop's volume applet. It can be set only while virtual surround is the default output, and only for apps that are playing sound. A browser is excluded as a whole, including browser games and videos in it.

### Switch without the app

For when the app is broken. 14-channel files can be copied; 7-channel files must be mirrored first.

```sh
# 14-channel file (not marked † in the table)
cp ~/.local/share/spatial-audio-switcher/hrir/dtshx.wav ~/.config/pipewire/hrir/current.wav

# 7-channel file: mirror to 14 channels
ffmpeg -y -i ~/.local/share/spatial-audio-switcher/hrir/razer.wav \
  -af "pan=14c|c0=c0|c1=c1|c2=c2|c3=c3|c4=c4|c5=c5|c6=c6|c7=c0|c8=c1|c9=c2|c10=c3|c11=c4|c12=c5|c13=c6" \
  -c:a pcm_f32le ~/.config/pipewire/hrir/current.wav

systemctl --user restart filter-chain.service
pactl set-default-sink effect_input.virtual-surround-7.1-hesuvi
```

> **The app's status will be out of date** after a manual switch, because it records the applied technology itself. Run `--apply` once to bring it back in line.

### Update, reinstall or move to another machine

The installer is per-user; sudo is asked only for pacman, on CachyOS. There it installs missing packages with pacman; on Bazzite nothing is installed system-wide and no reboot is needed (it only checks that the needed tools are present). It downloads the HeSuVi collection (26 MB, checksum verified) and extracts only its HRIR files; nothing from the Windows installer is run. Run again to update: it asks before replacing a different installed version.

```sh
curl -fsSL https://raw.githubusercontent.com/sea4friends/spatial-audio-switcher/main/install.sh | bash
```

### Remove everything

```sh
spatial-audio-switcher --off
systemctl --user disable --now filter-chain.service
rm ~/.config/pipewire/filter-chain.conf.d/sink-virtual-surround.conf ~/.config/pipewire/hrir/current.wav
rm -r ~/.local/share/spatial-audio-switcher ~/.cache/spatial-audio-switcher ~/.config/spatial-audio-switcher
rm ~/.local/bin/spatial-audio-switcher ~/.local/share/applications/io.github.sea4friends.SpatialAudioSwitcher.desktop
```

## Troubleshooting

| Symptom | Check | Fix |
| --- | --- | --- |
| No sound at all | `spatial-audio-switcher --status` | Run `--off` to play straight to the output device, then read `journalctl --user -u filter-chain -n 30`. |
| Virtual sink gone after reboot | `systemctl --user is-enabled filter-chain` | Press Apply in the app, or `systemctl --user enable --now filter-chain`. |
| Rear sounds seem to come from the front | `pactl list short sink-inputs` shows 2ch | The game is in stereo mode: set it to 7.1. If it is 8ch, try another technology; front/back perception differs per head. |
| Hollow, phasey, echoey sound | Game and device menus | Turn off in-game HRTF and any surround mode of the monitor, receiver or headset. |
| Music sounds dull | Default output is the virtual sink | Stereo music plays from two virtual front speakers. Exclude the player in **Apps** (or `--exclude <app>`), or use `--off`. |
| An app plays plain stereo although it should not | `spatial-audio-switcher --apps` says excluded | `--include <app>` while it plays, or turn off its **Exclude** switch in the app. |
| No sound after an output device change | `spatial-audio-switcher --outputs` | The output name changed: `--apply atmos <new-output>`. |
| "unexpected format" on Apply | A PipeWire update changed its example config | Compare `/usr/share/pipewire/filter-chain/sink-virtual-surround-7.1-hesuvi.conf` with `write_pipewire_conf()` in the app. |

## Files

| Path | Role |
| --- | --- |
| `~/.local/share/spatial-audio-switcher/hrir/` | HRIR library: 57 product captures + 255 research sets in `more/` |
| `~/.config/pipewire/hrir/current.wav` | The applied HRIR, always 14-channel |
| `~/.config/pipewire/filter-chain.conf.d/sink-virtual-surround.conf` | Sink definition, generated on every Apply from PipeWire's bundled example |
| `~/.config/spatial-audio-switcher/state.json` | Applied technology and output device |
| `~/.cache/spatial-audio-switcher/` | Test clip and rendered previews; safe to delete |
| `~/.local/state/wireplumber/stream-properties` | WirePlumber's per-app memory; excluded apps have a `"target"` there |

---

HRIRs from HeSuVi 2.0.0.1 (sourceforge.net/projects/hesuvi). Uses only CachyOS/Bazzite packages: python-gobject, GTK 4, libadwaita, ffmpeg, PipeWire. Licensed GPL-3.0-or-later.
