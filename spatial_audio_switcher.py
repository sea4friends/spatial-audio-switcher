#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Spatial Audio Switcher - pick a HeSuVi HRIR for PipeWire virtual surround, preview it, apply it.

Uses only system packages: python-gobject (GTK 4 + libadwaita), ffmpeg, pipewire, pactl.
"""
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk, Pango  # noqa: E402

APP_ID = "io.github.sea4friends.SpatialAudioSwitcher"
HOME = Path.home()
DATA = HOME / ".local/share/spatial-audio-switcher"
LIBRARY = DATA / "hrir"
CACHE = HOME / ".cache/spatial-audio-switcher"
STATE_FILE = HOME / ".config/spatial-audio-switcher/state.json"
PW_HRIR = HOME / ".config/pipewire/hrir/current.wav"
PW_CONF = HOME / ".config/pipewire/filter-chain.conf.d/sink-virtual-surround.conf"
SERVICE = "filter-chain.service"
VIRTUAL_SINK = "effect_input.virtual-surround-7.1-hesuvi"
VIRTUAL_OUT = "effect_output.virtual-surround-7.1-hesuvi"
ALSA_SOUNDS = Path("/usr/share/sounds/alsa")

# Best-effort names for HeSuVi presets (HeSuVi itself only shows file names).
VENDORS = {
    "atmos": "Dolby Atmos for Headphones",
    "dh": "Dolby Headphone",
    "dht": "Dolby Home Theater v4",
    "dtshx": "DTS Headphone:X",
    "dvs": "Dolby Virtual Speaker",
    "ds3d": "DirectSound3D",
    "gsx": "Sennheiser GSX",
    "hear": "Hear",
    "nahimic": "Nahimic",
    "oal": "OpenAL Soft",
    "oal_cia": "OpenAL Soft (CIAIR set)",
    "oal_dflt": "OpenAL Soft (default set)",
    "ooyh": "Out Of Your Head",
    "razer": "Razer Surround",
    "razer_fix": "Razer Surround (fixed)",
    "sbx": "Creative SBX Pro Studio",
    "cmss_ent": "Creative CMSS-3D Entertainment",
    "cmss_game": "Creative CMSS-3D Game",
    "cmss_rx": "Creative CMSS-3D (rx)",
    "sonic": "Windows Sonic for Headphones",
    "ssc": "SSC room",
    "waves": "Waves Nx",
    "none": "No virtualization (reference)",
}
DATABASES = {
    "aria": "ARI dummy head", "ari": "ARI database", "cf": "Club Fritz (Neumann KU 100)",
    "ciair": "CIAIR", "cipic": "CIPIC database", "irc": "IRCAM Listen", "mit": "MIT KEMAR",
    "scut": "SCUT", "tub": "TU Berlin", "tuc": "TU Chemnitz",
}

# 7.1 test-clip channel order: FL FR FC LFE BL BR SL SR; spoken label per position.
POSITIONS = [(0, "Front_Left"), (2, "Front_Center"), (1, "Front_Right"), (7, "Side_Right"),
             (5, "Rear_Right"), (4, "Rear_Left"), (6, "Side_Left")]

# HeSuVi 14-ch order (as in PipeWire's hesuvi conf):
#   FL-L FL-R SL-L SL-R BL-L BL-R FC-L FR-R FR-L SR-R SR-L BR-R BR-L FC-R
# 7-ch files hold only the left half + FC-L; the right half is its mirror image.
MIRROR_7_TO_14 = "pan=14c|" + "|".join(
    [f"c{i}=c{i}" for i in range(7)] + [f"c{7 + i}=c{i}" for i in range(7)])
# ffmpeg headphone filter wants (left ear, right ear) pairs in map order FL FR FC LFE BL BR SL SR.
HEADPHONE_ORDER = "pan=16c|" + "|".join(f"c{o}=c{i}" for o, i in enumerate(
    [0, 1, 8, 7, 6, 13, 6, 13, 4, 5, 12, 11, 2, 3, 10, 9]))
FF = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]


def run(cmd, check=True):
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def describe(stem):
    """Human label for a HRIR file stem like 'sbx67-' or 'dh++'."""
    base = stem.rstrip("+-")
    suffix = stem[len(base):]
    variant = f"  [variant {suffix}]" if suffix else ""
    if base in VENDORS:
        return VENDORS[base] + variant
    if base.startswith("sbx"):
        return f"{VENDORS['sbx']} {base[3:]}%{variant}"
    if base.startswith("oal_cia"):
        return f"{VENDORS['oal_cia']} #{base[7:]}{variant}"
    if base.startswith("ooyh"):
        return f"{VENDORS['ooyh']} #{base[4:]}{variant}"
    if base.startswith("ssc_"):
        return f"{VENDORS['ssc']}: {base[4:]}{variant}"
    return stem


class Hrir:
    def __init__(self, path, research):
        self.path = path
        self.research = research
        self.key = str(path.relative_to(LIBRARY))
        stem = path.stem
        if research:
            prefix = stem.rstrip("0123456789_")
            db = DATABASES.get(prefix, prefix.upper())
            num = stem[len(prefix):]
            self.label = f"Research: {db} {num}".rstrip()
        else:
            self.label = describe(stem)
        self.label += f"   ({stem})"


def scan_library():
    items = [Hrir(p, False) for p in sorted(LIBRARY.glob("*.wav"))]
    items += [Hrir(p, True) for p in sorted((LIBRARY / "more").glob("*.wav"))]
    return items


def database_notes():
    notes = {}
    info = LIBRARY / "more/info.csv"
    if info.exists():
        with open(info, encoding="utf-8", errors="replace") as fh:
            for row in csv.reader(fh, delimiter=";"):
                if len(row) >= 2:
                    notes[row[0].rstrip("*")] = row[1].split("/n")[0].strip()
    return notes


def channels(path):
    out = run(["ffprobe", "-v", "error", "-show_entries", "stream=channels", "-of", "csv=p=0", str(path)])
    return int(out.stdout.strip())


def to_hesuvi14(src, dst):
    """Write src as a 14-channel HeSuVi HRIR (mirroring 7-channel files)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".tmp.wav")
    af = ["-af", MIRROR_7_TO_14] if channels(src) == 7 else []
    run(FF + ["-i", str(src), *af, "-c:a", "pcm_f32le", str(tmp)])
    tmp.replace(dst)


