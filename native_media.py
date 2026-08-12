"""
native_media.py

Current version: v26.08.06.30

Optional PicoReader feature: play video/audio content -- streamed
directly from any plugin-registered domain (see register_stream_
domains() below), or downloaded local files -- via muOS's native mpv
or ffplay binaries, with gamepad controls translated to each player's
own keyboard shortcuts via a self-contained Linux uinput virtual-
keyboard -- no third-party binary (gptokeyb2/PortMaster) required.
Fully MIT-licensed, same as the rest of PicoReader; no bundled
executables, no GPL component. Fully plugin-agnostic (see the
ALLOWED_STREAM_DOMAINS section below) -- currently used by
librivox_fetch.py (audio) and any other plugin that registers its own
streaming domains the same way.

PLAYER SELECTION (v26.07.20.35): mpv is tried FIRST, ffplay is the
automatic fallback if mpv isn't found on a given device/build -- see
play_video_source()'s own docstring for the full reasoning (mpv has a real
on-screen progress bar via --osd-bar, which ffplay structurally has no
equivalent for; also Kaleb's own confirmed working default for
downloaded videos already).

CONTROL SCHEME (v26.07.29.09 -- CURRENT, read this if you're about to
touch any button mapping): video and audio now use the IDENTICAL scheme
(brought to parity at v26.07.29.09) -- every key sent by
_translate_loop() (video) and _audio_translate_loop() (audio) is a REAL
mpv and/or ffplay default, confirmed against mpv's own compiled-in
etc/input.conf and ffmpeg.org/ffplay.html rather than assumed. D-Pad
Left/Right = seek +-5s, D-Pad Up/Down = seek +-60s, L1/R1 = seek
+-10min, L2/R2 = chapter-skip (real on BOTH players -- see the
v26.07.29.11 accuracy note below) in single-file mode / track-skip in
a queue, X = mute, START = toggle permanent OSD (mpv only), SELECT =
toggle stats overlay (mpv only). Y differs by content: video = cycle
subtitles (real on both players); audio = toggle repeat (mpv only).
Speed control (mpv's '['/']') was REMOVED entirely at v26.07.29.07/.09
(Kaleb's report: unstable/laggy on the H700's hardware video decode
pipeline). See each function's own docstring for the complete current
table -- those docstrings are the single source of truth, this
top-of-file note deliberately does NOT re-list every key to avoid
re-duplicating (and re-going-stale on) the same information a third
place. Older comments elsewhere in this file describing earlier
schemes (brightness, speed control, a flat +-10min L2/R2 skip, or a
bundled input.conf overriding seek keys) predate this rewrite -- the
shared _MPV_INPUT_CONF now only overrides 't' (mpv has no real default
for subtitle-visibility toggle), every other key relies on mpv's own
genuine built-in default, no override needed.

ACCURACY CORRECTION (v26.07.29.11): ffplay's plain PGUP/PGDOWN already
does real chapter-seeking with an automatic +-10min fallback for
chapterless files (per ffmpeg.org/ffplay.html) -- NOT a plain seek
substitute as earlier comments in this file claimed. Same real feature
as mpv's, not a different one. If you find another comment anywhere in
this file still describing ffplay's PGUP/PGDOWN as "just a seek" with
"no chapter concept", it's stale -- fix it to match this note.

WHY UINPUT INSTEAD OF gptokeyb2: confirmed against muOS's own real source
(func.sh's GPTOKEYB() helper) that even muOS's own built-in Media Player
pulls the gptokeyb2 BINARY from PortMaster's install directory at runtime
-- meaning it is not guaranteed present on a stock muOS install (PortMaster
is a separate, optional setup step per muOS's own docs). Kaleb wants
PicoReader to remain a fully native app with no PortMaster dependency, so
this module implements the same underlying mechanism gptokeyb2 itself is
built on (Linux's /dev/uinput virtual-input-device API) directly, as
PicoReader's own code -- one implementation shared by both players, since
uinput key injection is player-agnostic (it's OS-level, not talking to
mpv/ffplay directly at all).

SCOPE (deliberate): only domains a loaded plugin has explicitly
registered via register_stream_domains() (see ALLOWED_STREAM_DOMAINS
below) -- no general "any URL" or "any local file" support. Every URL
is validated against that allowlist before either player is ever
invoked with it. This file itself knows nothing about which domains
are legitimate; librivox_fetch.py and any other streaming-capable
plugin each register their own real media-host domains at import time.

SECURITY: subprocess.run() is called with an argument LIST, never a shell
string -- no os.system()/os.execute()-style string interpolation anywhere
in this file, so a malicious/spoofed URL can't inject shell commands. This
is the one place in PicoReader that does real subprocess execution; every
other file in this project deliberately has none (see main.py's own
security-audit note). Scope is kept as narrow as possible specifically to
limit what that means in practice: validated JW-domain HTTPS URLs, or a
local file path this app itself just downloaded to ROMS/movies.

STATUS: CONFIRMED WORKING on real RG CubeXX-H and RG34XX-SP hardware --
the uinput device-creation/key-injection pipeline, and both mpv and
ffplay playback paths, are proven functional on real devices. The
current control scheme (above) has been simulated exhaustively off-
device (headless SDL, real App() instance, every button path dispatch-
checked) but the specific real-mpv-defaults REMAP itself (v26.07.27.01)
is NOT yet confirmed with real button presses on hardware -- that's
Kaleb's own next real-device test, not something simulation can finish
proving.
"""

import ctypes
import fcntl
import os
import json  # v26.07.23.16: used by the idle-backup crash-recovery file
import random
import shlex  # v26.07.30.01: safe shell-quoting for the GET_VAR/SET_VAR/
              # CAFFEINE/HOTKEY func.sh calls (see idle-suppress section)
import struct
import subprocess
import threading
import time
import urllib.parse


# ---------------------------------------------------------------------------
# v26.08.06.03 (Kaleb's request: rename native_video.py -> native_media.py
# and make it truly plugin-agnostic since it's now PUBLIC -- see main.py's
# top-of-file changelog for the full reasoning): the streaming allowlist
# used to be a hardcoded constant living HERE, specific to one particular
# plugin. That was the one piece of plugin-specific knowledge left in an
# otherwise generic file, and it's what justified this file being marked
# PRIVATE. Moved out to that plugin's own file, which registers its own
# domains into ALLOWED_STREAM_DOMAINS
# below via register_stream_domains() -- same mechanism librivox_fetch.py
# already uses for archive.org/librivox.org. This file now starts with a
# genuinely empty allowlist; nothing streams until SOME plugin registers
# its own real media-host domain(s) at import time.
ALLOWED_STREAM_DOMAINS = set()


def register_stream_domains(domains):
    """Lets a plugin add its own real media-host domain(s) to the
    streaming allowlist without this file needing to know the
    plugin's name. Safe to call multiple times (set, not list)."""

    for d in domains:
        ALLOWED_STREAM_DOMAINS.add(d.lower())

# ---------------------------------------------------------------------------
# v26.07.27.22 (Kaleb's request: "shuffle should feel more randomized,
# especially after the first shuffle -- have it randomize based on the
# first shuffle, avoiding the first 3-5 tracks from starting on top one
# more time"). A plain random.shuffle() is already a real, unbiased
# Fisher-Yates shuffle (confirmed -- no fixed random.seed() anywhere in
# this codebase), but a fair shuffle can still by chance re-open with a
# track from the very front of the LAST shuffle, which reads as "not
# random" even though it statistically isn't. _SHUFFLE_HEAD_MEMORY holds
# the identities of the last shuffle's opening tracks, IN-RAM ONLY for
# this running instance (module-level dict, never written to disk, reset
# on every app relaunch) -- video and audio tracked separately by queue
# kind so shuffling one never influences the other.
_SHUFFLE_HEAD_SIZE = 5
_SHUFFLE_HEAD_MEMORY = {"video": set(), "audio": set()}


def _shuffle_track_id(item):
    """Stable per-track identity for head-avoidance comparison -- prefers
    the real source URL (unique per track) over title (real playlists can
    have duplicate/blank titles)."""
    return item.get("_video_url") or item.get("_audio_url") or item.get("title") or id(item)


def _shuffled_order(items, kind):
    """Returns a freshly shuffled index order for `items`, avoiding (best
    effort) reusing any of the last shuffle's opening _SHUFFLE_HEAD_SIZE
    tracks as this shuffle's own opening tracks. First shuffle of a kind
    this instance has no memory yet, so it's just a normal shuffle.

    Direct construction, not rejection-sampling: splits items into
    "allowed" (wasn't in the last head) and "forbidden" (was), shuffles
    each pool separately, then builds the head from allowed tracks first.
    This GUARANTEES zero overlap whenever the queue has enough non-recent
    tracks to make that possible (the common case), in one single O(n)
    pass -- no retry loop, no chance of spinning or landing on a partial
    result by bad luck the way plain rejection-sampling could on a queue
    only a bit bigger than the head size. Degrades gracefully on a short
    queue: uses every allowed track it can, then fills any remaining head
    slots from the forbidden pool only as a last resort."""
    n = len(items)
    all_idx = list(range(n))
    last_head = _SHUFFLE_HEAD_MEMORY.get(kind, set())
    head_n = min(_SHUFFLE_HEAD_SIZE, n)

    if not last_head or head_n == 0:
        random.shuffle(all_idx)
        _SHUFFLE_HEAD_MEMORY[kind] = {_shuffle_track_id(items[i]) for i in all_idx[:head_n]}
        return all_idx

    allowed = [i for i in all_idx if _shuffle_track_id(items[i]) not in last_head]
    forbidden = [i for i in all_idx if _shuffle_track_id(items[i]) in last_head]
    random.shuffle(allowed)
    random.shuffle(forbidden)

    head = allowed[:head_n]
    rest = allowed[head_n:] + forbidden
    if len(head) < head_n:
        # Queue too small to fully avoid the last head -- top up with
        # forbidden tracks (unavoidable), then shuffle what's left of them
        # into the rest of the queue.
        short = head_n - len(head)
        head += forbidden[:short]
        rest = allowed[len(allowed):] + forbidden[short:]
    random.shuffle(rest)

    final_order = head + rest
    _SHUFFLE_HEAD_MEMORY[kind] = {_shuffle_track_id(items[i]) for i in final_order[:head_n]}
    return final_order


def is_allowed_stream_url(url):
    """True only for https:// URLs whose host is exactly one of the
    domains a plugin has registered via register_stream_domains(), or
    a subdomain of one (e.g. "b.jw-cdn.org" matches a registered
    "jw-cdn.org"; "notjw-cdn.org" does not -- checked via a leading-
    dot boundary, not a bare suffix match). This file has no domain
    knowledge of its own; ALLOWED_STREAM_DOMAINS is populated entirely
    by whichever plugins are loaded (see register_stream_domains())."""
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    if parts.scheme != "https" or not parts.hostname:
        return False
    host = parts.hostname.lower()
    return any(host == d or host.endswith("." + d) for d in ALLOWED_STREAM_DOMAINS)


# ---------------------------------------------------------------------------
# v26.07.20.15 (Kaleb's request): conditional pre-video memory trim.
# Deliberately NOT unconditional -- gc.collect()/malloc_trim() are not
# free (can pause tens to a couple hundred ms depending on what's
# allocated), so paying that cost before EVERY video, including short
# clips with no real memory pressure, would add a small consistent
# delay to the common case for no benefit. Instead this only acts when
# MemAvailable (Linux kernel's own "how much could actually be freed up
# for a new allocation" estimate -- NOT MemFree, which undercounts
# reclaimable cache/buffer memory) is genuinely low.
LOW_MEM_THRESHOLD_KB = 80 * 1024  # 80MB -- see maybe_trim_memory() docstring.
# v26.07.20.17 (Kaleb's request): lowered from 150MB. 150MB was a
# generous "definitely safe" guess, not measured. Kaleb correctly noted
# ffplay's own software-decode footprint at 480p/720p is genuinely small
# (tens of MB, not hundreds -- consistent with general embedded-Linux/
# RPi video player figures). 80MB is a middle ground: closer to what
# ffplay itself actually needs, while still leaving real headroom above
# that footprint for muOS's own background allocations and the gap
# between this check and ffplay finishing its own startup allocations --
# matching ffplay's footprint exactly would leave ~zero margin for
# anything else blipping during that window, which is exactly the
# scenario that causes an OOM-kill. Not derived from real on-device
# MemAvailable numbers yet -- the per-call logging added in v26.07.20.16
# is what should ultimately settle this: if real reading-session
# MemAvailable never approaches even 150MB in practice, that's the
# stronger signal for where this number truly belongs.


