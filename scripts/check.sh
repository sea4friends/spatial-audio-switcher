#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Project check: bash scripts/check.sh   (exit 0 = pass, ~7 s)
# Safe for a live desktop: installs only into a throw-away HOME, runs the GUI on a virtual X server
# and touches only its own test stream (client name SASCheck). Never runs --apply/--on/--off, never
# restarts filter-chain, never changes the default sink.
# Optional: SAS_HESUVI_EXE=/path/to/HeSuVi_2.0.0.1.exe (unset = the install checks are skipped)
#           SAS_SCRATCH=dir for temp files (default $TMPDIR or /tmp)
cd "$(dirname "$0")/.." || exit 1
REPO=$PWD
FAILS=0
pass() { echo "PASS  $*"; }
fail() { echo "FAIL  $*"; FAILS=$((FAILS+1)); }
skip() { echo "SKIP  $*"; }
check() { local what=$1; shift; if "$@" >/dev/null 2>&1; then pass "$what"; else fail "$what"; fi; }

WORK=$(mktemp -d "${SAS_SCRATCH:-${TMPDIR:-/tmp}}/sas-check.XXXXXX")
TESTPID=
DEVPID=
SPPID=
PINS=$HOME/.local/state/wireplumber/stream-properties
# a run that died between "exclude on" and "exclude off" leaves a SASCheck pin; the stream is gone then, so just report it
stale_pin() { grep -q '^Output/Audio:application.name:SAS\(\\s\)\?Check\(\\sSp\)\?=.*"target"' "$PINS" 2>/dev/null; }
cleanup() {
  [ -z "$TESTPID" ] || kill "$TESTPID" 2>/dev/null
  [ -z "$DEVPID" ] || kill "$DEVPID" 2>/dev/null
  [ -z "$SPPID" ] || kill "$SPPID" 2>/dev/null
  if stale_pin; then
    echo "NOTE  a SASCheck pin is left in $PINS (run died mid exclude round trip); remove the SASCheck / SAS\\sCheck\\sSp line to clear it"
  fi
  rm -rf "$WORK"
}
trap cleanup EXIT
EXE=${SAS_HESUVI_EXE:-}
APPPY=$REPO/spatial_audio_switcher.py

# 1. shell syntax
check "bash -n install.sh uninstall.sh" bash -n install.sh uninstall.sh
if command -v shellcheck >/dev/null; then
  check "shellcheck (warnings) install.sh uninstall.sh scripts/check.sh" shellcheck -S warning install.sh uninstall.sh scripts/check.sh
else skip "shellcheck not installed"; fi

# 2. python compiles; --list on the real (read-only) library
check "python compiles" python3 -c "import sys; compile(open(sys.argv[1]).read(), sys.argv[1], 'exec')" "$APPPY"
if [ -d "$HOME/.local/share/spatial-audio-switcher/hrir" ]; then
  n=$(python3 "$APPPY" --list 2>/dev/null | wc -l)
  check "--list prints 312 entries (got $n)" test "$n" = 312
else skip "--list: HRIR library not installed"; fi