def hardware_sinks():
    out = run(["pactl", "-f", "json", "list", "sinks"])
    sinks = []
    for s in json.loads(out.stdout):
        name = s["name"]
        if name.startswith(("effect_", "input.", "output.")):
            continue
        sinks.append((name, s.get("description") or name))
    return sinks


def default_sink():
    return run(["pactl", "get-default-sink"]).stdout.strip()


def system_output(names):
    """The system's current default output if it is one of names (real devices), else the first of names."""
    current = run(["pactl", "get-default-sink"], check=False).stdout.strip()
    return current if current in names else next(iter(names), None)


PINS_FILE = Path.home() / ".local/state/wireplumber/stream-properties"
PIN_PREFIX = "Output/Audio:application.name:"


def pinned_apps():
    """Names of apps WirePlumber has a per-app target for (what moving an app to a device leaves behind).
    A line is PREFIX<app name>={json}; the name may contain '=' or ':' so split at the '={'."""
    names = set()
    try:
        lines = PINS_FILE.read_text(errors="replace").splitlines()
    except OSError:
        return names
    for line in lines:
        if line.startswith(PIN_PREFIX) and "={" in line:
            name, _, js = line[len(PIN_PREFIX):].partition("={")
            try:
                if json.loads("{" + js).get("target"):
                    names.add(name)
            except ValueError:
                pass
    return names


def app_streams():
    """Apps playing sound right now: {application name: (sink-input ids, excluded, subtitle)}.
    Excluded = WirePlumber has a pin for the app. A stream on another sink without a pin was routed there
    by another app (e.g. an effects chain): shown, but not as excluded."""
    sinks = {s["index"]: s for s in json.loads(run(["pactl", "-f", "json", "list", "sinks"]).stdout)}
    pins = pinned_apps()
    apps = {}
    for s in json.loads(run(["pactl", "-f", "json", "list", "sink-inputs"]).stdout):
        name = s["properties"].get("application.name")
        if not name:
            continue
        sink = sinks.get(s["sink"], {})
        away = sink.get("name") != VIRTUAL_SINK
        desc = sink.get("description") or sink.get("name") or "another device"
        ids, _, shown = apps.get(name, ([], False, None))
        if away or shown is None:
            shown = desc if away else None
        apps[name] = (ids + [s["index"]], name in pins, shown)
    out = {}
    for name, (ids, pinned, shown) in apps.items():
        if pinned:
            sub = f"Excluded: plain stereo on {shown}" if shown else "Excluded"
        elif shown:
            sub = f"Routed to {shown} by another app"
        else:
            sub = "Virtual surround"
        out[name] = (ids, pinned, sub)
    return out