def get_mem_available_kb():
    """Returns /proc/meminfo's MemAvailable in KB, or None if it can't be
    read (e.g. not running on Linux, or the file format changes) --
    caller should treat None as "unknown, skip the check" rather than
    assuming either high or low pressure."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1])
    except Exception:
        pass
    return None


def _rss_kb():
    """Best-effort self RSS in KB via /proc/self/status -- for the
    before/after trim log line only, not used for the trim decision
    itself (that's MemAvailable, a system-wide figure, not this
    process's own RSS)."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except Exception:
        pass
    return None


def maybe_trim_memory(clear_caches_fn):
    """Checks real available RAM and, ONLY if it's below
    LOW_MEM_THRESHOLD_KB, calls `clear_caches_fn()` (caller-supplied --
    main.py's own texture-cache clearing, since this module has no
    knowledge of the reader's SDL state) then runs gc.collect() and
    glibc's malloc_trim(0) to actually hand freed memory back to the OS
    (gc.collect() alone frees it back to Python's/SDL's own allocator,
    but glibc doesn't always release that to the OS without an explicit
    trim). 80MB threshold: closer to ffplay's own real footprint while
    still leaving headroom for other allocations during the startup
    window (see LOW_MEM_THRESHOLD_KB's own comment for the reasoning) --
    not so low that it's basically "never fires". Returns True if a trim actually
    ran, False if skipped (either because there was enough headroom, or
    because MemAvailable couldn't be read at all -- fails safe by doing
    nothing rather than guessing). Best-effort: any exception from
    clear_caches_fn() itself is NOT caught here -- that's the caller's
    own reader-state logic and a bug there should surface normally, not
    be silently swallowed by this helper.

    v26.07.20.16 (Kaleb's question -- "how would I know if this is
    doing anything"): EVERY call now logs one line to FFPLAY_LOG with
    the MemAvailable reading and whether it skipped or trimmed, so a
    normal reading/video session on-device produces a visible record
    with no SSH/live-monitoring needed -- just check the log file
    afterward. When it DOES trim, also logs this process's own RSS
    before/after, so "did it actually free real memory" is answerable
    from the log alone, not just "did it decide to try"."""
    available = get_mem_available_kb()
    if available is None:
        _ffplay_log("[mem] MemAvailable unreadable -- skipped\n")
        return False
    if available >= LOW_MEM_THRESHOLD_KB:
        _ffplay_log(f"[mem] MemAvailable={available}KB (>= {LOW_MEM_THRESHOLD_KB}KB "
                     f"threshold) -- skipped, no trim needed\n")
        return False
    rss_before = _rss_kb()
    clear_caches_fn()
    import gc
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass  # non-glibc libc, or trim unavailable -- gc.collect() alone still helped some
    rss_after = _rss_kb()
    available_after = get_mem_available_kb()
    _ffplay_log(f"[mem] MemAvailable={available}KB (< {LOW_MEM_THRESHOLD_KB}KB threshold) "
                f"-- TRIMMED. RSS {rss_before}KB -> {rss_after}KB, "
                f"MemAvailable now {available_after}KB\n")
    return True




# ---------------------------------------------------------------------------
# ffplay discovery -- confirmed native to muOS (per Kaleb, and per muOS's
# own documented built-in Media Player system, which lists FFPlay as its
# default engine: muos.dev/systems/misc/mediaplayer). Checked at the
# standard system path first, falling back to PATH lookup for safety
# across muOS builds/devices.
_FFPLAY_CANDIDATES = ("/usr/bin/ffplay", "ffplay")


def find_ffplay():
    for candidate in _FFPLAY_CANDIDATES:
        if os.path.isabs(candidate):
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
        else:
            from shutil import which
            found = which(candidate)
            if found:
                return found
    return None


# ---------------------------------------------------------------------------
# Minimal Linux uinput bridge -- creates a virtual keyboard device and
# injects key press/release events. Constants below are the standard
# stable Linux kernel UAPI values (linux/input-event-codes.h,
# linux/uinput.h), not muOS-specific.

_UINPUT_PATH = "/dev/uinput"

EV_SYN = 0x00
EV_KEY = 0x01
SYN_REPORT = 0

# Key codes ffplay's own keyboard shortcuts respond to.
KEY_SPACE = 57
KEY_Q = 16
KEY_LEFT = 105
KEY_RIGHT = 106
KEY_UP = 103
KEY_DOWN = 108
# v26.07.21.01 (Kaleb's request): subtitle toggle. 't' is ffplay's own
# built-in default binding for "cycle subtitle stream" (its cycle
# includes a "none" state, so repeated taps effectively toggle on/off
# through whatever tracks exist -- confirmed via ffplay's documented
# default keymap, not guessed). mpv has no default binding on 't', so
# the bundled input.conf below adds "t cycle sub-visibility" explicitly
# -- same physical key drives both players, one shared KEY_T constant.
KEY_T = 20
KEY_I = 23  # 'i' -- v26.07.29.07: mpv's real default "toggle displaying
            # OSD stats" (script-binding stats/display-stats-toggle) --
            # codec, bitrate, resolution, dropped frames, etc. No real
            # ffplay equivalent, genuine no-op there.
# v26.07.21.02 (Kaleb's request): audio track cycle. 'a' is ffplay's own
# built-in default binding for "cycle audio channel". mpv has no default
# binding on 'a' either (its default audio-cycle key is '#'), so the
# bundled input.conf below adds "a cycle audio" explicitly -- same
# shared-key pattern as KEY_T/subtitles above.
KEY_A_LETTER = 30
# v26.07.27.01 REAL FIX (Kaleb: "mpv was fine, you're mapping the
# controls wrong" -- confirmed by pulling mpv's actual compiled-in
# default input.conf, github.com/mpv-player/mpv/blob/master/etc/
# input.conf, as ground truth rather than assumption). Several earlier
# sessions' D-pad schemes (brightness, then a custom KEY_G/KEY_V toggle
# pair) invented commands/keys instead of using mpv's own real
# defaults -- mpv's real 'v' key is actually "cycle sub-visibility"
# (subtitles), not video/album-art, and forcing "cycle video" on an
# audio-only stream with no real video track is a very plausible cause
# of a real on-device freeze Kaleb hit (D-pad Left/Right/Down, both
# local and streamed audio -- Left/Right also weren't genuine mpv
# defaults, just plain seek instead of mpv's real speed-control keys).
# All of that is now replaced with mpv's OWN real, documented default
# keys for the current unified scheme:
#   KEY_O + Shift      -- capital 'O', mpv's real default "no-osd
#     cycle-values osd-level 3 1" (permanent title/progress-bar
#     toggle). Lowercase 'o' is a DIFFERENT real default
#     ("show-progress", a momentary flash identical to what any other
#     action already triggers) -- capital O is the one that matches
#     the "toggle always-on" behavior actually wanted here.
#   KEY_LEFTBRACE/KEY_RIGHTBRACE -- '[' / ']', mpv's real default
#     speed-down-10%/speed-up-10% keys. LEGACY: speed control was
#     dropped from both video and audio entirely at v26.07.29.07/.09
#     (Kaleb's report: unstable/laggy on the H700's hardware video
#     decode pipeline) -- these constants are no longer tapped
#     anywhere, kept only in the uinput capability registration list
#     below (harmless if unused, same as other superseded keys there).
# Both confirmed ABSENT from ffplay's complete documented keymap
# (q/ESC/f/p/SPACE/m/9/0//,*;a/v/t/c/w/s/arrows/pgup/pgdn/mouse-click
# is the full real list) -- same genuine "unbound, true no-op" category
# as before, not a guess.
KEY_O = 24
KEY_LEFTBRACE = 26
KEY_RIGHTBRACE = 27
KEY_LEFTSHIFT = 42
KEY_M = 50  # 'm' -- v26.07.24.03: toggle mute, real native command on
            # both mpv and ffplay, see brightness-replacement comment above
# v26.07.27.05 (Kaleb's request -- Y/X in the audio player, after
# confirming volume keys are a no-op since muOS's own hardware volume
# mixer sits outside mpv/ffplay's software volume entirely): both
# confirmed real mpv defaults, cross-checked against ffplay's complete
# documented keymap (q/ESC/f/p/SPACE/m/9/0//,*;a/v/t/c/w/s/arrows/pgup/
# pgdn/mouse-click) -- neither 'l' nor Backspace appears there, so both
# are genuine, safe no-ops on ffplay, same as every other key here.
#   KEY_L + Shift -- capital 'L', mpv's real default
#     "cycle-values loop-file inf no" (toggle repeat on the current
#     track). Plain lowercase 'l' is a DIFFERENT real default (ab-loop,
#     mark-two-points looping) -- capital L is the simple whole-track
#     repeat toggle actually wanted here. Still audio's Y binding,
#     unchanged through every control reshuffle this session.
#   KEY_BACKSPACE -- mpv's real default "set speed 1" (reset playback
#     speed to normal). LEGACY: no longer tapped anywhere -- was
#     audio's X and video's X in turn, both superseded when speed
#     control itself was dropped entirely (see KEY_LEFTBRACE/
#     KEY_RIGHTBRACE above). Kept only in the uinput registration list.
KEY_L = 38
KEY_BACKSPACE = 14
# v26.07.27.21 (Kaleb's request -- Option B: give ffplay real
# substitute functionality on the buttons that are dead no-ops there,
# instead of leaving mpv-only features unreachable). Both confirmed
# real ffplay defaults (ffmpeg.org/ffplay.html "While playing"):
#   KEY_PAGEUP/KEY_PAGEDOWN -- ffplay's real "seek to previous/next
#     chapter, or +-10min if the file has no chapters" pair (verified
#     against ffmpeg.org/ffplay.html -- see the v26.07.29.11 accuracy
#     correction in the AI notes). Now video AND audio's L1/R1/L2/R2
#     all use this on ffplay -- see _translate_loop()'s/
#     _audio_translate_loop()'s own comments for the current mapping.
#   KEY_W -- ffplay's real "cycle video filters or show modes" key.
#     LEGACY: no longer tapped anywhere -- was audio's X (cycling
#     ffplay's built-in visualizer as a real substitute for mpv-only
#     speed-reset), superseded when audio's X became mute at
#     v26.07.29.09 and speed control was dropped entirely. Kept only
#     in the uinput registration list.
KEY_PAGEUP = 104
KEY_PAGEDOWN = 109
KEY_W = 17
# v26.07.21.22-33 (Kaleb's report, later disproven by Kaleb's own
# on-device test at v26.07.21.35: "it muted itself" -- kept this note
# as a record of what was tried and why it didn't work, rather than
# silently deleting the history). Original theory: sending a harmless
# synthetic keypress periodically would reset whatever "time since
# last input" muOS's idle watcher tracks, the same way a real button
# press does. Confirmed on real hardware this does NOT work -- the
# synthetic uinput keypress does not reset whatever timer actually
# gates DISPLAY_IDLE(). The REAL, proven mechanism is
# suppress_idle_display()/restore_idle_display() below -- found by
# examining how a real, shipped muOS app (Songo#5, a media player)
# solves this exact problem: not by resetting a timer, but by directly
# disabling the config values DISPLAY_IDLE() itself checks, then
# restarting the hotkey daemon so the change takes effect immediately.

_UI_SET_EVBIT = 0x40045564
_UI_SET_KEYBIT = 0x40045565
_UI_DEV_CREATE = 0x5501
_UI_DEV_DESTROY = 0x5502

# struct uinput_user_dev layout (older/portable UI_DEV_SETUP-free API):
# char name[UINPUT_MAX_NAME_SIZE=80]; struct input_id id (4x __u16 = 8
# bytes: bustype/vendor/product/version); __u32 ff_effects_max (4 bytes);
# then absmax[64]/absmin[64]/absfuzz[64]/absflat[64] (4 __s32 arrays of 64
# entries each = 1024 bytes) -- we leave all of that zeroed (this is a
# keyboard, not an absolute-axis device). Real kernel struct size is
# 80+8+4+1024 = 1116 bytes; verified against struct.calcsize() to catch
# any format-string drift before it silently writes a malformed device
# descriptor to the kernel.
_UINPUT_MAX_NAME_SIZE = 80
_UINPUT_USER_DEV_FMT = f"<{_UINPUT_MAX_NAME_SIZE}s HHHH I 1024x"
_DEVICE_NAME = b"PicoReader Virtual Keyboard"
assert struct.calcsize(_UINPUT_USER_DEV_FMT) == 1116, (
    "uinput_user_dev struct packing drifted from the real kernel size -- "
    "fix _UINPUT_USER_DEV_FMT before this is used")

# struct input_event layout: timeval (long sec, long usec -- 8 bytes each
# on 64-bit aarch64), then uint16 type, uint16 code, int32 value.
_INPUT_EVENT_FMT = "<qqHHi"


def _emit(fd, ev_type, code, value):
    ts = time.time()
    sec = int(ts)
    usec = int((ts - sec) * 1_000_000)
    os.write(fd, struct.pack(_INPUT_EVENT_FMT, sec, usec, ev_type, code, value))


class VirtualKeyboard:
    """Context-manager wrapper around a /dev/uinput virtual keyboard.
    Returns None from create() (never raises) if uinput isn't available
    or accessible -- callers treat that as "no gamepad controls this
    session" and still let the video play, rather than failing the whole
    feature over an input-translation nicety."""

    def __init__(self, fd):
        self._fd = fd

    @classmethod
    def create(cls):
        try:
            fd = os.open(_UINPUT_PATH, os.O_WRONLY | os.O_NONBLOCK)
        except OSError:
            return None
        try:
            fcntl.ioctl(fd, _UI_SET_EVBIT, EV_KEY)
            # v26.07.24.03 BUG FIX (found while wiring up the new video
            # D-pad bindings): KEY_G/KEY_V (audio's existing D-pad Up/
            # Down title/album-art toggle, shipped v26.07.23.26/.28)
            # were NEVER in this UI_SET_KEYBIT registration list -- a
            # uinput virtual device only reliably delivers key codes it
            # declared capability for at UI_DEV_CREATE time, so that
            # toggle was very likely silently non-functional on real
            # hardware this whole time, the same "button does nothing"
            # symptom as the unrelated brightness bug just fixed above,
            # but from a completely different root cause (missing
            # capability declaration, not an hwdec color-pipeline gap).
            # Added here alongside the new KEY_M (mute). KEY_BRIGHTNESS_
            # DOWN/UP removed -- no longer bound to anything.
            for key in (KEY_SPACE, KEY_Q, KEY_LEFT, KEY_RIGHT, KEY_UP, KEY_DOWN,
                        KEY_T, KEY_A_LETTER, KEY_I,
                        KEY_O, KEY_LEFTBRACE, KEY_RIGHTBRACE, KEY_LEFTSHIFT, KEY_M,
                        KEY_L, KEY_BACKSPACE, KEY_PAGEUP, KEY_PAGEDOWN, KEY_W):
                fcntl.ioctl(fd, _UI_SET_KEYBIT, key)
            dev = struct.pack(_UINPUT_USER_DEV_FMT, _DEVICE_NAME, 0x03, 0x1234, 0x5678, 1, 0)
            os.write(fd, dev)
            fcntl.ioctl(fd, _UI_DEV_CREATE)
        except OSError:
            try:
                os.close(fd)
            except OSError:
                pass
            return None
        # Give the kernel/udev a beat to register the new input device
        # before anything tries to use it -- same short settle delay
        # gptokeyb2 itself effectively gets from process-startup overhead.
        time.sleep(0.1)
        return cls(fd)

    def tap(self, key):
        """Press and release, with a real SYN_REPORT after each half --
        ffplay (like most terminal/X11 input consumers) only sees a key
        event once EV_SYN/SYN_REPORT flushes it."""
        try:
            _emit(self._fd, EV_KEY, key, 1)
            _emit(self._fd, EV_SYN, SYN_REPORT, 0)
            _emit(self._fd, EV_KEY, key, 0)
            _emit(self._fd, EV_SYN, SYN_REPORT, 0)
        except OSError:
            pass

    def tap_shifted(self, key):
        """Press+release `key` while KEY_LEFTSHIFT is held, same real
        SYN_REPORT-flushed pattern as tap(). Needed for mpv's real
        default permanent-OSD toggle, which is capital 'O' (Shift+o),
        not lowercase 'o' (a different real default, see KEY_O's own
        v26.07.27.01 comment above)."""
        try:
            _emit(self._fd, EV_KEY, KEY_LEFTSHIFT, 1)
            _emit(self._fd, EV_SYN, SYN_REPORT, 0)
            _emit(self._fd, EV_KEY, key, 1)
            _emit(self._fd, EV_SYN, SYN_REPORT, 0)
            _emit(self._fd, EV_KEY, key, 0)
            _emit(self._fd, EV_SYN, SYN_REPORT, 0)
            _emit(self._fd, EV_KEY, KEY_LEFTSHIFT, 0)
            _emit(self._fd, EV_SYN, SYN_REPORT, 0)
        except OSError:
            pass

    def close(self):
        try:
            fcntl.ioctl(self._fd, _UI_DEV_DESTROY)
        except OSError:
            pass
        try:
            os.close(self._fd)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Joystick -> ffplay key translation.
#
# v26.07.20.02: rewritten to match PicoReader's REAL input model, found by
# reading main.py's own event loop directly rather than assuming. main.py
# reads input entirely via SDL_PollEvent() (SDL_JOYBUTTONDOWN_EV /
# SDL_JOYHATMOTION_EV events) -- it never calls SDL_JoystickGetButton() or
# SDL_JoystickUpdate() anywhere, and the SDL_JoystickOpen(0) return value
# isn't even stored. An earlier draft of this module polled joystick state
# directly, which doesn't match how this app (or this SDL setup) actually
# works, and would not have functioned correctly. This version instead
# runs its own SDL_PollEvent() loop, using the identical ctypes struct
# layouts main.py's own input loop uses (copied field-for-field, not
# re-derived) so there's no risk of a mismatched struct silently misreading
# event data. Safe to run on a background thread here specifically because
# the main thread is blocked inside subprocess.run() for ffplay's entire
# duration -- nothing else is polling the event queue concurrently during
# that window.
#
# Button mapping passed in as JOY_A/JOY_B (main.py's own runtime-detected,
# device-specific SDL button indices -- see main.py's _sdl_map lookup) so
# this stays correctly mapped across devices rather than hardcoding index
# values here.

SDL_JOYHATMOTION_EV = 0x602
SDL_JOYBUTTONDOWN_EV = 0x603
SDL_HAT_UP = 1
SDL_HAT_RIGHT = 2
SDL_HAT_DOWN = 4
SDL_HAT_LEFT = 8

_POLL_INTERVAL = 0.01  # SDL_PollEvent itself is non-blocking; this just
                        # caps CPU use between empty polls.

# v26.07.21.35 REAL FIX (Kaleb's report: v26.07.21.22's synthetic-
# keypress "keepalive" theory was tested on real hardware and did NOT
# work -- "it muted itself"). Found the actual, proven mechanism by
# examining a real, shipped muOS media app (Songo#5) that solves this
# exact problem: NOT by resetting a timer via fake input, but by
# directly disabling the two config values muOS's own DISPLAY_IDLE()/
# SLEEP() routines check, then restarting the hotkey daemon
# (muhotkey/hotkey.sh) so the change takes effect immediately -- the
# daemon reads these once at startup, not on every loop iteration, so
# a plain file write alone doesn't take effect until it restarts.
# Songo#5's own scripts, verbatim (its actual shipped shell scripts
# in the real MustardOS/internal repo, not inferred):
#   set:    CAFFEINE on
#           SET_VAR "config" "settings/power/idle_sleep" "0"
#           SET_VAR "config" "settings/power/idle_display" "0"
#           HOTKEY restart
#   remove: CAFFEINE off
#           SET_VAR "config" "settings/power/idle_sleep" "$ORIGINAL"
#           SET_VAR "config" "settings/power/idle_display" "$ORIGINAL"
#           HOTKEY restart
# Replicated below in Python: GET_VAR/SET_VAR just read/write plain
# files under /opt/muos/config (same pattern already used for reading
# battery/WiFi elsewhere in this app); CAFFEINE on/off is a plain
# touch/rm of $MUOS_RUN_DIR/caffeine; HOTKEY restart is killall + a
# fresh setsid launch of hotkey.sh, both real muOS shell functions
# (script/var/func.sh) -- v26.07.30.01 (Kaleb's request, after
# reviewing MuTube's real implementation of this same problem): these
# now call the REAL func.sh shell functions (GET_VAR/SET_VAR/CAFFEINE/
# HOTKEY) via `bash -c '. func.sh; ...'`, instead of reimplementing what
# those functions do by reading/writing the backing config files and
# process names directly. This is more correct long-term: it can't
# silently drift out of sync if a future muOS release ever changes
# WHERE or HOW these settings are stored/applied, since it's calling
# muOS's own official accessor rather than assuming today's file
# layout stays the same forever. See _get_var()/_set_var()/_caffeine()/
# _restart_hotkey_daemon() below for the real-function calls, each with
# the ORIGINAL raw-file/process-signal approach kept as a fallback for
# the (real-device-impossible, sandbox/off-device-only) case where
# func.sh itself is missing -- so this is strictly more robust than
# before, never less.
_IDLE_SLEEP_CFG_PATH = "/opt/muos/config/settings/power/idle_sleep"
_IDLE_DISPLAY_CFG_PATH = "/opt/muos/config/settings/power/idle_display"
_CAFFEINE_PATH = "/run/muos/caffeine"
_HOTKEY_SCRIPT_PATH = "/opt/muos/script/mux/hotkey.sh"
_FUNC_SH_PATH = "/opt/muos/script/var/func.sh"
_IDLE_RESTORE_FALLBACK = "120"  # muOS's documented default idle timeout
# (seconds), used ONLY when restore_idle_display()/
# check_and_recover_stale_idle_backup() truly don't know the real
# original value (a failed GET_VAR probe). v26.07.30.02 (matching
# MuTube's exact reasoning): writing nothing back in that case would
# leave idle suppression (0) in effect indefinitely once suppress
# unconditionally forces it -- a probably-correct guess at muOS's own
# factory default is a better failure mode than that.

# v26.07.23.16 (Kaleb's request: "anything we missed based on past bugs
# we fixed historically" -- this is the SAME lesson as the caffeine-
# file crash-resilience fix, v26.07.23.14, applied to a more
# consequential piece of state that fix didn't cover). If PicoReader
# crashes/loses power WHILE idle_sleep/idle_display are forced to "0"
# (any playback session), those are real PERSISTENT muOS config values
# on a non-tmpfs partition -- confirmed by their path under /opt/muos/
# config, unlike _CAFFEINE_PATH's /run/muos (tmpfs, cleared on reboot).
# A crash there leaves the person's REAL screen-timeout/sleep settings
# stuck at "0" system-wide, surviving even a full reboot, with nothing
# to self-heal them -- worse than the caffeine bug, since that one at
# least degraded to "suspend blocked" (annoying but recoverable by
# playing something and quitting cleanly); this one silently discards
# the person's actual settings with no way back except re-entering
# their old numbers by hand in muOS's own Settings, if they even
# remember what they were.
#
# Fix: suppress_idle_display() now writes the ORIGINAL values to a
# small backup file (in PicoReader's own persistent data dir, set via
# set_idle_backup_path() at app startup -- native_media.py has no
# built-in notion of where that is) before ever touching the live
# config; restore_idle_display() deletes it on a clean restore.
# check_and_recover_stale_idle_backup(), called once at app startup
# BEFORE any playback this session, detects a leftover backup file
# (proof the last session ended abnormally mid-suppression) and
# restores the real values from it -- self-healing even across a
# reboot, unlike the live config values themselves would ever do on
# their own. Kept fully intact through the v26.07.30.01 func.sh
# rewrite below -- MuTube (the app this rewrite was ported from) has
# no equivalent crash-recovery, which would be a real regression for
# PicoReader specifically, not an improvement.
_idle_backup_path = None

# v26.07.30.07 REAL BUG FIX (Kaleb's request: "check the code, make sure
# we're not including buggy code like MuTube's standby issue" -- found
# by actually constructing an adversarial timing test, not just
# reasoning about it). suppress_idle_display()'s apply call has been
# backgrounded (subprocess.Popen, v26.07.30.02) since HOTKEY restart can
# cost ~1.5s+ and blocking on it delayed every video/audio start. But
# that created a REAL race: if playback ends/fails very quickly (before
# the background apply has actually finished landing its SET_VAR calls
# on the live config), restore_idle_display()'s own correct "put the
# real values back" writes can complete FIRST, and then the STILL-
# RUNNING background apply's "set to 0" writes land AFTER, silently
# overwriting the correct restore and leaving the device stuck with
# idle-suppression active -- exactly the "won't go to standby" failure
# mode. Confirmed reproducible with an adversarial mock (a deliberately
# slow background SET_VAR plus an immediate restore call): final state
# was stuck at 0/0 instead of the real original values.
# Fix: suppress_idle_display() stores the Popen handle here (a single-
# element list, not a bare variable, only so restore can clear it after
# waiting -- module-level globals need a mutable container to update
# from a different function without an explicit `global` on every
# access site); restore_idle_display() waits on it (bounded timeout, so
# a truly stuck background process can't hang restore forever) BEFORE
# doing its own work, guaranteeing correct ordering. In the common case
# (real playback lasting more than ~1.5s) this wait returns instantly,
# since the background process already finished minutes/hours earlier
# -- the responsiveness win from backgrounding is preserved for every
# normal video/audio session; only the pathological "playback ends in
# well under a second" case pays a (bounded, small) wait, which is
# exactly the case that would otherwise have silently corrupted the
# device's idle settings.
_suppress_apply_proc = [None]


def set_idle_backup_path(path):
    """Called once by main.py at startup, pointing at a file inside its
    own persistent DATA_DIR. Must be called before any playback if the
    crash-recovery protection below is wanted -- a safe no-op (old
    caffeine-file-only behavior) if never called."""
    global _idle_backup_path
    _idle_backup_path = path


def check_and_recover_stale_idle_backup():
    """Call once at app startup, before any playback this session.
    Returns True if a stale backup was found and the person's real
    idle_sleep/idle_display values were restored from it (worth logging
    -- see main.py's own call site), False if there was nothing to
    recover (the normal case -- last session either never played
    anything, or ended cleanly).

    v26.07.30.02: always writes SOMETHING back now (falling back to
    _IDLE_RESTORE_FALLBACK if the backup itself recorded None for a
    value -- i.e. the original GET_VAR probe failed last session, before
    the crash), rather than skipping that key entirely. See
    restore_idle_display()'s own docstring for why -- same reasoning,
    applied here since a stale backup is really just a restore that
    never got to run."""
    if not _idle_backup_path or not os.path.isfile(_idle_backup_path):
        return False
    try:
        with open(_idle_backup_path, "r") as f:
            backup = json.load(f)
    except (OSError, ValueError):
        # Corrupt/unreadable backup -- can't safely recover from it,
        # but don't leave it sitting there forever either.
        try:
            os.remove(_idle_backup_path)
        except OSError:
            pass
        return False
    orig_sleep = backup.get("idle_sleep") or _IDLE_RESTORE_FALLBACK
    orig_display = backup.get("idle_display") or _IDLE_RESTORE_FALLBACK
    _set_var("config", "settings/power/idle_sleep", orig_sleep)
    _set_var("config", "settings/power/idle_display", orig_display)
    _restart_hotkey_daemon()
    try:
        os.remove(_idle_backup_path)
    except OSError:
        pass
    return True


def _get_var(section, key):
    """Reads a muOS config value via the REAL GET_VAR shell function in
    muOS's own func.sh (ported from MuTube's approach, Kaleb's request),
    rather than reading the backing file directly -- stays correct even
    if a future muOS release changes where/how this is stored, since
    it's calling muOS's own official accessor instead of assuming
    today's file layout. Falls back to the original direct file read
    (the only way this worked before this rewrite) if func.sh itself is
    missing -- realistically only the sandbox/off-device case, since
    every real muOS install ships func.sh. Returns None on any failure,
    same "safe no-op" contract _read_config_var() always had."""
    if os.path.isfile(_FUNC_SH_PATH):
        try:
            result = subprocess.run(
                ["bash", "-c",
                 f". {shlex.quote(_FUNC_SH_PATH)}; "
                 f"GET_VAR {shlex.quote(section)} {shlex.quote(key)}"],
                capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                value = result.stdout.strip()
                if value:
                    return value
        except (OSError, subprocess.TimeoutExpired):
            pass
        return None
    # Fallback: func.sh missing (off-device/sandbox) -- old direct-file
    # behavior, only ever exercised for idle_sleep/idle_display here.
    path = {"settings/power/idle_sleep": _IDLE_SLEEP_CFG_PATH,
            "settings/power/idle_display": _IDLE_DISPLAY_CFG_PATH}.get(key)
    if not path:
        return None
    try:
        with open(path, "r") as f:
            return f.read().strip()
    except OSError:
        return None


def _set_var(section, key, value):
    """Writes a muOS config value via the real SET_VAR shell function.
    Same fallback contract as _get_var() above. Best-effort -- return
    value is for logging only, callers don't currently branch on it."""
    if os.path.isfile(_FUNC_SH_PATH):
        try:
            result = subprocess.run(
                ["bash", "-c",
                 f". {shlex.quote(_FUNC_SH_PATH)}; "
                 f"SET_VAR {shlex.quote(section)} {shlex.quote(key)} {shlex.quote(str(value))}"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            return result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False
    path = {"settings/power/idle_sleep": _IDLE_SLEEP_CFG_PATH,
            "settings/power/idle_display": _IDLE_DISPLAY_CFG_PATH}.get(key)
    if not path:
        return False
    try:
        with open(path, "w") as f:
            f.write(str(value))
        return True
    except OSError:
        return False


def _caffeine(on):
    """Real CAFFEINE on/off via func.sh (blocks suspend from every
    source). Falls back to the original raw touch/rm of _CAFFEINE_PATH
    if func.sh is missing -- caffeine's backing file lives on tmpfs
    (/run/muos), so unlike idle_sleep/idle_display this fallback was
    always safe/self-healing across a reboot even before this rewrite,
    kept unconditionally reachable rather than only in the off-device
    case for that reason."""
    if os.path.isfile(_FUNC_SH_PATH):
        try:
            subprocess.run(
                ["bash", "-c",
                 f". {shlex.quote(_FUNC_SH_PATH)}; CAFFEINE {'on' if on else 'off'}"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            return
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        if on:
            open(_CAFFEINE_PATH, "w").close()
        else:
            os.remove(_CAFFEINE_PATH)
    except OSError:
        pass


def _restart_hotkey_daemon():
    """Real `HOTKEY restart` via func.sh -- re-reads the now-changed
    idle_sleep/idle_display values immediately instead of waiting for
    the daemon's own next natural restart. Falls back to the original
    kill+relaunch reimplementation (killall + setsid) if func.sh is
    missing. Best-effort either way: if both paths fail (e.g. off-
    device, or muOS's own process names ever change), the config
    values are still written correctly, they just won't take effect
    until something else restarts the daemon (a normal settings-menu
    save would also do it) -- degrades gracefully rather than raising."""
    if os.path.isfile(_FUNC_SH_PATH):
        try:
            subprocess.run(
                ["bash", "-c",
                 f". {shlex.quote(_FUNC_SH_PATH)}; HOTKEY restart"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            return
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        subprocess.run(["killall", "-9", "muhotkey", "hotkey.sh"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        subprocess.Popen(["setsid", "-f", _HOTKEY_SCRIPT_PATH],
                          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL)
    except OSError:
        pass


def suppress_idle_display():
    """Called once, right before video/audio playback starts. Returns
    (orig_idle_sleep, orig_idle_display) -- whatever the user's real
    settings were, or None for either if unreadable (e.g. off-device)
    -- MUST be passed back to restore_idle_display() when playback
    ends, or the user's real idle settings stay disabled system-wide.
    Safe no-op (returns (None, None)) if the config paths don't exist.

    v26.07.23.29 BUG FIX/ROLLBACK (Kaleb's report: "the open close
    settings for keeping on don't work at all in any way it always goes
    to standby no matter what when you close the lid... let's default
    to the original plan for both video and audio [and] remove the
    settings toggle"): the v26.07.23.12-.20 "On Lid/Standby" feature
    (a 3-way audio mode and 2-way video mode, letting a deliberate lid-
    close/standby-press through to a real suspend in some modes) never
    actually worked as designed on Kaleb's real hardware -- closing the
    lid suspended regardless of which mode was selected. Since the
    exact root cause on-device couldn't be diagnosed further from here
    (this sandbox has no way to test real muOS suspend behavior),
    Kaleb's own direction was to roll the whole feature back rather
    than keep guessing at a fix: this function is back to its original,
    simpler, well-tested pre-v26.07.23.12 form -- always creates the
    caffeine file (blocking suspend from every source, matching how
    video's own screen-stays-on behavior worked reliably since
    v26.07.20.35, well before any of this) and always disables idle_
    sleep/idle_display, with no mode/parameter to select anything
    different.

    v26.07.30.02 (Kaleb's request, after direct comparison against
    MuTube's real implementation of this same problem): reworked to
    match MuTube's actual call pattern, not just its choice of shell
    functions (that part came in v26.07.30.01). Two real differences
    fixed here:
      1. ONE combined `bash -c` call for the probe (both GET_VARs in a
         single subprocess), and a SEPARATE combined call for the
         actual apply (CAFFEINE on + both SET_VARs + HOTKEY restart) --
         not four separate subprocess calls each re-sourcing func.sh
         independently like the v26.07.30.01 version. Cuts process-spawn
         overhead and shrinks the worst-case hang exposure a live bug-
         check pass found in that version (15s -> whatever this single
         apply call's own timeout is).
      2. The apply call is BACKGROUNDED (subprocess.Popen, fire-and-
         forget) rather than blocking. HOTKEY restart alone can cost
         ~1.5s+ (MuTube's own measurement); doing this synchronously,
         as v26.07.30.01 did, added that same delay before every video/
         audio actually started playing. Backgrounding it means
         playback starts immediately while the real suppress takes
         effect in parallel -- the tradeoff is a brief window (that
         same ~1.5s) where a video is already playing but idle-suppress
         hasn't landed yet, which is the same tradeoff MuTube itself
         accepted.
    The probe step stays synchronous/blocking (needs the real values
    before returning), and the crash-recovery backup file is written
    BEFORE the backgrounded apply call is fired -- if PicoReader
    crashes in that brief window, the backup is already safely on disk
    either way (see check_and_recover_stale_idle_backup()'s own
    docstring)."""
    orig_sleep = None
    orig_display = None
    if os.path.isfile(_FUNC_SH_PATH):
        try:
            probe = subprocess.run(
                ["bash", "-c",
                 f". {shlex.quote(_FUNC_SH_PATH)}; "
                 'echo "$(GET_VAR config settings/power/idle_sleep)|'
                 '$(GET_VAR config settings/power/idle_display)"'],
                capture_output=True, text=True, timeout=5)
            if probe.returncode == 0 and probe.stdout.strip():
                parts = probe.stdout.strip().split("|", 1)
                if len(parts) == 2:
                    orig_sleep = parts[0] or None
                    orig_display = parts[1] or None
        except (OSError, subprocess.TimeoutExpired):
            pass
        # v26.07.23.16: backup written BEFORE the backgrounded apply
        # call fires -- see this function's own v26.07.30.02 note above
        # on why ordering matters here now that apply is backgrounded.
        # Unlike the pre-v26.07.30.02 versions, this now writes
        # unconditionally (even if both probed values are None) --
        # the apply step below unconditionally forces idle_sleep/
        # idle_display to "0" regardless of whether the probe
        # succeeded (matching MuTube's "always suppress, worry about
        # the exact restore value separately" philosophy), so there's
        # always something real to recover from a crash now, not just
        # when the probe happened to succeed.
        if _idle_backup_path:
            try:
                with open(_idle_backup_path, "w") as f:
                    json.dump({"idle_sleep": orig_sleep, "idle_display": orig_display}, f)
            except OSError:
                pass
        try:
            _suppress_apply_proc[0] = subprocess.Popen(
                ["bash", "-c",
                 f". {shlex.quote(_FUNC_SH_PATH)}; "
                 "CAFFEINE on; "
                 "SET_VAR config settings/power/idle_sleep 0; "
                 "SET_VAR config settings/power/idle_display 0; "
                 "HOTKEY restart"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass
    else:
        # Off-device/sandbox fallback -- func.sh missing entirely.
        # Realistically only ever exercised off a real muOS device.
        orig_sleep = _get_var("config", "settings/power/idle_sleep")
        orig_display = _get_var("config", "settings/power/idle_display")
        _caffeine(True)
        _set_var("config", "settings/power/idle_sleep", "0")
        _set_var("config", "settings/power/idle_display", "0")
        _restart_hotkey_daemon()
        if _idle_backup_path:
            try:
                with open(_idle_backup_path, "w") as f:
                    json.dump({"idle_sleep": orig_sleep, "idle_display": orig_display}, f)
            except OSError:
                pass
    return orig_sleep, orig_display


def restore_idle_display(orig_sleep, orig_display):
    """Called once, when video/audio playback ends -- MUST be called
    even if playback ended abnormally (crash, early quit), or the
    user's real idle settings stay disabled. See play_video_source()'s own
    try/finally for where this is guaranteed to run.

    v26.07.30.02: this call stays BLOCKING (subprocess.run, not Popen)
    deliberately -- unlike suppress's apply call, this only runs after
    playback has already ended, so it can't be felt as load-time delay,
    and correctness matters more than speed for a value that's about to
    control the user's device again (same reasoning MuTube itself uses
    for its own restore call).

    v26.07.30.07 REAL BUG FIX: waits for suppress_idle_display()'s
    backgrounded apply call to finish (if it's somehow still running --
    see _suppress_apply_proc's own module-level comment for the full
    race condition this closes) BEFORE doing its own work, so a very-
    short-lived playback session can't have its correct restore silently
    overwritten by a late-arriving background "set to 0" write. Bounded
    wait (10s) so a genuinely stuck background process can't hang this
    call forever -- if it times out, proceeds anyway (best-effort, same
    as everything else in this module).

    Also v26.07.30.02: if orig_sleep/orig_display is None (the GET_VAR
    probe in suppress_idle_display() failed), this now falls back to
    _IDLE_RESTORE_FALLBACK (muOS's documented default idle timeout,
    120s) instead of skipping that key entirely. Since suppress now
    ALWAYS forces idle_sleep/idle_display to "0" regardless of whether
    the probe succeeded, skipping the restore write when the probe
    failed would leave the person's idle settings stuck at "0"
    indefinitely -- a real, if rare, regression risk. Writing a
    probably-correct guess (muOS's own factory default) is a better
    failure mode than that, matching MuTube's exact reasoning for doing
    the same thing."""
    proc = _suppress_apply_proc[0]
    if proc is not None:
        try:
            proc.wait(timeout=10)
        except Exception:
            pass  # best-effort -- proceed with restore regardless
        _suppress_apply_proc[0] = None
    sleep_val = orig_sleep if orig_sleep is not None else _IDLE_RESTORE_FALLBACK
    display_val = orig_display if orig_display is not None else _IDLE_RESTORE_FALLBACK
    if os.path.isfile(_FUNC_SH_PATH):
        try:
            subprocess.run(
                ["bash", "-c",
                 f". {shlex.quote(_FUNC_SH_PATH)}; "
                 "CAFFEINE off; "
                 f"SET_VAR config settings/power/idle_sleep {shlex.quote(sleep_val)}; "
                 f"SET_VAR config settings/power/idle_display {shlex.quote(display_val)}; "
                 "HOTKEY restart"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        _caffeine(False)
        _set_var("config", "settings/power/idle_sleep", sleep_val)
        _set_var("config", "settings/power/idle_display", display_val)
        _restart_hotkey_daemon()
    # v26.07.23.16: clean restore completed -- clear the backup file so
    # check_and_recover_stale_idle_backup() at the NEXT app startup
    # correctly sees nothing to recover.
    if _idle_backup_path:
        try:
            os.remove(_idle_backup_path)
        except OSError:
            pass


def _make_event_types():
    """Builds the same ctypes structs main.py's own poll loop uses,
    field-for-field identical -- kept local to this function (not
    module-level) since they're only needed inside _translate_loop, same
    scoping main.py itself uses for these."""
    class SDL_JoyHatEvent(ctypes.Structure):
        _fields_ = [("type", ctypes.c_uint32), ("timestamp", ctypes.c_uint32),
                    ("which", ctypes.c_int32), ("hat", ctypes.c_ubyte),
                    ("value", ctypes.c_ubyte), ("padding1", ctypes.c_ubyte),
                    ("padding2", ctypes.c_ubyte)]

    class SDL_JoyButtonEvent(ctypes.Structure):
        _fields_ = [("type", ctypes.c_uint32), ("timestamp", ctypes.c_uint32),
                    ("which", ctypes.c_int32), ("button", ctypes.c_ubyte),
                    ("state", ctypes.c_ubyte), ("padding1", ctypes.c_ubyte),
                    ("padding2", ctypes.c_ubyte)]

    return SDL_JoyHatEvent, SDL_JoyButtonEvent


def _translate_loop(sdl, joy_a, joy_b, vkbd, stop_event, joy_l1=None, joy_r1=None, joy_y=None, joy_x=None,
                     joy_l2=None, joy_r2=None, joy_start=None, joy_select=None, signal=None,
                     using_mpv=True):
    SDL_JoyHatEvent, SDL_JoyButtonEvent = _make_event_types()
    ev_buf = (ctypes.c_byte * 56)()

    while not stop_event.is_set():
        while sdl.SDL_PollEvent(ctypes.byref(ev_buf)) != 0:
            etype = ctypes.cast(ev_buf, ctypes.POINTER(ctypes.c_uint32))[0]
            if etype == SDL_JOYBUTTONDOWN_EV:
                bev = ctypes.cast(ev_buf, ctypes.POINTER(SDL_JoyButtonEvent))[0]
                if bev.button == joy_a:
                    vkbd.tap(KEY_SPACE)   # A -- pause/play
                elif bev.button == joy_b:
                    if signal is not None:
                        signal["abort"] = True
                    vkbd.tap(KEY_Q)       # B -- quit (this video, and the
                                          # whole queue if one is active)
                # v26.07.29.07 (Kaleb's request -- full video control
                # reshuffle): L1/R1 now do the +-10min tier in BOTH
                # single-video and queue modes (previously mode-aware,
                # +-60s single / +-10min queue -- see v26.07.29.05 for
                # what this replaces). mpv's real +-10min default is
                # SHIFT+PGUP/PGDOWN (plain PGUP/PGDOWN is chapter-skip
                # on mpv, see L2/R2 below). ffplay has no Shift-modified
                # variant of this key, so it gets plain PGUP/PGDOWN
                # instead -- per ffmpeg.org/ffplay.html, ffplay's own
                # real default for that key is "seek to previous/next
                # chapter, or +-10min if the file has no chapters" (the
                # exact same real action L2/R2 below uses for ffplay --
                # a real, if redundant, second way to reach it, not an
                # invented substitute).
                elif joy_l1 is not None and bev.button == joy_l1:
                    if using_mpv:
                        vkbd.tap_shifted(KEY_PAGEDOWN)  # L1 -- seek back ~10min (mpv)
                    else:
                        vkbd.tap(KEY_PAGEDOWN)          # L1 -- seek back ~10min (ffplay)
                elif joy_r1 is not None and bev.button == joy_r1:
                    if using_mpv:
                        vkbd.tap_shifted(KEY_PAGEUP)    # R1 -- seek forward ~10min (mpv)
                    else:
                        vkbd.tap(KEY_PAGEUP)            # R1 -- seek forward ~10min (ffplay)
                # L2/R2 stay mode-aware: QUEUE mode (real `signal` dict)
                # keeps its existing prev/next-track skip, unchanged.
                # SINGLE-FILE mode now does chapter-skip instead of the
                # old +-60s (moved to D-pad Up/Down below): plain
                # PGUP/PGDOWN is a genuine real default on BOTH players
                # here -- mpv's is "add chapter 1/-1"; ffplay's own
                # real default (per ffmpeg.org/ffplay.html) is "seek to
                # previous/next chapter, OR +-10min if the file has no
                # chapters" -- it already self-selects, so no
                # using_mpv branch is needed at all for this one.
                elif joy_l2 is not None and bev.button == joy_l2:
                    if signal is not None:
                        signal["skip"] = -1
                        vkbd.tap(KEY_Q)         # L2 -- previous video (queue)
                    else:
                        vkbd.tap(KEY_PAGEDOWN)  # L2 -- previous chapter (or
                                                # ~10min back if no chapters)
                elif joy_r2 is not None and bev.button == joy_r2:
                    if signal is not None:
                        signal["skip"] = 1
                        vkbd.tap(KEY_Q)         # R2 -- next video (queue)
                    else:
                        vkbd.tap(KEY_PAGEUP)    # R2 -- next chapter (or
                                                # ~10min forward if no chapters)
                # v26.07.29.08 (Kaleb's request: OSD stuff is more
                # "subtle" and suits the less-prominent START/SELECT
                # better; mute/subtitle are everyday actions that
                # belong on the main face buttons). Swaps X/Y <-> START/
                # SELECT from the v26.07.29.07 reshuffle -- same real
                # keys, just relocated:
                # Y -- subtitle cycle (KEY_T, moved here from SELECT).
                elif joy_y is not None and bev.button == joy_y:
                    vkbd.tap(KEY_T)      # Y -- subtitle cycle
                # X -- mute (KEY_M, moved here from START).
                elif joy_x is not None and bev.button == joy_x:
                    vkbd.tap(KEY_M)      # X -- mute
                elif joy_start is not None and bev.button == joy_start:
                    if using_mpv:
                        vkbd.tap_shifted(KEY_O)  # START -- toggle permanent OSD (mpv)
                elif joy_select is not None and bev.button == joy_select:
                    if using_mpv:
                        # v26.07.30.04: still taps 'i', but the bundled
                        # mpv input.conf now rebinds 'i' to a real core
                        # show-text+property-expansion command (WxH +
                        # codec) instead of the default script-binding
                        # to mpv's Lua stats overlay, which this device's
                        # mpv build likely doesn't have compiled in --
                        # see _MPV_INPUT_CONF's own comment for the full
                        # story.
                        vkbd.tap(KEY_I)          # SELECT -- show resolution/codec (mpv)
            elif etype == SDL_JOYHATMOTION_EV:
                hev = ctypes.cast(ev_buf, ctypes.POINTER(SDL_JoyHatEvent))[0]
                hv = hev.value
                # v26.07.29.07 (Kaleb's request -- full video control
                # reshuffle): D-pad Up/Down now do the +-60s seek tier,
                # in BOTH single-video and queue modes -- freed up since
                # OSD toggle/mute moved off D-pad entirely (now on
                # START/X respectively, see the button handler above --
                # relocated once more to X/Y <-> START/SELECT at
                # v26.07.29.08). mpv and ffplay both have the IDENTICAL real default here
                # (KEY_UP/KEY_DOWN = seek +-60s on both players, per
                # ffplay's own documented "up/down = 1 min" seeking --
                # confirmed against ffmpeg.org/ffplay.html), so no
                # using_mpv branch is needed at all for this one.
                #
                # D-pad Left/Right: unchanged -- mpv's small +-5s seek
                # tier / ffplay's own +-10min seek default (swapped in
                # from speed control at v26.07.29.05, see L1/R1's own
                # comment above for what replaced it there).
                if hv & SDL_HAT_LEFT:
                    if using_mpv:
                        vkbd.tap(KEY_LEFT)        # seek back ~5s (mpv)
                    else:
                        vkbd.tap(KEY_PAGEDOWN)    # seek back ~10min (ffplay)
                elif hv & SDL_HAT_RIGHT:
                    if using_mpv:
                        vkbd.tap(KEY_RIGHT)       # seek forward ~5s (mpv)
                    else:
                        vkbd.tap(KEY_PAGEUP)      # seek forward ~10min (ffplay)
                elif hv & SDL_HAT_UP:
                    vkbd.tap(KEY_UP)      # seek forward ~60s (mpv + ffplay)
                elif hv & SDL_HAT_DOWN:
                    vkbd.tap(KEY_DOWN)    # seek back ~60s (mpv + ffplay)
        time.sleep(_POLL_INTERVAL)


# v26.07.20.13 (Kaleb's request -- cleanup #1): base ffplay args
# collapsed into one named constant instead of being built inline inside
# play_video_source(), so the full flag set is readable/auditable in one
# place. Same behavior as v26.07.20.12, no functional change.
_FFPLAY_BASE_ARGS = [
    "-fs", "-framedrop",
    "-reconnect", "1", "-reconnect_streamed", "1",
    "-reconnect_at_eof", "1", "-reconnect_delay_max", "2",
    # v26.07.20.14 (Kaleb's request -- bug check #3): -rw_timeout is an
    # HTTP-protocol read/write timeout in MICROSECONDS. Without it, a
    # connection that hangs (accepted but never sends data -- distinct
    # from a hard failure, which -reconnect already covers) has no
    # bound at all: ffplay just sits there indefinitely with no
    # feedback to the user and no chance for -reconnect logic to kick
    # in, since that only fires on an actual completed
    # failure/disconnect, not a stall. 15s is generous enough to not
    # false-positive on a slow-but-working connection while still
    # failing a truly dead one in reasonable time. Harmlessly ignored
    # for local file playback, same as the reconnect flags.
    "-rw_timeout", "15000000",
]

# v26.07.20.13 (Kaleb's request -- cleanup #2): ffplay's own stderr, at
# "error" verbosity, is appended here instead of being discarded via
# "-loglevel quiet". Previously a real ffplay crash on-device left NO
# trail at all -- just "video stopped" with nothing to go on. Mirrors
# main.py's own CRASH_LOG convention (/tmp/picoreader_crash.log) but
# kept in a separate file so a long JW-video session doesn't interleave
# with/bloat the app's own crash log.
# v26.08.07.02 BUG FIX (same reasoning as main.py's CRASH_LOG move,
# same session): /tmp is RAM-backed on muOS, wiped by every reboot --
# including the hotkey OS reboot that's the ONLY way out of a genuinely
# frozen player session (Kaleb's real LibriVox report). That meant the
# one log most likely to explain a freeze was guaranteed erased by the
# exact event that required looking at it. Moved next to this file
# itself (real SD card storage).
FFPLAY_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "picoreader_ffplay.log")
# v26.07.20.18 (Kaleb's request -- log hygiene): caps FFPLAY_LOG at 1MB,
# same convention/cap as main.py's CRASH_LOG (LOG_CAP_BYTES) -- this log
# now fires on EVERY video play (v26.07.20.16 mem-trim logging), not
# just failures, so it's the more likely of the two to actually grow
# large over time. Simple truncate-on-cap, not real rotation -- same
# reasoning as CRASH_LOG's own comment.
_FFPLAY_LOG_CAP_BYTES = 1024 * 1024

# NOT included in _FFPLAY_BASE_ARGS: any -hwaccel/-codec:v h264_v4l2m2m
# flag. Whether this SoC + muOS's bundled ffmpeg build actually expose a
# working hardware decoder is UNVERIFIED -- ffplay itself has a history
# of not supporting -hwaccel reliably even on devices where ffmpeg does.
# Needs a real on-device check (`ffmpeg -decoders | grep v4l2` via
# SSH/telnet) before ever adding this -- do not guess.


def _ffplay_log(msg):
    try:
        if os.path.exists(FFPLAY_LOG) and os.path.getsize(FFPLAY_LOG) > _FFPLAY_LOG_CAP_BYTES:
            os.remove(FFPLAY_LOG)
        with open(FFPLAY_LOG, "a") as f:
            f.write(msg)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# mpv discovery -- confirmed present on muOS as a selectable Media Player
# core (same as ffplay), and confirmed by Kaleb as already his real
# default player for downloaded videos on his own device. Same
# candidate-list-then-PATH-fallback pattern as find_ffplay().
_MPV_CANDIDATES = ("/usr/bin/mpv", "mpv")


def find_mpv():
    for candidate in _MPV_CANDIDATES:
        if os.path.isabs(candidate):
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
        else:
            from shutil import which
            found = which(candidate)
            if found:
                return found
    return None


# v26.07.27.01 (cleanup, Kaleb's real-mpv-defaults control-scheme fix):
# every key the current button scheme sends is now a genuine mpv
# BUILT-IN default -- --no-config only skips loading a user's own
# mpv.conf/input.conf from their config directory, it does NOT disable
# mpv's compiled-in default keybindings (confirmed against mpv's own
# etc/input.conf, which documents exactly this). So none of those need
# an explicit line here anymore -- removed PGUP/PGDWN (nothing tapped
# KEY_PAGEUP/KEY_PAGEDOWN at the time) and the old g/v overrides (KEY_G/
# KEY_V no longer exist -- see this file's own top-of-file removal
# comment).
#
# v26.07.29.12 (bug-sweep cleanup): removed the "a cycle audio" line --
# dead since v26.07.29.06, when video's X (the only button that ever
# tapped KEY_A_LETTER/'a', cycle audio track) was reassigned to reset-
# speed and then to mute; nothing in the app has sent 'a' since. Only
# 't' remains: mpv genuinely has NO default binding on that letter
# (confirmed against mpv's own etc/input.conf), so it still needs to be
# declared explicitly for Y's subtitle-visibility toggle to work.
#
# v26.07.30.04 BUG FIX (Kaleb's on-device report: SELECT does nothing
# during video playback). Root cause, found by fetching mpv's OWN
# source docs directly rather than guessing: SELECT taps 'i', whose
# REAL default binding is `script-binding stats/display-stats-toggle`
# -- but the stats overlay is one of mpv's BUILT-IN LUA scripts
# (confirmed: mpv's own README lists "Lua (optional, required for the
# OSC pseudo-GUI...)" as an OPTIONAL compile-time dependency, and the
# stats script is Lua-based). muOS's mpv build, targeting a 1GB-RAM
# embedded handheld, plausibly wasn't compiled with Lua support at all
# -- if so, the ENTIRE stats script doesn't exist in that binary, so
# 'i' physically registers (confirmed via real fake-event dispatch
# testing) but has nothing to invoke: not an error, just silently no
# script bound there. This exactly matches "looks like it does
# nothing" rather than a wrong overlay or a crash.
# Fix: explicitly rebind 'i' here to mpv's own CORE `show-text` command
# with property expansion -- both guaranteed-present C-level features,
# not Lua, confirmed via mpv's real property-list docs (DOCS/man/
# input.rst): `${width}`/`${height}` (decoded video size) and
# `${current-tracks/video/codec}` (the modern shorthand for the current
# video track's codec name) are both real, current properties. This
# custom input.conf entry OVERRIDES mpv's default 'i' binding for this
# key (a real, documented input.conf mechanism -- mpv's own manual uses
# almost this exact line, `i show-text "Filename: ${filename}"`, as its
# canonical property-expansion example), so SELECT now shows a genuine
# "WIDTHxHEIGHT codec" line built from real decoder properties instead
# of depending on a script that may not exist on this device at all.
#
# v26.07.30.05 BUG FIX (found this session while continuing to verify
# the above, not a live report): this single input.conf is shared by
# BOTH video and audio playback (both call sites pass the same
# --input-conf file). The first version of this line only handled
# video -- for audio, width/height/current-tracks/video/codec are all
# genuinely unavailable (no video track exists), so it would have
# shown a useless "?x? unknown" on SELECT during audio playback.
# Verified directly against a real mpv process for BOTH cases this
# session (not guessed): tested with a real decoded video file (got
# "320x240 h264" as expected) and a real audio-only file (got "mp3
# audio" using the fix below), via mpv's own IPC `expand-text` command,
# which lets the exact production string be checked without needing to
# see an actual rendered OSD.
# Fix: uses mpv's `${?NAME:STR}`/`${!NAME:STR}` conditional property-
# expansion syntax (also real, documented core functionality, same
# section of input.rst as the plain `${NAME}` form) to pick one of two
# branches at expansion time depending on whether a video track is
# actually present: `${?width:...}` (video branch: WxH + codec) or
# `${!width:...}` (audio branch: falls back to the audio codec + the
# literal word "audio" for clarity) -- exactly one of the two ever
# expands to anything, since width is either available or it isn't.
# v26.07.30.06 (Kaleb's requests: audio bitrate, then video/audio
# title): extended to a real two-line OSD message. Both additions
# verified against a real mpv process with real metadata-tagged test
# files before shipping, not just reasoned through:
#   Line 1: `${media-title}` -- real core property, uses the file's own
#   embedded title tag if present, otherwise automatically falls back
#   to the filename (confirmed via mpv's own docs, and via a real
#   title-tagged test file: got back the literal tag text, not the
#   filename).
#   Line 2: unchanged video branch (WxH + codec), audio branch now
#   ALSO includes `${audio-bitrate}` -- a real, stable core property
#   (NOT one of the internal/unstable ones mpv's own docs warn about
#   elsewhere on the same page -- checked the surrounding docs
#   specifically to be sure). Plain `${audio-bitrate}` auto-formats to
#   a friendly "127 kbps"-style string (confirmed against a real 128k-
#   encoded test file: got back "127 kbps", not a raw bits-per-second
#   number) -- no manual unit math needed.
# The `\n` between the two lines is a real, documented C-style escape
# mpv's own property-expansion system supports (confirmed directly in
# mpv's docs: "`\n` becomes a newline character") -- NOT the same as
# trying to embed an actual multi-line string across separate
# input.conf lines, which was tried first and confirmed to fail
# ("Unterminated double quote" -- input.conf is strictly one binding
# per physical line). Final combined string verified end-to-end
# against real mpv for both media types via IPC's own `expand-text`
# command (shows the exact resolved text without needing a real
# display): video produced "My Test Video\n320x240 h264", audio
# produced "My Test Song\nmp3 127 kbps audio" -- both exactly as
# intended, no parse errors, no wrong property names.
_MPV_INPUT_CONF_PATH = "/tmp/picoreader_mpv_input.conf"
_MPV_INPUT_CONF = """\
t cycle sub-visibility
i show-text "${media-title}\\n${!current-tracks/video/albumart==yes:${?width:${width}x${height} ${current-tracks/video/codec:unknown}}}${?current-tracks/video/albumart==yes:${current-tracks/audio/codec:unknown} ${audio-bitrate:?} audio}${!width:${current-tracks/audio/codec:unknown} ${audio-bitrate:?} audio}" 3000
"""


def _write_mpv_input_conf():
    """Best-effort -- if this fails, mpv just falls back to its OWN
    built-in default bindings (which are close enough for the basics:
    space/p=pause, q=quit, arrows=seek -- only the exact seek amounts
    and the big L1/R1 jump wouldn't match). Never raises."""
    try:
        with open(_MPV_INPUT_CONF_PATH, "w") as f:
            f.write(_MPV_INPUT_CONF)
        return True
    except Exception:
        return False


# mpv's own defaults for everything not overridden above: --fs already
# applied via the CLI flag below; --panscan=1.0 (fill_screen mode) is
# mpv's built-in "zoom to fill, cropping overflow" -- genuinely simpler
# than ffplay's manual scale+crop -vf filter chain, same visual result.
#
# v26.07.20.37 (Kaleb's request -- checked muOS's own actual mpv
# invocation directly, github.com/MustardOS/internal
# script/launch/ext-mpv.sh): its real, shipped, tested command is
# "--no-config --fullscreen --keepaspect=yes --video-zoom=0
# --video-align-x=0 --video-align-y=0" -- notably, NO --vo override at
# all (settles the earlier "should we force --vo=drm for weak-GPU
# safety" question: muOS's own team, who tested this across their real
# supported devices, didn't feel the need to override mpv's own default
# vo selection either -- dropped that idea, no real evidence supported
# it). Also confirmed muOS's own script has ZERO reconnect/framedrop/
# osd-bar/msg-level flags -- our additions here are genuine value-adds
# on top of muOS's bare-minimum baseline, not in conflict with anything
# proven. Adopted --no-config from muOS's own script: prevents any
# stray user mpv config file on the device from silently interfering
# with these settings -- same defensive reasoning muOS's own team
# already applied.
_MPV_BASE_ARGS = [
    "--no-config",
    "--fs",
    # v26.08.07.04 (Kaleb's request: preemptively close the same gap
    # just fixed for audio in _MPV_AUDIO_ARGS -- see that entry's
    # v26.08.07.02 comment for the full root-cause reasoning). NOT a
    # live bug for video today: a real video file always carries an
    # actual video stream, so mpv creates a real window regardless of
    # this flag -- but that correctness depends on a content property
    # (a real video track existing) rather than being unconditional,
    # same fragility class as the audio bug. If a "video" URL ever
    # resolved to something audio-only (broken stream, wrong content-
    # type, a future plugin's edge case), this closes that off before
    # it can ever silently freeze input the same way. Documented no-op
    # for content that already has real video, so zero behavior change
    # for every current call.
    "--force-window=yes",
    "--osd-bar", "--osd-level=1",   # the whole reason for this switch
    "--framedrop=vo",               # same reasoning as ffplay's -framedrop
    "--network-timeout=15",         # same reasoning as ffplay's -rw_timeout
    "--msg-level=all=error",        # same reasoning as ffplay's -loglevel error
    # v26.07.20.36 BUG FIX (found during a requested re-review, not a
    # live report): this previously only passed
    # "reconnect_streamed=1,reconnect_delay_max=2" -- MISSING the base
    # "reconnect=1" and "reconnect_at_eof=1" flags. reconnect_streamed is
    # an ADDITIONAL flag on top of the base reconnect option in
    # ffmpeg/libavformat (which mpv uses directly for network streams
    # via --stream-lavf-o) -- without reconnect=1 also set, plain HTTP
    # reconnect likely never triggered at all, meaning this network-
    # resilience feature was silently incomplete since it first shipped.
    # Now matches the ffplay path's own complete, already-established
    # four-flag set exactly (see _FFPLAY_BASE_ARGS above).
    "--stream-lavf-o=reconnect=1,reconnect_streamed=1,reconnect_at_eof=1,reconnect_delay_max=2",
]


# ---------------------------------------------------------------------------
def play_video_source(source, is_local, sdl=None, joy_a=None, joy_b=None,
                   fill_screen=False, screen_w=None, screen_h=None,
                   joy_l1=None, joy_r1=None, joy_y=None, joy_x=None,
                   joy_l2=None, joy_r2=None, joy_start=None, joy_select=None,
                   signal=None, player_pref="mpv",
                   _manage_idle=True, osd_title=None):
    """v26.08.06.30 (renamed from play_jw_video -- fully generic in
    behavior already, just historically named after its original only
    caller). Plays a video, fullscreen, blocking until it exits.
    `source` is either a local file path (is_local=True) or a
    validated https:// URL from any plugin-registered domain
    (is_local=False, see register_stream_domains()) -- validation is
    the CALLER's responsibility via is_allowed_stream_url() before
    this is ever invoked, same pattern as gutenberg_fetch.py's
    download-time checks.
    `sdl` is the app's already-imported SDL module; `joy_a`/`joy_b` are
    main.py's own runtime-detected JOY_A/JOY_B button-index constants
    (see main.py's _sdl_map-derived globals) -- pass all three to get
    gamepad controls, or omit them to just play without controls.
    `joy_l1`/`joy_r1`/`joy_l2`/`joy_r2` and D-pad Left/Right/Up/Down --
    see _translate_loop's own comment for the full CURRENT control
    scheme (v26.07.27.01: real mpv/ffplay default keys throughout --
    small-tier seek on L1/R1, mode-aware L2/R2, speed control on D-pad
    Left/Right, OSD toggle/mute on D-pad Up/Down). v26.07.27.11
    (Kaleb's request to review every change for staleness): this
    docstring used to describe TWO different superseded schemes here
    (a since-removed D-pad brightness control, and seek durations from
    before the real-mpv-defaults fix) -- removed the duplicate,
    increasingly stale description rather than fix it a third time;
    _translate_loop is the single source of truth for this now.
    `joy_y` (optional) toggles/cycles subtitles -- sends 't', which is
    ffplay's own built-in default subtitle-cycle key, and is explicitly
    bound in the bundled mpv input.conf to "cycle sub-visibility" since
    mpv has no default binding on 't'. `joy_x` (optional) cycles the
    audio track the same way -- sends 'a' (ffplay's default), explicitly
    bound in the bundled mpv input.conf to "cycle audio" since mpv's own
    default audio-cycle key is '#', not 'a'. If uinput isn't available on
    this device, video still plays, just without gamepad controls;
    caller should toast that if sdl/joy_a/joy_b were passed but the
    vkbd failed to init (checked via the returned message).

    PLAYER SELECTION: mpv is tried FIRST by default (Kaleb's own
    confirmed real default for downloaded videos on his device already,
    and the only way to get a real OSD progress bar -- ffplay
    structurally has no equivalent, confirmed via ffmpeg-devel's own
    mailing list history of a never-mainlined patch proposal). Falls
    back to ffplay automatically if mpv isn't found on a given
    device/build -- same tolerant discovery pattern already used
    everywhere else in this file (native_image.py's libSDL2_image
    fallback to mini_jpeg.py is the same shape). Both players share the
    same basic keybindings (space/p=pause, q=quit, arrows=seek) so
    switching between them is invisible to the person holding the
    controller either way.

    `player_pref` -- v26.07.23.28 (Kaleb's request: "remove auto player
    mode and only use mpv as default"): "mpv" (default) or "ffplay" for
    an explicit manual override. Even with an explicit choice, this
    STILL falls back to the other player if the preferred one genuinely
    isn't found on this device -- an explicit preference means "prefer
    this one", not "only this one, fail hard otherwise". "auto" used to
    be a third, functionally-identical option (it always meant "prefer
    mpv" too) -- removed as a distinct settings value since it never
    actually did anything different from "mpv"; any unrecognized value
    still safely falls through to the same mpv-first behavior below.

    `osd_title` (v26.07.28.07, Kaleb's request: apply the same fix
    already proven for audio's --osd-playing-msg to video's queue
    transitions instead of PicoReader drawing its own overlay text).
    If given AND mpv ends up being the player actually used, passed as
    a real --osd-playing-msg literal -- mpv draws it INSIDE its own
    playback surface, the same layer the video itself is on, so there's
    no second competing layer for it to glitch against (unlike
    PicoReader's own SDL overlay card, which sits on a completely
    different compositing layer than whatever mpv/ffplay write to on
    this device -- see main.py's own top-of-file video-transition-
    glitch notes for the full diagnosis). Silently ignored if ffplay
    ends up being used instead -- ffplay has no equivalent on-screen
    text capability at all (same documented gap _MPV_AUDIO_ARGS' own
    docstring already notes for audio). `$` is escaped to `$$` before
    being passed -- mpv's own property-expansion syntax reads a bare
    `$` as the start of a property reference, and video/book titles are
    arbitrary text this app doesn't control the contents of.

    `fill_screen` picks between two scaling modes -- same concept as
    CTupe's own FILL_VF_ARG/FIT_VF_ARG split, driven by the CALLER's
    real per-device SW/SH so "fill" is correct on every aspect ratio
    PicoReader itself already supports:
      - fill_screen=False (default): letterboxed/pillarboxed fit,
        preserving aspect ratio, nothing cropped or stretched. mpv:
        its own default behavior (no extra flag needed). ffplay: no
        -vf filter at all, same reasoning.
      - fill_screen=True: crop-to-fill, no letterbox bars, no
        distortion -- some edge content is cropped for any video whose
        native aspect ratio doesn't match the device's. mpv: a single
        "--panscan=1.0" flag (mpv's own built-in zoom-to-fill). ffplay:
        the existing manual "-vf scale=W:H:...,crop=W:H" filter chain
        (v26.07.20.10's fix, kept for the fallback path). If
        fill_screen=True but screen_w/screen_h weren't given, silently
        falls back to fit rather than guessing a resolution.
    Returns (ok: bool, message: str | None)."""
    if not is_local and not is_allowed_stream_url(source):
        return False, "Not a recognized/allowed video source"
    if is_local and not os.path.isfile(source):
        return False, "Video file not found"

    if player_pref == "ffplay":
        player_bin = find_ffplay()
        using_mpv = False
        if not player_bin:
            player_bin = find_mpv()
            using_mpv = player_bin is not None
    else:  # "mpv" (or any unrecognized value -- fail safe to mpv-first)
        player_bin = find_mpv()
        using_mpv = player_bin is not None
        if not using_mpv:
            player_bin = find_ffplay()
    if not player_bin:
        return False, "No video player (mpv or ffplay) found on this device"

    want_controls = sdl is not None and joy_a is not None and joy_b is not None
    vkbd = VirtualKeyboard.create() if want_controls else None
    stop_event = threading.Event()
    thread = None
    if vkbd is not None:
        thread = threading.Thread(
            target=_translate_loop, args=(sdl, joy_a, joy_b, vkbd, stop_event, joy_l1, joy_r1, joy_y, joy_x,
                                            joy_l2, joy_r2, joy_start, joy_select, signal, using_mpv),
            daemon=True)
        thread.start()

    if using_mpv:
        # v26.07.20.36 BUG FIX (found during a requested re-review, not
        # a live report): previously always passed --input-conf
        # regardless of whether the write actually succeeded, pointing
        # mpv at a possibly-nonexistent file -- unclear/unverified
        # whether mpv treats that as a hard launch failure or a soft
        # warn-and-continue, so better not to risk it. Now only include
        # the flag if the write actually succeeded; otherwise mpv just
        # falls back to its own built-in default bindings (still gives
        # pause/quit/basic seek, just without the custom L1/R1 mapping
        # and without matching ffplay's exact seek amounts) rather than
        # risk breaking every mpv launch over one failed file write.
        input_conf_ok = _write_mpv_input_conf()
        args = list(_MPV_BASE_ARGS)
        if input_conf_ok:
            args += [f"--input-conf={_MPV_INPUT_CONF_PATH}"]
        if osd_title:
            # v26.07.28.07: see this function's own docstring on
            # osd_title -- literal text, "$" escaped to "$$" so mpv
            # never mis-reads an arbitrary title as a property
            # reference.
            args += [f"--osd-playing-msg={osd_title.replace('$', '$$')}"]
        # v26.07.20.36 BUG FIX: previously gated on
        # "fill_screen and screen_w and screen_h", inherited from
        # ffplay's branch below -- but that requirement is ffplay-
        # specific (its manual scale+crop needs explicit numbers).
        # mpv's --panscan=1.0 is a relative zoom-to-fill flag and needs
        # no dimensions at all; gating it on screen_w/screen_h being
        # truthy meant fill_screen could silently fail to apply on mpv
        # in any edge case where those happened to be None/0, even
        # though nothing was actually stopping it from working.
        if fill_screen:
            args += ["--panscan=1.0"]
        else:
            # v26.07.20.37: explicit fit-mode flags matching muOS's own
            # real ext-mpv.sh exactly, rather than relying on mpv's bare
            # defaults to happen to produce the same letterboxed result
            # -- removes any doubt, since this is the literal invocation
            # muOS's own built-in Media Player uses and has presumably
            # been tested against every supported device.
            args += ["--keepaspect=yes", "--video-zoom=0",
                     "--video-align-x=0", "--video-align-y=0"]
        args = [player_bin] + args + [source]
    else:
        args = list(_FFPLAY_BASE_ARGS)
        if fill_screen and screen_w and screen_h:
            w, h = int(screen_w), int(screen_h)
            args += ["-vf", f"scale={w}:{h}:force_original_aspect_ratio=increase:"
                             f"flags=fast_bilinear,crop={w}:{h}"]
        args = [player_bin] + args + [source, "-autoexit", "-loglevel", "error"]

    # v26.07.21.35 (real fix, see suppress_idle_display()'s own comment
    # for the full story of why v26.07.21.22's approach didn't work).
    # Called right before the player actually launches, restored in
    # the SAME finally block stop_event/vkbd cleanup already uses --
    # guaranteed to run whether playback ends normally, the player
    # crashes, or subprocess.run() itself raises.
    # v26.07.21.38: `_manage_idle` (internal -- not part of the public
    # signature callers should rely on) lets play_video_queue() below
    # suppress idle-display ONCE for a whole Play All/Shuffle All
    # session instead of once per video, same reasoning
    # play_audio_queue() already uses for audio -- avoids restarting
    # the hotkey daemon after every single video in a queue.
    if _manage_idle:
        _orig_idle_sleep, _orig_idle_display = suppress_idle_display()
    try:
        result = subprocess.run(args, check=False, stderr=subprocess.PIPE, text=True)
        if result.stderr:
            _ffplay_log(f"\n--- {source} ({'mpv' if using_mpv else 'ffplay'}) ---\n{result.stderr}")
    except OSError as e:
        return False, f"Couldn't start {'mpv' if using_mpv else 'ffplay'}: {e}"
    finally:
        if _manage_idle:
            restore_idle_display(_orig_idle_sleep, _orig_idle_display)
        stop_event.set()
        if thread is not None:
            thread.join(timeout=2)
        if vkbd is not None:
            vkbd.close()

    # v26.07.20.14 BUG FIX (Kaleb's request -- bug check): previously
    # this always returned (True, None) regardless of how the player
    # actually exited, so a real failure (bad URL, dead connection,
    # corrupt stream) was silently reported to the caller as a normal
    # successful playback session -- the UI had zero way to tell the
    # difference from the user just watching the whole video and
    # quitting normally. Both players exit 0 on a clean end-of-file or
    # a normal user quit; a non-zero code means it actually failed to
    # play. Surface that, with a short reason pulled from stderr (first
    # non-empty line only -- verbose players can be multi-line and this
    # becomes a toast message, not a log dump; full detail is always in
    # FFPLAY_LOG regardless of which player was used).
    if result.returncode != 0:
        reason = next((ln for ln in result.stderr.splitlines() if ln.strip()),
                       None) if result.stderr else None
        msg = f"Video playback failed: {reason}" if reason else "Video playback failed"
        return False, msg

    if vkbd is None and want_controls:
        return True, "Played without gamepad controls (uinput unavailable)"
    return True, None


def play_video_queue(items, start_index=0, shuffle=False, sdl=None, joy_a=None, joy_b=None,
                      joy_l1=None, joy_r1=None, joy_l2=None, joy_r2=None, joy_y=None, joy_x=None,
                      joy_start=None, joy_select=None, fill_screen=False, screen_w=None,
                      screen_h=None, player_pref="mpv", on_track_change=None, resolve_source=None):
    """v26.07.21.38 (Kaleb's request: "can we do the shuffle and play
    all feature playlist on all video pages too?"). Direct video sibling
    of play_audio_queue() -- same shape, same reasoning, plays a whole
    list of videos back-to-back via play_video_source() per item, either in
    the order given (`shuffle=False`, "Play All") or randomized
    (`shuffle=True`, "Shuffle All"). `items` is the same shape
    list_video_items()/list_mediator_category() etc. already return,
    each with a real "_video_url".

    Unlike audio (which had free shoulder buttons for skip), every
    other button is already spoken for during video playback -- see
    _translate_loop's own comment on why SELECT (next) and START (prev)
    are the queue-skip controls here instead of L/R.

    idle-display suppression is applied ONCE for the whole queue, same
    as play_audio_queue() -- play_video_source() is called with
    _manage_idle=False so it doesn't ALSO suppress/restore per video,
    which would restart the hotkey daemon after every single item.

    v26.07.21.39 (Kaleb's request: prefer an already-downloaded local
    copy over streaming): `resolve_source(item) -> (source, is_local)`,
    if given, is called for EVERY item instead of the hardcoded
    `item["_video_url"], is_local=False` -- lets the caller (main.py,
    which knows each plugin's own download-folder/filename
    convention; this file deliberately stays plugin-agnostic, see its
    own top-of-file note) decide per item whether a local downloaded
    copy exists and should be used instead. Falls back to the
    old hardcoded remote-URL behavior if resolve_source isn't given, so
    existing callers are unaffected.

    Returns (ok: bool, message: str | None), same "user quit isn't a
    failure" contract as play_audio_queue()."""
    if not items:
        return False, "Nothing to play"

    order = list(range(len(items)))
    if shuffle:
        # v26.07.27.22: see _shuffled_order()'s own docstring -- avoids
        # (best effort) reopening with the same tracks that started the
        # LAST shuffle on this queue kind, in-RAM only for this instance.
        order = _shuffled_order(items, "video")
        pos = 0
    else:
        pos = max(0, min(start_index, len(order) - 1))

    orig_sleep, orig_display = suppress_idle_display()
    signal = {"abort": False, "skip": 0}
    last_ok, last_msg = True, None
    try:
        while 0 <= pos < len(order):
            item = items[order[pos]]
            if resolve_source:
                source, is_local = resolve_source(item)
            else:
                source, is_local = item.get("_video_url"), False
            if not source:
                pos += 1
                continue
            if on_track_change:
                on_track_change(item, pos, len(order))
            signal["skip"] = 0
            # v26.07.28.07 (Kaleb's request): same string on_track_change's
            # own SDL card used to show, now handed to mpv's native OSD
            # instead -- see play_video_source()'s own docstring on osd_title.
            _label = "Shuffle All" if shuffle else "Play All"
            _osd_title = f"{_label} ({pos + 1}/{len(order)}) {item.get('title', '')}"
            ok, msg = play_video_source(
                source, is_local=is_local, sdl=sdl, joy_a=joy_a, joy_b=joy_b,
                joy_l1=joy_l1, joy_r1=joy_r1, joy_l2=joy_l2, joy_r2=joy_r2,
                joy_y=joy_y, joy_x=joy_x, joy_start=joy_start, joy_select=joy_select,
                signal=signal, fill_screen=fill_screen, screen_w=screen_w, screen_h=screen_h,
                player_pref=player_pref, _manage_idle=False, osd_title=_osd_title)
            if not ok:
                last_ok, last_msg = ok, msg
                break
            if signal["abort"]:
                break
            pos += signal["skip"] if signal["skip"] else 1
    finally:
        restore_idle_display(orig_sleep, orig_display)
    return last_ok, last_msg


# ---------------------------------------------------------------------------
# Audio (MP3) playback -- v26.07.21.36 (Kaleb's request: in-app audio
# playback for the Audio/song lists this app already browses and
# downloads, with an mpv/ffplay player choice matching the video
# player's own, plus a shuffle and a sequential "play all" mode).
# Shares the same player-discovery (find_mpv/find_ffplay), uinput
# button-translation approach, and idle-suppression mechanism as video
# playback -- deliberately NOT a separate reimplementation of any of
# those, just a leaner control set (no seek/subtitle/brightness --
# none of that applies to audio) and a queue wrapper around single-
# track playback for the two new list-playback modes.

_MPV_AUDIO_ARGS = [
    "--no-config", "--fs",
    # v26.08.07.02 REAL BUG FIX (Kaleb's report: LibriVox audio played
    # but the screen went black and ZERO controls worked -- not even
    # B/quit, forcing a full muOS hotkey reboot). Root cause, confirmed
    # against this file's OWN prior documentation just below: mpv only
    # creates a real video/window surface when the file has something
    # to show as "video" -- an embedded ID3 cover (APIC frame) counts,
    # nothing else does. --fs only fullscreens a window that ALREADY
    # exists; it does not force one into existence. JW's audio
    # apparently carries embedded art (mpv had a real window, --fs
    # worked, controls worked). LibriVox's archive.org-hosted files
    # don't embed cover art (normal/expected for LibriVox) -- so mpv
    # never created a window AT ALL, meaning there was never anything
    # for DRM/KMS to give input focus to, meaning the uinput-translated
    # keypresses genuinely had nowhere to land, exactly the v26.07.21.40
    # bug class below, just re-triggered by a content property that
    # bug fix didn't account for. --force-window=yes is mpv's own real,
    # documented option for precisely this situation (audio-only
    # playback that still wants a window for OSD/focus) -- forces
    # window creation unconditionally, regardless of whether the file
    # has an embedded "video" stream to show.
    "--force-window=yes",
    "--osd-bar", "--osd-level=1",
    # v26.07.21.41 (Kaleb's request: "whatever the native app supports
    # -- text title or album cover and title"). mpv NATIVELY shows an
    # MP3's embedded cover art (ID3 APIC frame) as its "video" if one
    # exists, and does nothing extra (just the plain OSD below) if the
    # file has none -- this app doesn't need to fetch/manage any
    # artwork itself, just not suppress it. --no-video (which WAS here)
    # was exactly what suppressed this -- removed. --osd-playing-msg
    # is mpv's own real property-expansion syntax (${media-title}
    # pulls the file's own ID3 title tag, same one mpv's file browser/
    # OSC would show) -- also native, not a custom overlay this app
    # draws itself.
    "--osd-playing-msg=${media-title}",
    "--network-timeout=15",
    "--msg-level=all=error",
    "--stream-lavf-o=reconnect=1,reconnect_streamed=1,reconnect_at_eof=1,reconnect_delay_max=2",
]

# v26.07.21.40 REAL BUG FIX (Kaleb's report: audio played but the whole
# app went unresponsive -- not even B/quit worked). Root cause: both
# audio configs skipped creating any real display surface (mpv had
# --no-video with no --fs at all; ffplay had -nodisp, which doesn't
# just hide video -- it skips window creation ENTIRELY). Both players'
# own keyboard/controller input handling is built around their SDL
# window's event loop, so with no window to hold focus, the actual
# uinput keypresses this app sends (via vkbd) had nowhere to land --
# the player process itself was fine and kept decoding/playing audio
# (that pipeline doesn't depend on the window), but literally nothing,
# including quit, could reach it. Fixed by giving both a real
# fullscreen surface, matching the working video path exactly: mpv
# gets --fs added above; ffplay drops -nodisp for -showmode 0 plus
# -fs below.
#
# v26.07.21.41 (Kaleb's request: "whatever the native app supports --
# text title or album cover and title"): "-showmode 0" is ffplay's own
# real, documented "video" mode -- for an MP3 with embedded cover art
# (ID3 APIC frame), that IS the video stream, so this already shows it
# natively, no extra code needed (same reasoning as mpv above, just
# ffplay's equivalent flag). For a file with no embedded art, mode 0
# is a plain blank frame, same as before. -window_title sets ffplay's
# own window title to the track name -- genuinely native, but an
# honest caveat: muOS's display stack has no window manager/compositor
# (see this file's own top-of-file KMSDRM note), so there's no title
# bar to actually render it in -- included anyway since it's free and
# harmless, in case a future muOS version or a different VO path ever
# does show it, but Kaleb shouldn't expect to see it today. ffplay has
# no equivalent to mpv's --osd-playing-msg (a real on-screen TEXT
# overlay) -- that's a genuine capability gap between the two players,
# not something this app is choosing to withhold from ffplay.
# v26.08.07.02 REAL BUG FIX (same root cause as mpv's --force-window
# above, ffplay's own equivalent): "-showmode 0" needs an actual video
# stream to render -- an embedded ID3 cover counts, nothing else does.
# For a file with no embedded art (LibriVox), there's no video stream
# for mode 0 to draw, so ffplay likely never created a real window at
# all -- this file's own EARLIER comment assumed "mode 0 is a plain
# blank frame" for that case, but that assumption was never actually
# confirmed on real hardware, and Kaleb's real LibriVox report (screen
# black, zero controls, forced hotkey reboot) contradicts it. Switched
# to "-showmode 1" (waveform) -- ffplay's own documented mode that
# always draws something from the audio itself, guaranteeing a real
# window regardless of whether the file has embedded art. Slightly
# different look than mode 0 for JW audio WITH embedded art (a
# waveform instead of the cover image), a deliberate tradeoff for a
# real window every time on every source.
_FFPLAY_AUDIO_ARGS = [
    "-showmode", "1", "-fs", "-autoexit",
    "-reconnect", "1", "-reconnect_streamed", "1",
    "-reconnect_at_eof", "1", "-reconnect_delay_max", "2",
    "-rw_timeout", "15000000",
    "-loglevel", "error",
]


def _audio_translate_loop(sdl, joy_a, joy_b, joy_l, joy_r, vkbd, stop_event, signal,
                           joy_l2=None, joy_r2=None, is_queue=False, joy_y=None, joy_x=None,
                           joy_start=None, joy_select=None, using_mpv=True):
    """Sibling of _translate_loop() (video's own), now with a matching
    button scheme -- pause, quit-track-vs-quit-queue, track skip, seek,
    and two view toggles. `signal` is a shared dict {"abort": bool,
    "skip": int} the OUTER queue loop (see play_audio_queue() below)
    reads after each track ends: abort=True means stop the whole queue
    (B was pressed); skip=+1/-1 means the CURRENT track was
    deliberately skipped (R2/L2), advance/retreat the queue position
    instead of treating it as the track naturally finishing. Ending
    the current track (to let the queue loop move on) is done the same
    way for skip and quit alike -- tap Q, the same key both mpv and
    ffplay already quit on -- the only difference is which flag gets
    set first so the queue loop knows which case it's actually
    handling.

    v26.07.27.01 REAL FIX (Kaleb: "mpv was fine, you're mapping the
    controls wrong" -- confirmed by pulling mpv's actual compiled-in
    default input.conf, github.com/mpv-player/mpv/blob/master/etc/
    input.conf, as ground truth rather than assuming). The previous
    scheme below invented custom overrides instead of using mpv's own
    real defaults -- mpv's real 'v' key is subtitle-visibility, not
    "cycle video" as previously assumed, and forcing that (plus
    non-default seek amounts) on Left/Right/Down is the likely real
    cause of Kaleb's on-device freeze (both local and streamed audio,
    all three of those keys). New scheme, every key now a genuine mpv
    default, each cross-checked against ffplay's complete documented
    keymap to confirm it's still a safe no-op there:

        A            -- pause/play (KEY_SPACE)
        B            -- quit track + queue (KEY_Q)
        L1 (joy_l)   -- seek back ~10min (mpv: Shift+PGDOWN, its real
                        default; ffplay: plain PGDOWN, its own real
                        default -- no shift concept there). Replaces
                        speed control at v26.07.29.09 (Kaleb's request,
                        for parity with video dropping speed control
                        entirely over a real hardware-decode catch-up
                        lag report).
        R1 (joy_r)   -- mirror of L1: seek forward ~10min (Shift+PGUP
                        mpv / plain PGUP ffplay, same self-selecting
                        chapter/10min behavior as ffplay's L2/R2 below).
        L2 (joy_l2)  -- QUEUE mode (is_queue=True, i.e. this session is
                        part of a Play All/Shuffle All run): previous
                        track (skip=-1, KEY_Q), unchanged. SINGLE-FILE
                        mode (is_queue=False): previous chapter (plain
                        PGDOWN -- was seek back ~60s before v26.07.29.09,
                        moved to D-pad Down below). A genuine real
                        default on BOTH players: mpv's is "add chapter
                        -1"; per ffmpeg.org/ffplay.html, ffplay's own
                        real default for plain PGDOWN is "seek to
                        previous chapter, or ~10min back if the file
                        has no chapters" -- it already self-selects, no
                        using_mpv branch needed.
        R2 (joy_r2)  -- mirror of L2: next track (skip=+1, KEY_Q) in
                        queue mode; next chapter (or ~10min forward if
                        no chapters) in single-file mode.
        D-pad LEFT   -- seek back ~5s (KEY_LEFT, mpv's real default).
                        ffplay: seek back ~10min (KEY_PAGEDOWN, its own
                        real default -- no speed feature to have
                        swapped in the first place, unchanged since
                        v26.07.29.05).
        D-pad RIGHT  -- seek forward ~5s (KEY_RIGHT), same reasoning.
                        ffplay: seek forward ~10min (KEY_PAGEUP).
        D-pad UP     -- seek forward ~60s (KEY_UP -- mpv and ffplay
                        share the IDENTICAL real default here, so no
                        using_mpv branch needed). Was OSD toggle before
                        v26.07.29.09 (moved to START below).
        D-pad DOWN   -- seek back ~60s (KEY_DOWN), same reasoning as
                        D-pad Up. Was mute before v26.07.29.09 (moved
                        to X below).
        Y (joy_y)    -- toggle repeat on the current track (Shift+L ->
                        mpv's real default "cycle-values loop-file inf
                        no"). v26.07.27.05 (Kaleb's request, after
                        confirming volume keys are a no-op here --
                        muOS's own hardware mixer sits outside mpv/
                        ffplay's software volume entirely, so 9/0
                        wouldn't do anything audible). Kept unchanged
                        through the v26.07.29.09 parity update -- audio's
                        own distinct feature, no video equivalent to
                        match it to.
        X (joy_x)    -- mute (KEY_M, mpv/ffplay's real native mute key
                        on both players). Was reset-speed-to-1x (mpv) /
                        cycle-visualizer (ffplay) before v26.07.29.09 --
                        dropped along with speed control itself, now
                        matches video's X exactly.
        START (joy_start) -- toggle permanent OSD (Shift+O, mpv's real
                        default -- moved here from D-pad Up at
                        v26.07.29.09). No real ffplay equivalent,
                        genuine no-op there. Was a plain pause/play
                        duplicate of A before v26.07.29.09.
        SELECT (joy_select) -- shows resolution + codec (KEY_I, rebound
                        via the bundled input.conf to a core show-text +
                        property-expansion command -- v26.07.30.04 fix,
                        see _MPV_INPUT_CONF's own comment; the default
                        'i' binding this used to rely on, mpv's Lua
                        stats script, likely isn't compiled into this
                        device's mpv build at all). No real ffplay
                        equivalent, genuine no-op there. Was a plain
                        quit duplicate of B before v26.07.29.09.

    `is_queue`, if True, means this loop is running inside
    play_audio_queue()'s session -- a real, persistent `signal` dict is
    being read by the outer queue loop after each track, so L2/R2's
    skip flag actually does something. False (the default, used by a
    plain single-track play_audio_file() call) means `signal` is just
    a throwaway dict nothing reads afterward -- track-skip there would
    have silently done nothing useful, which was a real, if minor, gap
    in the previous scheme (L2/R2 during a single track just ended it
    early with no macro-seek fallback at all)."""
    SDL_JoyHatEvent, SDL_JoyButtonEvent = _make_event_types()
    ev_buf = (ctypes.c_byte * 56)()
    while not stop_event.is_set():
        while sdl.SDL_PollEvent(ctypes.byref(ev_buf)) != 0:
            etype = ctypes.cast(ev_buf, ctypes.POINTER(ctypes.c_uint32))[0]
            if etype == SDL_JOYBUTTONDOWN_EV:
                bev = ctypes.cast(ev_buf, ctypes.POINTER(SDL_JoyButtonEvent))[0]
                if bev.button == joy_a:
                    vkbd.tap(KEY_SPACE)      # A -- pause/play
                elif bev.button == joy_b:
                    signal["abort"] = True
                    vkbd.tap(KEY_Q)          # B -- quit this track AND the queue
                # v26.07.29.09 (Kaleb's request -- bring audio into
                # parity with video's v26.07.29.07/.08 reshuffle): L2/R2
                # QUEUE mode unchanged (prev/next track). SINGLE-FILE
                # mode now does chapter-skip instead of +-60s (moved to
                # D-pad Up/Down below) -- plain PGUP/PGDOWN is a genuine
                # real default on BOTH players here, same as video's
                # identical change: mpv's is "add chapter 1/-1";
                # ffplay's own real default (per ffmpeg.org/ffplay.html)
                # is "seek to previous/next chapter, OR +-10min if no
                # chapters" -- it already self-selects, no using_mpv
                # branch needed.
                elif joy_r2 is not None and bev.button == joy_r2:
                    if is_queue:
                        signal["skip"] = 1
                        vkbd.tap(KEY_Q)         # R2 -- next track (queue)
                    else:
                        vkbd.tap(KEY_PAGEUP)    # R2 -- next chapter (or
                                                # ~10min forward if no chapters)
                elif joy_l2 is not None and bev.button == joy_l2:
                    if is_queue:
                        signal["skip"] = -1
                        vkbd.tap(KEY_Q)         # L2 -- previous track (queue)
                    else:
                        vkbd.tap(KEY_PAGEDOWN)  # L2 -- previous chapter (or
                                                # ~10min back if no chapters)
                # L1/R1: +-10min seek (was speed control -- dropped
                # entirely from audio too, Kaleb's explicit call, for
                # full parity with video's own speed-control removal).
                # Same real key reasoning as video's identical change:
                # mpv's real default is Shift+PGUP/PGDOWN; ffplay's is
                # plain PGUP/PGDOWN (no shift concept, real substitute).
                elif joy_r is not None and bev.button == joy_r:
                    if using_mpv:
                        vkbd.tap_shifted(KEY_PAGEUP)    # R1 -- seek forward ~10min (mpv)
                    else:
                        vkbd.tap(KEY_PAGEUP)            # R1 -- seek forward ~10min (ffplay)
                elif joy_l is not None and bev.button == joy_l:
                    if using_mpv:
                        vkbd.tap_shifted(KEY_PAGEDOWN)  # L1 -- seek back ~10min (mpv)
                    else:
                        vkbd.tap(KEY_PAGEDOWN)          # L1 -- seek back ~10min (ffplay)
                elif joy_y is not None and bev.button == joy_y:
                    vkbd.tap_shifted(KEY_L)  # Y -- toggle repeat (mpv only,
                                              # no real ffplay loop-toggle analog
                                              # exists) -- kept as-is, audio's
                                              # own distinct feature with no
                                              # video equivalent to match.
                elif joy_x is not None and bev.button == joy_x:
                    vkbd.tap(KEY_M)          # X -- mute (was reset-speed/
                                             # cycle-visualizer -- dropped
                                             # along with speed control, now
                                             # matches video's X exactly)
                # START -- toggle permanent OSD (was pause/play duplicate).
                # SELECT -- toggle stats overlay (was quit duplicate).
                # Both mpv-only, genuine no-op on ffplay -- matches
                # video's identical START/SELECT roles exactly.
                elif joy_start is not None and bev.button == joy_start:
                    if using_mpv:
                        vkbd.tap_shifted(KEY_O)  # START -- toggle permanent OSD (mpv)
                elif joy_select is not None and bev.button == joy_select:
                    if using_mpv:
                        # v26.07.30.04: still taps 'i', but the bundled
                        # mpv input.conf now rebinds 'i' to a real core
                        # show-text+property-expansion command (WxH +
                        # codec) instead of the default script-binding
                        # to mpv's Lua stats overlay, which this device's
                        # mpv build likely doesn't have compiled in --
                        # see _MPV_INPUT_CONF's own comment for the full
                        # story.
                        vkbd.tap(KEY_I)          # SELECT -- show resolution/codec (mpv)
            elif etype == SDL_JOYHATMOTION_EV:
                hev = ctypes.cast(ev_buf, ctypes.POINTER(SDL_JoyHatEvent))[0]
                hv = hev.value
                # D-pad Left/Right: unchanged -- mpv's small +-5s seek
                # tier / ffplay's own +-10min seek default.
                #
                # v26.07.29.09: D-pad Up/Down now do the +-60s seek
                # tier (was OSD toggle/mute, moved to START/X above) --
                # matches video's identical change exactly. mpv and
                # ffplay share the IDENTICAL real default here
                # (KEY_UP/KEY_DOWN = seek +-60s on both players), so no
                # using_mpv branch is needed.
                if hv & SDL_HAT_LEFT:
                    if using_mpv:
                        vkbd.tap(KEY_LEFT)        # D-pad left -- seek back ~5s (mpv)
                    else:
                        vkbd.tap(KEY_PAGEDOWN)    # D-pad left -- seek back ~10min (ffplay)
                elif hv & SDL_HAT_RIGHT:
                    if using_mpv:
                        vkbd.tap(KEY_RIGHT)       # D-pad right -- seek forward ~5s (mpv)
                    else:
                        vkbd.tap(KEY_PAGEUP)      # D-pad right -- seek forward ~10min (ffplay)
                elif hv & SDL_HAT_UP:
                    vkbd.tap(KEY_UP)      # D-pad up -- seek forward ~60s (mpv + ffplay)
                elif hv & SDL_HAT_DOWN:
                    vkbd.tap(KEY_DOWN)    # D-pad down -- seek back ~60s (mpv + ffplay)
        time.sleep(_POLL_INTERVAL)


def play_audio_file(url, sdl=None, joy_a=None, joy_b=None, joy_l=None, joy_r=None,
                     player_pref="mpv", signal=None, is_local=False, title=None,
                     joy_l2=None, joy_r2=None, joy_y=None, joy_x=None,
                     joy_start=None, joy_select=None):
    """Plays a single MP3, audio-only (no video window), blocking until
    it ends or is skipped/quit. Mirrors play_video_source()'s player-
    discovery and button-translation shape, minus every video-specific
    control. `signal`, if given, is the same shared dict
    _audio_translate_loop() writes to -- pass the SAME dict across an
    entire play_audio_queue() session so skip/abort state survives
    from one track's playback into the next call. Returns
    (ok: bool, message: str | None), same contract as play_video_source().
    Does NOT call suppress_idle_display()/restore_idle_display() itself
    -- see play_audio_queue() for why that's scoped around the WHOLE
    queue instead of once per track.

    v26.07.21.39 (Kaleb's request: prefer an already-downloaded local
    copy over streaming): `is_local=True` treats `url` as a local file
    path instead, validated via os.path.isfile() same as
    play_video_source()'s own is_local handling, rather than requiring a
    real remote streaming URL.

    v26.07.21.41 (Kaleb's request: native title/album-art support):
    `title`, if given, sets ffplay's own -window_title (native, but
    see _FFPLAY_AUDIO_ARGS's own comment on why it likely isn't
    visible on muOS's windowless display stack -- included anyway,
    it's free). mpv doesn't need this passed in -- --osd-playing-msg
    in _MPV_AUDIO_ARGS reads the file's own embedded ID3 title tag
    directly, no plumbing required.

    v26.07.27.01 (see _audio_translate_loop()'s own docstring for the
    full current scheme): `is_queue` is derived here as
    `signal is not None` -- i.e. only a genuine call from
    play_audio_queue() (which always passes its own real, persistent
    signal dict) is treated as queue mode; a plain single-track call
    (signal left at its default None) gets is_queue=False, so L2/R2
    correctly falls back to a macro-seek instead of a no-op skip."""
    if is_local:
        if not os.path.isfile(url):
            return False, "Audio file not found"
    elif not is_allowed_stream_url(url):
        return False, "Not a valid audio URL"

    if player_pref == "ffplay":
        player_bin = find_ffplay()
        using_mpv = False
        if not player_bin:
            player_bin = find_mpv()
            using_mpv = player_bin is not None
    else:
        player_bin = find_mpv()
        using_mpv = player_bin is not None
        if not using_mpv:
            player_bin = find_ffplay()
    if not player_bin:
        return False, "No audio player (mpv or ffplay) found on this device"

    want_controls = sdl is not None and joy_a is not None and joy_b is not None
    vkbd = VirtualKeyboard.create() if want_controls else None
    stop_event = threading.Event()
    thread = None
    if vkbd is not None:
        # v26.07.27.01: is_queue computed BEFORE signal gets defaulted
        # to a throwaway {} below -- a real signal dict only ever
        # arrives from play_audio_queue()'s own call, so this is a
        # reliable "am I in a queue?" check for _audio_translate_loop's
        # mode-aware L2/R2 handling.
        is_queue = signal is not None
        thread = threading.Thread(
            target=_audio_translate_loop,
            args=(sdl, joy_a, joy_b, joy_l, joy_r, vkbd, stop_event, signal if signal is not None else {}),
            kwargs={"joy_l2": joy_l2, "joy_r2": joy_r2, "is_queue": is_queue,
                    "joy_y": joy_y, "joy_x": joy_x,
                    "joy_start": joy_start, "joy_select": joy_select,
                    "using_mpv": using_mpv},
            daemon=True)
        thread.start()

    if using_mpv:
        wrote_ok = _write_mpv_input_conf()
        args = list(_MPV_AUDIO_ARGS)
        if wrote_ok:
            args += [f"--input-conf={_MPV_INPUT_CONF_PATH}"]
        args = [player_bin] + args + [url]
    else:
        args = list(_FFPLAY_AUDIO_ARGS)
        if title:
            args += ["-window_title", title]
        args = [player_bin] + args + [url]

    try:
        result = subprocess.run(args, check=False, stderr=subprocess.PIPE, text=True)
        if result.stderr:
            _ffplay_log(f"\n--- {url} ({'mpv' if using_mpv else 'ffplay'}, audio) ---\n{result.stderr}")
    except OSError as e:
        return False, f"Couldn't start {'mpv' if using_mpv else 'ffplay'}: {e}"
    finally:
        stop_event.set()
        if thread is not None:
            thread.join(timeout=2)
        if vkbd is not None:
            vkbd.close()

    if result.returncode != 0:
        reason = next((ln for ln in result.stderr.splitlines() if ln.strip()),
                       None) if result.stderr else None
        msg = f"Audio playback failed: {reason}" if reason else "Audio playback failed"
        return False, msg
    return True, None


def play_audio_queue(items, start_index=0, shuffle=False, sdl=None, joy_a=None, joy_b=None,
                      joy_l=None, joy_r=None, player_pref="mpv", on_track_change=None,
                      resolve_source=None, joy_l2=None, joy_r2=None, joy_y=None, joy_x=None,
                      joy_start=None, joy_select=None):
    """v26.07.21.36 (Kaleb's request): plays a whole list of audio
    items back-to-back, either in the order given (`shuffle=False`,
    "Play All") or in a randomized order (`shuffle=True`, "Shuffle
    All"). `items` is the SAME list shape every audio-capable plugin's
    audio loaders already return (each with a real "_audio_url" and
    "title", the exact fields already confirmed live throughout this
    session).
    `start_index` only affects sequential mode -- shuffle always starts
    from a fresh random order regardless. `on_track_change(item, idx,
    total)`, if given, is called right before each track starts, so
    the caller can show a "Now Playing" toast/status without this
    function needing to know anything about drawing.

    idle-display suppression is applied ONCE for the whole queue, not
    per track (see suppress_idle_display()'s own comment on why a
    per-pause-toggle version isn't implemented) -- covers the entire
    "Play All"/"Shuffle All" session in one restart of the hotkey
    daemon rather than one per track, which would be needless overhead
    for a list that could be dozens of songs long.

    v26.07.23.29 ROLLBACK (Kaleb's report: the v26.07.23.12-.20 "On
    Lid/Standby" three-way toggle never actually worked as designed on
    real hardware -- closing the lid suspended regardless of which mode
    was selected; Kaleb's own direction was to remove it rather than
    keep guessing at a fix): back to plain suppress_idle_display()/
    restore_idle_display(), same as video, with no mode parameter.

    v26.07.21.39 (Kaleb's request: prefer an already-downloaded local
    copy over streaming): `resolve_source(item) -> (source, is_local)`,
    if given, is called for EVERY item instead of the hardcoded
    `item["_audio_url"], is_local=False` -- see play_video_queue()'s
    identical addition for the full reasoning (this file staying
    plugin-agnostic, main.py owning the actual download-folder lookup).
    Falls back to the old hardcoded remote-URL behavior if
    resolve_source isn't given.

    R/L (see _audio_translate_loop()) skip forward/back within the
    queue; B stops the whole queue early. Returns (ok: bool,
    message: str | None) -- ok=True whenever the queue completes or is
    stopped by the user (B), matching play_video_source()'s own "user quit
    is not a failure" convention; ok=False only on a real playback
    error partway through."""
    if not items:
        return False, "Nothing to play"

    order = list(range(len(items)))
    if shuffle:
        # v26.07.27.22: see _shuffled_order()'s own docstring -- avoids
        # (best effort) reopening with the same tracks that started the
        # LAST shuffle on this queue kind, in-RAM only for this instance.
        order = _shuffled_order(items, "audio")
        pos = 0
    else:
        pos = max(0, min(start_index, len(order) - 1))

    orig_sleep, orig_display = suppress_idle_display()
    signal = {"abort": False, "skip": 0}
    last_ok, last_msg = True, None
    try:
        while 0 <= pos < len(order):
            item = items[order[pos]]
            if resolve_source:
                source, is_local = resolve_source(item)
            else:
                source, is_local = item.get("_audio_url"), False
            if not source:
                pos += 1
                continue
            if on_track_change:
                on_track_change(item, pos, len(order))
            signal["skip"] = 0
            ok, msg = play_audio_file(source, sdl=sdl, joy_a=joy_a, joy_b=joy_b,
                                       joy_l=joy_l, joy_r=joy_r, player_pref=player_pref,
                                       signal=signal, is_local=is_local, title=item.get("title"),
                                       joy_l2=joy_l2, joy_r2=joy_r2, joy_y=joy_y, joy_x=joy_x,
                                       joy_start=joy_start, joy_select=joy_select)
            if not ok:
                last_ok, last_msg = ok, msg
                break
            if signal["abort"]:
                break
            pos += signal["skip"] if signal["skip"] else 1
    finally:
        restore_idle_display(orig_sleep, orig_display)
    return last_ok, last_msg