# 3. install.sh in sandbox HOMEs
inst() {  # inst HOME [env...] -- runs install.sh with no terminal, output in $WORK/out
  local h=$1; shift
  env -u XDG_DATA_HOME -u XDG_CACHE_HOME -u XDG_CONFIG_HOME HOME="$h" "$@" setsid -w bash "$REPO/install.sh" </dev/null >"$WORK/out" 2>&1
}
if [ ! -f "${EXE:-}" ]; then skip "install checks: no HeSuVi exe (set SAS_HESUVI_EXE)"; else
  SB=$WORK/home1; mkdir "$SB"; D=$SB/.local/share/spatial-audio-switcher; A=$SB/.local/share/applications
  mkdir -p "$A"; touch "$A/io.github.OLD.SpatialAudioSwitcher.desktop"
  if inst "$SB" HESUVI_EXE="$EXE"; then
    check "install: launcher entry" test -f "$A/io.github.sea4friends.SpatialAudioSwitcher.desktop"
    check "install: symlink" test -L "$SB/.local/bin/spatial-audio-switcher"
    n=$(find "$D/hrir" -name '*.wav' | wc -l); check "install: 312 HRIRs (got $n)" test "$n" = 312
    check "install: old launcher removed" test ! -e "$A/io.github.OLD.SpatialAudioSwitcher.desktop"
  else fail "install: first run"; cat "$WORK/out"; fi
  inst "$SB" HESUVI_EXE="$EXE"; check "install: rerun says already up to date" grep -q "already up to date" "$WORK/out"
  echo "# changed" >> "$D/spatial_audio_switcher.py"
  inst "$SB" HESUVI_EXE="$EXE"
  check "install: changed copy updated without terminal" grep -q "^Updated\." "$WORK/out"
  # tampered exe must be refused
  cp "$EXE" "$WORK/bad.exe"; echo x >> "$WORK/bad.exe"; mkdir "$WORK/home2"
  if inst "$WORK/home2" HESUVI_EXE="$WORK/bad.exe"; then fail "install: tampered exe accepted"
  else check "install: tampered exe refused with checksum message" grep -qi checksum "$WORK/out"; fi
  # curl | bash path from a local tarball, run from a directory without the sources
  git archive --prefix=sas/ -o "$WORK/src.tar.gz" HEAD 2>/dev/null || tar czf "$WORK/src.tar.gz" -C "$REPO/.." --transform 's|^[^/]*|sas|' "$(basename "$REPO")"
  mkdir "$WORK/home3" "$WORK/cwd"
  if (cd "$WORK/cwd" && env -u XDG_DATA_HOME -u XDG_CACHE_HOME -u XDG_CONFIG_HOME HOME="$WORK/home3" HESUVI_EXE="$EXE" \
        SAS_SRC="file://$WORK/src.tar.gz" setsid -w bash <"$REPO/install.sh" >"$WORK/out" 2>&1) \
     && [ -f "$WORK/home3/.local/share/spatial-audio-switcher/spatial_audio_switcher.py" ] \
     && [ -L "$WORK/home3/.local/bin/spatial-audio-switcher" ]; then pass "install: curl|bash path"
  else fail "install: curl|bash path"; cat "$WORK/out"; fi
fi

# 3b. Bazzite / other distros: fake os-release in a sandbox, pacman/sudo/rpm-ostree stubbed to record any call
printf 'ID=bazzite\n' > "$WORK/os-bazzite"; printf 'ID=debian\n' > "$WORK/os-debian"
STUBS=$WORK/stubs; mkdir "$STUBS"
for c in pacman sudo rpm-ostree; do printf '#!/bin/sh\necho "%s $*" >> "%s/called"\nexit 1\n' "$c" "$WORK" > "$STUBS/$c"; chmod +x "$STUBS/$c"; done
mkdir "$WORK/home4"
if inst "$WORK/home4" SAS_OS_RELEASE="$WORK/os-debian"; then fail "other ID: accepted"
else check "other ID: refused with CachyOS and Bazzite message" grep -q "CachyOS and Bazzite" "$WORK/out"; fi
# only the commands the Bazzite branch looks for, minus 7z
NOZ=$WORK/noz; mkdir "$NOZ"
for c in python3 pactl pw-play ffmpeg ffprobe curl sha256sum tar update-desktop-database systemctl mktemp rm setsid env bash; do
  p=$(command -v "$c") && ln -s "$p" "$NOZ/$c"