def set_excluded(name, excluded, output):
    """Move an app to the real output or back to the virtual sink. WirePlumber remembers the move per
    app; moving to the default output (the virtual sink) clears that memory, so the app follows the
    default again. That is also why this works only while virtual surround is the default output."""
    if default_sink() != VIRTUAL_SINK:
        raise RuntimeError("Turn on virtual surround as the default output first")
    ids = app_streams().get(name, ([],))[0]
    if not ids:
        raise RuntimeError(f"{name} is not playing sound right now")
    for i in ids:
        run(["pactl", "move-sink-input", str(i), output if excluded else VIRTUAL_SINK])


def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def write_pipewire_conf(target):
    """Generate the filter-chain config from PipeWire's bundled HeSuVi example."""
    src = Path("/usr/share/pipewire/filter-chain/sink-virtual-surround-7.1-hesuvi.conf").read_text()
    conf = src.replace('"hrir_hesuvi/hrir.wav"', json.dumps(str(PW_HRIR)))
    conf = conf.replace('node.description = "Virtual Surround Sink"',
                        'node.description = "Virtual Surround 7.1 (HRIR)"')
    conf = conf.replace(f'node.name      = "{VIRTUAL_OUT}"',
                        f'node.name      = "{VIRTUAL_OUT}"\n'
                        f'                target.object  = {json.dumps(target)}')
    if str(PW_HRIR) not in conf or "target.object" not in conf:
        raise RuntimeError("PipeWire example config has an unexpected format")
    PW_CONF.parent.mkdir(parents=True, exist_ok=True)
    PW_CONF.write_text("# Generated by Spatial Audio Switcher - edits are overwritten on Apply\n" + conf)


def sink_names():
    return run(["pactl", "list", "short", "sinks"]).stdout


def apply_hrir(src, target, make_default):
    """Install src as the active HRIR, (re)start the virtual sink on target, optionally make it default."""
    to_hesuvi14(src, PW_HRIR)
    write_pipewire_conf(target)
    run(["systemctl", "--user", "enable", SERVICE])
    run(["systemctl", "--user", "restart", SERVICE])
    for _ in range(50):  # the sink appears asynchronously after the restart
        if VIRTUAL_SINK in sink_names():
            break
        time.sleep(0.1)
    else:
        raise RuntimeError(f"{VIRTUAL_SINK} did not appear; see: journalctl --user -u {SERVICE}")
    if make_default:
        run(["pactl", "set-default-sink", VIRTUAL_SINK])


def ensure_test_clip():
    """7.1 clip: a voice names a position, then footsteps play there, circling the listener."""
    clip = CACHE / "surround71.wav"
    if clip.exists():
        return clip
    CACHE.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=CACHE) as tmpdir:
        tmp = Path(tmpdir)
        steps = tmp / "steps.wav"
        run(FF + ["-f", "lavfi", "-i",
                  "aevalsrc='(random(0)*2-1)*exp(-35*mod(t\\,0.33))':s=48000:d=1.65",
                  "-af", "highpass=f=150,lowpass=f=5000,volume=0.6", "-ac", "1", str(steps)])
        listing = tmp / "list.txt"
        with open(listing, "w") as fh:
            for idx, name in POSITIONS:
                seg = tmp / f"seg{idx}.wav"
                voice = ALSA_SOUNDS / f"{name}.wav"
                if voice.exists():
                    inputs = ["-i", str(voice), "-i", str(steps)]
                    graph = ("[0:a]aresample=48000,aformat=channel_layouts=mono[v];"
                             "[v][1:a]concat=n=2:v=0:a=1,")
                else:
                    inputs = ["-i", str(steps)]
                    graph = "[0:a]"
                graph += f"apad=pad_dur=0.4,pan=7.1|c{idx}=c0[o]"
                run(FF + inputs + ["-filter_complex", graph, "-map", "[o]", "-c:a", "pcm_f32le", str(seg)])
                fh.write(f"file '{seg}'\n")
        run(FF + ["-f", "concat", "-safe", "0", "-i", str(listing), "-c:a", "pcm_f32le", str(clip)])
    return clip


def render_preview(hrir):
    """Binaural render of the test clip through one HRIR, cached per file."""
    out = CACHE / "previews" / hrir.key.replace("/", "__")
    if out.exists() and out.stat().st_mtime >= hrir.path.stat().st_mtime:
        return out
    clip = ensure_test_clip()
    out.parent.mkdir(parents=True, exist_ok=True)
    h14 = out.with_suffix(".hrir14.wav")
    to_hesuvi14(hrir.path, h14)
    graph = (f"[1:a]{HEADPHONE_ORDER}[h];"
             "[0:a][h]headphone=map=FL|FR|FC|LFE|BL|BR|SL|SR:hrir=multich,loudnorm=I=-20:TP=-2[o]")
    run(FF + ["-i", str(clip), "-i", str(h14), "-filter_complex", graph,
              "-map", "[o]", "-ar", "48000", "-c:a", "pcm_s16le", str(out)])
    h14.unlink()
    return out


def render_plain_stereo():
    out = CACHE / "previews" / "_plain_stereo.wav"
    if out.exists():
        return out
    clip = ensure_test_clip()
    out.parent.mkdir(parents=True, exist_ok=True)
    run(FF + ["-i", str(clip), "-af",
              "pan=stereo|FL=FL+0.707*FC+0.707*SL+0.707*BL|FR=FR+0.707*FC+0.707*SR+0.707*BR,"
              "loudnorm=I=-20:TP=-2", "-ar", "48000", "-c:a", "pcm_s16le", str(out)])
    return out