done
if inst "$WORK/home4" SAS_OS_RELEASE="$WORK/os-bazzite" PATH="$STUBS:$NOZ"; then fail "bazzite: missing 7z not detected"
else check "bazzite: missing 7z stops and names it" grep -q "Missing on this system: 7z" "$WORK/out"; fi
# stub ffmpeg that lists no headphone filter
FF=$WORK/noff; mkdir "$FF"; cp -P "$NOZ"/* "$FF"/; ln -sf "$(command -v 7z)" "$FF/7z"; rm "$FF/ffmpeg"
printf '#!/bin/sh\necho " ... scale V->V"\n' > "$FF/ffmpeg"; chmod +x "$FF/ffmpeg"
if inst "$WORK/home4" SAS_OS_RELEASE="$WORK/os-bazzite" PATH="$STUBS:$FF"; then fail "bazzite: missing headphone filter not detected"
else check "bazzite: missing ffmpeg headphone filter stops and names it" grep -q "Missing on this system: ffmpeg headphone filter" "$WORK/out"; fi
check "bazzite: missing dependency installs nothing, calls no pacman/sudo/rpm-ostree" test ! -e "$WORK/called" -a ! -e "$WORK/home4/.local"
if [ -f "${EXE:-}" ]; then
  if inst "$WORK/home4" SAS_OS_RELEASE="$WORK/os-bazzite" HESUVI_EXE="$EXE" PATH="$STUBS:$PATH"; then
    check "bazzite: installs when everything is present" test -L "$WORK/home4/.local/bin/spatial-audio-switcher"
    check "bazzite: no pacman/sudo/rpm-ostree called" test ! -e "$WORK/called"
  else fail "bazzite: install with all dependencies present"; cat "$WORK/out"; fi
else skip "bazzite: full install (no HeSuVi exe)"; fi

# 4+5. GUI smoke and exclude round trip on a virtual X server, test stream SASCheck only
if [ ! -d "$HOME/.local/share/spatial-audio-switcher/hrir" ]; then skip "GUI checks: HRIR library not installed"
elif ! command -v xvfb-run >/dev/null || ! command -v paplay >/dev/null || ! command -v ffmpeg >/dev/null; then skip "GUI checks: xvfb-run, paplay or ffmpeg missing"
else
  ffmpeg -loglevel error -f lavfi -i anullsrc=r=48000:cl=stereo -t 40 "$WORK/silence.wav"
  paplay --client-name=SASCheck "$WORK/silence.wav" & TESTPID=$!
  # a name with a space: WirePlumber stores it escaped (SAS\sCheck\sSp) and the app must decode it
  paplay --client-name="SAS Check Sp" "$WORK/silence.wav" & SPPID=$!
  # a second stream started on a real device by the player itself (never moved by us): not excluded, no pin
  DEVSINK=$(pactl list short sinks | awk '$2 !~ /^(effect_|input\.|output\.)/ {print $2; exit}')
  if [ -n "$DEVSINK" ]; then paplay --client-name=SASCheckDev --device="$DEVSINK" "$WORK/silence.wav" & DEVPID=$!; fi
  # the exclude round trip moves the stream to the real output, which only works with surround as default
  if [ "$(pactl get-default-sink)" = effect_input.virtual-surround-7.1-hesuvi ]; then EXCL=1; else EXCL=0; fi
  env -u WAYLAND_DISPLAY GDK_BACKEND=x11 GSK_RENDERER=cairo EXCL="$EXCL" DEV="$DEVSINK" PINS="$PINS" APPPY="$APPPY" \
    timeout 60 xvfb-run -a -s "-screen 0 1280x900x24" python3 -u - <<'PY'
import gi, importlib.util, os, sys, time
gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk
spec = importlib.util.spec_from_file_location("sas", os.environ["APPPY"])
sas = importlib.util.module_from_spec(spec); spec.loader.exec_module(sas)

class App(sas.App):
    def __init__(self):
        sas.Adw.Application.__init__(self, application_id=sas.APP_ID + ".Check", flags=Gio.ApplicationFlags.NON_UNIQUE)

app = App(); app.register(None); app.activate()
win = app.props.active_window

def wait(cond, secs):
    end = time.time() + secs
    while time.time() < end:
        while GLib.MainContext.default().iteration(False): pass
        if cond(): return True
        time.sleep(0.05)
    return False

def row(name="SASCheck"):
    return next((r for r in win.app_rows if r.get_title() == name), None)

def pinned(name="SASCheck"):
    name = name.replace(" ", "\\s")
    try: return any(l.startswith("Output/Audio:application.name:" + name + "=") and '"target"' in l
                    for l in open(os.environ["PINS"]))
    except OSError: return False

def labels(w):
    c = w.get_first_child()
    while c:
        if isinstance(c, Gtk.Label): yield c
        yield from labels(c)
        c = c.get_next_sibling()

ok = True
def result(good, what):
    global ok; ok &= bool(good)
    print(("PASS  " if good else "FAIL  ") + what)

result(win is not None and win.hrir_row.get_model().get_n_items() > 0, "GUI: window builds, HRIR list filled")
# the popup list items are built by the list factory under the row; each label carries its tooltip
result(wait(lambda: any(l.get_tooltip_text() for l in labels(win.hrir_row) if l.get_label()), 5),
       "GUI: HRIR dropdown list items have tooltips")
result(wait(row, 4), "GUI: Apps shows a row for SASCheck")
if os.environ["DEV"]:
    result(wait(lambda: row("SASCheckDev"), 4), "GUI: Apps shows a row for the --device stream")
    d = row("SASCheckDev")
    result(d is not None and not pinned("SASCheckDev"), "--device stream leaves no WirePlumber target")
    result(d is not None and not d.get_active() and (d.get_subtitle() or "").startswith("Routed to "),
           "--device stream: switch off, subtitle says Routed to")
    cli = os.popen("python3 " + os.environ["APPPY"] + " --apps").read().splitlines()
    result(any(l.startswith("SASCheckDev") and "Routed to" in l for l in cli), "--apps: --device stream is Routed to, not excluded")
else:
    print("SKIP  --device stream: no real output sink")
if os.environ["EXCL"] == "1" and row():
    row().set_active(True)
    result(wait(pinned, 6), "exclude on: SASCheck pinned in WirePlumber state")
    result(wait(lambda: row() is not None and row().get_active()
                and (row().get_subtitle() or "").startswith("Excluded: plain stereo on "), 4),
           "exclude on: switch on, subtitle says Excluded")
    row().set_active(False)
    result(wait(lambda: not pinned(), 6), "exclude off: pin cleared")
    result(wait(lambda: row() is not None and not row().get_active() and row().get_subtitle() == "Virtual surround", 4),
           "exclude off: switch off, subtitle says Virtual surround")
    sp = "SAS Check Sp"
    if wait(lambda: row(sp), 4):
        row(sp).set_active(True)
        result(wait(lambda: pinned(sp), 6), "exclude on (name with space): pinned in WirePlumber state")
        result(wait(lambda: row(sp) is not None and row(sp).get_active()
                    and (row(sp).get_subtitle() or "").startswith("Excluded: plain stereo on "), 4),
               "exclude on (name with space): switch on, subtitle says Excluded")
        row(sp).set_active(False)
        result(wait(lambda: not pinned(sp), 6), "exclude off (name with space): pin cleared")
        result(wait(lambda: row(sp) is not None and not row(sp).get_active() and row(sp).get_subtitle() == "Virtual surround", 4),
               "exclude off (name with space): switch off, subtitle says Virtual surround")
    else:
        result(False, "GUI: Apps shows a row for the name-with-space stream")
else:
    print("SKIP  exclude round trip: surround is not the default output (or no SASCheck row)")
sys.exit(0 if ok else 1)
PY
  rc=$?
  [ $rc -eq 0 ] || FAILS=$((FAILS+1))
  kill "$TESTPID" 2>/dev/null; wait "$TESTPID" 2>/dev/null; TESTPID=
  [ -z "$DEVPID" ] || { kill "$DEVPID" 2>/dev/null; wait "$DEVPID" 2>/dev/null; DEVPID=; }
  kill "$SPPID" 2>/dev/null; wait "$SPPID" 2>/dev/null; SPPID=
fi

[ $FAILS -eq 0 ] && echo "ALL CHECKS PASSED" || echo "$FAILS CHECK(S) FAILED"
[ $FAILS -eq 0 ]