def wide_factory(width_chars, max_width_chars):
    """Dropdown labels wider than the default (which cuts HRIR names short), full name as a tooltip."""
    factory = Gtk.SignalListItemFactory()
    factory.connect("setup", lambda _f, item: item.set_child(
        Gtk.Label(xalign=0, width_chars=width_chars, max_width_chars=max_width_chars,
                  ellipsize=Pango.EllipsizeMode.END)))

    def bind(_f, item):
        text = item.get_item().get_string()
        item.get_child().set_label(text)
        item.get_child().set_tooltip_text(text)

    factory.connect("bind", bind)
    return factory


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Spatial Audio Switcher")
        self.set_default_size(760, 720)
        self.state = load_state()
        self.player = None
        self.notes = database_notes()
        self.all_hrirs = scan_library()
        self.shown = []
        self.sinks = []

        self.toasts = Adw.ToastOverlay()
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        view.set_content(self.toasts)
        self.set_content(view)

        page = Adw.PreferencesPage()
        self.toasts.set_child(page)

        status = Adw.PreferencesGroup(title="Status")
        self.status_row = Adw.ActionRow(title="Applied technology")
        status.add(self.status_row)
        self.enable_row = Adw.SwitchRow(
            title="Use virtual surround as default output",
            subtitle="Off = apps play plain stereo straight to the output device")
        self.enable_row.connect("notify::active", self.on_enable_toggled)
        status.add(self.enable_row)
        page.add(status)

        tech = Adw.PreferencesGroup(title="Technology",
                                     description="Preview renders a 7.1 walk-around clip through the "
                                                 "selected HRIR and plays it on the output device, "
                                                 "without changing anything.")
        self.research_row = Adw.SwitchRow(title="Include research HRIR databases",
                                          subtitle="Measured heads: ARI, CIPIC, IRCAM, KEMAR…")
        self.research_row.connect("notify::active", lambda *_: self.fill_hrirs())
        tech.add(self.research_row)
        self.hrir_row = Adw.ComboRow(title="HRIR", enable_search=True)
        self.hrir_row.set_expression(Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))
        self.hrir_row.set_factory(wide_factory(-1, 40))  # the selected value in the row
        self.hrir_row.set_list_factory(wide_factory(50, 60))  # the popup list
        self.hrir_row.connect("notify::selected", lambda *_: self.update_hrir_note())
        tech.add(self.hrir_row)
        self.output_row = Adw.ComboRow(title="Output device",
                                       subtitle="Where the virtual surround sink sends its stereo signal")
        tech.add(self.output_row)
        page.add(tech)

        actions = Adw.PreferencesGroup(title="Actions")
        buttons = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=8,
                              row_spacing=8, max_children_per_line=3, homogeneous=True)
        self.busy_widgets = []
        for label, cb, css in [
            ("▶ Preview", self.on_preview, "suggested-action"),
            ("▶ Plain stereo", self.on_plain, None),
            ("■ Stop", self.on_stop, None),
            ("▶ Test applied sink", self.on_test_live, None),
            ("Apply", self.on_apply, "suggested-action"),
        ]:
            btn = Gtk.Button(label=label)
            if css:
                btn.add_css_class(css)
            btn.connect("clicked", cb)
            buttons.append(btn)
            if cb is not self.on_stop:
                self.busy_widgets.append(btn)
        actions.add(buttons)
        self.spinner = Adw.Spinner(margin_top=8, visible=False)
        actions.add(self.spinner)
        page.add(actions)

        exclude_label = Gtk.Label(label="Exclude", valign=Gtk.Align.END)
        exclude_label.add_css_class("dim-label")
        self.apps_group = Adw.PreferencesGroup(
            title="Apps", header_suffix=exclude_label,
            description="Apps playing sound right now. Exclude music players and browsers so they play "
                        "plain stereo; the choice is remembered for the next start.")
        self.app_rows = []
        self.apps_seen = None
        page.add(self.apps_group)
        # ponytail: polls pactl every second while the window is open; pactl subscribe if that ever shows up
        GLib.timeout_add_seconds(1, self.fill_apps, False)

        if self.state.get("hrir", "").startswith("more/"):
            self.research_row.set_active(True)  # fills the list via notify
        else:
            self.fill_hrirs()
        self.fill_sinks()
        self.refresh_status()
        self.fill_apps()

    # ---- data -> widgets
    def fill_hrirs(self):
        current = self.selected_hrir()
        wanted = current.key if current else self.state.get("hrir", "atmos.wav")
        research = self.research_row.get_active()
        self.shown = [h for h in self.all_hrirs if research or not h.research]
        self.shown.sort(key=lambda h: (h.research, h.label.lower()))
        self.hrir_row.set_model(Gtk.StringList.new([h.label for h in self.shown]))
        keys = [h.key for h in self.shown]
        self.hrir_row.set_selected(keys.index(wanted) if wanted in keys else 0)
        self.update_hrir_note()

    def fill_sinks(self):
        try:
            self.sinks = hardware_sinks()
        except (subprocess.CalledProcessError, ValueError, OSError) as e:
            self.toast(f"Cannot list output devices: {e}")
            self.sinks = []
        self.output_row.set_model(Gtk.StringList.new([d for _, d in self.sinks]))
        names = [n for n, _ in self.sinks]
        wanted = self.state.get("output")
        if wanted not in names:
            wanted = system_output(names)
        if wanted in names:
            self.output_row.set_selected(names.index(wanted))

    def fill_apps(self, force=True):
        """Rebuild the Apps rows; with force=False (the 1 s timer) only when something changed."""
        try:
            apps = app_streams()
        except (subprocess.CalledProcessError, ValueError, OSError) as e:
            if force:
                self.toast(f"Cannot list apps: {e}")
            return GLib.SOURCE_CONTINUE
        seen = {name: (excluded, sub) for name, (_, excluded, sub) in apps.items()}
        if not force and seen == self.apps_seen:
            return GLib.SOURCE_CONTINUE
        self.apps_seen = seen
        for row in self.app_rows:
            self.apps_group.remove(row)
        self.app_rows = []
        if not apps:
            self.app_rows.append(Adw.ActionRow(title="No app is playing sound", sensitive=False))
        for name, (_, excluded, sub) in sorted(apps.items(), key=lambda a: a[0].lower()):
            row = Adw.SwitchRow(title=GLib.markup_escape_text(name), active=excluded,
                                subtitle=GLib.markup_escape_text(sub))
            row.connect("notify::active", self.on_exclude, name)
            self.app_rows.append(row)
        for row in self.app_rows:
            self.apps_group.add(row)
        return GLib.SOURCE_CONTINUE

    def update_hrir_note(self):
        h = self.selected_hrir()
        if not h:
            return
        note = ""
        if h.research:
            prefix = h.path.stem.rstrip("0123456789_")
            note = next((v for k, v in self.notes.items() if k == prefix), "")
        self.hrir_row.set_subtitle(note or h.key)

    def refresh_status(self):
        applied = self.state.get("hrir")
        label = next((h.label for h in self.all_hrirs if h.key == applied), applied or "none")
        self.status_row.set_subtitle(label)
        active = run(["systemctl", "--user", "is-active", SERVICE], check=False).stdout.strip()
        is_default = default_sink() == VIRTUAL_SINK
        self.status_row.set_title(f"Applied technology  ·  sink {active}")
        self._syncing = True
        self.enable_row.set_active(is_default)
        self._syncing = False

    def selected_hrir(self):
        i = self.hrir_row.get_selected()
        return self.shown[i] if 0 <= i < len(self.shown) else None

    def selected_sink(self):
        i = self.output_row.get_selected()
        return self.sinks[i][0] if 0 <= i < len(self.sinks) else None

    # ---- helpers
    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=4))

    def in_background(self, work, done):
        """Run work() off the UI thread; done(result) or a toast on error back on it."""
        for w in self.busy_widgets:
            w.set_sensitive(False)
        self.spinner.set_visible(True)

        def finish(result, error):
            for w in self.busy_widgets:
                w.set_sensitive(True)
            self.spinner.set_visible(False)
            if error:
                self.toast(error)
            else:
                done(result)
            return False

        def target():
            try:
                result, error = work(), None
            except subprocess.CalledProcessError as e:
                result, error = None, (e.stderr or str(e)).strip().splitlines()[-1]
            except Exception as e:  # surface anything to the user instead of dying silently
                result, error = None, str(e)
            GLib.idle_add(finish, result, error)

        threading.Thread(target=target, daemon=True).start()

    def play(self, path, target):
        self.on_stop()
        cmd = ["pw-play"] + (["--target", target] if target else []) + [str(path)]
        self.player = subprocess.Popen(cmd, stderr=subprocess.DEVNULL)

    # ---- actions
    def on_preview(self, *_):
        h, sink = self.selected_hrir(), self.selected_sink()
        if h:
            self.in_background(lambda: render_preview(h), lambda p: self.play(p, sink))

    def on_plain(self, *_):
        sink = self.selected_sink()
        self.in_background(render_plain_stereo, lambda p: self.play(p, sink))

    def on_test_live(self, *_):
        if run(["systemctl", "--user", "is-active", SERVICE], check=False).stdout.strip() != "active":
            self.toast("Virtual surround sink is not running - press Apply first")
            return
        self.in_background(ensure_test_clip, lambda p: self.play(p, VIRTUAL_SINK))

    def on_stop(self, *_):
        if self.player and self.player.poll() is None:
            self.player.terminate()
        self.player = None

    def on_apply(self, *_):
        h, sink = self.selected_hrir(), self.selected_sink()
        if not h or not sink:
            self.toast("Select a technology and an output device first")
            return
        self.on_stop()
        make_default = self.enable_row.get_active() or "hrir" not in self.state

        def work():
            apply_hrir(h.path, sink, make_default)

        def done(_):
            self.state.update(hrir=h.key, output=sink)
            save_state(self.state)
            self.refresh_status()
            self.toast(f"Applied: {h.label}")

        self.in_background(work, done)

    def on_exclude(self, row, _pspec, name):
        excluded = row.get_active()
        try:
            set_excluded(name, excluded, self.state.get("output") or self.selected_sink())
            self.toast(f"{name}: " + ("plain stereo" if excluded else "virtual surround"))
        except (subprocess.CalledProcessError, RuntimeError) as e:
            self.toast(str(getattr(e, "stderr", "") or e).strip())
        # rebuild from the real state (flips the switch back on failure); not inside the row's own signal
        GLib.idle_add(lambda: self.fill_apps() and False)

    def on_enable_toggled(self, row, _pspec):
        if getattr(self, "_syncing", False):
            return
        if row.get_active():
            if VIRTUAL_SINK not in sink_names():
                self.toast("Virtual surround sink is not running - press Apply first")
                self._syncing = True
                row.set_active(False)
                self._syncing = False
                return
            target = VIRTUAL_SINK
        else:
            target = self.state.get("output") or self.selected_sink()
        if target:
            run(["pactl", "set-default-sink", target], check=False)
            self.toast("Default output: " + ("virtual surround" if row.get_active() else "plain stereo"))


def find_hrir(name):
    """Accept 'atmos', 'atmos.wav', 'more/ari002' or a path."""
    p = Path(name).expanduser()
    if p.is_file():
        return p
    for cand in (name, name + ".wav", "more/" + name, "more/" + name + ".wav"):
        if (LIBRARY / cand).is_file():
            return LIBRARY / cand
    sys.exit(f"Unknown HRIR: {name} (see --list)")


def cli(args):
    state = load_state()
    cmd = args[0]
    if cmd == "--list":
        for h in scan_library():
            print(f"{h.key:24s} {h.label}")
    elif cmd == "--outputs":
        for name, desc in hardware_sinks():
            print(f"{name:50s} {desc}")
    elif cmd == "--status":
        active = run(["systemctl", "--user", "is-active", SERVICE], check=False).stdout.strip()
        print(f"hrir:    {state.get('hrir', '-')}")
        print(f"output:  {state.get('output', '-')}")
        print(f"sink:    {active}")
        print(f"default: {default_sink()}")
    elif cmd == "--apply" and len(args) in (2, 3):
        src = find_hrir(args[1])
        target = (args[2] if len(args) == 3 else state.get("output")
                  or system_output([n for n, _ in hardware_sinks()]))
        if not target:
            sys.exit("No output device found: pass one from --outputs")
        apply_hrir(src, target, make_default=True)
        key = str(src.relative_to(LIBRARY)) if src.is_relative_to(LIBRARY) else str(src)
        state.update(hrir=key, output=target)
        save_state(state)
        print(f"Applied {key} -> {target}; default output is now the virtual surround sink")
    elif cmd == "--apps":
        for name, (_, _, sub) in app_streams().items():
            print(f"{name:40s} {sub}")
    elif cmd in ("--exclude", "--include") and len(args) == 2:
        output = state.get("output") or system_output([n for n, _ in hardware_sinks()])
        set_excluded(args[1], cmd == "--exclude", output)
        print(f"{args[1]}: " + ("plain stereo (remembered)" if cmd == "--exclude" else "virtual surround"))
    elif cmd == "--on":
        run(["pactl", "set-default-sink", VIRTUAL_SINK])
        print("Default output: virtual surround")
    elif cmd == "--off":
        if not state.get("output"):
            sys.exit("No output device recorded: use pactl set-default-sink <device>")
        run(["pactl", "set-default-sink", state["output"]])
        print(f"Default output: {state['output']} (plain stereo)")
    elif cmd == "--preview" and len(args) == 2:
        h = Hrir(find_hrir(args[1]), False) if args[1] != "plain" else None
        path = render_preview(h) if h else render_plain_stereo()
        target = state.get("output")
        subprocess.run(["pw-play"] + (["--target", target] if target else []) + [str(path)])
    else:
        print(__doc__.strip() + """

Usage: spatial-audio-switcher [--list | --outputs | --status | --on | --off
                               | --apply HRIR [OUTPUT] | --preview HRIR|plain
                               | --apps | --exclude APP | --include APP]
Without arguments the settings window opens.""")
        return 0 if cmd in ("-h", "--help") else 2
    return 0


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_activate(self):
        win = self.props.active_window
        if not win:
            if not LIBRARY.is_dir():
                print(f"HRIR library missing: {LIBRARY} - run install.sh", file=sys.stderr)
            win = Window(self)
        win.present()

    def do_shutdown(self):
        win = self.props.active_window
        if win:
            win.on_stop()
        Adw.Application.do_shutdown(self)


if __name__ == "__main__":
    for tool in ("ffmpeg", "ffprobe", "pactl", "pw-play", "systemctl"):
        if not shutil.which(tool):
            sys.exit(f"Missing required tool: {tool}")
    os.makedirs(CACHE, exist_ok=True)
    if len(sys.argv) > 1:
        try:
            sys.exit(cli(sys.argv[1:]))
        except subprocess.CalledProcessError as e:
            sys.exit((e.stderr or str(e)).strip())
        except RuntimeError as e:
            sys.exit(str(e))
    sys.exit(App().run(sys.argv))
