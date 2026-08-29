"""
jw_fetch.py

Current version: v26.08.26.07 (matches main.py's date-based scheme,
YY.MM.DD.XX). Inline "# vYY.MM.DD.XX" comments document non-obvious
behavior near the relevant code, same convention as main.py.

Optional PicoReader plugin: download JW.org EPUB publications directly
onto the device, using the same public media API JW.org's own official
apps use (b.jw-cdn.org/apis/pub-media/GETPUBMEDIALINKS) plus the
jw.org "What's New" RSS feed to auto-detect the newest Watchtower Study
Edition and Meeting Workbook issue without needing to know or guess a date.

PRIVATE PLUGIN -- per the person's explicit instruction, this file is
NOT to be published to a public GitHub repo alongside gutenberg_fetch.py.
Keep it local-only. See AI NOTES in main.py for the full legal reasoning
(jw.org Terms of Use, checked in-conversation, not guessed).

All pub codes below were verified LIVE against the real API before being
added here (not guessed) -- see main.py's AI NOTES for the verification
method if any of these ever need re-checking after a JW.org catalog change.

ARCHITECTURE -- READ THIS BEFORE DEBUGGING A UI/NAVIGATION ISSUE.
As of the v26.08.06.17-.20 "dl_items/dl_index unification" and the
several sessions since, almost all of the actual BROWSING, NAVIGATION,
STREAMING/DOWNLOADING, DELETING, and OFFLINE-DOWNLOADED-LIST machinery
that Kaleb interacts with for JW content lives in main.py as GENERIC,
plugin-agnostic code shared with gutenberg_fetch.py and
librivox_fetch.py -- NOT in this file. This file's real job is data
and config only:
  - AUDIO_SOURCES/VIDEO_SOURCES/CATEGORIES/STATIC_PUBLICATIONS: what
    exists and how it's organized (the actual content structure).
  - list_items()/list_audio_items()/list_mediator_category()/
    list_watchtower_audio_issues()/etc.: functions that FETCH real
    data from JW.org's own APIs, given a category/pub code/key.
  - PLUGIN_NAME/find_movies_dir()/find_music_dir()/
    sanitize_folder_name(): identity and folder-naming, called BY
    main.py's generic save/local-scan code, not implemented here.
  - download()/parse_epub_filename()/resolve_item_category(): the
    functions every PicoReader plugin implements, per the shared
    rules (see PLUGIN_TEMPLATE.py in the public repo).
main.py owns: the actual screens/menus (SCREEN_DOWNLOAD_*), the B-
button navigation between them, play_audio_item()/play_video_item()
and their local-vs-streamed resolution (_resolve_media_source()), the
Downloaded Audio/Video local-scan browsing and Delete feature, Pinned
Discoveries replay, and -- as of a real, confirmed bug this session --
the destination-folder-path logic (_category_dest_dir()) that used to
hardcode the wrong plugin under certain conditions. If something looks
broken in HOW content is browsed/played/deleted/organized on screen,
that's very likely a main.py bug, not a jw_fetch.py one, even though
it only shows up when JW content is what's on screen -- check
main.py's own AI notes/changelog first. If something looks broken in
WHAT content exists, what category it's filed under, or a specific
pub code/URL not resolving, that's this file.

HOW main.py FINDS AND WIRES THIS FILE UP -- entirely capability-based,
never name-locked to "jw_fetch" specifically (main.py's own comments
are explicit about this: the goal is that a future differently-named
plugin implementing the same interface would be picked up identically,
with zero main.py changes):
  - DOWNLOAD_PLUGINS: built once at import time by trying to import
    each of "gutenberg_fetch", "jw_fetch", "librivox_fetch" by
    filename and appending whichever ones succeed. A module simply
    not being present (this file stripped for a public-only build) is
    caught and logged, not fatal -- the whole rest of the app
    continues fine with a smaller DOWNLOAD_PLUGINS list. This is the
    ONLY place this file's actual filename is hardcoded anywhere in
    main.py.
  - MEDIA_PLUGIN: whichever loaded plugin has list_video_items or
    AUDIO_SOURCES -- this file today, since it's the only bundled
    module implementing that interface (gutenberg_fetch.py
    and librivox_fetch.py's own audio path use a different,
    MULTI_FILE-based mechanism instead, not this one). Every video/
    JW.org-audio-specific piece of main.py's UI is reached only
    through this reference, never by importing this file directly by
    name.
  - CHECKER_PLUGIN/LIBRIVOX_PLUGIN/GUTENBERG_PLUGIN: same pattern,
    each just `next(m for m in DOWNLOAD_PLUGINS if hasattr(m,
    "some_function"))` -- this file happens to satisfy several of
    these (check_new_publications for CHECKER_PLUGIN,
    parse_epub_filename for what GUTENBERG_PLUGIN's own lookup has to
    explicitly exclude it from, since both this file and
    gutenberg_fetch.py implement a function by that same name for
    unrelated purposes -- see that exclusion's own comment in
    main.py) purely because it happens to implement those functions,
    not because main.py special-cases it anywhere.
  - SUPPORTS_* flags (SUPPORTS_MANUAL_CODE/SUPPORTS_CATEGORIES/
    SUPPORTS_SEARCH/SUPPORTS_LOCAL_PUB_CATEGORY_LOOKUP, all set True
    below): checked via getattr(plugin, "SUPPORTS_X", False)
    throughout main.py to decide which optional UI affordances to
    show for whichever plugin is active -- same capability-detection
    principle as everything else above.
Net effect: this file could be deleted from a build entirely and
main.py would not need a single line changed -- it would just end up
with fewer DOWNLOAD_PLUGINS and MEDIA_PLUGIN/CHECKER_PLUGIN/etc. would
resolve to whatever's left (or None). That's precisely the property
that makes the public/private repo split safe -- the public main.py's
plugin-loading code has no jw_fetch-specific branch to strip.

HOW THIS PLUGIN DIFFERS FROM gutenberg_fetch.py:
  gutenberg_fetch.py queries a real search API (Gutendex) with free-text
  queries and gets back paginated results. This plugin works differently:
  - The catalog is small and fixed (a curated list of publications we know
    exist), so there's no search or pagination -- everything fits one page.
  - Downloads are a TWO-STEP process: first we call GETPUBMEDIALINKS to
    resolve the current download URL for a publication (URLs can change),
    then we fetch that URL. gutenberg_fetch.py only needs one step because
    Gutendex already gives us a direct EPUB URL in the catalog response.
  - Periodical issues (Watchtower, Workbook) need an YYYYMM issue code.
    We use the RSS feed to detect the actual latest issue, with a
    same-month fallback guess if the feed can't be reached.

PLUGIN CONTRACT -- same as gutenberg_fetch.py. See that file's docstring
for the full interface. list_items() here ignores `query`/`page` (the
catalog is small and fixed, no pagination needed) and always returns
has_next=False.

No pip dependencies -- stdlib urllib only. See gutenberg_fetch.py's
docstring for why this matters on muOS hardware.

BACK-ISSUES (v4): Watchtower ("w") lists every issue back to Jan 2016 via
generate_monthly_back_issues() -- safe, confirmed monthly with zero gaps
the whole range. Meeting Workbook ("mwb") gets its OWN generator,
generate_mwb_back_issues() -- Kaleb caught that v2 wrongly treated it as
pure-monthly too; live-verified it was actually monthly only through
Dec 2020, then changed to bi-monthly (odd months only, even months 404)
from Jan 2021 on. See MWB_BIMONTHLY_START.
Awake! ("g") does NOT use a generator for its 2016+ era -- its frequency
changed twice (6/yr Feb-Dec even months 2016-17, 3/yr Mar/Jul/Nov
2018-21, 1/yr 2022-present), so a per-year count alone can't derive
correct issue=YYYYMM codes. Instead AWAKE_BACK_ISSUES (v4, new) hard-codes
the full 2016-2025 back-issue list (28 issues) -- each one individually
confirmed live against GETPUBMEDIALINKS (HTTP 200 + EPUB file present)
before being added, same bar as everything else in this file. The
frequency changes were independently corroborated by Wikipedia's Awake!
article ("As of January 2016, it was published every two months and
was further reduced to three issues per year as of January 2018. In
2022, publication was reduced to one new issue per year") -- matches
our live results exactly. Titles sourced from jw.org's own magazine
pages. See AWAKE_BACK_ISSUES below for the full list and how to extend
it when a new issue comes out.
Awake! ALSO has an earlier confirmed-monthly era, Sept 2011 through Dec
2015 (v6, new, per Kaleb's request to go back to 2011) -- EVERY month
in this range individually checked (not spot-checked) against
GETPUBMEDIALINKS: Aug 2011 and earlier all 404 (EPUB doesn't exist),
Sept 2011 through Dec 2015 all HTTP 200 with a real EPUB file, zero
gaps across all 52 months. Genuinely safe for the same monthly-
generator approach "w" uses -- see generate_awake_monthly_issues() and
AWAKE_MONTHLY_START/END. Plain "Awake! (Month Year)" titles here (no
custom per-issue cover-story title needed, unlike the irregular 2016+
list) since this era really is one issue every month.
Watchtower ("w") and Public Watchtower ("wp") DO have an earlier era
too (correction -- an earlier version of this note said they didn't;
the original check tested the wrong issue-code format and got a false
100% 404). The real pre-2016 format is DAY-based (YYYYMMDD, not
YYYYMM): "w" always day 15, "wp" always day 1. Re-verified EVERY month
2011-2015 with the corrected format: Sept 2011 through Dec 2015 all
HTTP 200 with a real EPUB, zero gaps, clean Jan 2016 boundary (the old
day-based codes 404 from 2016 on; the new month-only codes take over
cleanly). See generate_w_pre2016_issues()/generate_wp_pre2016_issues().
Public Watchtower ("wp", v5, new): full back-issue list now implemented,
same spirit as Awake!'s but with THREE eras instead of two (jw.org/
Wikipedia's own publishing history, confirmed live against
GETPUBMEDIALINKS issue-by-issue for every month below):
  2016-2017: bi-monthly, ODD months only (Jan/Mar/May/Jul/Sep/Nov).
  2018-2021: 3/year, Jan/May/Sep only.
  2022-present: 1/year, an irregular month that changes every year
    (2022 May, 2023 May, 2024 Jul, 2025 Sep, 2026 Sep so far) -- exactly
    like Awake!, no formula, so WP_ANNUAL_ISSUES hard-codes each year's
    real month, individually confirmed live, same bar as AWAKE_BACK_ISSUES.
No EPUB exists before Jan 2016 (confirmed 404 for 2015 dates) -- same
floor as "w"/"mwb".
"""

import base64
import copy
import html
import json
import os
import re
import tempfile
import time
import urllib.request
import urllib.error
import urllib.parse

# v26.07.30.12 (Kaleb: "can't it just use epub engine to find the
# title?" -- for the Awake! theme-subtitle gap, see
# _fetch_awake_theme() below). Co-located pure-stdlib module, no
# main.py/SDL coupling (confirmed by reading its own imports), so this
# doesn't compromise jw_fetch.py's existing standalone-plugin design.
import epub_engine

# ---------------------------------------------------------------------------
# Plugin identity and capability flags
# ---------------------------------------------------------------------------

PLUGIN_NAME = "JW.org"

# v26.08.06.03 (Kaleb's request: rename native_video.py -> native_media.py
# and make it truly plugin-agnostic since it's now PUBLIC -- see main.py's
# top-of-file changelog): the streaming domain allowlist used to be a
# hardcoded JW_ALLOWED_DOMAINS constant living IN native_media.py. Moved
# here where it belongs (this file is already PRIVATE, never published),
# registered via the same register_stream_domains() mechanism
# librivox_fetch.py already uses for archive.org/librivox.org.
JW_ALLOWED_DOMAINS = ("jw.org", "wol.jw.org", "jw-cdn.org")
try:
    import native_media as _native_media_for_domains
    _native_media_for_domains.register_stream_domains(JW_ALLOWED_DOMAINS)
except Exception:
    # Streaming module not present/importable on this device (e.g. no
    # mpv/ffplay) -- downloads still work, same graceful-degradation
    # pattern librivox_fetch.py's own registration already relies on.
    pass

# ---------------------------------------------------------------------------
# "Listen to this book" -- EPUB-to-audio linking
# ---------------------------------------------------------------------------
# v26.08.05.01 (Kaleb's request: link a downloaded JW.org EPUB to its
# matching audio, offered from within the reader). Unlike the shelved
# LibriVox/Gutenberg correlation idea (cross-catalog ID matching,
# ~90%+ reliable at best), this is same-publisher: every EPUB this
# plugin downloads is already named with its own pub code (and issue,
# for periodicals) baked into the filename -- see download()'s
# safe_filename pattern, "{pub}_{LANG}.epub" or "{pub}_{LANG}_{issue}.
# epub". Parsing the filename back out is exact, not a guess.
# v26.08.05.01: built lazily (not at import time) -- LANG isn't defined
# until later in this file, and this regex needs to reflect whatever
# LANG actually is rather than a copy frozen at a point before it exists.
_EPUB_FILENAME_RE = None


def _epub_filename_re():
    global _EPUB_FILENAME_RE
    if _EPUB_FILENAME_RE is None:
        _EPUB_FILENAME_RE = re.compile(
            # v26.08.07.06 BUG FIX (Kaleb's report: "co-pgm20_E.epub"
            # stuck un-migrated in a leftover LibriVox folder). Root
            # cause, confirmed live: real JW pub codes can contain
            # hyphens (Convention Program codes like "co-pgm20", the
            # ten real tract codes like "t-ftr"/"t-god" already in
            # STATIC_PUBLICATIONS below) -- the old [a-z0-9]+ class
            # simply couldn't match any of them, so parse_epub_filename()
            # returned None for every one, and the migration tool's
            # Pass 1 skipped them as "not JW.org's" rather than moving
            # them. Added the hyphen to the character class -- every
            # existing plain alphanumeric pub code still matches
            # identically (hyphen is additive, not a behavior change
            # for anything that worked before).
            r"^([a-z0-9-]+)_" + re.escape(LANG) + r"(?:_(\d+))?\.epub$", re.IGNORECASE)
    return _EPUB_FILENAME_RE

# Standard 66-book canonical order (Genesis through Revelation) --
# matches the booknum GETPUBMEDIALINKS?pub=nwt&booknum=N expects.
# Anchor points spot-verified live against real chapter-audio counts
# before trusting the full table: Genesis(1)=50ch, Exodus(2)=40ch,
# Psalms(19)=150ch, Malachi(39)=4ch, Matthew(40)=28ch, John(43)=21ch,
# Revelation(66)=22ch -- all matched real Bible chapter counts exactly,
# confirming the standard canonical order is what this API uses.
BIBLE_BOOK_ORDER = [
    "Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy", "Joshua",
    "Judges", "Ruth", "1 Samuel", "2 Samuel", "1 Kings", "2 Kings",
    "1 Chronicles", "2 Chronicles", "Ezra", "Nehemiah", "Esther", "Job",
    "Psalms", "Proverbs", "Ecclesiastes", "Song of Solomon", "Isaiah",
    "Jeremiah", "Lamentations", "Ezekiel", "Daniel", "Hosea", "Joel",
    "Amos", "Obadiah", "Jonah", "Micah", "Nahum", "Habakkuk", "Zephaniah",
    "Haggai", "Zechariah", "Malachi",
    "Matthew", "Mark", "Luke", "John", "Acts", "Romans", "1 Corinthians",
    "2 Corinthians", "Galatians", "Ephesians", "Philippians", "Colossians",
    "1 Thessalonians", "2 Thessalonians", "1 Timothy", "2 Timothy",
    "Titus", "Philemon", "Hebrews", "James", "1 Peter", "2 Peter",
    "1 John", "2 John", "3 John", "Jude", "Revelation",
]
SUBBOOK_NUM_BY_NAME = {name: i + 1 for i, name in enumerate(BIBLE_BOOK_ORDER)}
# v26.08.06.27 (Kaleb's request: rename for generic naming -- describes
# the actual pattern this powers, "one EPUB containing several
# separately-titled, individually-numbered sub-books" -- not size
# (a Bible happens to be large, but that's incidental) and not
# specifically JW/Bible (the same shape could describe a numbered
# short-story collection or any other book-of-books). Was BIBLE_
# BOOKNUM_BY_NAME.
BIBLE_PUBS = {"nwt", "bi12"}  # v26.08.05.09 BUG FIX (found during a
# systematic audit of every publication's audio support): "nwt1984"
# was never a real pub code -- the actual 1984 Edition Bible pub code
# is "bi12" (confirmed live against STATIC_PUBLICATIONS and the audio
# API itself, GETPUBMEDIALINKS?pub=bi12&booknum=1&fileformat=MP3
# correctly returns 50 real Genesis chapters). This meant the 1984
# Edition Bible was silently routed through the WRONG "Listen to this
# Book" path (the generic periodical/book branch instead of the
# booknum-based Bible one) for every session before this fix -- never
# caught earlier because none of this session's Bible testing happened
# to use the 1984 edition specifically, only the 2013 Revision ("nwt").

# v26.08.05.06 (Kaleb's request: make "Listen to this Book" work with
# the songbook too). "sjjls" (the printed songbook EPUB) has NO plain
# GETPUBMEDIALINKS audio track list the way every other pub here does
# -- confirmed live, pub=sjjls&fileformat=MP3 404s. The real audio
# lives under a completely different lookup, the same mediator-
# category browsing SJJChorus/"Sing Out Joyfully to Jehovah--Vocals"
# already uses under AUDIO_SOURCES (see list_mediator_audio_category()
# below) -- so this pub needs its own branch in find_audio_for_epub()
# rather than the normal list_audio_items(pub, issue) call every other
# EPUB uses.
# v26.08.05.16 (Kaleb's request: "song book should give option for
# choir and meeting instrumentals" -- confirmed live this session that
# the songbook now has 163 songs across three real, separately-browsable
# audio categories under AUDIO_SOURCES' Music group: SJJChorus
# ("--Vocals", the only one this used to ever offer), SJJMeetings
# ("--Meetings"), and SJJInstrumental ("--Instrumental"). Hardcoding
# just Vocals meant "Listen to this Book" could never reach the other
# two, even though they're the same book's audio, just different
# renditions. Now a dict of all three.
#
# v26.08.06.22 (Kaleb's request: generalize main.py's "audio variant"
# picker so it's a reusable capability, not a JW-named screen -- see
# get_audio_variants() below and main.py's SCREEN_LISTEN_AUDIO_VARIANT,
# formerly SCREEN_LISTEN_SONGBOOK_CHOICE). SHORT_LABELS added
# specifically for that picker: main.py used to hardcode its own
# {"vocals": "Vocals", ...} display dict, the one piece of genuinely
# JW-specific text living outside this file. SONGBOOK_PUB_TO_CATEGORY's
# own titles ("\u201cSing Out Joyfully\u201d to Jehovah\u2014Vocals")
# are the right length for a category heading, wrong length for a
# picker row on a 720px-wide overlay -- SHORT_LABELS is deliberately a
# separate, shorter set of display strings for that narrower context,
# not a duplicate of the same data.
SONGBOOK_PUB_TO_CATEGORY = {
    "vocals":       ("SJJChorus", "\u201cSing Out Joyfully\u201d to Jehovah\u2014Vocals"),
    "meetings":     ("SJJMeetings", "\u201cSing Out Joyfully\u201d to Jehovah\u2014Meetings"),
    "instrumental": ("SJJInstrumental", "\u201cSing Out Joyfully\u201d to Jehovah\u2014Instrumental"),
}
SONGBOOK_CATEGORY_ORDER = ("vocals", "meetings", "instrumental")  # display order
SONGBOOK_PUBS = {"sjjls"}  # pub codes that are the songbook (currently just one)
SONGBOOK_SHORT_LABELS = {"vocals": "Vocals", "meetings": "Meetings", "instrumental": "Instrumental"}


def get_audio_variants(pub):
    """v26.08.06.22 (Kaleb's request: generalize the songbook's
    Vocals/Meetings/Instrumental picker into a real, reusable plugin
    capability instead of a JW-specific screen main.py had to know
    about by name). Generic contract: given a pub code, returns a list
    of (key, label) pairs if this publication has more than one real
    audio rendition to choose between, or None if it has just the one
    normal track list (every pub except the songbook, right now).
    main.py's "Listen to this Book" flow calls this via a plain
    getattr(MEDIA_PLUGIN, "get_audio_variants", None) capability check
    -- completely optional, works unchanged for a plugin that doesn't
    implement it -- and if it gets a real list back, offers a generic
    picker built ENTIRELY from these (key, label) pairs (no jw_fetch-
    specific strings anywhere in main.py itself), then passes the
    chosen key back in as audio_variant= on find_audio_for_epub()
    below. Any future plugin (or future JW pub) with the same "pick a
    rendition first" need gets this for free -- no main.py changes."""
    if pub not in SONGBOOK_PUBS:
        return None
    return [(key, SONGBOOK_SHORT_LABELS.get(key, key.title())) for key in SONGBOOK_CATEGORY_ORDER]



def parse_epub_filename(filename):
    """Given a filename this plugin itself produced (e.g. "w_E_202610.
    epub", "lffi_E.epub", "nwt_E.epub"), returns a dict describing what
    it is -- {"pub": ..., "issue": ... or None, "is_bible": bool} -- or
    None if it doesn't match this plugin's own naming pattern at all
    (e.g. a Gutenberg book, or a hand-renamed file). Exact parsing, not
    a guess: this plugin controls the naming convention on the way out
    (see download()), so reading it back is deterministic."""
    if not filename:
        return None
    m = _epub_filename_re().match(os.path.basename(filename))
    if not m:
        return None
    pub, issue = m.group(1).lower(), m.group(2)
    return {"pub": pub, "issue": issue, "is_bible": pub in BIBLE_PUBS}


def find_audio_for_epub(filename, book_title=None, audio_variant=None):
    """Top-level entry point for "Listen to this book". Given the
    filename of a currently-open EPUB (and, for Bible books, the title
    of the book currently being read, e.g. "Genesis" -- taken from
    whatever TOC entry is on screen), returns (audio_items, error) in
    the same shape list_audio_items() already uses, or (None, reason)
    if this doesn't look like a JW.org EPUB / audio isn't available.

    audio_variant (v26.08.05.16, renamed from songbook_category in
    v26.08.06.22 as part of generalizing the picker that supplies it
    -- see get_audio_variants() above): one of that function's own
    returned keys ("vocals"/"meetings"/"instrumental" for the
    songbook), only meaningful for pubs get_audio_variants() actually
    returns choices for. Caller (main.py's generic SCREEN_LISTEN_
    AUDIO_VARIANT, formerly the JW-named SCREEN_LISTEN_SONGBOOK_
    CHOICE) asks the person first. Defaults to "vocals" if not given,
    matching this feature's original (pre-choice-screen) behavior
    exactly, so any caller that doesn't know about the choice screen
    still works.

    Does NOT do the TOC-to-track correlation itself -- that's epub_
    engine.correlate_toc_to_audio() (plugin-agnostic, lives with the
    EPUB-structure code it belongs with) and, for Bible books, epub_
    engine.EpubDocument.get_bible_chapter_files(). This function's only
    job is "does this pub have audio, and what is it" -- the JW.org-
    specific half of the problem, matching the split already used for
    the shelved LibriVox idea (cross-catalog matching stays plugin-
    specific; chapter-position correlation stays plugin-agnostic)."""
    parsed = parse_epub_filename(filename)
    if not parsed:
        return None, "Not a JW.org-downloaded EPUB"
    if parsed["is_bible"]:
        if not book_title:
            return None, "No Bible book context given"
        booknum = SUBBOOK_NUM_BY_NAME.get(book_title.strip())
        if not booknum:
            return None, f'"{book_title}" not recognized as a Bible book'
        return list_audio_items(parsed["pub"], booknum=booknum)
    if parsed["pub"] in SONGBOOK_PUBS:
        cat = audio_variant if audio_variant in SONGBOOK_PUB_TO_CATEGORY else "vocals"
        key, title = SONGBOOK_PUB_TO_CATEGORY[cat]
        return list_mediator_audio_category(key, title)
    return list_audio_items(parsed["pub"], issue=parsed["issue"])

# ---------------------------------------------------------------------------
# Self-updating annual-issue cache (wp/g)
# ---------------------------------------------------------------------------
# v26.07.30.11 (Kaleb: "can we make it have a built in month checker to
# guess based on previous issues... then update a JSON list" -- so wp/g
# stop needing a manual code edit every year). Mirrors main.py's own
# APP_DIR/DATA_DIR pattern but computed independently here so this
# plugin file stays self-contained (doesn't import main.py).
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
PERIODICAL_CACHE_PATH = os.path.join(DATA_DIR, "jw_periodical_cache.json")

# v26.08.03.02 (Kaleb's request: detect new Audio/Video categories JW.org
# adds -- e.g. "International Music"/"Audio Descriptions", both found
# missing and hand-added this session -- without needing a main.py code
# update every time). See check_new_categories()/_merge_discovered_
# categories() near the end of this file for the mechanism; this is just
# the cache file path, same pattern as PERIODICAL_CACHE_PATH above.
DISCOVERED_CATEGORIES_PATH = os.path.join(DATA_DIR, "jw_discovered_categories.json")


def _load_json_cache(path, default=None):
    """v26.08.21.08 (duplicate-code consolidation, checking jw_fetch.py
    after the main.py/native_media.py sweeps, Kaleb's request). The
    "load a JSON cache file, fall back to `default` if it's missing or
    fails to parse" pattern was duplicated identically across 4 cache-
    loading functions (_load_periodical_cache, _load_audio_
    availability_cache, _load_discovered_pubs, _load_category_
    discovery_cache) -- 3 defaulted to {}, 1 to {"video": [], "audio":
    []}. Uses copy.deepcopy() on every return (not just a shallow
    dict(default)) so the SAME default object is never handed back to
    two different call sites -- important here specifically because
    the {"video": [], "audio": []} default has nested lists a caller
    could mutate in place; a shallow copy would still share those
    inner lists across callers and silently corrupt an unrelated
    cache."""
    if default is None:
        default = {}
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return copy.deepcopy(default)
    return copy.deepcopy(default)


def _load_periodical_cache():
    return _load_json_cache(PERIODICAL_CACHE_PATH)


def _save_periodical_cache(cache):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(PERIODICAL_CACHE_PATH, "w") as f:
            json.dump(cache, f)
    except Exception:
        pass  # best-effort -- a failed save just means re-probing next time


def _probe_annual_issue(pub, year):
    """Live-probe every month of `year` against GETPUBMEDIALINKS for
    `pub`, checked DECEMBER FIRST down to January, returning the first
    (= latest) month that resolves to a real EPUB. This is for
    irregular ~once-a-year publications (wp since 2022, g currently)
    where there's no formula to derive the month from, unlike w/mwb
    above. Bounded to at most 12 real network requests, and stops
    immediately on the first hit (so a late-in-year issue costs far
    fewer than 12 -- e.g. a September issue costs 4 checks: Dec, Nov,
    Oct, Sep). Returns None if nothing in `year` has a real issue yet
    (not published this year so far) OR the network can't be reached.

    v26.07.30.11 BUG FIX (caught by testing this against a YEAR
    ALREADY KNOWN to have a real issue, not just trusting it): a real
    "not yet published" miss returns HTTP 404 (confirmed live, e.g.
    wp issue=202512 -- valid pub, just no issue that month), which
    urllib raises as HTTPError -- a URLError subclass. The original
    except clause caught that as if it meant "network unreachable"
    and aborted the ENTIRE probe on the very first miss (December),
    never even trying November/October/September. Confirmed live:
    _probe_annual_issue("wp", 2025) returned None instead of the real
    202509 before this fix. HTTPError (a real response, just a miss)
    is now caught separately from genuine network failure (no
    response at all) -- only the latter stops the probe early."""
    for m in range(12, 0, -1):
        issue = f"{year}{m:02d}"
        params = {"pub": pub, "langwritten": LANG, "issue": issue, "output": "json"}
        try:
            data = _get_json(API_BASE + "?" + urllib.parse.urlencode(params))
        except urllib.error.HTTPError:
            continue  # a real miss (404/400) -- try the next earlier month
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            return None  # genuine network failure -- don't treat as "not out yet"
        if _extract_epub(data):
            return issue
    return None


def _fetch_awake_theme(issue):
    """v26.07.30.12 (Kaleb: "can't it just use epub engine to find the
    title?" -- exactly right, and it works). AWAKE_BACK_ISSUES' nice
    "No. 1 2025 -- Coping With Rising Prices" style subtitle isn't
    available from GETPUBMEDIALINKS itself (confirmed live -- its
    pubName/title fields are generic, no theme text anywhere in the
    JSON). But the REAL EPUB has it in two places, confirmed live by
    downloading g_E_202511.epub and inspecting it directly (not
    assumed): the OPF's own dc:title is "Awake!, No. 1 2025" (gives
    the "No. X YYYY" numbering), and the magazine's actual cover page
    (spine[0]) has the theme headline as its first visible text,
    repeated twice back-to-back before the copyright notice (e.g.
    "Coping With Rising Prices Coping With Rising Prices \u00a9 2025...").
    This downloads the EPUB to a throwaway temp file (~3MB, deleted
    immediately after -- one-time cost per new issue, cached
    afterward, not a standing storage/RAM footprint), opens it with
    the SAME epub_engine.EpubDocument class the reader itself uses (no
    separate parsing logic to maintain), and combines both pieces.
    Returns None on any failure (network, parse, unexpected page
    shape) -- caller falls back to a generic month/year label, this is
    a nice-to-have, never something download/browse should block on."""
    params = {"pub": "g", "langwritten": LANG, "issue": issue, "fileformat": "EPUB"}
    try:
        data = _get_json(API_BASE + "?" + urllib.parse.urlencode(params))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None
    epub_info = _extract_epub(data)
    if not epub_info:
        return None
    url = epub_info.get("file", {}).get("url")
    if not url or not url.startswith("https://"):
        return None
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=".epub")
        os.close(fd)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            with open(tmp_path, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
        doc = epub_engine.EpubDocument(tmp_path)
        # "No. X YYYY" from the OPF's own dc:title -- same regex
        # pattern main.py's library scan already uses for dc:title.
        opf_text = doc._read(doc.opf_path)
        m = re.search(r"<dc:title[^>]*>(.*?)</dc:title>", opf_text, re.DOTALL | re.IGNORECASE)
        numbering = None
        if m:
            raw_title = re.sub(r"<[^>]+>", "", m.group(1)).strip()
            num_m = re.search(r"(No\.\s*\d+\s+\d{4})", raw_title)
            if num_m:
                numbering = num_m.group(1)
        # Theme headline from the cover page (first spine entry).
        theme = None
        # v26.07.30.12 BUG FIX (again caught by testing against the
        # KNOWN answer): spine[0] isn't the real content page -- it's
        # a generic "cover.xhtml" wrapper (just the cover IMAGE, alt
        # text "Cover"), and spine[1] is "toc.xhtml". Confirmed live
        # by dumping the real spine order: the actual page with the
        # theme headline text is the first entry that ISN'T one of
        # those two generic wrapper pages.
        content_file = next(
            (f for f in doc.spine if "cover" not in f.lower() and "toc" not in f.lower()),
            None)
        if content_file:
            cover_html = doc._read(content_file)
            # v26.07.30.12 BUG FIX (caught by testing against the KNOWN
            # answer, not trusting the first result): the cover page's
            # own <style> block content was surviving the tag-strip
            # (stripping tags doesn't remove non-visible tag CONTENT
            # like CSS/JS) and leaking into the extracted text --
            # confirmed live, first attempt returned "No. 1 2025 --
            # Cover img { max-width: 100%%; ... }" instead of the real
            # theme. Strip <style>/<script> blocks (content and all)
            # before the generic tag-strip.
            cover_html = re.sub(r"<(style|script)\b[^>]*>.*?</\1>", " ", cover_html,
                                 flags=re.DOTALL | re.IGNORECASE)
            cover_text = re.sub(r"<[^>]+>", " ", cover_html)
            cover_text = html.unescape(cover_text)
            # v26.07.30.12 BUG FIX (caught by testing against a THIRD
            # known issue): confirmed live that some covers embed a
            # zero-width space (\u200b, likely a line-break hint in
            # the original markup) inconsistently between the two
            # repeated theme occurrences -- e.g. "Survive?\u2014..."
            # vs "Survive?\u200b\u2014...". That made the two
            # occurrences not byte-identical, so the repeated-phrase
            # regex below found no match. Strip invisible formatting
            # characters before comparing.
            cover_text = cover_text.replace("\u200b", "").replace("\u00ad", "")
            cover_text = re.sub(r"\s+", " ", cover_text).strip()
            # Theme headline repeats twice back-to-back before the
            # copyright notice -- take everything up to the first "©"
            # and dedupe an exact repeated halves if present.
            before_copyright = cover_text.split("\u00a9")[0].strip()
            # v26.07.30.12 BUG FIX (again caught by testing against a
            # SECOND known issue, not trusting the first success): the
            # naive "split the pre-copyright text exactly in half"
            # heuristic broke on issues where "No. X YYYY" ALSO
            # appears on the cover page after the doubled theme
            # (confirmed live: Nov 2024's cover reads "What Has
            # Happened to Respect? What Has Happened to Respect? No. 1
            # 2024 \u00a9 2024...", which doesn't split into two equal
            # halves the way Nov 2025's did). Fixed with a proper
            # repeated-phrase match instead of assuming a 50/50 split
            # -- finds the shortest phrase P such that the text starts
            # with "P P", regardless of what (if anything) follows.
            rep_m = re.match(r"^(.+?)\s+\1(?:\s|$)", before_copyright)
            theme = rep_m.group(1) if rep_m else before_copyright
        if numbering and theme:
            return f"{numbering} -- {theme}"
        return theme or None
    except Exception:
        return None  # best-effort -- any failure just means no theme this time
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _get_annual_issue(pub, year):
    """Returns the confirmed issue=YYYYMM for `pub`'s single annual
    issue in `year`, or None if not published yet this year. Checks
    the on-disk cache first (at most one live probe per pub per
    calendar day -- re-checks once per day if the prior check that day
    found nothing yet, so a mid-year release gets picked up the next
    time the app is opened without hammering the API on every single
    category browse). A cache HIT with issue=None from a PRIOR day is
    treated as stale and re-probed -- only same-day negative results
    are trusted without re-checking.

    v26.07.30.12: when a NEW "g" (Awake!) issue is found for the first
    time, also fetches and caches its real theme subtitle (see
    _fetch_awake_theme()) alongside the issue code -- one-time cost,
    not repeated on later cache hits."""
    cache = _load_periodical_cache()
    today = time.strftime("%Y-%m-%d")
    pub_cache = cache.get(pub, {})
    entry = pub_cache.get(str(year))
    if entry and (entry.get("issue") or entry.get("checked") == today):
        return entry.get("issue")
    issue = _probe_annual_issue(pub, year)
    new_entry = {"issue": issue, "checked": today}
    if issue and pub == "g":
        theme = _fetch_awake_theme(issue)
        if theme:
            new_entry["theme"] = theme
    pub_cache[str(year)] = new_entry
    cache[pub] = pub_cache
    _save_periodical_cache(cache)
    return issue


def _get_cached_theme(pub, year):
    """Pure cache read (no network) for the theme text _get_annual_
    issue() may have already fetched and stored -- returns None if
    there's no cache entry for this pub/year or it has no theme."""
    cache = _load_periodical_cache()
    entry = cache.get(pub, {}).get(str(year))
    return entry.get("theme") if entry else None


# ---------------------------------------------------------------------------
# Audio-availability cache (Publications > Books/Brochures/Tracts filtering)
# ---------------------------------------------------------------------------
# v26.07.30.17 (Kaleb's request: "any categories that don't have audio
# just be sure to omit them from showing" -- titles were showing in
# Publications browsing even when they turned out to have no audio,
# only failing with "no audio available" after selecting one).
# Confirmed live this session: 47 of 59 STATIC_PUBLICATIONS titles have
# real MP3 audio -- unlike periodical issues (which can genuinely
# change availability week to week), whether a PUBLICATION has audio
# at all is effectively permanent once known, so this caches True/False
# forever with no re-check window, unlike the periodical caches above.
AUDIO_AVAILABILITY_CACHE_PATH = os.path.join(DATA_DIR, "jw_audio_availability.json")


def _load_audio_availability_cache():
    return _load_json_cache(AUDIO_AVAILABILITY_CACHE_PATH)


def _save_audio_availability_cache(cache):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(AUDIO_AVAILABILITY_CACHE_PATH, "w") as f:
            json.dump(cache, f)
    except Exception:
        pass


def _pub_has_audio(pub, extra=None):
    """True/False, cached permanently once determined (see module note
    above for why a permanent cache is safe here, unlike the
    periodical caches). A cache miss does ONE live GETPUBMEDIALINKS?
    fileformat=MP3 check -- same lightweight metadata-only request
    list_audio_items() itself makes, not a real download."""
    cache = _load_audio_availability_cache()
    if pub in cache:
        return cache[pub]
    params = {"pub": pub, "langwritten": LANG, "fileformat": "MP3"}
    if isinstance(extra, dict):
        params.update(extra)
    url = API_BASE + "?" + urllib.parse.urlencode(params)
    try:
        data = _get_json(url)
        entries = data.get("files", {}).get(LANG, {}).get("MP3", [])
        has_audio = isinstance(entries, list) and len(entries) > 0
    except urllib.error.HTTPError:
        # v26.07.30.17 BUG FIX (caught by checking the cache file
        # directly after a real run -- it was empty of any False
        # entries at all, meaning every negative result was being
        # re-checked live on every single visit instead of cached).
        # Same bug class as _probe_annual_issue()'s earlier fix this
        # session: a "no audio" answer for a real, valid pub code is a
        # normal HTTP 404 (confirmed live, e.g. pub=od) -- a legitimate
        # response, not a network failure. The broad except below was
        # catching this too and refusing to cache it. HTTPError is now
        # caught separately as a real negative result.
        has_audio = False
    except (urllib.error.URLError, TimeoutError, ValueError, OSError, KeyError, TypeError):
        # Genuine network/parse failure -- report False for THIS check
        # but do NOT cache it, so the next visit tries fresh instead of
        # permanently remembering a transient failure as "no audio".
        return False
    cache[pub] = has_audio
    _save_audio_availability_cache(cache)
    return has_audio


def filter_items_with_audio(items):
    """Public hook main.py's audio-publications browse calls after the
    normal list_items(category=X) fetch -- drops any item confirmed to
    have no real audio, so Publications browsing only ever shows titles
    that will actually work when selected, instead of failing after the
    fact. Items without a "_pub" key (shouldn't happen for this catalog,
    but defensive) are kept rather than silently dropped."""
    result = []
    for item in items:
        pub = item.get("_pub")
        if not pub or _pub_has_audio(pub, item.get("_extra")):
            result.append(item)
    return result


# ---------------------------------------------------------------------------
# Discovered-publications cache (search/manual-code -> permanent catalog)
# ---------------------------------------------------------------------------
# v26.07.30.14 (Kaleb: "what if instead I search for a book and it
# finds it and downloads, can we cache that URL in the proper category
# for future?"). When a search or manual pub-code hit gets downloaded
# and its pub code ISN'T already in STATIC_PUBLICATIONS/PERIODICALS/
# generate_km_back_issues()'s "km", it's genuinely new to this app's
# local catalog -- worth remembering so it shows up in the normal
# category browse next time instead of needing the same search again.
DISCOVERED_PUBS_CACHE_PATH = os.path.join(DATA_DIR, "jw_discovered_pubs.json")


def _load_discovered_pubs():
    return _load_json_cache(DISCOVERED_PUBS_CACHE_PATH)


def _save_discovered_pubs(cache):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(DISCOVERED_PUBS_CACHE_PATH, "w") as f:
            json.dump(cache, f)
    except Exception:
        pass


def _is_known_pub(pub):
    """True if `pub` is already reachable through the normal category
    browse some other way -- STATIC_PUBLICATIONS, PERIODICALS, the
    hardcoded "km" Kingdom Ministry archive, or already remembered in
    the discovered-pubs cache. False means downloading it again later
    would require the same search/manual-code lookup as this time."""
    if pub in {p for p, _t, _e, _c in STATIC_PUBLICATIONS}:
        return True
    if pub in {p for p, _t, _c in PERIODICALS}:
        return True
    if pub == "km":
        return True
    if pub in _load_discovered_pubs():
        return True
    return False


def _classify_pub_category(pub):
    """Live-only classification (never guessed) of which real jw.org
    category `pub` belongs to, via the same finder-redirect technique
    already used this session to verify Books vs Brochures for the
    existing static table: https://www.jw.org/finder?wtlocale=E&pub=X
    resolves through to the real canonical /en/library/<section>/...
    URL. Returns one of the CATEGORY_* constants, or None if the
    redirect doesn't land somewhere this app has a matching category
    for (e.g. a tract, guideline, or something else not modeled here)
    -- callers should treat None as "don't file it anywhere, better to
    leave it unfiled than mis-categorize.\""""
    url = f"https://www.jw.org/finder?wtlocale=E&pub={urllib.parse.quote(pub)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        resp = urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT)
        final_url = resp.geturl()
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    if "/library/books/" in final_url:
        return CATEGORY_BOOKS
    if "/library/brochures/" in final_url:
        return CATEGORY_BROCHURES
    if "/library/tracts/" in final_url:
        return CATEGORY_TRACTS
    if "/library/bible/" in final_url:
        return CATEGORY_BIBLES
    return None


def _remember_discovered_pub(item):
    """v26.07.30.14: called after a successful download() -- if this
    item's pub code isn't already reachable through the normal
    category browse, classify and cache it so it IS from now on.
    Best-effort and silent on any failure (network, classification
    miss) -- a book search/download must never fail or feel slower
    because of this; worst case, the same search just works again next
    time, same as before this feature existed. Skipped entirely for
    anything that looks like a periodical issue (has an "issue" key in
    _extra) -- this is for standalone books/brochures/tracts/bibles,
    not dated issues, which have their own dedicated caching system
    above (_get_annual_issue() et al)."""
    pub = item.get("_pub")
    if not pub or _is_known_pub(pub):
        return
    extra = item.get("_extra")
    if isinstance(extra, dict) and "issue" in extra:
        return  # periodical issue -- not what this cache is for
    category = _classify_pub_category(pub)
    if not category:
        return  # couldn't confidently classify -- leave it unfiled
    cache = _load_discovered_pubs()
    cache[pub] = {
        "title": item.get("title", pub),
        "category": category,
        "extra": extra,
    }
    _save_discovered_pubs(cache)


# v26.08.03.07 (Kaleb's request: "would this even work" for finding new
# EPUBs proactively, not just after a search happens to hit one).
# Reuses every piece of the reactive mechanism just above --
# _is_known_pub()/_load_discovered_pubs()/_save_discovered_pubs() -- so
# anything this finds shows up in the normal category browse exactly
# the same way a remembered search result does; list_items() already
# merges _load_discovered_pubs() into the catalog, no separate wiring
# needed.
#
# HOW IT WORKS: jw.org's own /en/library/{section}/ listing pages embed
# each publication's real pub code directly, via a data-page-id="toc-
# {pub}" attribute -- confirmed live, e.g. data-page-id="toc-wcg" on
# the Books page. Newest releases appear first on the page (confirmed
# live: 2025/2024/2023 Service Year Reports at the top of Books),
# which matches what "check for new books/brochures/tracts" actually
# needs -- this deliberately does NOT chase the site's real pagination
# to rebuild the full historical catalog (STATIC_PUBLICATIONS already
# covers that, hand-verified once; re-crawling it every check would be
# pure repeated cost for zero new information).
#
# Every candidate pub code gets a REAL GETPUBMEDIALINKS?fileformat=EPUB
# check before being added -- this is the step that actually delivers
# "only EPUB files" (confirmed live this session: two titles found this
# way, wcgr and scl, turned out to be PDF/JWPUB-only and were correctly
# filtered out, not added). The real title comes from GETPUBMEDIALINKS'
# own pubName field, not scraped HTML text -- one less thing that can
# go stale if jw.org changes their page markup.
def _scrape_library_page_pub_codes(section):
    """Returns the list of real pub codes (data-page-id="toc-{pub}")
    found on page 1 of https://www.jw.org/en/library/{section}/, in
    page order (newest first, per jw.org's own layout)."""
    url = f"https://www.jw.org/en/library/{section}/"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    return re.findall(r'data-page-id="toc-([a-zA-Z0-9]+)"', html)


def _pub_epub_info(pub):
    """Returns (title, ok) -- ok=True and the real pubName if `pub` has
    a real downloadable EPUB (confirmed live via GETPUBMEDIALINKS, same
    as every other pub-existence check in this file), else (None,
    False). Never raises -- network/parse failures are treated the
    same as "no EPUB", the safe default for a discovery feature."""
    params = {"pub": pub, "fileformat": "EPUB", "langwritten": LANG, "output": "json"}
    try:
        data = _get_json(API_BASE + "?" + urllib.parse.urlencode(params))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None, False
    if not isinstance(data, dict):
        return None, False  # jw.org returns a [{"status":404,...}] list on a miss
    return data.get("pubName") or pub, True


def check_new_publications():
    """Public entry point (wire to a Settings action, e.g. 'Check for
    New Publications'). Returns (added_count, error). Safe to call
    repeatedly -- every candidate is checked against the CURRENT known
    set (_is_known_pub(), which already includes anything promoted
    into STATIC_PUBLICATIONS since the last check), so nothing gets
    reported or re-added twice."""
    added = 0
    any_error = None
    library_sections = (
        ("books", CATEGORY_BOOKS),
        ("brochures", CATEGORY_BROCHURES),
        ("tracts", CATEGORY_TRACTS),
    )
    for section, category in library_sections:
        try:
            candidates = _scrape_library_page_pub_codes(section)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            any_error = str(e)
            continue
        for pub in candidates:
            if _is_known_pub(pub):
                continue
            if pub == current_year_es_code():
                # v26.08.03.07: PERIODICALS' own "es" entry already
                # dynamically resolves to THIS year's code at request
                # time (see current_year_es_code()) -- adding it again
                # here under its literal "es26"-style code would be a
                # real duplicate menu entry for the exact same content,
                # not a genuine find. Past years' "es" codes (es20-es25
                # etc.) aren't covered by that dynamic entry and ARE
                # genuine finds -- only the current year gets skipped.
                continue
            title, has_epub = _pub_epub_info(pub)
            if not has_epub:
                continue  # real PDF/JWPUB-only title -- not what this app can read
            cache = _load_discovered_pubs()
            cache[pub] = {"title": title, "category": category, "extra": None}
            _save_discovered_pubs(cache)
            added += 1
    return added, any_error



# SUPPORTS_MANUAL_CODE tells main.py to show a Y-button code-entry screen.
# This is distinct from SUPPORTS_SEARCH (gutenberg_fetch.py): we're not
# filtering a catalog, we're doing a direct live lookup of one specific
# exact code the person already knows -- for publications not in the
# curated STATIC_PUBLICATIONS list below. The on-validate path checks the
# code against the live API BEFORE leaving the entry screen, so a typo
# shows a clear error and lets the person fix it immediately rather than
# bouncing to the results list with nothing in it.
# v26.08.07.05 BUG FIX (Kaleb's report: "folder cleanup tool didn't move
# epubs from LibriVox folder to Gutenberg folder"). Root cause: main.py's
# _scan_and_migrate_stray_books() Pass 1 used to duck-type "does this
# plugin have its own local, network-free parse_epub_filename()/
# resolve_item_category() pair" (this plugin's real pair, the ONLY
# functions that contract was ever written for -- local pub-code lookup,
# {"_pub": code} in, category string out) to decide which plugins get
# Pass 1's per-file classify-and-move treatment, and treated every OTHER
# plugin as a Pass-2 "single no-local-resolver plugin" candidate.
# gutenberg_fetch.py later grew its OWN same-named parse_epub_filename()/
# resolve_item_category() pair (v26.08.06.07, for a completely different
# feature -- local Gutenberg-ID lookup for the reader-menu visibility
# check, real contract: int book ID in/out, NOT this plugin's dict
# contract). That same-name coincidence made Gutenberg silently start
# passing Pass 1's duck-type check too, which (a) crashed Pass 1 outright
# the moment it hit a real Gutenberg-tagged .epub anywhere outside
# Gutenberg's own folder tree (int has no .get(), never caught) and
# (b) left LibriVox as the ONLY remaining "no local resolver" plugin, so
# Pass 2 -- built for exactly-one-such-plugin -- silently pointed at the
# wrong plugin and never touched the real Gutenberg-in-LibriVox leftovers
# Kaleb was reporting. Fixed with an explicit, unambiguous marker instead
# of duck-typing by function name: main.py's Pass 1 now requires this
# flag (True only here) rather than just checking whether the two
# functions exist under these names, so a future plugin reusing these
# names for something else can never collide with this again.
SUPPORTS_LOCAL_PUB_CATEGORY_LOOKUP = True

SUPPORTS_MANUAL_CODE = True

# SUPPORTS_CATEGORIES tells main.py to show a category picker (see
# CATEGORIES above) before the browse list, instead of dumping the whole
# catalog at once -- Kaleb's request, since the full catalog spans very
# different kinds of publications (Bibles, tracts, periodicals...).
# Selecting a category calls list_items(category=...); search (Y) still
# works as normal, scoped to whichever category is currently open.
SUPPORTS_CATEGORIES = True

# SUPPORTS_SEARCH tells main.py to show the existing generic Y-button
# search box (same one gutenberg_fetch.py uses) and call
# list_items(query=...) with what's typed. v0.1.161+: this is now a REAL
# live search against jw.org's own search service (see search_media() below)
# instead of a local substring filter -- confirmed live to find real,
# resolvable EPUBs for arbitrary topics (Bible books, doctrine subjects,
# dated periodicals like "daily text", etc.), not just exact pub titles.
#
# Scoped to PUBLICATIONS ONLY, not videos: main.py's generic
# SUPPORTS_SEARCH -> download() path has no route to download_video()/
# ROMS/movies (that's a separate, dedicated screen -- see
# SCREEN_DOWNLOAD_VIDEO_SOURCES). Returning a video-shaped item here
# would silently fail against the wrong download() function. A real
# "search videos by free text" UI would need a main.py change; per
# Kaleb's instruction this plugin stays search-UI-self-contained, so
# video results are simply excluded from list_items(query=...) results
# rather than half-wired. See search_media()'s own docstring if a future
# session revisits adding a dedicated video-search screen.
SUPPORTS_SEARCH = True

# v0.1.162: VIDEO_SOURCES -- lets main.py build the "Videos" picker
# screen (Download Books > JW > Videos) WITHOUT hardcoding any JW-specific
# titles or pub codes itself. Previously main.py had a hardcoded 4-item
# label list PLUS a matching elif chain PLUS four near-duplicate App
# methods, one per source -- all of that collapses to one generic loop +
# one generic loader method now that the plugin declares this list.
#
# Each entry:
#   "label"  str   -- shown in the picker, exactly as before
#   "loader" str   -- name of a function on THIS module, called with
#                     "args" as keyword arguments, returning the same
#                     (items, error_message) shape list_video_items() etc.
#                     already return. main.py calls it via getattr(), so
#                     it never needs to know the function names up front.
#   "args"   dict  -- kwargs passed to the loader (e.g. {"pub": "lffv"})
#   "search" bool  -- True marks the live free-text search entry instead
#                     of a fixed loader; main.py special-cases only this
#                     one flag (opens its existing text-entry screen,
#                     calls search_media(query, filter="videos") itself --
#                     that part is genuinely main.py's job, it owns the
#                     text-entry UI).
#
# Order matches the original hardcoded list (Kaleb's original menu
# order), with "Search Videos" added at the end, same as before.
VIDEO_SOURCES = [
    # v26.07.21.27 (Kaleb's request: "make sure the categories are
    # nested properly, try to replicate the website's order"). Full
    # rebuild, order AND completeness both verified against a live
    # fetch of jw.org's real VideoOnDemand tree (?detailed=1&
    # clientType=www at every level, not guessed) -- this superseded
    # the incremental v26.07.15.09 through v26.07.21.26 history above,
    # which had drifted from the real site order and was missing real
    # subcategories in several places (JW Broadcasting was missing
    # Featured Videos; Programs and Events was missing 3 of its 4 real
    # children; Our Meetings and Ministry was missing 5 of its 8; Series
    # was missing 10 of its 32; Music was missing 4 of its 6).
    # Top-level order now matches jw.org's own tree exactly: JW
    # Broadcasting, Children, Teenagers, Family, Programs and Events,
    # Our Activities, Our Meetings and Ministry, Our Organization, The
    # Bible, Dramas, Series, Music, Interviews and Experiences.
    # v26.07.27.04 (Kaleb's request: remove the duplicate "Governing
    # Body Update" category): "Governing Body Updates" (below, now
    # removed) was this app's own curated filter over StudioNewsReports
    # -- not a real jw.org tree entry -- narrowing that category down to
    # just titles containing "Governing Body Update". But
    # StudioNewsReports is ALSO exposed, unfiltered, as "News and
    # Announcements" right above under JW Broadcasting (a real jw.org
    # tree entry) -- meaning every Governing Body Update video already
    # appears there too, just alongside the category's other news items
    # instead of pre-filtered out. Two categories surfacing overlapping
    # content this directly is exactly the kind of duplicate Kaleb
    # flagged -- removed the custom one, kept the official one.
    # "Search Videos" (this app's own UI, not jw.org's) is now the only
    # entry left that isn't from the real site tree -- kept at the very
    # end, since it was never claiming to replicate site structure
    # either.
    {"label": "JW Broadcasting",
     "loader": "list_mediator_category", "args": {},
     "subcategories": [
         {"label": "Featured Videos", "key": "StudioFeatured"},
         {"label": "Monthly Programs", "key": "StudioMonthlyPrograms"},
         {"label": "Talks", "key": "StudioTalks"},
         {"label": "News and Announcements", "key": "StudioNewsReports"},
     ]},
    {"label": "Children",
     "loader": "list_mediator_category", "args": {},
     "subcategories": [
         {"label": "Video Lessons", "key": "BJF"},
         {"label": "Songs", "key": "ChildrenSongs"},
         {"label": "Dramas", "key": "ChildrenMovies"},
     ]},
    {"label": "Teenagers",
     "loader": "list_mediator_category", "args": {},
     "subcategories": [
         {"label": "Spiritual Growth", "key": "TeenSpiritualGrowth"},
         {"label": "Social Life", "key": "TeenSocialLife"},
         {"label": "Goals", "key": "TeenGoals"},
         {"label": "Interviews and Experiences", "key": "TeenWhatPeersSay"},
         {"label": "Dramas", "key": "TeenMovies"},
     ]},
    {"label": "Family",
     "loader": "list_mediator_category", "args": {},
     "subcategories": [
         {"label": "Family Challenges", "key": "FamilyChallenges"},
         {"label": "Dating and Marriage", "key": "FamilyDatingMarriage"},
         {"label": "Family Worship", "key": "FamilyWorship"},
         {"label": "Dramas", "key": "FamilyMovies"},
     ]},
    {"label": "Programs and Events",
     "loader": "list_mediator_category", "args": {},
     "subcategories": [
         {"label": "Morning Worship", "key": "VODPgmEvtMorningWorship"},
         {"label": "Special Programs", "key": "VODPgmEvtSpecial"},
         {"label": "Gilead Graduations", "key": "VODPgmEvtGilead"},
         {"label": "Annual Meetings", "key": "VODPgmEvtAnnMtg"},
     ]},
    {"label": "Our Activities",
     "loader": "list_mediator_category", "args": {},
     "subcategories": [
         {"label": "Translation", "key": "VODActivitiesTranslation"},
         {"label": "Audio and Video Production", "key": "VODActivitiesAVProduction"},
         {"label": "Publishing and Distribution", "key": "VODActivitiesPrintingShipping"},
         {"label": "Construction", "key": "VODActivitiesConstruction"},
         {"label": "Relief Work", "key": "VODActivitiesReliefWork"},
         {"label": "Theocratic Schools and Training", "key": "VODActivitiesTheoSchools"},
         {"label": "Special Events", "key": "VODActivitiesSpecialEvents"},
     ]},
    # "Essential Bible Teachings" (VODMinistryTeachings, 27 items) is
    # BYTE-IDENTICAL to Series' own "Essential Bible Teachings"
    # (SeriesBibleTeachings, same 27 titles, confirmed) -- jw.org itself
    # cross-lists this one under two parents, same precedent as the
    # BibleBooks/Introduction-to-Bible-Books case below. Skipped here,
    # kept under Series (its real order position there).
    {"label": "Our Meetings and Ministry",
     "loader": "list_mediator_category", "args": {},
     "subcategories": [
         {"label": "Weekly Meetings", "key": "VODMinistryMidweekMeeting"},
         {"label": "Tools for the Ministry", "key": "VODMinistryTools"},
         {"label": "Improving Our Skills", "key": "VODMinistryImproveSkills"},
         {"label": "Preaching Methods", "key": "VODMinistryMethods"},
         {"label": "Expanding Our Ministry", "key": "VODMinistryExpandMinistry"},
         {"label": "Meetings, Assemblies, and Conventions", "key": "MeetingsConventions"},
         {"label": "Sample Conversations (2016-2023)", "key": "VODSampleConversations"},
     ]},
    {"label": "Our Organization",
     "loader": "list_mediator_category", "args": {},
     "subcategories": [
         {"label": "Reports From Around the World", "key": "Reports"},
         {"label": "Bethel", "key": "VODOrgBethel"},
         {"label": "Organized to Accomplish Our Ministry", "key": "AccomplishMinistry"},
         {"label": "History", "key": "VODOrgHistory"},
         {"label": "Legal Developments", "key": "VODOrgLegal"},
         {"label": "Bloodless Medicine", "key": "VODOrgBloodlessMedicine"},
     ]},
    # "Books of the Bible" (VODBible key BibleBooks, 67 items) is
    # BYTE-IDENTICAL to Series' "Introduction to Bible Books" (same 67
    # titles, confirmed via direct set comparison) -- jw.org itself
    # cross-lists the same category under two different parents.
    # Skipped here (would be a true duplicate menu entry), kept under
    # Series in its real order position.
    {"label": "The Bible",
     "loader": "list_mediator_category", "args": {},
     "subcategories": [
         {"label": "Bible Reading and Study", "key": "VODBibleReadingStudy"},
         {"label": "Bible Teachings", "key": "VODBibleTeachings"},
         {"label": "Bible Accounts", "key": "VODBibleAccounts"},
         {"label": "People, Places, and Things", "key": "VODBibleMedia"},
         {"label": "Bible Translations", "key": "VODBibleTranslations"},
         {"label": "Apply Bible Principles", "key": "VODBiblePrinciples"},
         {"label": "Creation", "key": "VODBibleCreation"},
     ]},
    # "The Good News According to Jesus" (VODMovies key DramasGoodNews,
    # 9 items) substantially overlaps the existing 6-episode Series
    # entry for the same title (list_good_news_items(), a curated
    # subset) -- skipped here per the near-duplicate precedent already
    # established; the fuller 9-item version lives under Series in its
    # real order position (key SeriesGoodNews, a DIFFERENT, separate
    # real category from DramasGoodNews despite the same name).
    {"label": "Dramas",
     "loader": "list_mediator_category", "args": {},
     "subcategories": [
         {"label": "Bible Times", "key": "VODMoviesBibleTimes"},
         {"label": "Modern Day", "key": "VODMoviesModernDay"},
         {"label": "Extra Features", "key": "VODMoviesExtras"},
         {"label": "Animated", "key": "VODMoviesAnimated"},
     ]},
    # Series -- all 32 real jw.org children, real order. "The Good News
    # According to Jesus" keeps its existing custom loader
    # (list_good_news_items(), a curated 6-episode subset) rather than
    # switching to the generic loader against the real 9-item
    # SeriesGoodNews category -- unchanged behavior, just repositioned
    # to its real order slot (was previously tacked on at the end).
    {"label": "Series",
     "loader": "list_mediator_category", "args": {},
     "subcategories": [
         {"label": "A Day in the Life of...", "key": "SeriesADayInTheLifeOf"},
         {"label": "Apply Yourself to Reading and Teaching", "key": "VODMinistryApplyTeaching"},
         {"label": "Become Jehovah's Friend\u2014Songs", "key": "SeriesBJFSongs"},
         {"label": "Become Jehovah's Friend\u2014Video Lessons", "key": "SeriesBJFLessons"},
         {"label": "Dig for Treasures", "key": "SeriesDigForTreasures"},
         {"label": "Enjoy Life Forever", "key": "SeriesLFFVideos"},
         {"label": "Essential Bible Teachings", "key": "SeriesBibleTeachings"},
         {"label": "For a Happy Marriage", "key": "SeriesHappyMarriage"},
         {"label": "Full-Time Service Builds Christian Qualities", "key": "SeriesFullTimeService"},
         {"label": "Imitate Their Faith", "key": "SeriesImitateFaith"},
         {"label": "Introduction to Bible Books", "key": "SeriesBibleBooks"},
         {"label": "Iron Sharpens Iron", "key": "SeriesIronSharpens"},
         {"label": "Learn From Jehovah's Friends", "key": "SeriesJehovahsFriends"},
         {"label": "Learn From Them", "key": "SeriesLearnFromThem"},
         {"label": "Lessons From The Watchtower", "key": "SeriesWTLessons"},
         {"label": "Love People\u2014Make Disciples", "key": "VODLovePeople"},
         {"label": "My Teen Life", "key": "SeriesMyTeenLife"},
         {"label": "Neeta and Jade", "key": "SeriesNeetaJade"},
         {"label": "Organizational Accomplishments", "key": "SeriesOrgAccomplishments"},
         {"label": "Our History in Motion", "key": "SeriesOurHistory"},
         {"label": "Pure Worship\u2014Chapter Introductions", "key": "VODPureWorshipIntro"},
         {"label": "Reasons for Faith", "key": "SeriesReasonsFaith"},
         {"label": "The Bible Changes Lives", "key": "SeriesBibleChangesLives"},
         {"label": "The Good News According to Jesus", "loader": "list_good_news_items", "args": {}},
         {"label": "Truth Transforms Lives", "key": "SeriesTruthTransforms"},
         {"label": "Viewpoints on the Origin of Life", "key": "SeriesOriginsLife"},
         {"label": "Walk Courageously With God", "key": "SeriesWCGVideos"},
         {"label": "Was It Designed?", "key": "SeriesWasItDesigned"},
         {"label": "Website and App Help", "key": "SeriesWebsiteAppHelp"},
         {"label": "What Your Peers Say", "key": "SeriesWhatPeersSay"},
         {"label": "Where Are They Now?", "key": "SeriesWhereAreTheyNow"},
         {"label": "Whiteboard Animations", "key": "SeriesWhiteboard"},
     ]},
    # "Children's Songs" (ChildrensSongs, 85 items) is BYTE-IDENTICAL to
    # Children's own "Songs" (ChildrenSongs, same 85 items, confirmed)
    # -- same cross-listing pattern as the other dedup cases above.
    # Skipped here, kept under Children in its real order position.
    {"label": "Music",
     "loader": "list_mediator_category", "args": {},
     "subcategories": [
         {"label": "Original Songs", "key": "VODOriginalSongs"},
         {"label": "\u201cSing Out Joyfully\u201d to Jehovah\u2014Meetings", "key": "VODSJJMeetings"},
         {"label": "Convention Music Presentations", "key": "VODConvMusic"},
         {"label": "Making Music", "key": "MakingMusic"},
         {"label": "Sing to Jehovah", "key": "VODSingToJah"},
     ]},
    {"label": "Interviews and Experiences",
     "loader": "list_mediator_category", "args": {},
     "subcategories": [
         {"label": "Truth Transforms Lives", "key": "VODIntExpTransformations"},
         {"label": "Blessings of Sacred Service", "key": "VODIntExpBlessings"},
         {"label": "Enduring Trials", "key": "VODIntExpEndurance"},
         {"label": "Young People", "key": "VODIntExpYouth"},
         {"label": "Science", "key": "OriginsLife"},
         {"label": "From Our Archives", "key": "VODIntExpArchives"},
     ]},
    # v26.08.03.02 (Kaleb's request -- confirmed live via the real
    # mediator VideoOnDemand tree): "Audio Descriptions" was a genuinely
    # missing real top-level category (VODAudioDescriptions, type
    # "container") -- narrated-description versions of existing videos
    # for the visually impaired. It has zero media of its own and 48
    # real children (confirmed live, GET .../categories/E/
    # VODAudioDescriptions?detailed=1) -- same "loader"/"subcategories"
    # shape as every other container entry above, not a special case.
    # One child spot-checked live (VODLFFVideosAD, 67 real videos, real
    # progressiveDownloadURL files at every resolution) to confirm this
    # tree actually plays, not just lists.
    {"label": "Audio Descriptions",
     "loader": "list_mediator_category", "args": {},
     "subcategories": [
         {"label": "Weekly Meetings", "key": "VODMidweekMeetingAD"},
         {"label": "The Good News According to Jesus", "key": "SeriesGoodNewsAD"},
         {"label": "JW Broadcasting", "key": "VODStudioAD"},
         {"label": "A Day in the Life of...", "key": "SeriesADayInTheLifeOfAD"},
         {"label": "Apply Bible Principles", "key": "VODBiblePrinciplesAD"},
         {"label": "Become Jehovah's Friend\u2014Songs", "key": "SeriesBJFSongsAD"},
         {"label": "Become Jehovah's Friend\u2014Video Lessons", "key": "SeriesBJFLessonsAD"},
         {"label": "Dig for Treasures", "key": "SeriesDigForTreasuresAD"},
         {"label": "Dramas", "key": "VODDramasAD"},
         {"label": "Enjoy Life Forever!\u2014Videos", "key": "VODLFFVideosAD"},
         {"label": "Essential Bible Teachings", "key": "VODSeriesBibleTeachingsAD"},
         {"label": "Family", "key": "VODFamilyAD"},
         {"label": "For a Happy Marriage", "key": "SeriesHappyMarriageAD"},
         {"label": "Full-Time Service Builds Christian Qualities", "key": "SeriesFullTimeServiceAD"},
         {"label": "Imitate Their Faith", "key": "SeriesImitateFaithAD"},
         {"label": "Interviews and Experiences", "key": "VODIntExpAD"},
         {"label": "Introduction to Bible Books", "key": "VODBibleBooksAD"},
         {"label": "Iron Sharpens Iron", "key": "SeriesIronSharpensAD"},
         {"label": "Learn From Jehovah\u2019s Friends", "key": "SeriesJehovahsFriendsAD"},
         {"label": "Learn From Them", "key": "SeriesLearnFromThemAD"},
         {"label": "Lessons From The Watchtower", "key": "SeriesWTLessonsAD"},
         {"label": "Love People\u2014Make Disciples", "key": "VODLovePeopleAD"},
         {"label": "My Teen Life", "key": "SeriesMyTeenLifeAD"},
         {"label": "Organizational Accomplishments", "key": "OrgAccomplishmentsAD"},
         {"label": "Original Songs", "key": "VODOriginalSongsAD"},
         {"label": "Our Activities", "key": "VODOurActivitiesAD"},
         {"label": "Our History in Motion", "key": "SeriesOurHistoryAD"},
         {"label": "Our Meetings and Ministry", "key": "VODMinistryAD"},
         {"label": "Our Organization", "key": "VODOurOrganizationAD"},
         {"label": "Programs and Events", "key": "VODProgramsEventsAD"},
         {"label": "Reasons for Faith", "key": "SeriesReasonsFaithAD"},
         {"label": "\u201cSing Out Joyfully\u201d\u2014Meetings", "key": "VODSJJMeetingsAD"},
         {"label": "Teenagers", "key": "VODTeenagersAD"},
         {"label": "The Bible", "key": "VODBibleAD"},
         {"label": "The Bible Changes Lives", "key": "SeriesBibleChangesLivesAD"},
         {"label": "Tools for the Ministry", "key": "VODMinistryToolsAD"},
         {"label": "Truth Transforms Lives", "key": "VODIntExpTransformationsAD"},
         {"label": "Walk Courageously With God\u2014Videos", "key": "SeriesWCGVideosAD"},
         {"label": "What Your Peers Say", "key": "SeriesWhatPeersSayAD"},
         {"label": "Whiteboard Animations", "key": "SeriesWhiteboardAD"},
         {"label": "2026 Eternal Happiness Convention", "key": "2026ConventionAD"},
         {"label": "2025 Pure Worship Convention", "key": "2025ConventionAD"},
         {"label": "2024 \u201cDeclare the Good News!\u201d Convention", "key": "2024ConventionAD"},
         {"label": "2023 \u201cExercise Patience\u201d! Convention", "key": "2023ConventionAD"},
         {"label": "2022 \u201cPursue Peace\u201d! Convention", "key": "2022ConventionAD"},
         {"label": "2021 Powerful by Faith! Convention", "key": "2021ConventionAD"},
         {"label": "2020 \u201cAlways Rejoice\u201d! Convention", "key": "2020ConventionAD"},
         {"label": "2019 \u201cLove Never Fails\u201d! Convention", "key": "2019ConventionAD"},
     ]},
    {"label": "Search Videos", "search": True},
    # v26.08.07.18: same "Downloaded" marker entry as AUDIO_SOURCES --
    # see that one's own comment for the full reasoning.
    {"label": "Downloaded", "downloaded": True},
]

AUDIO_SOURCES = [
    # v26.07.30.16 (Kaleb's request: "make a category in audio called
    # publications and another for music, nest all the music there and
    # publications nest all the audio books there" -- and to fold
    # Watchtower Study Audio / Bible Reading Audio in under Publications
    # since they're audiobook-style content too, not deleted since
    # neither is actually redundant: Watchtower's shortcut resolves a
    # specific CURRENT periodical issue -- genuinely different from a
    # STATIC_PUBLICATIONS title -- and NWT needs its own book-by-book
    # picker no other entry replicates). "Music" below is the exact
    # same 6 real mediator "Audio" subcategories as before, just
    # nested one level deeper -- v26.07.23.01's original verification
    # against the live mediator API still stands, nothing re-derived.
    {"label": "Music", "subcategories": [
        # v26.08.03.13 BUG FIX (Kaleb's request: "double check our
        # curated categories match JW.org exactly in hierarchy" --
        # confirmed live via a full ordered comparison against the
        # real mediator Audio category tree): International Music is
        # genuinely FIRST in jw.org's own real order, Original Songs
        # second -- this file had them the other way around since
        # International Music was added mid-list on v26.08.03.02
        # rather than at its real position. Every other category in
        # both VIDEO_SOURCES and AUDIO_SOURCES was re-verified against
        # live order at the same time and confirmed already correct;
        # this was the one real mismatch found.
        {"label": "International Music", "music_category": True,
         "loader": "list_mediator_audio_category",
         "args": {"key": "AudioInternationalMusic", "title": "International Music"}},
        {"label": "Original Songs", "music_category": True,
         "loader": "list_original_songs_audio", "args": {}},
        {"label": "\u201cSing Out Joyfully\u201d to Jehovah\u2014Meetings", "music_category": True,
         "loader": "list_mediator_audio_category",
         "args": {"key": "SJJMeetings", "title": "\u201cSing Out Joyfully\u201d to Jehovah\u2014Meetings"}},
        {"label": "\u201cSing Out Joyfully\u201d to Jehovah\u2014Vocals", "music_category": True,
         "loader": "list_mediator_audio_category",
         "args": {"key": "SJJChorus", "title": "\u201cSing Out Joyfully\u201d to Jehovah\u2014Vocals"}},
        {"label": "\u201cSing Out Joyfully\u201d to Jehovah\u2014Instrumental", "music_category": True,
         "loader": "list_mediator_audio_category",
         "args": {"key": "SJJInstrumental", "title": "\u201cSing Out Joyfully\u201d to Jehovah\u2014Instrumental"}},
        {"label": "Sing to Jehovah\u2014Chorus", "music_category": True,
         "loader": "list_mediator_audio_category",
         "args": {"key": "Vocal", "title": "Sing to Jehovah\u2014Chorus"}},
        {"label": "Children\u2019s Songs", "music_category": True,
         "loader": "list_mediator_audio_category",
         "args": {"key": "AudioChildrenSongs", "title": "Children\u2019s Songs"}},
        {"label": "Kingdom Melodies", "music_category": True,
         "loader": "list_mediator_audio_category",
         "args": {"key": "KingdomMelodies", "title": "Kingdom Melodies"}},
    ]},
    # "Publications": audiobook versions. "pub_category" entries are a
    # NEW mechanism (not shared with VIDEO_SOURCES' "subcategories") --
    # main.py drills into jw_fetch.list_items(category=X) for these
    # (the SAME live catalog EPUB browsing already uses -- one shared
    # source of truth, not a second hardcoded list to keep in sync),
    # then resolves whichever title is picked via list_audio_items().
    # Confirmed live this session: 47 of the app's 59 STATIC_
    # PUBLICATIONS entries have real MP3 audio (the other 12 --
    # Service Year Reports, a couple others -- genuinely don't); no
    # attempt is made to pre-filter the list to just those 47, since
    # that set can drift as JW.org adds narration to older titles --
    # selecting a title with no audio just shows "no audio available",
    # same graceful failure as every other not-every-format-exists
    # case already in this file.
    {"label": "Publications", "subcategories": [
        # v26.07.30.28 (Kaleb: "did we implement the full backlog of
        # watchtowers and awakes and study issues too just like epub?
        # but the audio?" -- real gap found and fixed: confirmed live
        # that audio goes back to at least 201601, same historical
        # depth as EPUB, but the app only ever offered the current
        # week). "issues": True is a new marker (parallel to "books")
        # -- main.py's SCREEN_DOWNLOAD_AUDIO_ISSUES browses the full
        # back-issue list via "issue_loader" instead of only ever
        # fetching whatever "This Week" resolves to. Label dropped
        # "(This Week)" since it's the full range now, newest first.
        # v26.08.05.13 (Kaleb: "drop the term audio since we're
        # already in audio" -- also dropped from the three siblings
        # below): matches the convention every OTHER Publications
        # entry already used (New World Translation, Books, Life
        # Stories, etc. -- none of them said "Audio" either). This
        # entry and Meeting Workbook Audio were the ONLY two that
        # still had it, left over from before that convention was
        # applied to the Bible entries; Public Watchtower Audio/
        # Awake! Audio (added last session) matched THEM instead of
        # noticing the wider inconsistency -- see classify_audio_
        # folder() below, updated with the new folder-name spelling
        # for all four so existing downloads still migrate correctly.
        {"label": "Watchtower Study", "issues": True, "use_album_folder": True,
         "issue_loader": "list_watchtower_audio_issues",
         "loader": "list_audio_items", "args": {"pub": "w"}},
        # v26.08.05.10 (Kaleb's request: "add watchtower and awakes all
        # the way back including the public version of watchtowers
        # too"). New entries, same "issues": True shape as Watchtower
        # Study just above -- the audio issue-picker screen
        # (SCREEN_DOWNLOAD_AUDIO_ISSUES) is fully generic already, so
        # these needed no new UI code, just new issue_loader functions
        # (see list_wp_audio_issues()/list_awake_audio_issues() in
        # jw_fetch.py for how far back each one reaches and exactly
        # how that range was confirmed).
        {"label": "Public Watchtower", "issues": True, "use_album_folder": True,
         "issue_loader": "list_wp_audio_issues",
         "loader": "list_audio_items", "args": {"pub": "wp"}},
        {"label": "Awake!", "issues": True, "use_album_folder": True,
         "issue_loader": "list_awake_audio_issues",
         "loader": "list_audio_items", "args": {"pub": "g"}},
        # v26.07.30.18 (Kaleb: "make sure most books, brochures,
        # bibles, tracts and workbooks get audiobooks... I know they
        # exist" -- real gap found and fixed): Meeting Workbook had
        # genuine audio (confirmed live) but was completely unreachable
        # -- Watchtower's shortcut only ever covered "w", never "mwb".
        {"label": "Meeting Workbook", "issues": True, "use_album_folder": True,
         "issue_loader": "list_mwb_audio_issues",
         "loader": "list_audio_items", "args": {"pub": "mwb"}},
        # v26.07.30.27 (Kaleb: "Bible Reading Should just be New World
        # Translation and Same (1984 edition) and reflect that into how
        # it labeled in the app too under Bibles" -- both labels now
        # match STATIC_PUBLICATIONS' own Bibles entries for "nwt"/
        # "bi12" exactly, one consistent name whether you're browsing
        # Bibles for the EPUB or Publications for its audio).
        # v26.07.30.32: "use_album_folder" on all four periodical/Bible
        # entries here (Watchtower, Meeting Workbook, both Bible
        # editions) -- see read_mp3_album_tag()'s own docstring for
        # why these four specifically are safe for this and other
        # sources (e.g. Life Stories) deliberately are not.
        {"label": "New World Translation", "books": True, "use_album_folder": True,
         "loader": "list_audio_items", "args": {"pub": "nwt"}},
        # v26.07.30.18: same gap, different Bible edition -- "bi12"
        # (1984 Edition) has its own real per-book audio (confirmed
        # live, 50 real chapters for Genesis alone) that NWT's own
        # book-picker entry doesn't cover (different pub code).
        {"label": "New World Translation (1984 Edition)", "books": True, "use_album_folder": True,
         "loader": "list_audio_items", "args": {"pub": "bi12"}},
        # v26.07.30.18: "Article Series" edge case Kaleb specifically
        # flagged -- these are jw.org web articles, not standalone
        # EPUB publications (confirmed earlier this session none of
        # them have a downloadable EPUB), but several DO have real
        # audio via the exact same list_audio_items() mechanism as
        # everything else here, confirmed live: "lfs" (Life Stories,
        # 26 real entries) and "mrt" (More Topics -- general Bible/
        # science/history articles, 102 real entries). Other article-
        # series pub codes checked and confirmed NO audio: "ijw"
        # (400 Bad Request -- generic landing-page wrapper, not real
        # content), "ljfac" (404). Ordinary AUDIO_SOURCES entries, not
        # a "books"/"pub_category" special case -- pub=lfs/mrt with no
        # extra params already returns each series' FULL flat list in
        # one call, same as Original Songs.
        {"label": "Life Stories", "loader": "list_audio_items", "args": {"pub": "lfs"}},
        {"label": "More Topics", "loader": "list_audio_items", "args": {"pub": "mrt"}},
        # v26.07.30.19 (Kaleb's follow-up: real JW Library screenshots
        # of the full Article Series list). Checked every remaining
        # series against GETPUBMEDIALINKS live: "hdu" (How Your
        # Donations Are Used) confirmed with 35 real audio entries --
        # added. "Was It Designed?" (ijwwd) and "Imprisoned for Their
        # Faith" (ijwif) DO have real downloadable content (the file
        # sizes Kaleb's screenshot showed are real) but confirmed
        # JWPUB-ONLY -- no EPUB, no separate MP3 track list, so this
        # EPUB/MP3-based app has no way to support them. Everything
        # else checked (Young People Ask, Illustrated Bible Stories,
        # The Bible Changes Lives, Bible Questions Answered, and the
        # rest) confirmed to have neither EPUB nor audio at all --
        # these are curated indexes into existing Watchtower Public
        # Edition articles, not separate publications.
        {"label": "How Your Donations Are Used", "loader": "list_audio_items", "args": {"pub": "hdu"}},
        # v26.07.30.20 (Kaleb's follow-up: real live investigation of
        # the "Bible Verses Explained" finder link he sent). Different
        # mechanism from every other Publications entry -- no shared
        # pub code, addressed by individual docid instead -- but the
        # docids cluster in one confirmed-live, gap-tolerant numeric
        # range (502300100-502300162, exactly 55 real entries, scanned
        # well past both edges to confirm zero hits outside it). See
        # list_docid_range_audio()'s docstring for the full mechanism.
        {"label": "Bible Verses Explained", "loader": "list_docid_range_audio",
         "args": {"start_docid": 502300100, "end_docid": 502300162}},
        # v26.07.30.21 (Kaleb's batch of finder links): "foa" (From Our
        # Archives) confirmed live with real audio via the plain shared
        # pub code, same simple mechanism as Life Stories/More Topics --
        # no docid range needed for this one. Checked but NOT added
        # from that same batch: "ijwex" (Experiences of Jehovah's
        # Witnesses) and "ijwfq"/"ijwhf"/"ijwia" (FAQ/Family/Imitate
        # Their Faith character pages) -- all real article-index pages,
        # but their docid ranges are confirmed live to be too sparse to
        # probe (Experiences: only 4 real hits in a 150-docid window,
        # vs. 55 hits in 63 slots for Bible Verses Explained) -- would
        # cost thousands of requests to find everything, not worth it.
        {"label": "From Our Archives", "loader": "list_audio_items", "args": {"pub": "foa"}},
        # "pub_category" values are the real CATEGORY_* string VALUES
        # ("Books" / "Brochures and Booklets" / "Tracts"), not the
        # Python constant names -- AUDIO_SOURCES is defined earlier in
        # this file than CATEGORY_BOOKS/CATEGORY_BROCHURES/
        # CATEGORY_TRACTS themselves, so referencing the actual Python
        # names here isn't possible at module-load time. If any of
        # those three constants' STRING VALUE ever changes, these three
        # lines need updating to match (a real coupling, kept as
        # narrow and visible as possible rather than hidden).
        {"label": "Books", "pub_category": "Books"},
        {"label": "Brochures and Booklets", "pub_category": "Brochures and Booklets"},
        {"label": "Tracts", "pub_category": "Tracts"},
    ]},
    {"label": "Search Audio", "search": True},
    # v26.08.07.18 (Kaleb's request: "we would really need a way to
    # access them [downloaded audio] in library" -- a persistent,
    # always-reachable entry point, not just the offline-only local
    # fallback list_local_folder_items() already provides). "downloaded"
    # is a marker main.py's button handler checks for BEFORE the
    # generic loader dispatch (source["loader"]/source["args"]) --
    # there's no real network loader for this, main.py routes straight
    # to a recursive local-file scan instead (list_local_media_
    # recursive() -- see its own docstring).
    {"label": "Downloaded", "downloaded": True},
]

# Standard NWT book numbering (1-66, Genesis through Revelation) -- this
# is the fixed Bible book order/numbering GETPUBMEDIALINKS' booknum=
# param uses, confirmed directly this session (booknum=1 -> "Chapter 1"
# entries under a Genesis-shaped 50-chapter list; booknum=19 -> a
# 150-chapter Psalms list). Standard, non-language-specific numbering
# (same across all NWT translations), not something that needs a
# per-entry live check the way pub codes/issue dates do.
# ---------------------------------------------------------------------------
# Auto-discovery of new Audio/Video categories (v26.08.03.02, Kaleb's
# request -- "would it be possible to have our plugin detect new
# categories... self-generate... similar to JW Library").
#
# HOW IT WORKS: this only ever ADDS entries, never edits/removes the
# hand-curated lists above. check_new_categories() walks the real live
# mediator category tree (same root "Audio"/"VideoOnDemand" containers
# used to confirm "International Music"/"Audio Descriptions" this
# session) and compares every key it finds against every key already
# known (collected from VIDEO_SOURCES/AUDIO_SOURCES themselves via
# _known_category_keys(), so the "known" list can never drift out of
# sync with the real hand-curated data). Anything genuinely new gets
# written to DISCOVERED_CATEGORIES_PATH in the exact same {"label",
# "loader", "args"}/{"label","subcategories":[...]} shape as a normal
# VIDEO_SOURCES/AUDIO_SOURCES entry -- then _merge_discovered_
# categories() (called once, at import time, right after this) appends
# them as a single extra top-level "New Categories (Video)"/"New
# Categories (Audio)" entry, clearly separated from the hand-reviewed
# list rather than silently blended into it. Kaleb can browse/use them
# immediately; promoting one into the real curated list above (proper
# name, right position) is a manual step, same review bar as every
# other entry in this file.
#
# Recursion stops at any key already known -- a whole existing branch
# (e.g. "Series", 32 real children) is never re-walked, only the parts
# of the live tree this file doesn't already cover. max_depth guards
# against a pathological future tree; every real category checked this
# session (Audio, VideoOnDemand, VODAudioDescriptions) is 2 levels deep.
# v26.08.03.02: real jw.org categories confirmed BYTE-IDENTICAL to an
# already-curated entry under a different key/parent (see each match's
# own "BYTE-IDENTICAL" comment above in VIDEO_SOURCES/AUDIO_SOURCES) --
# deliberately not re-listed as their own entries, and must not be
# reported as "new" by check_new_categories() either.
_KNOWN_DUPLICATE_KEYS = {
    "VODMinistryTeachings",  # == SeriesBibleTeachings ("Essential Bible Teachings")
    "BibleBooks",            # == SeriesBibleBooks ("Introduction to Bible Books")
    "DramasGoodNews",        # == SeriesGoodNews ("The Good News According to Jesus")
    "ChildrensSongs",        # == ChildrenSongs ("Children's Songs")
    "AudioOriginalSongs",    # == list_original_songs_audio()'s own curated source
    "SeriesGoodNews",        # == list_good_news_items()'s own curated 6-episode subset
}


def _known_category_keys():
    """Collects every real mediator category key already referenced
    anywhere in VIDEO_SOURCES/AUDIO_SOURCES (top-level or nested
    subcategories), so discovery can never re-report something already
    hand-curated. Also includes _KNOWN_DUPLICATE_KEYS -- real jw.org
    categories that are BYTE-IDENTICAL to an already-curated entry
    under a different key (jw.org itself cross-lists some categories
    under two parents; this app deliberately keeps just one copy -- see
    each key's own comment above in VIDEO_SOURCES/AUDIO_SOURCES for the
    live-verified duplicate pair). Without this, every one of these
    would be wrongly re-reported as "new" on every check."""
    keys = set(_KNOWN_DUPLICATE_KEYS)

    def _walk(nodes):
        for node in nodes:
            k = node.get("key") or (node.get("args") or {}).get("key")
            if k:
                keys.add(k)
            if node.get("subcategories"):
                _walk(node["subcategories"])

    _walk(VIDEO_SOURCES)
    _walk(AUDIO_SOURCES)
    return keys


def _fetch_category_detail(key):
    url = MEDIATOR_CATEGORY_URL.format(lang=LANG, key=key) + "?detailed=1&clientType=www"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _category_status(key):
    """v26.08.03.03 (Kaleb's request: detect categories JW.org removes
    or renames, not just adds). Returns (exists, live_name):
      exists=True   -- key is live; live_name is its CURRENT real name
                        (may differ from what we have cached -- a rename)
      exists=False  -- key confirmed GONE (a real 404, not a network
                        hiccup -- the only case safe to prune on)
      exists=None   -- inconclusive (timeout/connection error/5xx) --
                        deliberately NOT treated as removal, so a bad
                        wifi moment can never wipe out real categories
    """
    try:
        data = _fetch_category_detail(key)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False, None
        return None, None  # 5xx etc -- inconclusive, leave it alone
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None, None  # inconclusive
    cat = data.get("category", data)
    return True, (cat.get("name") or None)


def _revalidate_node(node, is_audio):
    """Re-checks one previously-discovered node (leaf or container)
    against the live API: confirmed-gone (404) leaves get dropped,
    renamed ones get their "label" synced to the current live name,
    containers get recursed into (and dropped entirely if every child
    turned out to be gone too). Returns the updated node, or None if it
    should be removed."""
    key = node.get("key") or (node.get("args") or {}).get("key")
    if key:
        exists, live_name = _category_status(key)
        if exists is False:
            return None  # confirmed removed by JW.org -- prune it
        if exists and live_name and live_name != node["label"]:
            node = dict(node, label=live_name)  # renamed -- sync menu label
            if node.get("args", {}).get("title"):
                node = dict(node, args=dict(node["args"], title=live_name))  # sync args too
        return node

    if node.get("subcategories"):
        kept = []
        for child in node["subcategories"]:
            revalidated = _revalidate_node(child, is_audio)
            if revalidated:
                kept.append(revalidated)
        if not kept:
            return None  # every child gone -- drop the whole container
        return dict(node, subcategories=kept)

    return node  # nothing to check (e.g. a "search" marker) -- keep as-is


def _revalidate_discovered_cache(cache):
    """Runs _revalidate_node over the whole existing discovery cache
    before any new-discovery walk -- so removed categories disappear
    and renamed ones get corrected on every check, not just additions."""
    out = {"video": [], "audio": []}
    for bucket, is_audio in (("video", False), ("audio", True)):
        for node in cache.get(bucket, []):
            revalidated = _revalidate_node(node, is_audio)
            if revalidated:
                out[bucket].append(revalidated)
    return out


def _check_curated_categories_alive():
    """v26.08.03.03: read-only sanity pass over the HAND-CURATED
    VIDEO_SOURCES/AUDIO_SOURCES lists -- confirms every real "key" is
    still live. Deliberately does NOT auto-edit the curated lists (that
    static, reviewed data shouldn't silently change itself -- same
    principle as the rest of this file's "never guess, ask before
    changes" standard); just reports which labels look gone so Kaleb
    can decide whether to remove/rename them. Returns a list of
    (label, key) pairs confirmed 404."""
    dead = []

    def _walk(nodes):
        for node in nodes:
            key = node.get("key") or (node.get("args") or {}).get("key")
            if key and key not in _KNOWN_DUPLICATE_KEYS:
                exists, _live_name = _category_status(key)
                if exists is False:
                    dead.append((node.get("label", key), key))
            if node.get("subcategories"):
                _walk(node["subcategories"])

    _walk(VIDEO_SOURCES)
    _walk(AUDIO_SOURCES)
    return dead


def _walk_new_subcategories(key, known_keys, is_audio, depth=0, max_depth=3):
    """Live-fetches one category and returns a VIDEO_SOURCES/
    AUDIO_SOURCES-shaped node for it (leaf: real loader+args; container:
    nested "subcategories"), or None if it has neither real media nor
    any genuinely new children -- e.g. a category that turned out to be
    entirely already-known, or a dead/empty one."""
    try:
        data = _fetch_category_detail(key)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None
    cat = data.get("category", data)
    name = cat.get("name") or key
    subs = cat.get("subcategories", [])
    has_media = bool(cat.get("media"))

    if subs and depth < max_depth:
        children = []
        for s in subs:
            sk = s.get("key")
            if not sk or sk in known_keys:
                continue  # already hand-curated elsewhere -- skip, don't re-walk
            child = _walk_new_subcategories(sk, known_keys, is_audio, depth + 1, max_depth)
            if child:
                children.append(child)
        if children:
            return {"label": name, "subcategories": children}
        if has_media:
            pass  # container also has its own direct media -- fall through below
        else:
            return None

    if has_media:
        loader = "list_mediator_audio_category" if is_audio else "list_mediator_category"
        return {"label": name, "loader": loader, "args": {"key": key, "title": name}}
    return None


def _all_keys_in_cache(cache):
    keys = set()

    def _walk(nodes):
        for n in nodes:
            k = n.get("key") or (n.get("args") or {}).get("key")
            if k:
                keys.add(k)
            if n.get("subcategories"):
                _walk(n["subcategories"])

    for bucket in cache.values():
        _walk(bucket)
    return keys


def check_new_categories():
    """Public entry point (wire to a Settings action, e.g. 'Check for
    New Categories'). Returns (added, removed, error). Safe to call
    repeatedly:
      - re-checks against the CURRENT hand-curated lists each time, so
        anything promoted into the real curated lists since the last
        check stops showing up as "new"
      - v26.08.03.03: also revalidates every PREVIOUSLY discovered
        category first -- confirmed-gone ones (real 404s) get dropped,
        renamed ones get their label corrected -- before looking for
        anything genuinely new. Bounded cost: only re-checks what this
        app itself auto-added before, not the whole hand-curated tree
        (see check_curated_categories() for that heavier, separate check).
    """
    before_cache = _load_category_discovery_cache()
    before_keys = _all_keys_in_cache(before_cache)

    cache = _revalidate_discovered_cache(before_cache)
    after_revalidate_keys = _all_keys_in_cache(cache)
    removed = len(before_keys - after_revalidate_keys)

    known = _known_category_keys() | after_revalidate_keys
    any_error = None

    for root_key, is_audio, bucket in (("VideoOnDemand", False, "video"), ("Audio", True, "audio")):
        try:
            data = _fetch_category_detail(root_key)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
            any_error = str(e)
            continue
        subs = data.get("category", data).get("subcategories", [])
        for s in subs:
            sk = s.get("key")
            if not sk or sk in known:
                continue
            node = _walk_new_subcategories(sk, known, is_audio)
            if node:
                cache[bucket].append(node)
                known.add(sk)

    added = len(_all_keys_in_cache(cache) - after_revalidate_keys)

    _save_category_discovery_cache(cache)
    _apply_discovered_categories(cache)
    return added, removed, any_error


def check_curated_categories():
    """Public entry point for a SEPARATE, heavier Settings action (e.g.
    'Verify Curated Categories'). Walks every real key in the hand-
    curated VIDEO_SOURCES/AUDIO_SOURCES trees live -- 60+ requests
    including the 48-entry Audio Descriptions tree, meaningfully
    slower than check_new_categories() -- so kept as its own explicit
    action rather than folded into every regular check. Does NOT
    modify VIDEO_SOURCES/AUDIO_SOURCES (hand-curated data is only ever
    hand-edited); returns the list of (label, key) pairs confirmed gone
    so Kaleb can decide what to do with them."""
    return _check_curated_categories_alive()


def _load_category_discovery_cache():
    return _load_json_cache(DISCOVERED_CATEGORIES_PATH, default={"video": [], "audio": []})


def _save_category_discovery_cache(discovered):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(DISCOVERED_CATEGORIES_PATH, "w") as f:
            json.dump(discovered, f)
    except Exception:
        pass  # best-effort, same as every other cache in this file


def _apply_discovered_categories(discovered):
    """Appends one extra top-level 'New Categories (...)' entry to
    VIDEO_SOURCES/AUDIO_SOURCES for whatever's in the discovery cache --
    removes any previous auto-added entry first so this is idempotent
    (safe to call every app launch, not just right after a fresh
    check_new_categories() call)."""
    global VIDEO_SOURCES, AUDIO_SOURCES
    VIDEO_SOURCES[:] = [s for s in VIDEO_SOURCES if not s.get("_auto_discovered")]
    AUDIO_SOURCES[:] = [s for s in AUDIO_SOURCES if not s.get("_auto_discovered")]

    if discovered.get("video"):
        search_idx = next((i for i, s in enumerate(VIDEO_SOURCES) if s.get("search")), len(VIDEO_SOURCES))
        VIDEO_SOURCES.insert(search_idx, {
            "label": "New Categories (Video)", "_auto_discovered": True,
            "subcategories": discovered["video"]})
    if discovered.get("audio"):
        search_idx = next((i for i, s in enumerate(AUDIO_SOURCES) if s.get("search")), len(AUDIO_SOURCES))
        AUDIO_SOURCES.insert(search_idx, {
            "label": "New Categories (Audio)", "_auto_discovered": True,
            "subcategories": discovered["audio"]})


# Apply whatever was found on a previous check_new_categories() run,
# every time this module loads -- so newly-discovered categories show
# up in the menu on the very next app launch, not just the launch where
# the check itself was run. Deliberately does NOT hit the network at
# import time (that would slow down every single app launch) -- only
# check_new_categories() itself (a manual Settings action) does that.
_apply_discovered_categories(_load_category_discovery_cache())


BIBLE_BOOKS = [
    (1, "Genesis"), (2, "Exodus"), (3, "Leviticus"), (4, "Numbers"), (5, "Deuteronomy"),
    (6, "Joshua"), (7, "Judges"), (8, "Ruth"), (9, "1 Samuel"), (10, "2 Samuel"),
    (11, "1 Kings"), (12, "2 Kings"), (13, "1 Chronicles"), (14, "2 Chronicles"),
    (15, "Ezra"), (16, "Nehemiah"), (17, "Esther"), (18, "Job"), (19, "Psalms"),
    (20, "Proverbs"), (21, "Ecclesiastes"), (22, "Song of Solomon"), (23, "Isaiah"),
    (24, "Jeremiah"), (25, "Lamentations"), (26, "Ezekiel"), (27, "Daniel"),
    (28, "Hosea"), (29, "Joel"), (30, "Amos"), (31, "Obadiah"), (32, "Jonah"),
    (33, "Micah"), (34, "Nahum"), (35, "Habakkuk"), (36, "Zephaniah"), (37, "Haggai"),
    (38, "Zechariah"), (39, "Malachi"), (40, "Matthew"), (41, "Mark"), (42, "Luke"),
    (43, "John"), (44, "Acts"), (45, "Romans"), (46, "1 Corinthians"), (47, "2 Corinthians"),
    (48, "Galatians"), (49, "Ephesians"), (50, "Philippians"), (51, "Colossians"),
    (52, "1 Thessalonians"), (53, "2 Thessalonians"), (54, "1 Timothy"), (55, "2 Timothy"),
    (56, "Titus"), (57, "Philemon"), (58, "Hebrews"), (59, "James"), (60, "1 Peter"),
    (61, "2 Peter"), (62, "1 John"), (63, "2 John"), (64, "3 John"), (65, "Jude"),
    (66, "Revelation"),
]

# Shown on-screen under the manual-code input box. main.py reads this via
# getattr() so it's optional/plugin-owned -- main.py's text-entry code has
# no JW-specific knowledge, keeping concerns cleanly separated.
# Codes here are all verified LIVE against the real API (same standard as
# STATIC_PUBLICATIONS -- nothing is guessed or assumed).
#
# Awake! GOTCHA worth remembering: its "issue" is a real YYYYMM release
# month, but the on-site "No. N YYYY" label does NOT map to that year/month
# directly. Confirmed live: "Awake! No. 1 2025" is actually issue=202511
# (November 2025), not 202501. Since Awake! only publishes ~1x/year now
# (irregular timing), there's no reliable way to guess its current issue.
# Manual code entry with a known issue is the practical approach for now.
# To find the right issue= value, check jw.org/en/library/magazines/ and
# look at the download links for the specific issue you want.
MANUAL_CODE_HINT = ("Format: CODE SPACE YYYYMM  |  e.g. w 202001 = Jan 2020 Study WT  |  "
                     "e.g. mwb 201806 = Jun 2018 Workbook  |  e.g. g 202511 = Awake! No. 1 2025  |  "
                     "e.g. g 202411 = Awake! No. 1 2024")
# Was the abbreviation-style "w=Watchtower g=Awake! mwb=Workbook es=Daily
# Text" -- didn't communicate that a SPACE + YYYYMM issue is required for
# periodicals (Kaleb couldn't tell from it what to actually type). Now
# shows one full worked example per format, plus TWO Awake! examples since
# its issue number is the least intuitive (see GOTCHA above -- "No. 1
# YYYY" is issue YYYY11, i.e. released in November of the SAME labeled
# year, not January or the prior year as you'd guess). Both g 202511
# (2025) and g 202411 (2024) verified live against GETPUBMEDIALINKS
# (real EPUB returned for each, confirmed via jw.org's own download links
# AND a direct API call, not guessed from the pattern of a single data
# point). A third, g 202311 (Awake! No. 1 2023, "Can Our Planet
# Survive?"), is also live-verified and available if a 2023 example is
# ever wanted instead/in addition -- not included here yet to keep this
# hint from growing past what fits comfortably above the keyboard grid.
# Verified this still wraps cleanly (all words visible, no dropped/
# clipped text) and the on-screen keyboard grid still fits below it at
# every Font Size step 14-32pt on the code-entry screen in main.py.

# ---------------------------------------------------------------------------
# API configuration
# ---------------------------------------------------------------------------

# JW.org's own public media API -- the same endpoint their official apps
# use. No authentication required, but this is not a documented public API;
# use it respectfully (reasonable timeouts, no hammering).
# Reference: confirmed via network inspection of official JW apps.
API_BASE = "https://b.jw-cdn.org/apis/pub-media/GETPUBMEDIALINKS"

# v0.1.106: jw.org's own "mediator" API -- what the site's front-end
# itself calls to populate a video category page (e.g. the JW
# Broadcasting nav link is really just a client-side route,
# #en/categories/VODStudio, backed by this endpoint -- confirmed via
# direct fetch of that page: the static HTML has no video listing at
# all, just nav chrome, because the real list loads from here). Same
# jw-cdn.org domain as API_BASE above, still jw.org's own
# infrastructure, not a third party. Category key confirmed live:
# StudioMonthlyPrograms is JW Broadcasting's monthly programs list,
# newest first, 65 items as of this writing, each with a naturalKey
# (e.g. "pub-jwb-139_E_1_VIDEO") and a flat "files" list (not grouped
# by track under files[LANG][MP4] the way GETPUBMEDIALINKS is) -- one
# entry per quality, already exactly what's needed to build a
# downloadable item without a second API call.
MEDIATOR_CATEGORY_URL = "https://b.jw-cdn.org/apis/mediator/v1/categories/{lang}/{key}"

# RSS feed used to detect the actual latest Watchtower/Workbook issue.
# This is a publicly available feed linked from jw.org itself. We parse
# the title strings to extract month/year and convert to YYYYMM issue codes.
WHATS_NEW_RSS = "https://www.jw.org/en/whats-new/rss/WhatsNewWebArticles/feed.xml"
# v0.1.105: jw.org renamed this feed (was .../WhatsNewArticles/feed.xml).
# Found because Kaleb pulled the live feed directly and its <link>/
# self-referencing atom:link both showed "WhatsNewWebArticles" instead of
# our old "WhatsNewArticles" -- confirmed live: old URL now 404s, new URL
# is a real 200 with real items. This had been silently breaking
# check_new_issues() (falls back to current_issue_guess() on any
# failure, so it never surfaced as an error -- just quietly stopped
# finding the real current issue).

# v0.1.107: jw.org's general news feed -- Governing Body Update videos
# are published as NEWS RELEASES (jw.org/en/news/region/global/...),
# not filed under the Video Library category tree at all (checked --
# no dedicated category for them there). Confirmed live this feed does
# carry them (title starts "NEWS RELEASES | <year> Governing Body
# Update #N").
NEWS_RSS = "https://www.jw.org/en/news/rss/FullNewsRSS/feed.xml"

REQUEST_TIMEOUT = 15
USER_AGENT = "PicoReader/1.0 (muOS EPUB reader; personal, non-commercial)"

# Language code used in all API calls. "E" = English.
# The API accepts standard two-letter codes for other languages.
LANG = "E"

# ---------------------------------------------------------------------------
# Publication catalog
# ---------------------------------------------------------------------------

# Category names, in menu order -- Kaleb's requested grouping.
# v0.1.89: CATEGORY_WHATS_NEW restores the RSS "scan for recent
# publications" view that became unreachable once SUPPORTS_CATEGORIES
# routing was added (main.py's open_downloader() always sends this
# plugin straight to the category picker now, so the old flat
# category=None view -- where every RSS-detected "(new)" issue across
# every category surfaced together -- never got called anymore). The
# RSS detection itself (check_new_issues()) was never removed; it just
# lost its only UI entry point. This pseudo-category is a real entry in
# CATEGORIES so it shows up in the normal picker, but list_items()
# special-cases it below to return ONLY the RSS-detected "(new)" hits,
# across every category, instead of one category's full catalog.
CATEGORY_WHATS_NEW = "New Issues"  # v26.07.09.11: renamed from "What's
# New (RSS)" -- that label implied general JW.org news, but this only
# ever surfaces newly-detected PERIODICAL issues (Watchtower/Awake/
# Workbook) via check_new_issues(). Confirmed this was genuinely
# confusing Kaleb about what the feature does.
CATEGORY_BIBLES = "Bibles"
# v26.07.30.09 (Kaleb's request, matching real JW Library app screens):
# jw.org itself splits Books from Brochures & Booklets as two separate
# library sections (confirmed live via /en/library/books/ vs
# /en/library/brochures/ and per-title finder redirects -- see the
# STATIC_PUBLICATIONS reclassification below). Previously merged into
# one "Books & Brochures" category; now matches jw.org's own split.
CATEGORY_BOOKS = "Books"
CATEGORY_BROCHURES = "Brochures and Booklets"
CATEGORY_TRACTS = "Tracts"

CATEGORY_WATCHTOWER_STUDY = "Watchtower\u2014Study Edition"
CATEGORY_WATCHTOWER_PUBLIC = "Watchtower\u2014Public Edition"
CATEGORY_AWAKE = "Awake!"
CATEGORY_WORKBOOKS = "Meeting Workbooks"
# v0.1.110: CATEGORY_VIDEOS is a pseudo-category, same principle as
# CATEGORY_WHATS_NEW -- a real entry in CATEGORIES so it shows up in the
# normal category picker. Moved here per Kaleb: the four video features
# (Enjoy Life Forever, JW Broadcasting, Governing Body Updates, The Good
# News According to Jesus) used to each be their own separate line in
# the Library popup menu, cluttering it -- now they're one "Videos"
# entry that opens a small sub-picker (main.py's
# SCREEN_DOWNLOAD_VIDEO_SOURCES / draw_download_video_sources()).
# Doesn't route through list_items() below at all -- main.py
# special-cases selecting it.
CATEGORY_VIDEOS = "Videos"
# v26.07.10.01: CATEGORY_AUDIO -- same pseudo-category pattern as
# CATEGORY_VIDEOS just above. Kaleb's bug-report feature request:
# downloadable JW audio (MP3), saved into muOS's native GMU Music Player
# content folder (ROMS/Music -- confirmed against Kaleb's own device,
# same verification bar as find_movies_dir()'s ROMS/movies). Opens
# main.py's SCREEN_DOWNLOAD_AUDIO_SOURCES / draw_download_audio_sources()
# sub-picker, same as Videos does -- doesn't route through list_items().
CATEGORY_AUDIO = "Audio"
# v26.07.30.09 (Kaleb's request, matching real JW Library app): "Our
# Kingdom Ministry" -- confirmed live via GETPUBMEDIALINKS to have real
# EPUB editions for issue=YYYYMM from 2012-01 through 2015-12 (2011 and
# earlier: PDF/JWPUB only, no EPUB; 2016 onward: 404, replaced by the
# Meeting Workbook -- CATEGORY_WORKBOOKS above). A closed, finite
# archive with no "current issue" -- see generate_km_back_issues().
CATEGORY_KINGDOM_MINISTRY = "Kingdom Ministry"
# v26.08.07.06 (Kaleb's report, same session as the pub-code hyphen
# fix above): Convention Program EPUBs (pub codes like "co-pgm20")
# had nowhere to file -- no matching category existed at all, so even
# once the filename parsed, resolve_item_category() returned None
# ("never guess") and the migration tool still skipped them. New
# category, name matches JW Library's own real naming.
CATEGORY_PROGRAMS = "Programs"
CATEGORIES = [CATEGORY_WHATS_NEW, CATEGORY_BIBLES, CATEGORY_BOOKS, CATEGORY_BROCHURES, CATEGORY_TRACTS,
              CATEGORY_WATCHTOWER_STUDY, CATEGORY_WATCHTOWER_PUBLIC, CATEGORY_AWAKE, CATEGORY_WORKBOOKS,
              CATEGORY_KINGDOM_MINISTRY, CATEGORY_VIDEOS, CATEGORY_AUDIO]
# v26.08.07.06: CATEGORY_PROGRAMS is intentionally NOT added to this
# browsable list -- it exists only so resolve_item_category()/
# STATIC_PUBLICATIONS below can file Convention Program EPUBs into a
# correctly-named folder (this session's actual bug report: the
# migration tool). Making it a live, browsable category (a "Programs"
# tile with its own list_items() fetch) is a separate, bigger feature
# not part of this fix -- would need its own real verification work,
# not done here.


# v26.07.23.06 (Kaleb's request: save downloaded EPUBs into per-category
# subfolders under LIBRARY_DIR, same pattern as the JW Audio/Videos
# category subfolders -- and "have the library manager check all sub
# folders"). main.py's start_download() checks this optional list
# before using dl_category as a folder name: CATEGORY_WHATS_NEW ("New
# Issues") mixes Watchtower/Awake!/Workbook hits together with no
# single real category behind it (an RSS feed of whatever's newest,
# not a genre/publication-type), so a book downloaded from it stays at
# the LIBRARY_DIR root instead of a misleading "New Issues" folder --
# same "no single stable category" reasoning already used for Search
# Audio/Search Videos staying flat (see main.py's _current_audio_
# source/_current_video_source docstrings). CATEGORY_VIDEOS/
# CATEGORY_AUDIO are never reached here either (they open their own
# dedicated sub-pickers, never list_items(), so dl_category never
# equals them for an EPUB download) but are harmless to list.
CATEGORIES_NO_FOLDER = [CATEGORY_WHATS_NEW]

_PUB_TO_CATEGORY = None  # built lazily, see _pub_category_map() below


def _pub_category_map():
    """v26.07.23.08 (Kaleb's request: "New Issues... should show
    category markers" -- a New Issues hit shouldn't have to stay flat
    just because the BROWSE view mixes categories; the item itself
    already has a real category, we just weren't looking it up).
    Combines STATIC_PUBLICATIONS' and PERIODICALS' own pub->category
    columns into one lookup dict, built once and cached at module
    level -- pure data already defined above, no new source of truth."""
    global _PUB_TO_CATEGORY
    if _PUB_TO_CATEGORY is None:
        m = {pub: cat for pub, _title, _extra, cat in STATIC_PUBLICATIONS}
        m.update({pub: cat for pub, _title, cat in PERIODICALS})
        m["km"] = CATEGORY_KINGDOM_MINISTRY  # not in STATIC_PUBLICATIONS/
        # PERIODICALS -- generated separately by generate_km_back_issues()
        # since it's a closed archive with no current-issue concept.
        m.update({pub: entry.get("category") for pub, entry in _load_discovered_pubs().items()
                   if entry.get("category")})
        _PUB_TO_CATEGORY = m
    return _PUB_TO_CATEGORY


def resolve_item_category(item):
    """Public hook main.py calls ONLY when the currently open category
    is in CATEGORIES_NO_FOLDER (currently just "New Issues") -- looks
    up this specific item's own pub code (item["_pub"], present on
    every item this plugin returns) against the real category mapping,
    so e.g. a Watchtower Study Edition hit still files under "Watchtower
    -- Study Edition" instead of a generic "New Issues" folder (or
    staying flat). Pure local dict lookup, no network call needed --
    unlike Gutenberg's equivalent, which has to fetch a detail page
    since bookshelf/category tags aren't in its list-view response at
    all. Returns None (not a folder-worthy result) for any pub code
    this map doesn't recognize, rather than guessing."""
    pub = item.get("_pub")
    if not pub:
        return None
    return _pub_category_map().get(pub)

# Fixed-code publications that don't need an issue parameter.
# Format: (pub_code, display_title, extra_params_dict_or_None, category)
# extra_params: passed directly to GETPUBMEDIALINKS alongside pub= and
# langwritten=. Some publications (e.g. the plain NWT) need fileformat=EPUB
# explicitly or the API returns a 400 error -- see _resolve_download_url()
# and lookup_pub_code() for the retry logic that handles this.
# ALL codes here were verified LIVE before being added. Titles for the
# codes below sourced from wol.jw.org's official "Abbreviations of
# Publication Titles" page (https://wol.jw.org/en/wol/d/r1/lp-e/1200270068)
# and jw.org's Tracts & Invitations page (https://www.jw.org/en/library/tracts/).
STATIC_PUBLICATIONS = [
    # v26.07.30.09: Books vs Brochures reclassification (Kaleb's
    # request, matching real JW Library app screens -- see the two
    # screenshots he provided). Every entry below was checked live
    # against jw.org's own finder redirect (https://www.jw.org/finder?
    # wtlocale=E&pub=<code> -- follows through to the real canonical
    # /en/library/books/... or /en/library/brochures/... URL), not
    # guessed. Kaleb's own rule of thumb for future additions:
    # brochures run ~30 pages, books 100+. Songbooks ("sjjls") are
    # books per Kaleb's explicit call, even though they're shorter --
    # jw.org's own site doesn't file them as brochures either.
    ("nwt",   "New World Translation", {"fileformat": "EPUB"}, CATEGORY_BIBLES),
    ("bi12",  "New World Translation (1984 Edition)", None, CATEGORY_BIBLES),
    ("lffi",  "Enjoy Life Forever! -- Introductory Bible Lessons", None, CATEGORY_BROCHURES),
    ("lff",   "Enjoy Life Forever! -- An Interactive Bible Course", None, CATEGORY_BOOKS),
    ("sjjls", '"Sing Out Joyfully" to Jehovah', None, CATEGORY_BOOKS),
    ("od",    "Organized to Do Jehovah's Will", None, CATEGORY_BOOKS),
    ("wcg",   "Walk Courageously With God", None, CATEGORY_BOOKS),
    ("lfb",   "Lessons You Can Learn From the Bible", None, CATEGORY_BOOKS),
    ("jy",    "Jesus -- The Way, the Truth, the Life", None, CATEGORY_BOOKS),
    ("cl",    "Draw Close to Jehovah", None, CATEGORY_BOOKS),
    ("rr",    "Pure Worship of Jehovah -- Restored At Last!", None, CATEGORY_BOOKS),
    # -- added per Kaleb's request --
    ("be",    "Benefit From Theocratic Ministry School Education", None, CATEGORY_BOOKS),
    ("cf",    '"Come Be My Follower"', None, CATEGORY_BOOKS),
    ("jd",    "Live With Jehovah's Day in Mind", None, CATEGORY_BOOKS),
    ("ia",    "Imitate Their Faith", None, CATEGORY_BOOKS),
    ("jr",    "God's Word for Us Through Jeremiah", None, CATEGORY_BOOKS),
    ("bt",    '"Bearing Thorough Witness" About God\'s Kingdom', None, CATEGORY_BOOKS),
    ("mbs",   "Memorial Bible Reading Schedule", None, CATEGORY_BROCHURES),
    ("yb11",  "2011 Yearbook of Jehovah's Witnesses", None, CATEGORY_BOOKS),
    ("yb12",  "2012 Yearbook of Jehovah's Witnesses", None, CATEGORY_BOOKS),
    ("yb13",  "2013 Yearbook of Jehovah's Witnesses", None, CATEGORY_BOOKS),
    ("yb14",  "2014 Yearbook of Jehovah's Witnesses", None, CATEGORY_BOOKS),
    ("yb15",  "2015 Yearbook of Jehovah's Witnesses", None, CATEGORY_BOOKS),
    ("yb16",  "2016 Yearbook of Jehovah's Witnesses", None, CATEGORY_BOOKS),
    ("yb17",  "2017 Yearbook of Jehovah's Witnesses", None, CATEGORY_BOOKS),
    # v26.07.15.13 (Kaleb's request -- systematic pass through jw.org's
    # real Books/Brochures library looking for EPUB-available titles not
    # yet in this list): confirmed live via GETPUBMEDIALINKS this
    # session, real pub codes pulled directly from jw.org's own page
    # markup (not guessed). Yearbook itself stopped after 2017,
    # replaced by annual Service Year Reports -- confirmed yb70 through
    # yb10 all 404 (no EPUB ever existed for those, so the existing
    # yb11-yb17 range above was already complete) and syr17-syr21 have
    # real EPUB editions; syr22 onward tried and 404'd (PDF/JWPUB only
    # for the more recent years -- exactly the "not every publication
    # has an EPUB" pattern Kaleb flagged).
    ("syr17",  "2017 Service Year Report of Jehovah's Witnesses Worldwide", None, CATEGORY_BOOKS),
    ("syr18",  "2018 Service Year Report of Jehovah's Witnesses Worldwide", None, CATEGORY_BOOKS),
    ("syr19",  "2019 Service Year Report of Jehovah's Witnesses Worldwide", None, CATEGORY_BOOKS),
    ("syr20",  "2020 Service Year Report of Jehovah's Witnesses Worldwide", None, CATEGORY_BOOKS),
    ("syr21",  "2021 Service Year Report of Jehovah's Witnesses Worldwide", None, CATEGORY_BOOKS),
    ("lvs",   "How to Remain in God's Love", None, CATEGORY_BOOKS),
    ("bhs",   "What Can the Bible Teach Us?", None, CATEGORY_BOOKS),
    # Tried and confirmed NO EPUB this session (PDF/JWPUB only) --
    # listed here, not added above, so a future pass doesn't re-check
    # the same ones: wcgr (References for Walk Courageously With God),
    # scl (Scriptures for Christian Living), it (Insight on the
    # Scriptures), nwtstg (Bible Glossary), syr22/23/24/25.
    # v26.07.15.14 (Kaleb's follow-up -- continuing the systematic
    # pass): tried known/documented JW pub-code conventions for several
    # remaining titles. Two guesses ("rs"=Reasoning From the Scriptures,
    # "kl"=Knowledge That Leads to Everlasting Life, "uw", "dp", "is1",
    # "is2", "re", "yp1", "yp2", "w88", "g88", "kr" -- all either the
    # wrong code or genuinely no EPUB) came back 404 and were NOT
    # added. Two guesses hit real live publications, but NOT the ones
    # originally guessed -- confirmed via the API's own returned pubName
    # before adding, exactly to avoid mislabeling one publication with
    # another's title:
    #   "gt" was guessed as Theocratic Ministry School Guidebook --
    #   wrong guess, but it's actually "The Greatest Man Who Ever
    #   Lived" (confirmed live, real EPUB).
    #   "kt" was a guess for something else entirely -- it's actually
    #   "Would You Like to Know the Truth?" (confirmed live, real
    #   EPUB, older evangelism booklet).
    #   "sp" was guessed as a songbook -- it's actually "Spirits of the
    #   Dead -- Can They Help You or Harm You? Do They Really Exist?"
    #   (confirmed live, real EPUB, a brochure -- see v26.07.30.09
    #   reclassification below when CATEGORY_BOOKS/CATEGORY_BROCHURES
    #   were split apart to match jw.org's own real category split).
    ("bh",    "What Does the Bible Really Teach?", None, CATEGORY_BOOKS),
    ("gt",    "The Greatest Man Who Ever Lived", None, CATEGORY_BOOKS),
    # v26.07.30.09 BUG FIX (Kaleb's question about JW category coverage
    # prompted a live re-check): "kt" was filed under CATEGORY_BOOKS
    # when it was added -- confirmed live via jw.org's own finder
    # redirect that it's actually a TRACT (/en/library/tracts/know-
    # truth-tract/), not a book. Moved.
    ("kt",    "Would You Like to Know the Truth?", None, CATEGORY_TRACTS),
    ("sp",    "Spirits of the Dead -- Can They Help You or Harm You? Do They Really Exist?", None, CATEGORY_BROCHURES),
    # -- added per Kaleb's request, all verified live against
    # GETPUBMEDIALINKS before being added (pub, title, EPUB availability
    # all confirmed via a real API round-trip, not guessed from the
    # download URLs Kaleb supplied) --
    ("lr",    "Learn From the Great Teacher", None, CATEGORY_BOOKS),
    ("my",    "My Book of Bible Stories", None, CATEGORY_BOOKS),
    ("th",    "Apply Yourself to Reading and Teaching", None, CATEGORY_BROCHURES),
    ("rj",    "Return to Jehovah", None, CATEGORY_BROCHURES),
    ("ypq",   "Answers to 10 Questions Young People Ask", None, CATEGORY_BROCHURES),
    ("hf",    "Your Family Can Be Happy", None, CATEGORY_BROCHURES),
    ("yc",    "Teach Your Children", None, CATEGORY_BROCHURES),
    ("mb",    "My Bible Lessons", None, CATEGORY_BROCHURES),
    ("hl",    "How Can You Have a Happy Life?", None, CATEGORY_BROCHURES),
    ("ll",    "Listen to God and Live Forever", None, CATEGORY_BROCHURES),
    ("lc",    "Was Life Created?", None, CATEGORY_BROCHURES),
    ("lf",    "The Origin of Life -- Five Questions Worth Asking", None, CATEGORY_BROCHURES),
    # v26.07.30.15 (Kaleb's request: "find any other brochures, tracts,
    # books or magazines we need to add" -- systematic sweep of jw.org's
    # live Books/Brochures/Tracts/Magazines/Bible pages against this
    # table). Only real finds with confirmed EPUB, both verified live:
    #   "lmd" (Love People--Make Disciples) -- real EPUB, brochure per
    #   finder redirect. "wfg" (Wisdom From the Gospels), "brfi"
    #   (Purple Triangles), "nwtsty" (NWT Study Edition), "scl"
    #   (Scriptures for Christian Living), "wcgr" (References for Walk
    #   Courageously With God), "inv"/"co-inv26" (meeting/convention
    #   invitations) all confirmed live to have NO EPUB (PDF/JWPUB/RTF/
    #   BRL/MP3 only) -- tried, not added. Bible page also checked:
    #   bi10/bi22/by/int/rh all JWPUB-only, no EPUB, not added.
    ("lmd",   "Love People -- Make Disciples", None, CATEGORY_BROCHURES),
    # Tracts -- these are short (a few pages) and jw.org may only offer
    # some of them as PDF rather than EPUB; if a download fails here,
    # that's most likely why (not a bug in this plugin).
    ("t-ftr", "Can We Enjoy Life Forever?", None, CATEGORY_TRACTS),
    ("t-fam", "How Can You Have a Happy Family?", None, CATEGORY_TRACTS),
    ("t-god", "Who Is the True God?", None, CATEGORY_TRACTS),
    ("t-pry", "Is Anyone Listening to Our Prayers?", None, CATEGORY_TRACTS),
    ("t-jss", "Does Jesus' Advice Work Today?", None, CATEGORY_TRACTS),
    ("t-kng", "How Will God's Kingdom Solve Our Problems?", None, CATEGORY_TRACTS),
    ("t-sfr", "Is Living Without Pain or Sadness Possible?", None, CATEGORY_TRACTS),
    ("t-dth", "Will You Ever See Your Loved Ones Who Have Died?", None, CATEGORY_TRACTS),
    ("t-rlg", "Do All Religions Please God?", None, CATEGORY_TRACTS),
    # v26.07.30.15: same sweep as above -- confirmed live real EPUB.
    ("t-36",  "What Is the Kingdom of God?", None, CATEGORY_TRACTS),
    # v26.08.07.06 (Kaleb's report: co-pgm20_E.epub stuck un-migrated).
    # Convention Program codes -- each confirmed LIVE against
    # GETPUBMEDIALINKS before adding, exact pubName used verbatim, not
    # guessed. co-pgm17 and co-pgm23 were also checked and are genuine
    # 404s (no EPUB for those years) -- correctly NOT added, matches
    # jw.org's own real availability rather than assuming a full range.
    ("co-pgm18", "2018 Convention Program", None, CATEGORY_PROGRAMS),
    ("co-pgm19", "2019 Convention Program", None, CATEGORY_PROGRAMS),
    ("co-pgm20", "2020 Convention Program", None, CATEGORY_PROGRAMS),
    ("co-pgm21", "2021 Convention Program", None, CATEGORY_PROGRAMS),
    ("co-pgm22", "2022 Convention Program", None, CATEGORY_PROGRAMS),
]

# Periodicals that need an `issue=YYYYMM` parameter.
# For these, we try the RSS feed first (most accurate), then fall back to
# a same-month guess via current_issue_guess(). The daily text (es) is a
# special case: its code is year-specific (es26 for 2026, es27 for 2027)
# rather than using an issue parameter, so it's handled separately below.
# Format: (pub_code, display_title, category)
# "wp" (public Watchtower) and "g" (Awake!) confirmed live on jw.org's own
# magazines page (https://www.jw.org/en/library/magazines/) -- both now
# publish only ~1x/year (public Watchtower reduced to 1 issue/year as of
# 2022; Awake! has published irregularly, ~1x/year, for a while).
#
# Historical EPUB availability (verified live against GETPUBMEDIALINKS,
# not guessed): "w" and "mwb" resolve for issue=YYYYMM back to January
# 2016 (w_E_201601, mwb_E_201601 both confirmed) but 404 for 2015 and
# earlier (w_E_201501, w_E_201510, w_E_201512, mwb_E_201512 all tried and
# failed) -- EPUB format for these two periodicals doesn't appear to
# exist before 2016. "g" and "wp" issue dates can't be reliably guessed
# at all (their real publish months are irregular) -- use the manual
# pub-code entry (Y Enter Code) with a specific known issue instead of
# relying on the "this month, guess" fallback for those two.
PERIODICALS = [
    ("w",   "Watchtower -- Study Edition", CATEGORY_WATCHTOWER_STUDY),
    ("wp",  "Watchtower -- Public Edition", CATEGORY_WATCHTOWER_PUBLIC),
    ("g",   "Awake!", CATEGORY_AWAKE),
    ("mwb",  "Meeting Workbook", CATEGORY_WORKBOOKS),
    # "mwbr" (found on jw.org's Meeting Workbooks library page) could NOT
    # be verified live -- tried 8+ plausible issue=YYYYMM guesses against
    # the real GETPUBMEDIALINKS API (including current/recent months) and
    # every one 404'd. Either it needs a different issue-code convention
    # than mwb, or it isn't downloadable this way at all. Left commented
    # out until confirmed -- this catalog's own standard is "verified
    # LIVE before being added," and this doesn't meet that bar yet.
    # ("mwbr", "References for Life and Ministry Meeting Workbook", CATEGORY_WORKBOOKS),
    # v26.08.03.07 BUG FIX (found as a side effect of testing publication
    # auto-discovery, not by inspection): this was filed under
    # CATEGORY_BOOKS -- confirmed live via jw.org's own finder redirect
    # (finder?pub=es20 -> /en/library/BROCHURES/Examining-the-Scriptures-
    # Daily-2020/) that the real category is Brochures, not Books.
    ("es",  "Examining the Scriptures Daily (current year)", CATEGORY_BROCHURES),
]

# v26.08.03.07 (Kaleb: "if you find anything... add them so there's less
# fetching"): six real past-year "Examining the Scriptures Daily"
# brochures found via check_new_publications()'s live library-page scan,
# confirmed to have real EPUBs via GETPUBMEDIALINKS, hand-promoted here
# from the discovered-pubs cache so the app doesn't need to re-discover
# them every check. The CURRENT year stays on PERIODICALS' own dynamic
# "es" entry above (current_year_es_code()) -- these are specifically
# the years that entry can't reach.
STATIC_PUBLICATIONS += [
    ("es25", "Examining the Scriptures Daily\u20142025", None, CATEGORY_BROCHURES),
    ("es24", "Examining the Scriptures Daily\u20142024", None, CATEGORY_BROCHURES),
    ("es23", "Examining the Scriptures Daily\u20142023", None, CATEGORY_BROCHURES),
    ("es22", "Examining the Scriptures Daily\u20142022", None, CATEGORY_BROCHURES),
    ("es21", "Examining the Scriptures Daily\u20142021", None, CATEGORY_BROCHURES),
    ("es20", "Examining the Scriptures Daily\u20142020", None, CATEGORY_BROCHURES),
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_json(url):
    """Fetch a URL and parse the response as JSON.
    Raises urllib.error.URLError, TimeoutError, ValueError, or OSError --
    callers handle these. Same pattern as gutenberg_fetch.py."""
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _extract_epub(data):
    """Pull the first EPUB entry out of a GETPUBMEDIALINKS response.

    The API response structure is:
      data["files"][LANG]["EPUB"] -> list of file objects
    Each file object has a ["file"]["url"] we can download.
    Returns None if the path doesn't exist or the list is empty -- the
    caller decides what to do (usually retry with fileformat=EPUB)."""
    try:
        epubs = data["files"][LANG]["EPUB"]
    except (KeyError, TypeError):
        return None
    if not epubs:
        return None
    return epubs[0]


def _wp_valid_issue(issue):
    """Rounds an arbitrary YYYYMM guess down to the nearest ACTUAL valid
    Public Watchtower issue month, using the same era rules
    generate_wp_back_issues() models (bi-monthly 2016+, tri-annual
    2018+, annual-with-irregular-month 2022+ per WP_ANNUAL_ISSUES).
    Needed for the same reason _mwb_valid_issue() is: current_issue_
    guess() just returns "this calendar month", which is wrong for wp
    almost every month once it went annual with a hard-coded, irregular
    per-year month. If the current year's issue isn't in WP_ANNUAL_
    ISSUES yet (not published/confirmed), falls back to the most recent
    year that IS in the table."""
    y, m = int(issue[:4]), int(issue[4:6])
    if (y, m) >= WP_ANNUAL_START:
        # v26.07.15.02 BUG FIX (Kaleb's report -- 2025/2026 wp missing):
        # this used to require the CALENDAR month to have reached
        # WP_ANNUAL_ISSUES[y] before trusting that year's entry (e.g.
        # wouldn't use 2026:9 until the calendar hit September 2026).
        # That's wrong: WP_ANNUAL_ISSUES entries are only ever added
        # after being individually confirmed live (see comment above
        # the dict), so presence in the table already means the EPUB
        # exists NOW, regardless of calendar month -- confirmed live
        # 2026-07: issue=202609 (Sept 2026, "next" year-row) already
        # resolves via GETPUBMEDIALINKS today, months before September.
        # Same root cause as mwb's v26.07.09.14 fix: JW.org publishes
        # periodicals genuinely ahead of the calendar.
        if y in WP_ANNUAL_ISSUES:
            return f"{y}{WP_ANNUAL_ISSUES[y]:02d}"
        # v26.07.30.11 (Kaleb: "built in month checker... update a JSON
        # list" -- so this table stops needing a manual edit every
        # year): before falling back to the last KNOWN year, try a
        # live probe/cache lookup for the actual current year first.
        # WP_ANNUAL_ISSUES stays as-is for years already confirmed
        # (zero network cost); only a genuinely new, not-yet-in-the-
        # table year triggers this.
        probed = _get_annual_issue("wp", y)
        if probed:
            return probed
        candidates = [yy for yy in WP_ANNUAL_ISSUES if yy < y]
        py = max(candidates) if candidates else max(WP_ANNUAL_ISSUES)
        return f"{py}{WP_ANNUAL_ISSUES[py]:02d}"
    elif (y, m) >= WP_TRIANNUAL_START:
        for mm in (9, 5, 1):
            if m >= mm:
                return f"{y}{mm:02d}"
        return f"{y - 1}09"
    else:
        if m % 2 == 0:
            m -= 1  # always valid: m was 2-12 (even), so m-1 is 1-11 (odd)
        return f"{y}{m:02d}"


def _g_valid_issue(_issue=None):
    """Best available guess for Awake!'s current issue. Unlike mwb/wp,
    there's no formula to derive this from -- Awake! now publishes
    roughly once a year at an irregular month with no pattern (see
    AWAKE_BACK_ISSUES) -- so current_issue_guess()'s calendar-month
    guess would be wrong almost every month of the year. Ignores its
    argument; kept for the same call signature as _mwb_valid_issue()/
    _wp_valid_issue() so all three can be dispatched identically.

    v26.07.30.13 BUG FIX (Kaleb: "if it doesn't have the last five
    years worth, will it check those too?" -- testing that surfaced a
    real bug in the v26.07.30.11 version of this function): the
    original only ever checked the SINGLE current calendar year --
    when that year hasn't published yet (the normal case for most of
    the year), it fell straight back to AWAKE_BACK_ISSUES[0], silently
    skipping any INTERMEDIATE years that might already be missing from
    the static table (confirmed via a deliberate gap simulation: with
    2023-2025 artificially removed, this returned 2022's issue instead
    of correctly finding 2025's). Now walks backward from the current
    year down to (but not including) the newest static-table year,
    returning the first one that actually resolves -- correctly finds
    the true newest real issue regardless of how many trailing years
    are missing from the table, capped defensively at 24 years back."""
    newest_known_year = int(AWAKE_BACK_ISSUES[0][0][:4])
    cur_year = int(time.strftime("%Y"))
    for yy in range(cur_year, max(newest_known_year, cur_year - 24), -1):
        probed = _get_annual_issue("g", yy)
        if probed:
            return probed
    return AWAKE_BACK_ISSUES[0][0]



def current_issue_guess():
    """This month as YYYYMM -- a fallback issue code for periodicals when
    the RSS feed can't be reached. JW.org typically publishes a month or
    two ahead of the calendar, so this guess may be one issue behind the
    actual latest. check_new_issues() via RSS is preferred when available."""
    return time.strftime("%Y%m")


def current_year_es_code():
    """Returns the pub code for this year's daily text booklet.
    The pattern (confirmed live) is "es" + 2-digit year: es26 for 2026,
    es27 for 2027, etc. Unlike other periodicals, this doesn't use an
    issue= parameter -- the year is baked into the pub code itself."""
    return "es" + time.strftime("%y")


# Earliest confirmed-live EPUB issue for "w" (Study Watchtower) -- see the
# PERIODICALS comment above: w_E_201601 confirmed reachable, w_E_201512
# confirmed 404. Safe to generate every month from here to "now" because
# "w" has published monthly with NO gaps or frequency changes across this
# entire range (confirmed live).
EARLIEST_MONTHLY_ISSUE = (2016, 1)

# Awake! ("g") had an EARLIER monthly era too, before the 2016+ frequency
# changes AWAKE_BACK_ISSUES hard-codes -- confirmed live, EVERY month
# individually checked against GETPUBMEDIALINKS (not spot-checked), per
# Kaleb's request to go back to 2011. Aug 2011 and earlier: 404 (EPUB
# doesn't exist). Sept 2011 through Dec 2015: HTTP 200 with a real EPUB
# file present for all 52 consecutive months, zero gaps -- genuinely
# safe for the same monthly-generator approach "w" uses, unlike the
# irregular 2016+ era. Jan 2016 onward is where AWAKE_BACK_ISSUES's
# hard-coded list picks up, so this era ends at Dec 2015 to avoid
# overlapping it.
AWAKE_MONTHLY_START = (2011, 9)
AWAKE_MONTHLY_END = (2015, 12)

# Pubs safe for generate_monthly_back_issues() -- i.e. confirmed monthly
# with zero gaps/frequency changes since EARLIEST_MONTHLY_ISSUE. Maps
# pub code -> display title. "mwb" is deliberately NOT here -- it
# changed frequency in 2021 (see generate_mwb_back_issues() below) and
# needs its own generator. Do NOT add "g"/"wp" either without first
# confirming their exact per-year issue months (count/year alone isn't
# enough -- see MANUAL_CODE_HINT/GOTCHA above for why).
MONTHLY_BACK_ISSUE_PUBS = {
    "w": "Watchtower -- Study Edition",
}

# Awake! ("g") back issues, 2016-2025 -- hard-coded, NOT generated, because
# Awake!'s publishing frequency changed twice in this range (see the
# BACK-ISSUES note in the module docstring above for the full history).
# Every (issue, title) pair below was individually confirmed live against
# GETPUBMEDIALINKS (HTTP 200 + a real EPUB file present in the response)
# before being added -- same verification bar as STATIC_PUBLICATIONS.
# Topic titles sourced from jw.org's own magazine library pages
# (jw.org/en/library/magazines/awake-noN-YYYY-month/) to match each
# issue number to its real subject.
# Newest first. To add a new issue when one is released:
#   1) find its real month from jw.org/en/library/magazines/
#   2) confirm issue=YYYYMM returns HTTP 200 with an EPUB file via
#      GETPUBMEDIALINKS (same two-step check used for every row here)
#   3) only then add the row below.
AWAKE_BACK_ISSUES = [
    ("202611", "No. 1 2026 -- What You Can Do About Loneliness"),
    ("202511", "No. 1 2025 -- Coping With Rising Prices"),
    ("202411", "No. 1 2024 -- What Has Happened to Respect?"),
    ("202311", "No. 1 2023 -- Can Our Planet Survive?--Reasons for Hope"),
    ("202207", "No. 1 2022 -- A World in Turmoil--How You Can Cope"),
    ("202111", "No. 3 2021 -- Should You Believe in a Creator?--You Decide"),
    ("202107", "No. 2 2021 -- Technology--Your Master or Your Servant?"),
    ("202103", "No. 1 2021 -- Wisdom for Life and Happiness"),
    ("202011", "No. 3 2020 -- Is There a Cure for Prejudice?"),
    ("202007", "No. 2 2020 -- 5 Questions About Suffering Answered"),
    ("202003", "No. 1 2020 -- Find Relief From Stress"),
    ("201911", "No. 3 2019 -- Can the Bible Make Your Life Better?"),
    ("201907", "No. 2 2019 -- Six Lessons Children Need to Learn"),
    ("201903", "No. 1 2019 -- Will We Ever Feel Safe and Secure?"),
    ("201811", "No. 3 2018 -- Help for Those Who Grieve"),
    ("201807", "No. 2 2018 -- 12 Secrets of Successful Families"),
    ("201803", "No. 1 2018 -- The Way of Happiness"),
    ("201712", "No. 6 2017 -- Is the World out of Control?"),
    ("201710", "No. 5 2017 -- When Disaster Strikes"),
    ("201708", "No. 4 2017 -- Are You Doing Too Much?"),
    ("201706", "No. 3 2017 -- Is the Bible Really From God?"),
    ("201704", "No. 2 2017 -- What Is Behind the Supernatural?"),
    ("201702", "No. 1 2017 -- Teen Depression--Why? What Can Help?"),
    ("201612", "No. 6 2016 -- Disease--How to Reduce the Risk"),
    ("201610", "No. 5 2016 -- Did Jesus Really Exist?"),
    ("201608", "No. 4 2016 -- How to Harness Your Habits"),
    ("201606", "No. 3 2016 -- Breaking the Language Barrier"),
    ("201604", "No. 2 2016 -- Is the Bible Just a Good Book?"),
    ("201602", "No. 1 2016 -- Attitude Makes a Difference!"),
]


def _month_range_desc(start_year, start_month, end_year, end_month):
    """Yields (year, month) tuples from (end_year, end_month) back down to
    (start_year, start_month) inclusive, descending (newest first) -- the
    order back-issue lists should display in."""
    y, m = end_year, end_month
    while (y, m) >= (start_year, start_month):
        yield (y, m)
        m -= 1
        if m == 0:
            m = 12
            y -= 1


WATCHTOWER_MONTHLY_START = (2011, 9)
WATCHTOWER_MONTHLY_END = (2015, 12)
W_DAY = 15   # Study Watchtower ("w") always used day 15 pre-2016
WP_DAY = 1   # Public Watchtower ("wp") always used day 1 pre-2016


_MONTHS_FULL = ["January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November", "December"]


def _periodical_item(pub, title, issue):
    """v26.08.21.09 (duplicate-code consolidation -- jw_fetch.py
    periodical-item builder, Kaleb's explicit go-ahead after reviewing
    the risk/value tradeoff). The subtitle/filename/_pub/_extra shape
    was copy-pasted identically across ~14 sites building periodical
    back-issue dicts (Watchtower Study/Public, Awake!, Our Kingdom
    Ministry, across both their bounded pre-2016/audio-only eras and
    their open-ended 2016+ eras). This is the ATOMIC piece: given an
    already-decided title and issue CODE STRING, builds the dict the
    exact same way every site already did by hand. Guarantees these 4
    fields can never drift or be forgotten when a future era/pub is
    added -- the single highest-value protection this consolidation
    gives, since a missed _extra or a mistyped filename template
    wouldn't be an obvious bug (JW.org's API would just 404 quietly,
    same failure mode as any other wrong pub code -- see this file's
    live-verification discipline elsewhere)."""
    return {
        "title":    title,
        "subtitle": f"pub: {pub}  issue: {issue}",
        "filename": f"{pub}_{LANG}_{issue}.epub",
        "_pub":     pub,
        "_extra":   {"issue": issue},
    }


def _monthly_periodical_item(pub, title_base, y, m, day=None):
    """v26.08.21.09: convenience wrapper over _periodical_item() for
    the common "title_base (Month Year)" case. day=None builds a
    month-only YYYYMM issue code (the 2016+ era convention); a real
    day value (W_DAY/WP_DAY) builds YYYYMMDD, matching each pre-2016/
    audio-only era's own confirmed real GETPUBMEDIALINKS format."""
    issue = f"{y}{m:02d}{day:02d}" if day is not None else f"{y}{m:02d}"
    return _periodical_item(pub, f"{title_base} ({_MONTHS_FULL[m - 1]} {y})", issue)


def generate_w_pre2016_issues():
    """Study Watchtower ("w") back-issue list for its pre-2016 era, Sept
    2011 through Dec 2015 -- Kaleb's correction: the original v0.1.159
    check tested the WRONG issue-code format for this era (YYYYMM,
    month-only, same as the 2016+ format) and got 100% 404, wrongly
    concluding EPUB didn't exist before 2016. Kaleb supplied a real
    working URL (w_E_20151215.epub) that revealed the actual pre-2016
    format is DAY-based (YYYYMMDD), always the 15th for the Study
    edition. Re-verified EVERY month 2011-2015 with this corrected
    format (not spot-checked): Aug 2011 and earlier still 404, but Sept
    2011 through Dec 2015 all HTTP 200 with a real EPUB, 52 consecutive
    months, zero gaps -- same clean monthly range as Awake!'s. Confirmed
    the Jan 2016 boundary is clean too: 20160115 (day-based) 404s, while
    201601 (month-only, the existing 2016+ format) succeeds -- no
    overlap between the two eras."""
    return [_monthly_periodical_item("w", "Watchtower -- Study Edition", y, m, day=W_DAY)
            for y, m in _month_range_desc(WATCHTOWER_MONTHLY_START[0], WATCHTOWER_MONTHLY_START[1],
                                           WATCHTOWER_MONTHLY_END[0], WATCHTOWER_MONTHLY_END[1])]


def generate_wp_pre2016_issues():
    """Public Watchtower ("wp") back-issue list for its pre-2016 era --
    same era/correction as generate_w_pre2016_issues() above, but always
    day 1 instead of day 15 (confirmed independently, same method: every
    month 2011-2015 checked live, Sept 2011-Dec 2015 all HTTP 200 with
    day=01, zero gaps, Jan 2016 boundary clean)."""
    return [_monthly_periodical_item("wp", "Watchtower -- Public Edition", y, m, day=WP_DAY)
            for y, m in _month_range_desc(WATCHTOWER_MONTHLY_START[0], WATCHTOWER_MONTHLY_START[1],
                                           WATCHTOWER_MONTHLY_END[0], WATCHTOWER_MONTHLY_END[1])]


def generate_awake_monthly_issues():
    """Awake! ("g") back-issue list for its EARLIER confirmed-monthly era,
    Sept 2011 through Dec 2015 (see AWAKE_MONTHLY_START/END comment) --
    a separate, bounded range from generate_monthly_back_issues() since
    that one is open-ended (no END month) and only "w" uses it. Uses
    plain "Awake! (Month Year)" titles, not the custom per-issue
    cover-story titles AWAKE_BACK_ISSUES (2016+) has, since this earlier
    era doesn't need one -- it's genuinely one issue every month, no
    irregular "No. N" numbering to disambiguate."""
    return [_monthly_periodical_item("g", "Awake!", y, m)
            for y, m in _month_range_desc(AWAKE_MONTHLY_START[0], AWAKE_MONTHLY_START[1],
                                           AWAKE_MONTHLY_END[0], AWAKE_MONTHLY_END[1])]


# ---------------------------------------------------------------------------
# AUDIO-ONLY back-issue eras (2008-2011) -- deliberately separate from
# the EPUB-tied generators above
# ---------------------------------------------------------------------------
# v26.08.05.10 (Kaleb's request: extend the Watchtower/Public Watchtower/
# Awake! AUDIO back-issue pickers under Publications as far back as real
# audio actually goes -- these are pure audio browsing, no EPUB needed,
# so they can reach further back than "Listen to this Book" or the EPUB
# Download Browse screens ever could, both of which are hard-floored at
# Sept 2011 by real EPUB non-existence, confirmed exhaustively earlier
# this project). Exhaustively probed EVERY month (not spot-checked),
# Jan 2005 through Aug 2011, against GETPUBMEDIALINKS for all three
# pubs, before writing any of this:
#   2005-2007: confirmed 100% no audio, all three pubs, no exceptions.
#   2008-2009: confirmed 100% audio present, all 12 months, all three
#     pubs, zero gaps -- safe to generate unconditionally.
#   2010: confirmed BROKEN/spotty for all three (w: 0/12 months; wp:
#     1/12, February only; g: 0/12) -- excluded entirely. A single
#     real hit surrounded by eleven real misses isn't a pattern worth
#     modeling, and guessing which (if any) other months might also
#     secretly work isn't this project's style -- left out rather than
#     guessed at.
#   2011 Jan-Aug (the months before the existing Sept 2011 boundary):
#     confirmed clean for w and wp (12/12 for the full year, including
#     these earlier months); g is missing exactly June 2011 (confirmed
#     twice, not a one-off network blip) -- included with that single
#     month explicitly excluded rather than assumed clean like the rest.
AUDIO_EARLY_ERA_YEARS = (2009, 2008)  # descending (newest first)
G_2011_AUDIO_GAP_MONTHS = {6}  # June 2011 confirmed no Awake! audio


def generate_w_early_era_audio_issues():
    """Study Watchtower AUDIO back-issues for 2008-2009 plus Jan-Aug
    2011 -- see the AUDIO-ONLY era comment block above for exactly how
    each month was confirmed. Kept separate from generate_w_pre2016_
    issues() (that one's range is genuinely tied to EPUB availability,
    confirmed 100% absent before Sept 2011; this is audio-only, no
    EPUB dependency, so it safely reaches further back)."""
    # v26.08.05.11 BUG FIX (caught by this function's own picker
    # producing "January 2011" as its oldest-displayed entry instead
    # of "January 2008" -- all 32 real entries WERE present, just in
    # the wrong overall order): 2011 is newer than 2008-2009, so it
    # must come FIRST to keep the whole list genuinely newest-to-
    # oldest -- this order must NOT be swapped.
    items = [_monthly_periodical_item("w", "Watchtower -- Study Edition", 2011, m, day=W_DAY)
             for m in range(8, 0, -1)]
    items += [_monthly_periodical_item("w", "Watchtower -- Study Edition", y, m, day=W_DAY)
              for y in AUDIO_EARLY_ERA_YEARS for m in range(12, 0, -1)]
    return items


def generate_wp_early_era_audio_issues():
    """Public Watchtower AUDIO back-issues for 2008-2009 plus Jan-Aug
    2011 -- same era/confirmation as generate_w_early_era_audio_issues()
    above, but day=1 (WP_DAY) instead of day=15, same convention as
    generate_wp_pre2016_issues() already uses for its own (EPUB-tied,
    Sept-2011-onward) range."""
    items = [_monthly_periodical_item("wp", "Watchtower -- Public Edition", 2011, m, day=WP_DAY)
             for m in range(8, 0, -1)]
    items += [_monthly_periodical_item("wp", "Watchtower -- Public Edition", y, m, day=WP_DAY)
              for y in AUDIO_EARLY_ERA_YEARS for m in range(12, 0, -1)]
    return items


def generate_g_early_era_audio_issues():
    """Awake! AUDIO back-issues for 2008-2009 plus Jan-Aug 2011 (minus
    June 2011, the one confirmed real gap in that stretch -- see
    G_2011_AUDIO_GAP_MONTHS above). Plain YYYYMM, same convention as
    generate_awake_monthly_issues() already uses for its own range."""
    items = [_monthly_periodical_item("g", "Awake!", 2011, m)
             for m in range(8, 0, -1) if m not in G_2011_AUDIO_GAP_MONTHS]
    items += [_monthly_periodical_item("g", "Awake!", y, m)
              for y in AUDIO_EARLY_ERA_YEARS for m in range(12, 0, -1)]
    return items


KM_FIRST_EPUB_ISSUE = (2012, 1)
KM_LAST_EPUB_ISSUE = (2015, 12)


def generate_km_back_issues():
    """v26.07.30.09 (Kaleb's request, matching real JW Library app):
    "Our Kingdom Ministry" (pub "km") back-issue list. Unlike w/mwb/wp/
    g, this is a CLOSED archive with no current issue -- confirmed live
    against GETPUBMEDIALINKS: issue=201101 and earlier -> PDF/JWPUB
    only, no EPUB; issue=201201 through 201512 -> real EPUB editions,
    every month checked has one; issue=201601 and later -> 404
    (replaced by the Meeting Workbook, CATEGORY_WORKBOOKS, starting
    2016). No current_issue_guess()/RSS involvement needed or
    appropriate here -- this deliberately does NOT follow the w/mwb/wp/
    g pattern of a "latest known" entry, since there isn't one."""
    return [_monthly_periodical_item("km", "Our Kingdom Ministry", y, m)
            for y, m in _month_range_desc(KM_FIRST_EPUB_ISSUE[0], KM_FIRST_EPUB_ISSUE[1],
                                           KM_LAST_EPUB_ISSUE[0], KM_LAST_EPUB_ISSUE[1])]


def generate_monthly_back_issues(pub, newest_issue=None):
    """Full back-issue list, one per month, from EARLIEST_MONTHLY_ISSUE
    (Jan 2016) up to newest_issue (defaults to this month via
    current_issue_guess() if not given -- pass the RSS-confirmed issue
    from check_new_issues() when available for accuracy).
    pub must be a key in MONTHLY_BACK_ISSUE_PUBS ("w" currently) --
    raises ValueError otherwise, since this generation strategy is only
    safe for pubs confirmed monthly with no gaps (see comment above
    MONTHLY_BACK_ISSUE_PUBS)."""
    if pub not in MONTHLY_BACK_ISSUE_PUBS:
        raise ValueError(f"generate_monthly_back_issues: {pub!r} is not confirmed "
                          f"monthly-safe (only {sorted(MONTHLY_BACK_ISSUE_PUBS)} are)")
    title_base = MONTHLY_BACK_ISSUE_PUBS[pub]
    if newest_issue:
        ny, nm = int(newest_issue[:4]), int(newest_issue[4:6])
    else:
        guess = current_issue_guess()
        ny, nm = int(guess[:4]), int(guess[4:6])
    return [_monthly_periodical_item(pub, title_base, y, m)
            for y, m in _month_range_desc(EARLIEST_MONTHLY_ISSUE[0], EARLIEST_MONTHLY_ISSUE[1], ny, nm)]


# Meeting Workbook ("mwb") frequency CHANGED in 2021 -- Kaleb caught this
# after testing: it was NOT monthly the whole way back to 2016 like "w"
# is. Live-verified directly against GETPUBMEDIALINKS (not guessed):
#   2016-01 through 2020-12: every month has a real issue (12/year).
#   2021-01 onward: each workbook spans TWO months -- only odd months
#     (Jan/Mar/May/Jul/Sep/Nov) have a real issue; even months 404
#     (spot-checked 202102/202104/202106/202108/202110/202112, all 404,
#     and 202202/202204/202402 also 404, confirming the pattern holds
#     through at least 2024). The transition is a clean year boundary --
#     202101 is odd/real, 202012 (the month before) is real too (still
#     in the monthly era).
# generate_monthly_back_issues() would have generated a bogus even-month
# entry for every year 2021+ that 404s if selected -- this dedicated
# generator models both eras correctly instead.
MWB_BIMONTHLY_START = (2021, 1)


def _mwb_valid_issue(issue):
    """Rounds an arbitrary YYYYMM guess down to the nearest valid Meeting
    Workbook issue month -- i.e. in the bi-monthly era (2021+, see
    MWB_BIMONTHLY_START) an even month isn't a real issue, so step back
    one month to the preceding (valid, odd) one. Needed because
    current_issue_guess() just returns "this calendar month", which is
    wrong for mwb roughly half the time since the 2021 frequency change."""
    y, m = int(issue[:4]), int(issue[4:6])
    if (y, m) >= MWB_BIMONTHLY_START and m % 2 == 0:
        m -= 1  # always valid: m was 2-12 (even), so m-1 is 1-11 (odd), same year
    return f"{y}{m:02d}"


def _w_probe_furthest_available(months_ahead=6):
    """v26.07.30.10 (Kaleb: "I want our app to always be on the same
    page for new releases" -- investigating that led to finding a real
    bug, see list_items()'s Step 3/4 fix comment). "w" is monthly with
    no parity quirks, so this is the same idea as _mwb_probe_furthest_
    available() just above but stepping one month at a time instead of
    two. Used as the fallback truth-source when check_new_issues()'s
    RSS feed doesn't currently have a "w" entry at all -- same
    reasoning as the mwb probe: a real published issue can exist
    before the RSS feed's rolling window happens to mention it.
    Bounded to at most `months_ahead` real network requests."""
    guess = current_issue_guess()
    y, m = int(guess[:4]), int(guess[4:6])
    latest_confirmed = None
    for _ in range(months_ahead + 1):
        issue = f"{y}{m:02d}"
        params = {"pub": "w", "langwritten": LANG, "issue": issue, "output": "json"}
        try:
            data = _get_json(API_BASE + "?" + urllib.parse.urlencode(params))
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            break
        if not _extract_epub(data):
            break
        latest_confirmed = issue
        m += 1
        if m > 12:
            m = 1
            y += 1
    return latest_confirmed


def _mwb_probe_furthest_available(months_ahead=6):
    """v26.07.23.31 (Kaleb's request: "meeting workbooks are missing...
    we need to create a check for all future issues of the next six
    months in advance. Because currently we have the whole years
    workbooks released"). Confirmed live (July 23, 2026): check_new_
    issues()'s RSS feed had ZERO "mwb" entries that day at all (only a
    Watchtower one), so generate_mwb_back_issues() fell all the way
    back to the bare calendar guess -- which only reached July 2026.
    But September AND November 2026 were BOTH already real, live,
    downloadable EPUBs on jw-cdn.org at that exact same moment (checked
    directly against GETPUBMEDIALINKS, not assumed) -- JW.org evidently
    publishes mwb issues well ahead of both the calendar and the RSS
    feed noticing them. There's no real mediator category for EPUB
    publications the way there is for audio/video (confirmed live --
    every reasonable category-key guess for Meeting Workbooks 404'd;
    that API is audio/video-only, publications use the separate
    pub-code-keyed GETPUBMEDIALINKS lookup instead, which has no
    "browse this publication's whole catalog" capability of its own),
    so there's nothing to switch to there -- this probe is the fix.

    Rather than trust the RSS feed OR a bare calendar guess, this
    actively CHECKS each real bi-monthly issue slot (odd months only,
    starting from the calendar-guess-corrected "now") directly against
    GETPUBMEDIALINKS -- the same live-availability mechanism every
    other pub-code lookup in this file already uses -- continuing as
    long as issues keep being found, up to `months_ahead` months past
    today. Returns the LATEST confirmed-available issue code (YYYYMM),
    or None if even today's own calendar-guess issue isn't live yet
    (e.g. genuinely offline -- caller should fall back to the RSS/
    calendar-guess chain as before in that case).

    A real "not yet published" issue returns HTTP 200 with a JSON LIST
    containing a {"status": 404} error object (confirmed live, NOT a
    dict shaped like a real hit) -- _extract_epub()'s existing try/
    except (KeyError, TypeError) already handles that shape safely
    without any special-casing needed here.

    Bounded to at most ~months_ahead/2 + 1 real network requests (bi-
    monthly = one real issue slot per 2 calendar months) -- a small,
    fixed number of GETPUBMEDIALINKS calls, not an unbounded probe."""
    guess = _mwb_valid_issue(current_issue_guess())
    y, m = int(guess[:4]), int(guess[4:6])
    latest_confirmed = None
    max_checks = (months_ahead // 2) + 1
    for _ in range(max_checks):
        issue = f"{y}{m:02d}"
        params = {"pub": "mwb", "langwritten": LANG, "issue": issue, "output": "json"}
        try:
            data = _get_json(API_BASE + "?" + urllib.parse.urlencode(params))
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            break  # network issue -- stop, use whatever was already confirmed
        if not _extract_epub(data):
            break  # first miss -- this issue isn't published yet, stop probing further ahead
        latest_confirmed = issue
        m += 2  # advance to the next bi-monthly slot
        if m > 12:
            m -= 12
            y += 1
    return latest_confirmed


def generate_mwb_back_issues(newest_issue=None):
    """Full Meeting Workbook back-issue list, monthly from Jan 2016
    through Dec 2020, then odd-months-only (bi-monthly) from Jan 2021
    onward -- see MWB_BIMONTHLY_START comment above for why. newest_issue
    defaults to a real live-availability probe (see _mwb_probe_furthest_
    available()'s own docstring) if not given, falling back to the RSS-
    confirmed latest (check_new_issues()), then a parity-corrected
    calendar guess, only if the probe itself can't reach the network.

    v26.07.09.14 BUG FIX (Kaleb's report -- missing 2026 workbooks /
    "guess latest issue" seemed broken): this used to default straight to
    raw current_issue_guess() with NO correction at all, even though
    _mwb_valid_issue() already existed for exactly this. Confirmed live:
    current_issue_guess() returned 202607 while check_new_issues() (RSS)
    confirmed 202611 was the real latest -- JW.org publishes issues
    genuinely months ahead of the calendar, not just the +-1 parity
    _mwb_valid_issue() alone corrects for.

    v26.07.23.31 BUG FIX (Kaleb's report -- "meeting workbooks are
    missing... we have the whole year's workbooks released"): the RSS-
    first fallback chain above wasn't enough either -- confirmed live
    the RSS feed can go through periods with ZERO "mwb" entries at all
    (only reporting OTHER periodicals like Watchtower), silently
    dropping this function all the way back to the bare calendar guess
    even though real, live, already-published issues existed 2-4
    months further ahead. Live GETPUBMEDIALINKS availability (the real
    source of truth, not an announcement feed that may or may not have
    noticed yet) is now tried FIRST -- RSS and the calendar guess are
    still kept as fallbacks for when the network genuinely can't be
    reached at all, same graceful-degradation spirit as everywhere else
    in this file."""
    if newest_issue:
        ny, nm = int(newest_issue[:4]), int(newest_issue[4:6])
    else:
        probed = _mwb_probe_furthest_available()
        if probed:
            guess = probed
        else:
            rss_hit = next((issue for pub, _t, issue in check_new_issues() if pub == "mwb"), None)
            guess = rss_hit or _mwb_valid_issue(current_issue_guess())
        ny, nm = int(guess[:4]), int(guess[4:6])
    items = []
    for y, m in _month_range_desc(EARLIEST_MONTHLY_ISSUE[0], EARLIEST_MONTHLY_ISSUE[1], ny, nm):
        if (y, m) >= MWB_BIMONTHLY_START and m % 2 == 0:
            continue  # even month in the bi-monthly era -- not a real issue
        items.append(_monthly_periodical_item("mwb", "Meeting Workbook", y, m))
    return items


# Public Watchtower ("wp") back-issue eras -- see BACK-ISSUES note in the
# module docstring for the full history and how each boundary/month was
# confirmed. Three distinct eras, oldest to newest:
WP_BIMONTHLY_START = (2016, 1)   # odd months only: Jan/Mar/May/Jul/Sep/Nov
WP_TRIANNUAL_START = (2018, 1)   # Jan/May/Sep only
WP_ANNUAL_START = (2022, 1)      # 1/year, month varies -- see table below

# One issue per year from 2022 on -- month is irregular (like Awake!'s
# "No. 1" issue), so it can't be derived and must be hard-coded. Each
# entry individually confirmed live via GETPUBMEDIALINKS before being
# added, same bar as AWAKE_BACK_ISSUES. To add a new year: find the month
# from jw.org/en/library/magazines/, confirm issue=YYYYMM returns a real
# EPUB, then add the row.
WP_ANNUAL_ISSUES = {
    2022: 5,
    2023: 5,
    2024: 7,
    2025: 9,
    2026: 9,
}


def generate_wp_back_issues(newest_issue=None):
    """Full Public Watchtower back-issue list, Jan 2016 through newest_issue
    (defaults to the RSS-confirmed latest via check_new_issues() if not
    given, falling back to a parity-corrected calendar guess only if RSS
    is unreachable -- see generate_mwb_back_issues()'s v26.07.09.14 fix
    comment for why the naive calendar guess alone isn't safe here,
    especially for wp: since 2022 it's annual at a fixed irregular month
    per WP_ANNUAL_ISSUES, so an under-guessed range could exclude the
    entire current year's entry, not just be one issue short).
    Models all three publishing eras -- see the constants above and the
    module docstring's BACK-ISSUES note for how each was confirmed."""
    if newest_issue:
        ny, nm = int(newest_issue[:4]), int(newest_issue[4:6])
    else:
        rss_hit = next((issue for pub, _t, issue in check_new_issues() if pub == "wp"), None)
        guess = rss_hit or _wp_valid_issue(current_issue_guess())
        ny, nm = int(guess[:4]), int(guess[4:6])
    items = []
    # v26.07.30.13 (Kaleb: "if it doesn't have the last five years
    # worth, will it check those too?" -- good catch, it didn't).
    # v26.07.30.11's original version only ever probed the SINGLE
    # newest year (`ny`) -- if the yearly maintenance backfill (see
    # standing memory note) got skipped more than once, older gap
    # years would silently vanish from this list instead of being
    # found. Now walks every year from the static table's newest known
    # year + 1 through `ny`, probing/caching whichever ones are
    # missing. Each miss still costs at most 12 real requests (same
    # _probe_annual_issue() bound as before) and is cached afterward,
    # so this is a one-time cost per gap year, not a recurring one.
    # Capped at 10 years to keep a worst-case cold catch-up bounded on
    # a handheld device -- a real gap that large would mean the app
    # hasn't been updated/opened in a decade, at which point Kaleb
    # opening an issue and hitting this is the least of anyone's
    # problems, but the cap keeps it from ever being unbounded.
    annual_issues = dict(WP_ANNUAL_ISSUES)
    if ny >= WP_ANNUAL_START[0]:
        # v26.07.30.13: cap the YEAR RANGE itself (not a live-check
        # counter -- a counter would wrongly penalize free same-day
        # cache hits from a prior probe in this same session). This is
        # a defensive ceiling only; ny is always near the real current
        # year so the actual range here is normally tiny (1-2 years).
        for yy in range(WP_ANNUAL_START[0], min(ny, WP_ANNUAL_START[0] + 24) + 1):
            if yy in annual_issues:
                continue
            probed = _get_annual_issue("wp", yy)
            if probed:
                annual_issues[yy] = int(probed[4:6])
    for y, m in _month_range_desc(WP_BIMONTHLY_START[0], WP_BIMONTHLY_START[1], ny, nm):
        if (y, m) >= WP_ANNUAL_START:
            if y not in annual_issues or m != annual_issues[y]:
                continue
        elif (y, m) >= WP_TRIANNUAL_START:
            if m not in (1, 5, 9):
                continue
        else:
            if m % 2 == 0:
                continue  # even month in the bi-monthly era -- not a real issue
        items.append(_monthly_periodical_item("wp", "Watchtower -- Public Edition", y, m))
    return items


def check_new_issues():
    """Parse the jw.org What's New RSS feed to find the actual latest
    Watchtower Study Edition and Meeting Workbook issue codes.

    Why RSS instead of just guessing? JW.org publishes issues ahead of
    the calendar month, so same-month guessing is unreliable. The RSS
    feed titles contain the month and year ("THE WATCHTOWER-STUDY EDITION
    | September 2026"), which we convert to YYYYMM issue codes.

    Key gotcha: bi-monthly Workbook titles like "November-December 2026"
    must resolve to the FIRST month (mwb_E_202611, not 202612) -- that's
    the actual issue code confirmed live. The regex matches but discards
    the second month.

    Returns a list of (pub_code, title, issue_YYYYMM) tuples, deduplicated.
    Best-effort only: returns [] if the feed can't be reached -- never
    raises, so the calling code can always fall back to current_issue_guess()
    without extra error handling."""
    req = urllib.request.Request(WHATS_NEW_RSS, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError):
        return []  # network failure -- caller falls back to guess

    # Build a month-name -> month-number lookup for all 12 months
    months = {m: i + 1 for i, m in enumerate([
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December"])}
    month_re = "|".join(months.keys())

    found = {}
    for m in re.finditer(r"<title>(.*?)</title>", text, re.S):
        title = m.group(1).strip()
        # Match "Month YYYY" or "Month-Month YYYY" (bi-monthly), capture
        # only the first month. Unicode dashes (\u2013 en-dash, \u2014
        # em-dash) are included because RSS feeds sometimes use them.
        date_m = re.search(
            rf"({month_re})(?:[\s\u2013\u2014-]+(?:{month_re}))?\s+(\d{{4}})",
            title)
        if not date_m:
            continue
        mon, year = date_m.group(1), date_m.group(2)
        issue = f"{year}{months[mon]:02d}"
        if "WATCHTOWER" in title.upper() and "STUDY" in title.upper():
            key = ("w", issue)
            found[key] = title
        elif "WATCHTOWER" in title.upper():
            key = ("wp", issue)
            found[key] = title
        elif "AWAKE" in title.upper():
            key = ("g", issue)
            found[key] = title
        elif "WORKBOOK" in title.upper():
            key = ("mwb", issue)
            found[key] = title

    return [(pub, title, issue) for (pub, issue), title in found.items()]


# ---------------------------------------------------------------------------
# Required plugin functions
# ---------------------------------------------------------------------------

def list_items(query=None, page=1, category=None):
    """Build and return the catalog of available JW.org publications,
    optionally scoped to one category (see CATEGORIES), OR -- when
    `query` is a non-empty string -- a REAL live search against jw.org's
    own search service instead of the static local catalog (v0.1.161+;
    see search_media()'s docstring for how that API works and its
    publications-only scope). `category` is ignored during a live
    search -- jw.org's search API doesn't support scoping by this app's
    local category groupings, so results are simply the API's own
    top matches regardless of which category screen search was opened
    from. (Cosmetic-only quirk: main.py's search-box label may say
    "Search {category}" per its own generic labeling logic, but the
    actual results are unscoped -- same category/global distinction
    gutenberg_fetch.py already has for its own search, not new here.)

    Unlike gutenberg_fetch.py, browsing WITHOUT a query doesn't call an
    API here -- the catalog is assembled locally from STATIC_PUBLICATIONS
    and PERIODICALS, with the RSS feed used only to determine the current
    periodical issue codes. The actual download URL is resolved lazily in
    download() via _resolve_download_url() -- we don't need it for the
    browse list, and (for live search results) not verified to have an
    EPUB until then either -- same as manual pub-code entry already works.

    page is ignored: the catalog (even a single category) is small enough
    to show in full. has_next is always False.

    Catalog assembly order (query=None only):
    1. Static publications (books, courses -- no issue needed)
    2. New issues found via RSS (labeled "(new)")
    3. Periodicals not already covered by RSS (labeled "(this month, guess)")
    4. Daily text (special case: year-specific pub code, no issue param)"""
    items = []

    # v0.1.161: a typed query now bypasses the static catalog entirely
    # and does a real live jw.org search instead of a local substring
    # filter -- confirmed live to find genuine matches (Bible books,
    # doctrine topics, dated periodicals) the old substring-only filter
    # could never have found since it only ever saw titles already
    # present in STATIC_PUBLICATIONS/PERIODICALS.
    query = (query or "").strip()
    if query:
        results, err = search_media(query, filter="all")
        if err:
            return [], False, err
        pub_items = [dict(it) for it in results if it.get("_kind") == "pub"]
        if not pub_items:
            # search_media()'s own all->publications->videos fallback only
            # fires when the RAW result list is empty -- it doesn't know
            # this caller specifically needs pub-kind items. "all" often
            # returns a non-empty list that's 100% videos (confirmed
            # live: "love", "evolution", "monthly broadcast may 2026"),
            # which is a distinct, more common case than zero results.
            # Retry explicitly scoped to publications before giving up.
            results, err = search_media(query, filter="publications")
            if err:
                return [], False, err
            pub_items = [dict(it) for it in results if it.get("_kind") == "pub"]
        for it in pub_items:
            it.pop("_kind", None)  # internal tag, not part of the plugin contract
        if not pub_items:
            return [], False, (
                f'No downloadable publications found for "{query}" '
                f"(video-only results aren't shown here -- see README)")
        return pub_items, False, None

    # v0.1.110: CATEGORY_VIDEOS is routed straight to the video-source
    # picker (SCREEN_DOWNLOAD_VIDEO_SOURCES) by main.py before this
    # function is ever called -- it isn't a real publication grouping.
    # Defensive no-op only, in case a future caller reaches here anyway.
    if category == CATEGORY_VIDEOS:
        return [], False, None

    # v0.1.89: "What's New (RSS)" is a pseudo-category, not a real
    # publication grouping -- it returns ONLY what check_new_issues()
    # actually detected via RSS, across every category, and skips the
    # static-publications/guessed-periodical/back-issue steps below
    # entirely. This is the flat "what's actually new" view that existed
    # before SUPPORTS_CATEGORIES routing made it unreachable.
    if category == CATEGORY_WHATS_NEW:
        new_issues = check_new_issues()
        if not new_issues:
            return [], False, None
        for pub, title, issue in new_issues:
            items.append({
                "title":    f"{title} (new)",
                "subtitle": f"pub: {pub}  issue: {issue}",
                "filename": f"{pub}_{LANG}_{issue}.epub",
                "_pub":     pub,
                "_extra":   {"issue": issue},
            })
        return items, False, None

    # Step 1: static publications
    # These are books/courses that don't change issue-to-issue. The item
    # dict doesn't include a _download_url because we resolve it at download
    # time -- the URL can change and we want the freshest link each time.
    for pub, title, extra, cat in STATIC_PUBLICATIONS:
        if category and cat != category:
            continue
        items.append({
            "title":    title,
            "subtitle": f"pub: {pub}",
            "filename": f"{pub}_{LANG}.epub",
            "_pub":     pub,
            "_extra":   extra,   # passed to GETPUBMEDIALINKS at download time
        })

    # v26.07.30.14 (Kaleb: "cache that url in the proper category for
    # future" -- for books found via search/manual code and
    # downloaded): merge in anything _remember_discovered_pub() has
    # saved, same shape/behavior as a STATIC_PUBLICATIONS entry, so it
    # shows up in the normal category browse from now on instead of
    # needing the same search again.
    for pub, entry in _load_discovered_pubs().items():
        cat = entry.get("category")
        if category and cat != category:
            continue
        items.append({
            "title":    entry.get("title", pub),
            "subtitle": f"pub: {pub}",
            "filename": f"{pub}_{LANG}.epub",
            "_pub":     pub,
            "_extra":   entry.get("extra"),
        })

    # Step 2: RSS-detected new issues
    # If the feed is reachable, these are the actual currently-published
    # issues -- more accurate than guessing from the calendar.
    pub_to_category = {pub: cat for pub, _t, cat in PERIODICALS}
    new_issues = check_new_issues()
    if category:
        new_issues = [ni for ni in new_issues if pub_to_category.get(ni[0]) == category]
    covered = {(pub, issue) for pub, _t, issue in new_issues}
    # v26.07.30.10 BUG FIX (Kaleb: "I want our app to always be on the
    # same page for new releases"): a pub whose RSS hit exists but at a
    # DIFFERENT issue than Step 3/4's guess wasn't being recognized as
    # "already covered" -- only an EXACT issue match skipped the guess
    # entry. Confirmed live: RSS had w=202610 ("new"), but the raw
    # calendar guess for w is 202607 -- different issue, so the old
    # code added a SECOND, stale, wrongly-labeled "(July 2026, latest
    # known)" entry right below the correct "(new)" one. Fix: track
    # which PUBS (not pub+issue pairs) RSS already covered, and skip
    # the whole guess step for those -- if RSS found anything real for
    # a pub, trust it completely rather than also guessing.
    covered_pubs = {pub for pub, _t, _issue in new_issues}
    for pub, title, issue in new_issues:
        items.append({
            "title":    f"{title} (new)",
            "subtitle": f"pub: {pub}  issue: {issue}",
            "filename": f"{pub}_{LANG}_{issue}.epub",
            "_pub":     pub,
            "_extra":   {"issue": issue},
        })

    # Step 3 & 4: periodicals not yet covered + daily text
    for pub, title, cat in PERIODICALS:
        if category and cat != category:
            continue
        if pub == "es":
            # Daily text: year-baked-into-code pattern (es26, es27, ...)
            code = current_year_es_code()
            items.append({
                "title":    title,
                "subtitle": f"pub: {code}",
                "filename": f"{code}_{LANG}.epub",
                "_pub":     code,
                "_extra":   None,
            })
            continue
        if pub in covered_pubs:
            continue  # v26.07.30.10: RSS already has a real hit for
            # this pub -- don't ALSO show a guessed entry (see fix
            # comment above covered_pubs for the bug this closes).
        # v26.07.30.10: for w/mwb, prefer a live GETPUBMEDIALINKS probe
        # over the bare calendar guess when RSS has nothing for this
        # pub at all (same reasoning/precedent as _mwb_probe_furthest_
        # available(), already proven live 2026-07-23: RSS can go
        # through periods with zero entries for a pub even though real
        # issues already exist months ahead). Falls back to the old
        # guess only if the probe itself can't reach the network.
        if pub == "w":
            issue = _w_probe_furthest_available() or current_issue_guess()
        elif pub == "mwb":
            issue = _mwb_probe_furthest_available() or _mwb_valid_issue(current_issue_guess())
        elif pub == "wp":
            issue = _wp_valid_issue(current_issue_guess())
        elif pub == "g":
            issue = _g_valid_issue(current_issue_guess())
        else:
            issue = current_issue_guess()
        if (pub, issue) in covered:
            continue  # already listed via RSS above -- don't duplicate
        # v26.07.15.02: label with the REAL month/year the guess resolved
        # to, not a hard-coded "this month" -- for wp/g (no RSS tracking)
        # and even mwb/w when RSS is unreachable, the guess routinely
        # snaps to an issue months away from the calendar month (e.g.
        # wp in July often resolves to the prior September). Calling
        # that "(this month, guess)" reads as wrong/missing even when
        # the issue and entry are both correct -- just mislabeled.
        iy, im = int(issue[:4]), int(issue[4:6])
        label = f"{_MONTHS_FULL[im - 1]} {iy}" if 1 <= im <= 12 else issue
        # v26.07.30.12 (Kaleb: "can't it just use epub engine to find
        # the title?"): for a freshly auto-detected Awake! issue,
        # _get_annual_issue() already fetched and cached the real
        # theme subtitle via _fetch_awake_theme() -- use it here
        # instead of the generic month/year label when available.
        display_title = title
        if pub == "g":
            theme = _get_cached_theme("g", iy)
            if theme:
                display_title = theme
        items.append({
            "title":    f"{display_title} ({label}, latest known)" if display_title == title
                        else f"{display_title} (latest known)",
            "subtitle": f"pub: {pub}  issue: {issue}",
            "filename": f"{pub}_{LANG}_{issue}.epub",
            "_pub":     pub,
            "_extra":   {"issue": issue},
        })

    # Step 5: full back-issue lists for pubs with a safe, verified
    # generator. Only generated when actually browsing that pub's own
    # category (not the "all categories" view) -- ~120 entries is fine
    # for THIS list (see main.py's draw_download_browse, which already
    # windows/scrolls rather than rendering everything), but would be
    # noise mixed into every other category's results. "wp"/"g"
    # deliberately excluded -- see MONTHLY_BACK_ISSUE_PUBS's comment for
    # why (count/year alone isn't enough to generate their issue months
    # safely).
    # v26.07.09.14: Study and Public used to share ONE combined category
    # (CATEGORY_WATCHTOWER) -- confirmed genuinely confusing (mixed pub
    # codes interleaving in a way that didn't read as clean date order,
    # per Kaleb's report) and split into two separate categories, each
    # now a normal 1:1 category:pub mapping like every other entry here.
    category_pubs = {
        CATEGORY_WATCHTOWER_STUDY:  ("w",),
        CATEGORY_WATCHTOWER_PUBLIC: ("wp",),
        CATEGORY_WORKBOOKS:  ("mwb",),
    }
    for pub in category_pubs.get(category, ()):
        newest = next((issue for p, _t, issue in new_issues if p == pub), None)
        covered = {(pub, newest)} if newest else set()
        # v26.07.30.10: also skip whatever Step 3/4 actually displayed
        # (probed value for w/mwb, not the stale raw guess -- must match
        # exactly what was appended above or this dedup silently stops
        # working and the same issue shows twice, as it briefly did
        # after the Step 3/4 probe fix landed and this block still
        # deduped against the OLD unprobed guess).
        if pub == "w":
            guess = _w_probe_furthest_available() or current_issue_guess()
        elif pub == "mwb":
            guess = _mwb_probe_furthest_available() or _mwb_valid_issue(current_issue_guess())
        elif pub == "wp":
            guess = _wp_valid_issue(current_issue_guess())
        else:
            guess = current_issue_guess()
        covered.add((pub, guess))
        # v26.08.04.03 BUG FIX (found via a deliberate RSS-empty
        # simulation while stress-testing this exact area): `newest`
        # above is RSS-only, so when RSS has nothing for "w" this used
        # to pass newest_issue=None straight into generate_monthly_
        # back_issues(), which -- unlike generate_mwb_back_issues()/
        # generate_wp_back_issues(), both of which self-probe when
        # given None -- just falls back to the bare calendar guess.
        # Confirmed live: with RSS's "w" entry suppressed, probe found
        # 202610 (shown correctly in Step 3/4 as "latest known") but
        # this Step 5 list capped at the calendar guess 202608, so the
        # full Watchtower Study category browse silently DROPPED
        # September 2026 entirely (jumped from the isolated Step 3/4
        # October entry straight to August here) even though it's a
        # real, live-confirmed issue. Fix: pass `guess` (already probed
        # above) as the fallback whenever RSS didn't have an entry, so
        # this list's own newest bound always matches what Step 3/4
        # already decided was real -- same fix shape for mwb/wp too,
        # harmless there since they already self-probe to the same value.
        newest_for_gen = newest or guess
        if pub == "mwb":
            gen = generate_mwb_back_issues(newest_issue=newest_for_gen)
        elif pub == "wp":
            gen = generate_wp_back_issues(newest_issue=newest_for_gen)
        else:
            gen = generate_monthly_back_issues(pub, newest_issue=newest_for_gen)
        for item in gen:
            issue = item["_extra"]["issue"]
            if (pub, issue) in covered:
                continue  # already listed above (new/guess) -- don't duplicate
            items.append(item)

    # v0.1.160: Watchtower's EARLIER pre-2016 era (Sept 2011-Dec 2015,
    # day-based issue codes) -- see generate_w_pre2016_issues()/
    # generate_wp_pre2016_issues() docstrings for the full correction
    # story (Kaleb caught that the original "no EPUB before 2016" claim
    # was wrong -- it just needed a day-based issue code, not month-only).
    # Same combined-eras pattern as Awake! above.
    if category == CATEGORY_WATCHTOWER_STUDY:
        for item in generate_w_pre2016_issues():
            issue = item["_extra"]["issue"]
            if ("w", issue) in covered:
                continue
            items.append(item)
    if category == CATEGORY_WATCHTOWER_PUBLIC:
        for item in generate_wp_pre2016_issues():
            issue = item["_extra"]["issue"]
            if ("wp", issue) in covered:
                continue
            items.append(item)

    # Awake! ("g") back issues -- two eras combined. AWAKE_BACK_ISSUES
    # (2016+, hard-coded) for the irregular-frequency modern era, plus
    # generate_awake_monthly_issues() (Sept 2011-Dec 2015, generated) for
    # the earlier confirmed-monthly era -- see AWAKE_MONTHLY_START/END.
    # Only shown when actually browsing the Awake! category, same as
    # w/mwb above -- 80 combined entries would be noise mixed into every
    # other category's results.
    if category == CATEGORY_AWAKE:
        covered_g = {("g", issue) for p, _t, issue in new_issues if p == "g"}
        # v26.07.30.11: _g_valid_issue() may now resolve to a live-
        # probed year beyond AWAKE_BACK_ISSUES' static table -- adding
        # it to covered_g here (as before) is enough to keep it from
        # being duplicated below; Step 3/4 above already gives it its
        # own visible "(new)" or "(latest known)" row, same as w/wp/
        # mwb, so no separate row is added here (a dedicated one would
        # just reintroduce the exact duplicate-row bug fixed earlier
        # this session for w/mwb).
        latest_g = _g_valid_issue()
        covered_g.add(("g", latest_g))
        # v26.07.30.13 (Kaleb: "if it doesn't have the last five years
        # worth, will it check those too?"): the above only ever
        # backfills the SINGLE newest year (via _g_valid_issue) --
        # older gap years between AWAKE_BACK_ISSUES' static table and
        # the newest one need their own rows here, or they'd silently
        # vanish. Unlike the single-newest-year case, these DO need
        # their own row (Step 3/4 only ever surfaces one "latest"
        # entry, not a whole run of backfilled years), each with its
        # real theme via _fetch_awake_theme() same as the newest one
        # gets. Bounded the same defensive way as generate_wp_back_
        # issues()'s year-range cap.
        newest_known_year = int(AWAKE_BACK_ISSUES[0][0][:4])
        latest_year = int(latest_g[:4])
        for yy in reversed(range(newest_known_year + 1, min(latest_year - 1, newest_known_year + 24) + 1)):
            gap_issue = _get_annual_issue("g", yy)
            if not gap_issue or ("g", gap_issue) in covered_g:
                continue
            theme = _get_cached_theme("g", yy)
            gy, gm = int(gap_issue[:4]), int(gap_issue[4:6])
            gap_title = theme or f"Awake! ({_MONTHS_FULL[gm - 1]} {gy})"
            items.append(_periodical_item("g", gap_title, gap_issue))
            covered_g.add(("g", gap_issue))
        for issue, title in AWAKE_BACK_ISSUES:
            if ("g", issue) in covered_g:
                continue  # already listed above (new/guess) -- don't duplicate
            items.append(_periodical_item("g", title, issue))
        for item in generate_awake_monthly_issues():
            if ("g", item["_extra"]["issue"]) in covered_g:
                continue
            items.append(item)

    # Kingdom Ministry ("km") -- closed archive, no current-issue guess
    # involved (see generate_km_back_issues() docstring). Only shown
    # when actually browsing this category, same "don't clutter every
    # other category" reasoning as the w/mwb/wp/g back-issue blocks
    # above.
    if category == CATEGORY_KINGDOM_MINISTRY:
        items.extend(generate_km_back_issues())

    return items, False, None


def lookup_pub_code(code, issue=None):
    """Manual pub-code lookup for publications NOT in STATIC_PUBLICATIONS.

    Called by main.py when the user confirms a code on the Y-button manual-
    entry screen. Unlike list_items(), this performs a LIVE API round-trip
    immediately -- the point is to catch typos on the entry screen with a
    clear error ("not found") rather than only failing later at download time.

    Two-attempt strategy (why it's needed):
      Some publications (confirmed: the plain NWT "nwt") return HTTP 400
      from GETPUBMEDIALINKS unless fileformat=EPUB is explicit. A single
      attempt without fileformat would always fail for these. So:
        Attempt 1: without fileformat (works for most pubs)
        Attempt 2: with fileformat=EPUB (fallback for pubs that need it)
      If attempt 1 raises HTTPError 400, we fall through to attempt 2
      rather than giving up. This was a real bug before being fixed: the
      original code returned on the first error and never reached the retry.

    Returns (item_dict, None) on success, (None, error_string) on failure."""
    code = (code or "").strip().lower()
    if not code:
        return None, "Enter a publication code"
    if len(code) > 40:
        return None, "That doesn't look like a publication code"

    params = {"pub": code, "langwritten": LANG, "output": "json"}
    if issue:
        params["issue"] = issue.strip()

    def _try(p):
        """One attempt at the API. Returns (data_dict, None) on success or
        (None, error_string) on failure. error_string "INVALID_CODE" is a
        sentinel meaning the API returned 400 (unknown pub code) -- distinct
        from a real network error so we can give a better message."""
        try:
            return _get_json(API_BASE + "?" + urllib.parse.urlencode(p)), None
        except urllib.error.HTTPError as e:
            if e.code == 400:
                # 400 means the pub code isn't recognized by the API
                # (confirmed live) -- NOT a network problem. We use
                # "INVALID_CODE" so the outer function can distinguish
                # "needs retry with fileformat=EPUB" from "bad code".
                return None, "INVALID_CODE"
            return None, f"Server error ({e.code})"
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            return None, f"Network error: {e}"
        except ValueError as e:
            return None, f"Bad response from server: {e}"

    # Attempt 1: no fileformat param
    data, err = _try(params)
    epub = _extract_epub(data) if isinstance(data, dict) else None

    if not epub:
        # Attempt 2: explicit fileformat=EPUB (fallback for pubs like NWT)
        retry_params = dict(params, fileformat="EPUB")
        data2, err2 = _try(retry_params)
        epub2 = _extract_epub(data2) if isinstance(data2, dict) else None
        if epub2:
            data, epub, err = data2, epub2, None
        elif err2 is None:
            # Retry got a real response but still no epub -- use its data
            # (more specific / informative) over the first attempt's result
            err, data = None, data2

    if not epub:
        if isinstance(data, dict) and data.get("pubName"):
            return None, f'"{html.unescape(data["pubName"])}" has no EPUB available'
        if err and err != "INVALID_CODE":
            return None, err
        return None, f'"{code}" not found (check the code and try again)'

    title = html.unescape(data.get("pubName", code))
    fname_suffix = f"_{issue.strip()}" if issue else ""
    return {
        "title":    title,
        "subtitle": f"pub: {code}" + (f"  issue: {issue.strip()}" if issue else ""),
        "filename": f"{code}_{LANG}{fname_suffix}.epub",
        "_pub":     code,
        "_extra":   ({"issue": issue.strip()} if issue else None),
    }, None


def _resolve_download_url(item):
    """Resolve the current EPUB download URL for an item at download time.

    WHY resolve at download time instead of storing the URL in list_items()?
    JW.org's CDN URLs are time-limited and can change between catalog builds
    and actual download. Calling GETPUBMEDIALINKS fresh at download time
    always gives us a valid, current URL.

    Constructs the API request from item["_pub"] and item["_extra"] (which
    carries the issue= param for periodicals, or fileformat=EPUB for pubs
    that need it). Returns (url_string, None) on success or (None, error)."""
    params = {"pub": item["_pub"], "langwritten": LANG, "output": "json"}
    if item.get("_extra"):
        params.update(item["_extra"])
    url = API_BASE + "?" + "&".join(
        f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
    try:
        data = _get_json(url)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
        return None, str(e)
    epub = _extract_epub(data)
    if not epub:
        return None, f'"{html.unescape(data.get("pubName", item["title"]))}" has no EPUB available'
    return epub["file"]["url"], None


# ---------------------------------------------------------------------------
# Video downloads (v0.1.92)
# ---------------------------------------------------------------------------
# Separate from the EPUB catalog above: videos are looked up by pub code
# (e.g. "lffv" for Enjoy Life Forever videos) via the SAME GETPUBMEDIALINKS
# endpoint, just with fileformat=MP4 instead of EPUB. Confirmed live
# structure (real response inspected, not guessed):
#   data["files"][LANG]["MP4"] -> list of track objects, EACH TRACK
#   REPEATED ONCE PER RESOLUTION (e.g. same "track" number appears at
#   both "240p" and "720p" -- these are NOT duplicates, they're
#   different files for the same video). Each entry has:
#     "title"  -- human-readable video title (used for the saved filename)
#     "label"  -- resolution string, e.g. "240p", "480p", "720p"
#     "track"  -- track number (groups resolutions of the same video)
#     "file": {"url": ...}
#     "filesize" -- bytes
#
# Kaleb confirmed 480p plays back fine on the RG CubeXX-H (already tested
# via CTupe) and fits the 720x720 screen well -- so PREFERRED_VIDEO_LABEL
# below is "480p", falling back to the next closest if a given video
# doesn't have that rendition (not every video is transcoded at every
# resolution).
#
# Videos are saved with the real TITLE as the filename (sanitized), not
# the pub-code-based CDN filename (e.g. "lffv_E_011_r480P.mp4") -- so they
# sit sensibly alongside a person's other video files instead of showing
# a cryptic name. See _sanitize_video_filename().

PREFERRED_VIDEO_LABEL = "480p"
# Fallback order if the preferred label isn't available for a given track --
# closest-to-preferred first.
VIDEO_LABEL_FALLBACK = ["480p", "360p", "720p", "240p"]


def _sanitize_video_filename(title):
    """Turn a real video title into a safe filename. Strips characters
    that are risky across filesystems (/, :, ?, *, etc.) and JW.org's
    typographic punctuation (em dash, curly quotes), collapses repeated
    spaces, and trims to a sane length. Never returns an empty string --
    falls back to "video" if sanitizing would strip everything.

    v26.07.23.04 BUG FIX (found during a category-folder-naming audit):
    the curly-quote-to-straight-quote conversion used to run AFTER the
    bad_chars strip -- so a curly double quote (\u201c/\u201d, common in
    real JW.org titles/category names, e.g. "Sing Out Joyfully" to
    Jehovah) got converted to a literal straight '"' character in the
    FINAL output, even though '"' is explicitly in bad_chars because
    it's one of the characters FAT32/exFAT (what SD cards actually use)
    forbids in a filename. Confirmed live against every real music
    category name: this could have produced a folder name muOS's own
    SD card filesystem might refuse to create. Fixed by doing ALL
    typographic normalization first, then stripping bad_chars last, so
    a straight quote introduced by curly-quote conversion still gets
    caught by the same strip pass everything else goes through -- no
    unsafe character can survive regardless of which order it enters
    the string."""
    cleaned = title
    cleaned = cleaned.replace("\u2014", "-").replace("\u2013", "-")
    cleaned = cleaned.replace("\u2018", "'").replace("\u2019", "'")
    cleaned = cleaned.replace("\u201c", '"').replace("\u201d", '"')
    bad_chars = '/\\:*?"<>|'
    cleaned = "".join(c for c in cleaned if c not in bad_chars)
    cleaned = " ".join(cleaned.split())  # collapse whitespace runs
    cleaned = cleaned.strip(" .")       # trailing dot/space breaks on some FSes
    if len(cleaned) > 120:
        cleaned = cleaned[:120].rstrip()
    return cleaned or "video"


def _extract_video_tracks(data, quality=None):
    """Group data["files"][LANG]["MP4"] entries by track number, picking
    ONE rendition per track per VIDEO_LABEL_FALLBACK order (or, if
    `quality` is given, that label first, then the normal fallback order
    for anything without that exact rendition available -- v26.07.20.08,
    added for PicoReader's Streaming Quality setting; NOT used by any
    download call site, which all still call this with quality=None, so
    downloads stay pinned to the original 480p-first default regardless
    of what streaming quality is selected). Returns a list of dicts:
    {"title", "url", "label", "filesize", "track"}. Returns [] if the
    path doesn't exist (e.g. this pub has no videos)."""
    try:
        entries = data["files"][LANG]["MP4"]
    except (KeyError, TypeError):
        return []
    if not isinstance(entries, list):
        return []  # v0.1.140: malformed shape (e.g. a dict instead of a
                   # list) -- treat as "no videos" rather than crash below.

    by_track = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue  # v0.1.140: skip any non-dict entry instead of
                       # crashing on entry.get() -- see VIDEO API NOTES.
        track = entry.get("track")
        label = entry.get("label")
        by_track.setdefault(track, {})[label] = entry

    fallback_order = VIDEO_LABEL_FALLBACK
    if quality and quality in VIDEO_LABEL_FALLBACK:
        fallback_order = [quality] + [l for l in VIDEO_LABEL_FALLBACK if l != quality]

    tracks = []
    for track, by_label in by_track.items():
        chosen = None
        for label in fallback_order:
            if label in by_label:
                chosen = by_label[label]
                break
        if chosen is None:  # unknown label naming -- just take any one
            chosen = next(iter(by_label.values()))
        try:
            url = chosen["file"]["url"]
        except (KeyError, TypeError):
            continue
        tracks.append({
            "title":    chosen.get("title", f"video_{track}"),
            "url":      url,
            "label":    chosen.get("label", "?"),
            "filesize": chosen.get("filesize", 0),
            "track":    track,
        })
    tracks.sort(key=lambda t: (t["track"] if t["track"] is not None else 0))
    return tracks


def _list_mediator_category_items(category_key, default_title, limit=None):
    """v0.1.109: shared logic behind list_broadcast_items() and
    list_good_news_items() -- both just point this at a different
    MEDIATOR_CATEGORY_URL key. Pulled out once a second category
    (SeriesGoodNews) needed the exact same media-list-to-item-list
    conversion, rather than duplicating it a second time. Returns
    (items, error_message) in the shape ready for download_video():
    {"title", "subtitle", "filename", "_video_url", "track",
    "_published"}. No track-grouping needed (unlike GETPUBMEDIALINKS/
    _extract_video_tracks) -- each media entry already IS one specific
    video (naturalKey encodes it), with a flat per-quality "files" list."""
    url = MEDIATOR_CATEGORY_URL.format(lang=LANG, key=category_key)
    req = urllib.request.Request(url + "?detailed=1&clientType=www",
                                 headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
        return [], str(e)

    media = data.get("category", {}).get("media", [])
    if not media:
        return [], "No videos found"
    # v26.08.03.14 BUG FIX (Kaleb's question: "are videos shown in the
    # same default order?" -- checked live, they weren't). This used to
    # force every category into newest-published-first order
    # unconditionally -- correct for feed-style categories (JW
    # Broadcasting, News and Announcements), where the raw API order is
    # ALSO already newest-first without any sorting needed (confirmed
    # live), but WRONG for curated episodic series (checked live:
    # "Enjoy Life Forever", 91 episodes) where the raw order IS the
    # real intended lesson/narrative sequence -- e.g. "Welcome to Your
    # Bible Study" first, "Never Give Up Hope!" second -- and re-
    # sorting by publish date scrambled it into upload-date order that
    # matches neither jw.org's real site nor any sensible viewing
    # sequence. The API's own natural order already correctly serves
    # BOTH cases; removing this sort fixes series without breaking
    # feeds (both confirmed live, not assumed).
    if limit:
        media = media[:limit]

    items = []
    for m in media:
        files = m.get("files", [])
        by_label = {f.get("label"): f for f in files}
        chosen = next((by_label[l] for l in VIDEO_LABEL_FALLBACK if l in by_label), None)
        if chosen is None and files:
            chosen = files[0]
        if not chosen or not chosen.get("progressiveDownloadURL"):
            continue
        title = m.get("title", default_title)
        safe_name = _sanitize_video_filename(title)
        size_mb = chosen.get("filesize", 0) / (1024 * 1024) if chosen.get("filesize") else 0
        published = m.get("firstPublished", "")
        items.append({
            "title":       title,
            "subtitle":    f'{chosen.get("label","?")}  ~{size_mb:.0f} MB  ({published[:10]})',
            "filename":    f"{safe_name} ({chosen.get('label','?')}).mp4",
            "_video_url":  chosen["progressiveDownloadURL"],
            "track":       m.get("naturalKey"),
            "_published":  published,
        })
    return items, None


def list_mediator_category(key, title, limit=None):
    """v26.07.15.08 (Kaleb's request -- 22 more video categories at
    once): thin public wrapper around _list_mediator_category_items()
    so a new VIDEO_SOURCES entry can just point at a category key/title
    via its "args", the same way list_broadcast_items()/
    list_good_news_items() do internally -- without needing a
    dedicated one-off function per category. All 22 keys below were
    confirmed live this session (category tree walk + media count
    check via MEDIATOR_CATEGORY_URL), not guessed."""
    return _list_mediator_category_items(key, title, limit)


def _list_mediator_audio_category_items(category_key, default_title):
    """v26.07.23.01 (Kaleb's request -- real music sub-categories he
    found in the JW Library app's Audio tab that PicoReader was
    missing entirely): audio equivalent of
    _list_mediator_category_items() just above. Confirmed live via the
    real mediator "Audio" container category (GET .../categories/E/
    Audio?detailed=1&clientType=www) -- its "subcategories" list is the
    literal ground truth for every real music category, not a guess:

        AudioOriginalSongs -> "Original Songs" (already had its own
            loader, list_original_songs_audio(), kept as-is)
        SJJMeetings        -> "Sing Out Joyfully" to Jehovah--Meetings
        SJJChorus          -> "Sing Out Joyfully" to Jehovah--Vocals
        SJJInstrumental    -> "Sing Out Joyfully" to Jehovah--Instrumental
        Vocal              -> Sing to Jehovah--Chorus
        AudioChildrenSongs -> Children's Songs
        KingdomMelodies    -> Kingdom Melodies

    Unlike video categories, each audio media entry has exactly ONE
    file (confirmed live: files[0], label is always null, no
    resolution/rendition choice needed) -- so this returns items
    shaped for download_audio() ("_audio_url"/.mp3), not
    download_video(). "The Good News According to Jesus--Soundtrack
    1/2/3" and "Commit Your Way to Jehovah--Soundtrack" (also visible
    in Kaleb's screenshots) are NOT categories in this tree -- confirmed
    live there are only 7 real subcategories total under Audio, and
    none of their media titles contain "Soundtrack". Those are
    standalone single-file releases (their own pub codes), not folders
    to browse/download-all -- out of scope here unless Kaleb wants them
    added as individual AUDIO_SOURCES entries instead.
    """
    url = MEDIATOR_CATEGORY_URL.format(lang=LANG, key=category_key)
    req = urllib.request.Request(url + "?detailed=1&clientType=www",
                                 headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
        return [], str(e)

    media = data.get("category", {}).get("media", [])
    if not media:
        return [], "No audio found"

    items = []
    for m in media:
        files = m.get("files", [])
        chosen = files[0] if files else None
        if not chosen or not chosen.get("progressiveDownloadURL"):
            continue
        title = m.get("title", default_title)
        safe_name = _sanitize_video_filename(title)  # generic sanitizer,
                                                       # same as list_audio_items()
        size_mb = chosen.get("filesize", 0) / (1024 * 1024) if chosen.get("filesize") else 0
        items.append({
            "title":      title,
            "subtitle":   f"MP3  ~{size_mb:.1f} MB",
            "filename":   f"{safe_name}.mp3",
            "_audio_url": chosen["progressiveDownloadURL"],
            "track":      m.get("naturalKey"),
        })
    if not items:
        return [], f'"{default_title}" has no audio available'
    return items, None


def list_mediator_audio_category(key, title):
    """Thin public wrapper around _list_mediator_audio_category_items(),
    same role as list_mediator_category() plays for video -- lets an
    AUDIO_SOURCES entry point straight at a category key/title."""
    return _list_mediator_audio_category_items(key, title)


def list_broadcast_items(limit=None):
    """v0.1.106: Kaleb asked for a "check for new videos" feature; no
    dedicated official RSS feed exists for videos (the general
    WHATS_NEW_RSS feed doesn't reliably surface them -- checked a real
    snapshot, zero video items in it), so per Kaleb's direction this
    polls jw.org's own JW Broadcasting monthly-programs category
    directly instead (MEDIATOR_CATEGORY_URL, key="StudioMonthlyPrograms")
    -- confirmed this is what jw.org's own site itself fetches to
    populate that category page (the page's static HTML has no listing
    at all, it's a client-side route). Still 100% jw.org's own
    infrastructure (b.jw-cdn.org), not a third party.

    v26.07.15.06 (Kaleb's request -- same fix as Morning Worship's
    v26.07.15.05): originally capped at limit=12, newest-first, on the
    assumption new-video checks only cared about "what's new," not the
    full archive. Confirmed live the mediator API has no server-side
    pagination here either -- one request to StudioMonthlyPrograms
    already returns the entire category (66 programs, July 2026 back
    to December 2017) in a single response; the cap was purely this
    function truncating it afterward. Removed so the full archive
    reaches main.py's browse screen, same as Morning Worship."""
    return _list_mediator_category_items("StudioMonthlyPrograms", "JW Broadcasting", limit)


def list_good_news_items():
    """v0.1.109: Kaleb asked to add "The Good News According to Jesus"
    (the dramatized episode series about Jesus's life/teachings) as a
    category -- found via the same VideoOnDemand > Series category tree
    already explored for Governing Body Updates (SeriesGoodNews key).
    Confirmed live: 6 episodes as of this writing (pub "gnj"), e.g.
    Episode 1: "The True Light of the World". Small, slow-growing
    catalog (new episodes roughly a few times a year) -- no limit
    needed, just return all of them.

    v26.07.09.14 BUG FIX (Kaleb's report): _list_mediator_category_items()
    sorts by publish date, newest first -- correct for Broadcasting
    ("what's new"), but confirmed live that these episodes were NOT
    published in narrative order (Episode 1 published 2024-12-23,
    Episodes 2-3 on 2026-01-19, Episodes 4-6 on 2026-05-01 -- a
    date-sort scrambles them). Re-sorted here by the actual episode
    number parsed from each title ("Episode N: ..."), ascending, so the
    list reads in watch order. Falls back to leaving publish-date order
    for any title that doesn't match the pattern (future-proofing
    against a title format change upstream, rather than crashing or
    silently mis-sorting)."""
    items, err = _list_mediator_category_items("SeriesGoodNews", "The Good News According to Jesus")
    if items:
        def _episode_num(item):
            m = re.match(r"Episode (\d+)", item.get("title", ""))
            return int(m.group(1)) if m else float("inf")  # unmatched titles sort last
        items.sort(key=_episode_num)
    return items, err


# v26.08.11 REMOVED: list_original_songs_items() and
# list_morning_worship_items() -- both genuinely unreachable dead
# code, confirmed via a full-codebase search before removal, not
# assumed. Neither was ever wired into AUDIO_SOURCES/VIDEO_SOURCES's
# real "loader" config -- both superseded by the generic list_
# mediator_category() config-driven approach (a hardcoded key/title
# directly in VIDEO_SOURCES, no dedicated wrapper function needed),
# and Original Songs' audio path specifically by list_original_songs_
# audio() further down this file.


# ---------------------------------------------------------------------------
# Free-text search (OmniSearch) -- v0.1.161+
# ---------------------------------------------------------------------------
# Separate service from GETPUBMEDIALINKS. Reverse-engineered live from
# jw.org's own Search page network calls (confirmed, not guessed):
#   1. GET https://b.jw-cdn.org/tokens/jworg.jwt -> a plain-text JWT.
#      Scoped (per its own decoded payload) to filters: all/publications/
#      videos/audio/bible/indexes and sites: jw.org/wol.
#   2. GET https://b.jw-cdn.org/apis/search/results/{lang}/{filter}
#          ?sort=rel&q={query}
#      with header Authorization: Bearer {token}. Confirmed live: without
#      this header the API returns HTTP 200 with a JSON *error body*
#      (status 401 inside the payload, not an HTTP error) -- so callers
#      must check for that shape too, not just catch HTTPError.
# Token is cached in memory and reused until ~30s before its own "exp"
# claim -- avoids fetching a fresh JWT on every search.
SEARCH_TOKEN_URL = "https://b.jw-cdn.org/tokens/jworg.jwt"
SEARCH_API_URL = "https://b.jw-cdn.org/apis/search/results/{lang}/{filter}"

_search_token_cache = {"token": None, "exp": 0}


def clear_search_token_cache():
    """v26.07.09.10: Resets the cached OmniSearch bearer token, forcing the next
    search_media()/list_items(query=...) call to fetch a brand-new token
    instead of reusing one from an earlier visit to this plugin.

    Called by main.py at the JW plugin's two real exit points (backing
    out of SCREEN_DOWNLOAD_CATEGORIES or SCREEN_DOWNLOAD_BROWSE to
    SCREEN_DOWNLOAD_SOURCES/SCREEN_LIBRARY) -- incognito-style: one
    token per plugin visit, gone the moment you leave, even though the
    token itself would otherwise stay valid for its full ~7-day
    lifetime (confirmed live) if left cached at the module level for
    the rest of the app's process lifetime."""
    _search_token_cache["token"] = None
    _search_token_cache["exp"] = 0


def _jwt_exp(token):
    """Best-effort decode of a JWT's `exp` claim (seconds since epoch),
    without any signature verification -- we don't need to trust the
    token, just know when jw-cdn.org itself says it expires, so we know
    when to fetch a new one. Returns None if anything about the token
    looks unexpected (caller falls back to a short default lifetime)."""
    try:
        payload = token.split(".")[1]
        padded = payload + "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(padded)).get("exp")
    except Exception:
        return None


def _get_search_token():
    """Return (token, error). Cached -- see module docstring above."""
    now = time.time()
    if _search_token_cache["token"] and now < _search_token_cache["exp"] - 30:
        return _search_token_cache["token"], None
    req = urllib.request.Request(SEARCH_TOKEN_URL, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            token = resp.read().decode("utf-8", errors="replace").strip()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return None, str(e)
    if not token:
        return None, "Empty token response"
    exp = _jwt_exp(token) or (now + 300)  # 5 min fallback if exp unreadable
    _search_token_cache["token"] = token
    _search_token_cache["exp"] = exp
    return token, None


def _walk_search_results(node, items, limit):
    """Recursively collect {"type": "item"} entries out of OmniSearch's
    nested results (top-level list of groups, each group has its own
    nested "results" list -- e.g. a "Videos" carousel group alongside
    flatter groups for articles/publications). Three subtypes are
    directly usable by this plugin's existing download machinery:
      - subtype "video"       -> a real playable video (has a lank like
                                  pub-XXX_N_VIDEO, matched by the SAME
                                  _VIDEO_LINK_RE/_VIDEO_DOCID_RE regexes
                                  parse_video_link() already uses for
                                  in-text epub links).
      - subtype "audio"       -> v26.07.10.02: a real downloadable MP3
                                  (lank like pub-XXX_N_AUDIO, same shape
                                  as video's pub-track lanks -- see
                                  _AUDIO_LINK_RE). Confirmed live this
                                  was previously being silently dropped
                                  here even though the raw API already
                                  returned real audio hits (e.g.
                                  filter="audio", q="love" -> 12 results)
                                  -- there was simply no download path
                                  for audio yet when this function was
                                  first written; there is now.
      - subtype "publication" -> a real pub code (lank "pub-XXX") that
                                  MAY have an EPUB -- same as manual
                                  pub-code entry, not verified until
                                  download() actually calls
                                  GETPUBMEDIALINKS, consistent with how
                                  the static catalog already works.
    Everything else (videoCategory, article/"pa-" WOL hits, bible verses,
    etc.) is skipped -- there's no existing download path for those."""
    if limit and len(items) >= limit:
        return
    if isinstance(node, dict):
        if node.get("type") == "item":
            subtype = node.get("subtype")
            lank = node.get("lank") or ""
            title = html.unescape(node.get("title") or "")
            context = node.get("context")
            if subtype == "video" and lank:
                items.append({
                    "title":     title,
                    "subtitle":  html.unescape(context) if context else "Video",
                    "_kind":     "video",
                    "_raw_lank": lank,
                })
            elif subtype == "audio" and lank:
                # v26.07.10.02: same "raw lank, lazy resolve" shape as
                # video -- see resolve_search_audio_item(). "duration" is
                # a real field on audio search results (confirmed live,
                # e.g. "4:16") -- shown in the subtitle same as context
                # would be, since it's more useful here than a text
                # snippet for something you're about to listen to.
                duration = node.get("duration")
                items.append({
                    "title":     title,
                    "subtitle":  duration or (html.unescape(context) if context else "Audio"),
                    "_kind":     "audio",
                    "_raw_lank": lank,
                })
            elif subtype == "publication" and lank.startswith("pub-"):
                code = lank[len("pub-"):]
                sub = f"pub: {code}"
                if context:
                    sub += f"  ({html.unescape(context)})"
                items.append({
                    "title":    title,
                    "subtitle": sub,
                    "filename": f"{code}_{LANG}.epub",
                    "_pub":     code,
                    "_extra":   None,
                    "_kind":    "pub",
                })
        for v in node.values():
            if isinstance(v, (list, dict)):
                _walk_search_results(v, items, limit)
                if limit and len(items) >= limit:
                    return
    elif isinstance(node, list):
        for child in node:
            _walk_search_results(child, items, limit)
            if limit and len(items) >= limit:
                return


def _search_media_once(query, filter, limit, token):
    """One raw request to OmniSearch. Returns (items, error_message)."""
    url = (SEARCH_API_URL.format(lang=LANG, filter=filter) + "?" +
           urllib.parse.urlencode({"sort": "rel", "q": query}))
    req = urllib.request.Request(url, headers={
        "User-Agent":    USER_AGENT,
        "Accept":        "application/json",
        "Authorization": f"Bearer {token}",
    })
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
        return [], f"Search failed: {e}"

    # Confirmed live: an auth failure comes back as HTTP 200 with a JSON
    # *list* of RFC-7807-style error objects (status 401 inside), not an
    # HTTPError -- must be checked explicitly, not just caught above.
    if isinstance(data, list):
        detail = data[0].get("title") if data and isinstance(data[0], dict) else None
        return [], f"Search auth error: {detail or 'unknown'}"

    items = []
    _walk_search_results(data.get("results", []), items, limit)
    return items, None


def search_media(query, filter="all", limit=25):
    """v26.08.06.27 (renamed from search_jw -- Kaleb's request for
    generic naming across the plugin contract: this function was
    already usable by any plugin, not JW-specific, just named after
    where it was first written).

    Free-text search against jw.org's real search service (OmniSearch).
    Returns (items, error_message) -- error_message is None on success.

    filter: one of "all", "publications", "videos", "audio", "bible",
    "indexes" (the exact set the search JWT itself is scoped to).

    v0.1.161+: when filter="all" comes back with zero usable items, we
    automatically retry with "publications" then "videos" before giving
    up. Confirmed live this is a real, common gap -- topics like "faith",
    "school", and "daily text" rank WOL articles (which this plugin has
    no download path for) above every actual pub/video in the "all"
    view, even though real matches exist under the narrower filters.
    Only kicks in for the default "all" -- an explicit filter from the
    caller (e.g. the person picked "Videos only") is respected as-is,
    even if it comes back empty, so we don't silently substitute a
    different filter than what was asked for.

    Item dicts come in three flavors, tagged by "_kind":
      "pub"   -- ready to hand straight to download() unchanged (same
                 shape lookup_pub_code()/list_items() already produce).
      "video" -- NOT ready for download_video() yet; only carries
                 "_raw_lank" (no _video_url resolved). Call
                 resolve_search_video_item() on it first -- see that
                 function's docstring for why resolution is lazy here.
      "audio" -- v26.07.10.02: same lazy-resolve shape as "video" --
                 carries "_raw_lank", not ready for download_audio()
                 until resolve_search_audio_item() is called on it."""
    query = (query or "").strip()
    if not query:
        return [], "Enter a search term"
    if len(query) > 200:
        return [], "Search term too long"

    token, err = _get_search_token()
    if err:
        return [], f"Search unavailable: {err}"

    items, err = _search_media_once(query, filter, limit, token)
    if err:
        return [], err

    if not items and filter == "all":
        for fallback in ("publications", "videos"):
            items, err = _search_media_once(query, fallback, limit, token)
            if err:
                return [], err
            if items:
                break

    if not items:
        return [], f'No results for "{query}"'
    return items, None


def resolve_search_video_item(item, quality=None):
    """Resolve a "_kind": "video" item from search_media() into a real
    downloadable item (adds "_video_url") ready for download_video().

    Reuses resolve_video_link() -- the SAME function that already
    resolves in-text video links found inside EPUB chapters -- by
    reconstructing a fake href from the raw lank. This means every edge
    case resolve_video_link() already handles (docid-style links,
    single-video "track=x" pubs, monthly-broadcast pubs needing an
    issue=) is inherited here for free, instead of re-implemented.

    v26.07.20.08: optional `quality`, passed straight through.

    Returns (item, error_message), same contract as resolve_video_link().
    Lazy (called at selection/download time, not at search time) because
    eagerly resolving EVERY video in a result list would mean one extra
    GETPUBMEDIALINKS round-trip per result -- wasteful when the person
    is just browsing search results, not downloading all of them."""
    lank = item.get("_raw_lank")
    if item.get("_kind") != "video" or not lank:
        return None, "Not an unresolved search video item"
    return resolve_video_link("lank=" + lank, quality=quality)


def list_video_items(pub, issue=None, quality=None):
    """Fetch and return the video catalog for a video pub code (e.g. "lffv")
    as a list of item dicts ready for main.py's download-list UI:
    {"title", "subtitle", "filename", "_video_url", "track"}.

    v26.07.20.08: optional `quality` ("480p"/"720p") passed straight to
    _extract_video_tracks() -- see that function's own docstring. None
    (the default, used by every existing call site) preserves the
    original 480p-first behavior exactly.

    v0.1.101: added optional issue (YYYYMM string) -- monthly-broadcast
    pubs like "jwbai" 400 Bad Request without it. Confirmed live: pub=
    jwbai with no issue -> HTTP 400; pub=jwbai&issue=201507 -> resolves
    fine. One-off pubs (e.g. "lffv") don't use issue and ignore it if
    passed (the API param is simply omitted when issue is None).

    v0.1.94: two changes per Kaleb --
    (1) "(With Audio Descriptions)" tracks are separate real videos in
        the API (own track number, own file), not a variant flag -- but
        Kaleb doesn't want them cluttering the list, so they're filtered
        out here by title substring match.
    (2) filename now includes the resolution label, e.g.
        "Never Give Up Hope! (480p).mp4" -- so the label is visible
        directly in ROMS/movies without opening the file.

    Returns (items, error_message). error_message is None on success."""
    params = {"pub": pub, "langwritten": LANG, "fileformat": "MP4",
              "alllangs": "0", "output": "json"}
    if issue:
        params["issue"] = issue
    url = API_BASE + "?" + "&".join(
        f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
    try:
        data = _get_json(url)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
        return [], str(e)

    tracks = _extract_video_tracks(data, quality=quality)
    if not tracks:
        return [], f'"{pub}" has no videos available'

    items = []
    for t in tracks:
        if "with audio description" in t["title"].lower():
            continue  # v0.1.94: Kaleb doesn't want these in the list
        safe_name = _sanitize_video_filename(t["title"])
        size_mb = t["filesize"] / (1024 * 1024) if t["filesize"] else 0
        items.append({
            "title":       t["title"],
            "subtitle":    f'{t["label"]}  ~{size_mb:.0f} MB',
            "filename":    f"{safe_name} ({t['label']}).mp4",
            "_video_url":  t["url"],
            "track":       t["track"],  # v0.1.98: needed to match an
                                         # in-text "lank=pub-X_NN_VIDEO"
                                         # link back to the right item.
        })
    return items, None


_VIDEO_LINK_RE = re.compile(
    r"lank=pub-([A-Za-z0-9-]+)_(?:(\d{6})_)?(x|\d+)_VIDEO", re.IGNORECASE)
_VIDEO_DOCID_RE = re.compile(r"lank=docid-(\d+)_(\d+)_VIDEO", re.IGNORECASE)


def parse_video_link(href):
    """v0.1.98: does this in-text link (from epub_engine's kind="external"
    LinkSpan) point at a JW video? Formats confirmed via full scans of
    real epubs (wcg_E.epub: 43 links / 11 pub families; lff_E.epub: 430
    links / 14 pub families):
      - lffi_E.epub: "...finder?lank=pub-lffv_11_VIDEO&wtlocale=E"
        (pub + track, no issue)
      - wcg_E.epub: "...lank=pub-jwbai_201507_1_VIDEO..."
        (pub + 6-digit YYYYMM issue + track -- a monthly broadcast pub)
      - wcg_E.epub: "...lank=pub-jwb-102_7_VIDEO..." (pub code itself
        contains a HYPHEN -- JW Broadcasting's numbered-episode style)
      - v0.1.104, lff_E.epub: "...lank=pub-ivfa1_x_VIDEO..." (track is
        the literal letter "x", not a number -- confirmed live these are
        all single-video pubs, e.g. pub=ivfa1 has exactly one track
        regardless, so "x" means "there's only one, don't disambiguate")
      - v0.1.104, lff_E.epub: "...lank=docid-1112024020_1_VIDEO&ts=..."
        (a completely different addressing scheme -- by docid, not pub
        code -- confirmed the API accepts docid= as its own param,
        separate from pub=; the trailing ts=HH:MM:SS-HH:MM:SS is a
        play-range within the video, not a separate file, so we just
        download the whole video same as any other link)
    Returns (kind, pub_or_docid, issue, track):
      - kind="pub": normal case, pub_or_docid is the pub code, track is
        an int, or the literal string "x" for single-video pubs.
      - kind="docid": pub_or_docid is the docid string, issue/track None.
      - kind=None if href doesn't match any known video-link pattern.
    Does NOT hit the network -- just regex matching on the href string."""
    m = _VIDEO_DOCID_RE.search(href or "")
    if m:
        return "docid", m.group(1), None, None
    m = _VIDEO_LINK_RE.search(href or "")
    if not m:
        return None, None, None, None
    pub, issue, track = m.group(1), m.group(2), m.group(3)
    track = track if track.lower() == "x" else int(track)
    return "pub", pub, issue, track


def resolve_video_link(href, quality=None):
    """v0.1.98: full resolve for an in-text video link -- parse_video_link()
    then one GETPUBMEDIALINKS call to find the actual video. Returns
    (item, error_message); item is a dict from list_video_items() (or an
    equivalent one built from a docid lookup) ready for download_video(),
    or None on failure.

    v26.07.20.08: optional `quality` ("480p"/"720p"), passed straight
    through to whichever resolver actually runs. None (default, used by
    every download call site) preserves the original 480p-first behavior.

    v0.1.104: branches on parse_video_link()'s new "kind":
      - "docid": a completely different lookup (GETPUBMEDIALINKS?docid=
        instead of pub=) -- confirmed live this returns its own
        self-contained file list, no separate pub/track matching needed.
      - "pub" with track="x": confirmed live these pubs have exactly one
        video regardless of track number, so just take the first/only
        item instead of matching a specific track.
      - "pub" with a real track number: unchanged from before."""
    kind, ident, issue, track = parse_video_link(href)
    if kind is None:
        return None, "Not a recognized video link"
    if kind == "docid":
        return _resolve_docid_video(ident, quality=quality)
    items, err = list_video_items(ident, issue=issue, quality=quality)
    if err:
        return None, err
    if track == "x":
        return (items[0], None) if items else (None, f'"{ident}" has no videos available')
    for item in items:
        if item.get("track") == track:
            return item, None
    return None, f'Video track {track} not found in "{ident}"'


# v26.07.10.02: audio equivalent of _VIDEO_LINK_RE. Surveyed live this
# session across several search queries ("love", "faith", "prayer",
# "psalm") -- every real audio lank found follows the simple
# "pub-XXX_N_AUDIO" shape (e.g. "pub-osg_102_AUDIO", "pub-sjjc_50_AUDIO",
# "pub-pksjj_137_AUDIO") -- no docid-style or issue-bearing variant seen
# for audio the way video has both. The optional 6-digit issue group is
# kept anyway (same pattern as _VIDEO_LINK_RE) since it costs nothing and
# would just never match if genuinely absent -- safer than assuming this
# survey was exhaustive.
_AUDIO_LINK_RE = re.compile(
    r"lank=pub-([A-Za-z0-9-]+)_(?:(\d{6})_)?(x|\d+)_AUDIO", re.IGNORECASE)


def parse_audio_link(href):
    """v26.07.10.02: audio equivalent of parse_video_link() -- does NOT
    hit the network, just regex matching. Returns (pub, issue, track);
    pub is None if href doesn't match the known audio-link pattern."""
    m = _AUDIO_LINK_RE.search(href or "")
    if not m:
        return None, None, None
    pub, issue, track = m.group(1), m.group(2), m.group(3)
    track = track if track.lower() == "x" else int(track)
    return pub, issue, track


def resolve_audio_link(href):
    """v26.07.10.02: audio equivalent of resolve_video_link() -- one
    list_audio_items() call (no booknum -- every real audio lank found
    this session pointed at song/pub collections like osg/sjjc/sjji/
    pksjj/snv, not NWT Bible-book audio, which isn't linked this way),
    then matches by track number. Returns (item, error_message)."""
    pub, issue, track = parse_audio_link(href)
    if pub is None:
        return None, "Not a recognized audio link"
    items, err = list_audio_items(pub, issue=issue)
    if err:
        return None, err
    if track == "x":
        return (items[0], None) if items else (None, f'"{pub}" has no audio available')
    for item in items:
        if item.get("track") == track:
            return item, None
    return None, f'Audio track {track} not found in "{pub}"'


def resolve_search_audio_item(item):
    """v26.07.10.02: audio equivalent of resolve_search_video_item() --
    same lazy-resolve-at-download-time shape, reusing resolve_audio_link()
    the same way the video version reuses resolve_video_link()."""
    lank = item.get("_raw_lank")
    if item.get("_kind") != "audio" or not lank:
        return None, "Not an unresolved search audio item"
    return resolve_audio_link("lank=" + lank)


def _resolve_docid_video(docid, quality=None):
    """v0.1.104: resolve a docid-based video link (see parse_video_link's
    docstring). GETPUBMEDIALINKS accepts docid as its own top-level param
    (confirmed live -- separate from pub=) and returns a self-contained
    file list for that specific video; the trailing ts=HH:MM:SS-HH:MM:SS
    some of these links carry is a play-range within the video, not a
    separate file, so we download the whole thing same as any other
    link. v26.07.20.08: optional `quality`, same meaning/default as
    list_video_items()'s -- passed straight to _extract_video_tracks()."""
    params = {"docid": docid, "langwritten": LANG, "fileformat": "MP4",
              "alllangs": "0", "output": "json"}
    url = API_BASE + "?" + "&".join(
        f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
    try:
        data = _get_json(url)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
        return None, str(e)
    tracks = _extract_video_tracks(data, quality=quality)
    if not tracks:
        return None, f'docid "{docid}" has no videos available'
    # Prefer the standard 480p rendition same as list_video_items does
    # implicitly via _extract_video_tracks' own ordering; just take the
    # first non-audio-description track here since a docid link always
    # points at exactly one specific video, not a list to pick from.
    t = tracks[0]
    safe_name = _sanitize_video_filename(t["title"])
    size_mb = t["filesize"] / (1024 * 1024) if t["filesize"] else 0
    return {
        "title": t["title"],
        "subtitle": f'{t["label"]}  ~{size_mb:.0f} MB',
        "filename": f"{safe_name} ({t['label']}).mp4",
        "_video_url": t["url"],
        "track": t.get("track"),
    }, None


def find_movies_dir():
    """Locate muOS's native Media Player content folder (ROMS/movies),
    SD1/SD2 aware -- same principle as mux_launch.sh never hardcoding a
    single storage path (see main.py AI NOTES). Checks both real muOS
    mount points and returns the first that exists; falls back to the
    SD1 path (creating it) if neither is found yet, since a video
    download should still succeed on a fresh setup rather than fail.

    v0.1.92: confirmed the "movies" folder name and location against
    Kaleb's own device screenshot (/mnt/sdcard/ROMS/movies).
    v26.07.18.02 (Kaleb's report): /mnt/union/ROMS/... is muOS's actual
    universal shared ROMS mount (SD1+SD2 merged view) -- confirmed
    earlier for the Ports launcher (see _ports_launcher_path() in
    main.py), but this finder never got the same correction. Added as
    the first candidate; /mnt/sdcard and /mnt/mmc kept as fallbacks for
    setups where /mnt/union isn't present."""
    candidates = [
        "/mnt/union/ROMS/movies",
        "/mnt/sdcard/ROMS/movies",
        "/mnt/mmc/ROMS/movies",
    ]
    for path in candidates:
        if os.path.isdir(path):
            return path
    # Neither exists yet -- default to the union mount and create it so
    # the very first video download on a fresh card still works.
    fallback = candidates[0]
    try:
        os.makedirs(fallback, exist_ok=True)
    except OSError:
        pass
    return fallback


def download_video(item, dest_dir):
    """Download the video for `item` (from list_video_items()) into
    dest_dir (normally find_movies_dir()'s result). Same streaming +
    .part-file + atomic-rename pattern as download() below -- see that
    function's docstring for why each piece matters.

    Returns (ok, message, dest_path) -- same contract as download()."""
    # v26.07.15.16: sanitize with basename() before join -- filename
    # comes from jw.org's API, which is trusted, but this is a cheap
    # defense-in-depth guard against a spoofed/MITM'd response trying
    # to write outside dest_dir via "../" segments. Real filenames are
    # unaffected since basename() only strips path separators.
    safe_filename = os.path.basename(item["filename"])
    dest_path = os.path.join(dest_dir, safe_filename)
    if os.path.exists(dest_path):
        return False, f'"{safe_filename}" already downloaded', dest_path

    video_url = item.get("_video_url")
    if not video_url:
        return False, "No video URL resolved for this item", None
    # v26.07.15.17: see matching comment in gutenberg_fetch.py's
    # download() -- guards against a spoofed API response supplying
    # a non-https URL.
    if not video_url.startswith("https://"):
        return False, "Rejected non-https download URL", None

    tmp_path = dest_path + ".part"
    req = urllib.request.Request(video_url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            with open(tmp_path, "wb") as f:
                while True:
                    chunk = resp.read(65536)  # 64 KB chunks -- flat RAM use
                    if not chunk:
                        break
                    f.write(chunk)
        os.replace(tmp_path, dest_path)  # atomic rename
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        return False, f"Download failed: {e}", None

    return True, f'Downloaded "{item["title"]}" to ROMS/movies', dest_path


def list_docid_range_audio(start_docid, end_docid):
    """v26.07.30.20 (Kaleb's follow-up on Article Series audio coverage
    -- real discovery this session): some article-series content (this
    was found via "Bible Verses Explained") is addressable by a plain
    GETPUBMEDIALINKS?docid=X&track=1&fileformat=MP3 call -- no shared
    "pub" code the way Life Stories/More Topics/etc. work, but the
    docids for one series cluster in a tight, confirmed-live numeric
    block (Bible Verses Explained: 502300100-502300162, exactly 55 real
    entries -- verified by scanning well past both edges and finding
    zero hits outside that range). This is NOT screen-scraped HTML --
    every result comes from the same stable JSON API used everywhere
    else in this file, with the real title read directly from the
    response, so it's no more fragile than any other loader here.
    Gaps within the range (a docid with no entry, likely a different
    series or an internal-only ID) are silently skipped, not treated as
    errors. Bounded to at most (end_docid - start_docid + 1) real
    requests, same one-time-cost-then-obvious-to-cache shape as the
    other probing loaders in this file -- callers/UI can still re-fetch
    every time since a fixed range like this is cheap and stable, but a
    future session could add caching here the same way if it's ever
    worth it.
    Returns (items, error_message) matching every other loader's
    contract; error_message is None on success even if some docids in
    the range are gaps."""
    items = []
    for docid in range(start_docid, end_docid + 1):
        params = {"docid": docid, "langwritten": LANG, "fileformat": "MP3", "track": 1}
        url = API_BASE + "?" + urllib.parse.urlencode(params)
        try:
            data = _get_json(url)
        except urllib.error.HTTPError:
            continue  # gap in the range -- not every docid is used
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            continue  # transient failure -- skip this one, don't abort the whole range
        entries = data.get("files", {}).get(LANG, {}).get("MP3", [])
        if not entries or not isinstance(entries[0], dict):
            continue
        entry = entries[0]
        try:
            file_url = entry["file"]["url"]
        except (KeyError, TypeError):
            continue
        title = entry.get("title", f"docid {docid}")
        safe_name = _sanitize_video_filename(title)
        size_mb = entry.get("filesize", 0) / (1024 * 1024) if entry.get("filesize") else 0
        items.append({
            "title":      title,
            "subtitle":   f"MP3  ~{size_mb:.1f} MB",
            "filename":   f"{safe_name}.mp3",
            "_audio_url": file_url,
            "track":      entry.get("track"),
        })
    return items, None


def list_audio_items(pub, issue=None, booknum=None):
    """v26.07.10.01: MP3 equivalent of list_video_items() -- confirmed
    live this session against GETPUBMEDIALINKS?fileformat=MP3 for both
    real cases this is used for: pub=\"nwt\"+booknum (Bible chapter
    audio, e.g. booknum=1 -> 50 Genesis chapters) and pub=\"w\"+issue
    (Watchtower Study Edition per-article audio, e.g. 7 articles for one
    issue). Unlike video, MP3 entries have no rendition/label variants
    to choose between (data[\"files\"][LANG][\"MP3\"] is already a flat
    list, one file per entry) -- confirmed via direct schema inspection,
    so this is simpler than _extract_video_tracks(), no grouping needed.

    Returns (items, error_message), same contract as list_video_items().
    """
    params = {"pub": pub, "langwritten": LANG, "fileformat": "MP3",
              "alllangs": "0", "output": "json"}
    if issue:
        params["issue"] = issue
    if booknum:
        params["booknum"] = str(booknum)
    url = API_BASE + "?" + "&".join(
        f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
    try:
        data = _get_json(url)
    except urllib.error.HTTPError as e:
        # v26.07.30.16 (surfaced by testing the new Publications audio
        # browsing feature -- a pub with no MP3 at all, e.g. "od",
        # returns a real 404, confirmed live): friendlier than the raw
        # "HTTP Error 404: Not Found" this used to show, which reads
        # like an app bug rather than "this title just doesn't have
        # audio" -- matches the wording _resolve_download_url() already
        # uses for the equivalent no-EPUB case.
        if e.code == 404:
            return [], f'"{pub}" has no audio available'
        return [], str(e)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
        return [], str(e)

    try:
        entries = data["files"][LANG]["MP3"]
    except (KeyError, TypeError):
        entries = []
    if not isinstance(entries, list):
        return [], f'"{pub}" has no audio available'

    items = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            url = entry["file"]["url"]
        except (KeyError, TypeError):
            continue
        title = entry.get("title", "audio")
        safe_name = _sanitize_video_filename(title)  # same sanitizer --
                                                       # generic enough,
                                                       # not video-specific
                                                       # despite the name
        size_mb = entry.get("filesize", 0) / (1024 * 1024) if entry.get("filesize") else 0
        items.append({
            "title":       title,
            "subtitle":    f"MP3  ~{size_mb:.1f} MB",
            "filename":    f"{safe_name}.mp3",
            "_audio_url":  url,
            "track":       entry.get("track"),  # v26.07.10.02: needed to
                                                  # match a "lank=pub-X_NN_AUDIO"
                                                  # search result back to
                                                  # the right item, same
                                                  # role list_video_items()'s
                                                  # "track" field already
                                                  # plays for video.
        })
    if not items:
        return [], f'"{pub}" has no audio available'
    return items, None


# v26.08.11 REMOVED: list_watchtower_study_audio() and list_meeting_
# workbook_audio() -- both genuinely unreachable dead code, confirmed
# via a full-codebase search before removal, not assumed. Both were
# the older "resolve just the current/latest issue, no picker" design
# (see the removed AUDIO_SOURCES top-comment this same cleanup pass
# also removed, which described this exact shape) -- fully superseded
# by list_watchtower_audio_issues()/list_mwb_audio_issues() (the real,
# currently-wired "issue_loader" functions) once full back-issue
# browsing replaced "This Week only". list_meeting_workbook_audio()
# explicitly mirrored list_watchtower_study_audio()'s own logic, so
# both went together.


def list_watchtower_audio_issues():
    """v26.07.30.28 (Kaleb: "did we implement the full backlog of
    watchtowers and awakes and study issues too just like epub? but the
    audio?" -- real gap found: confirmed live that audio exists back to
    at least 201601, same historical depth as EPUB, but the app only
    ever offered "This Week"). Returns [(issue, display_label), ...]
    for the audio issue-picker screen, reusing generate_monthly_back_
    issues("w") -- the SAME generator EPUB browsing already uses -- so
    the historical range and labeling are identical, not a second
    implementation to keep in sync. Newest-first, same RSS-then-guess
    resolution the old "This Week only" design used for its single
    current issue, now applied to picking out the top entry here too.

    v26.08.05.10 BUG FIX (found auditing this picker specifically,
    Kaleb's request to extend it): this only ever called generate_
    monthly_back_issues("w"), which is bounded by EARLIEST_MONTHLY_
    ISSUE (Jan 2016) -- the whole 2011-2015 day-based pre-2016 era
    (generate_w_pre2016_issues(), already used by EPUB browsing) was
    silently missing from this picker specifically. Also now includes
    generate_w_early_era_audio_issues() (2008-2009 + Jan-Aug 2011,
    audio-only, no EPUB equivalent -- see that function's own comment
    for exactly how each month was confirmed)."""
    rss_hit = next((issue for pub, _t, issue in check_new_issues() if pub == "w"), None)
    newest = rss_hit or current_issue_guess()
    items = generate_monthly_back_issues("w", newest_issue=newest)
    items += generate_w_pre2016_issues()
    items += generate_w_early_era_audio_issues()
    return [(it["_extra"]["issue"], it["title"]) for it in items]


def list_wp_audio_issues():
    """v26.08.05.10 (Kaleb's request: add a Public Watchtower Audio
    picker, matching the depth of the just-fixed Watchtower Study
    Audio one). Same three-piece assembly: generate_wp_back_issues()
    for 2016-present (already models all three of wp's real eras --
    bi-monthly/tri-annual/annual), generate_wp_pre2016_issues() for
    the 2011-2015 day-based era, generate_wp_early_era_audio_issues()
    for 2008-2009 + Jan-Aug 2011 (audio-only, no EPUB equivalent)."""
    rss_hit = next((issue for pub, _t, issue in check_new_issues() if pub == "wp"), None)
    newest = rss_hit or _wp_valid_issue(current_issue_guess())
    items = generate_wp_back_issues(newest_issue=newest)
    items += generate_wp_pre2016_issues()
    items += generate_wp_early_era_audio_issues()
    return [(it["_extra"]["issue"], it["title"]) for it in items]


def list_awake_audio_issues():
    """v26.08.05.10 (Kaleb's request: add an Awake! Audio picker --
    there wasn't one at all before this, only Watchtower Study and
    Meeting Workbook had back-issue audio browsing). Assembles: the
    current live-resolved latest issue (_g_valid_issue(), in case it's
    moved past AWAKE_BACK_ISSUES' static table), AWAKE_BACK_ISSUES
    itself (2016-present, hard-coded irregular frequency), generate_
    awake_monthly_issues() (Sept 2011-Dec 2015, confirmed-monthly
    era), and generate_g_early_era_audio_issues() (2008-2009 + Jan-Aug
    2011 minus June, audio-only, no EPUB equivalent)."""
    items = []
    latest_g = _g_valid_issue()
    known_issues = {issue for issue, _t in AWAKE_BACK_ISSUES}
    if latest_g not in known_issues:
        theme = _get_cached_theme("g", int(latest_g[:4]))
        title = theme or f"Awake! (issue {latest_g})"
        items.append((latest_g, title))
    items += list(AWAKE_BACK_ISSUES)
    items += [(it["_extra"]["issue"], it["title"]) for it in generate_awake_monthly_issues()]
    items += [(it["_extra"]["issue"], it["title"]) for it in generate_g_early_era_audio_issues()]
    return items


def list_mwb_audio_issues():
    """v26.07.30.28: same idea as list_watchtower_audio_issues(), for
    Meeting Workbook -- reuses generate_mwb_back_issues() (already
    models the 2016-2020 monthly / 2021+ bimonthly frequency change
    correctly, confirmed live earlier this project) rather than
    duplicating that logic here."""
    rss_hit = next((issue for pub, _t, issue in check_new_issues() if pub == "mwb"), None)
    newest = rss_hit or _mwb_probe_furthest_available() or _mwb_valid_issue(current_issue_guess())
    items = generate_mwb_back_issues(newest_issue=newest)
    return [(it["_extra"]["issue"], it["title"]) for it in items]


def list_original_songs_audio():
    """v26.07.15.04 (Kaleb's request, following up on the video-only
    Original Songs entry added under VIDEO_SOURCES): confirmed live via
    jw.org's own finder link (jw.org/finder?...&lank=pub-osg_115_AUDIO)
    that "osg" (Original Songs) has a real standalone MP3 release too --
    list_audio_items("osg") already works with zero changes, same as any
    other pub code (GETPUBMEDIALINKS?pub=osg&fileformat=MP3 returns a
    flat 137-entry list, confirmed live).

    One wrinkle needing a dedicated loader instead of a plain
    AUDIO_SOURCES {"pub": "osg"} entry: about half those 137 entries are
    "(With Audio Descriptions)" narrated duplicates of the other half
    (confirmed live: same songs, titles suffixed, track numbers 500+/
    600+ vs. the plain versions at 1-118) -- filtered out here so the
    picker shows each song once. If audio-described versions are ever
    wanted as their own option, that's a separate AUDIO_SOURCES entry,
    not a flag on this one.
    """
    items, err = list_audio_items("osg")
    if items:
        items = [it for it in items if "(With Audio Descriptions)" not in it.get("title", "")]
    return items, err


def find_music_dir():
    """Locate muOS's native GMU Music Player content folder (ROMS/Music),
    SD1/SD2-aware -- same principle as find_movies_dir() just above.
    v26.07.10.01: \"Music\" (capital M) confirmed against Kaleb's own
    device -- unlike \"movies\", muOS itself has no fixed default naming
    for music content (confirmed via muos.dev docs: content folder names
    are fully user-defined), so this is specifically Kaleb's own setup,
    not a muOS-wide convention.
    v26.07.18.02: /mnt/union/ROMS/... added as first candidate, same
    universal-mount fix as find_movies_dir() -- see that function's
    docstring for the reasoning.
    """
    candidates = [
        "/mnt/union/ROMS/Music",
        "/mnt/sdcard/ROMS/Music",
        "/mnt/mmc/ROMS/Music",
    ]
    for path in candidates:
        if os.path.isdir(path):
            return path
    fallback = candidates[0]
    try:
        os.makedirs(fallback, exist_ok=True)
    except OSError:
        pass
    return fallback


def sanitize_folder_name(label):
    """v26.07.23.03 (Kaleb's request: organize downloads into per-
    category subfolders inside ROMS/Music and ROMS/movies, named after
    the category, e.g. "Kingdom Melodies", "Sing Out Joyfully to
    Jehovah -- Meetings"). Thin public wrapper around
    _sanitize_video_filename() -- same character-safety rules (strips
    /\\:*?"<>|, normalizes JW.org's curly quotes/dashes, collapses
    whitespace) apply equally well to a folder name as a filename, no
    separate implementation needed."""
    return _sanitize_video_filename(label)


def _id3_syncsafe_to_int(b):
    """Converts a 4-byte ID3v2 syncsafe integer (each byte only uses its
    low 7 bits) to a real int -- used for both the overall tag size in
    the 10-byte ID3 header and individual frame sizes in ID3v2.4."""
    return (b[0] << 21) | (b[1] << 14) | (b[2] << 7) | b[3]


def _id3_decode_text_frame(data):
    """Decodes an ID3v2 text frame's payload: first byte is the
    encoding (0=Latin-1, 1=UTF-16 with BOM, 2=UTF-16BE, 3=UTF-8), rest
    is the text itself, often null-terminated."""
    if not data:
        return None
    encoding_byte = data[0]
    text_data = data[1:]
    try:
        if encoding_byte == 0:
            text = text_data.decode('latin-1')
        elif encoding_byte == 1:
            text = text_data.decode('utf-16')
        elif encoding_byte == 2:
            text = text_data.decode('utf-16-be')
        elif encoding_byte == 3:
            text = text_data.decode('utf-8')
        else:
            text = text_data.decode('latin-1', errors='ignore')
    except (UnicodeDecodeError, LookupError):
        return None
    return text.rstrip('\x00').strip() or None


def read_mp3_album_tag(filepath):
    """v26.07.30.32 (Kaleb: "make sure folders collect magazines and
    book into a folder with their appropriate name using the mp3 album
    names"). Reads just the ID3v2 TALB (Album) frame from a real MP3
    file already on disk -- no external tagging library, just enough
    of the ID3v2.2/.3/.4 frame format to find one frame, since that's
    all this needs. Confirmed live this session that JW.org's own MP3s
    carry genuinely useful album tags: Watchtower Study Audio ->
    "The Watchtower, October 2026" (issue-level), Meeting Workbook ->
    "Life and Ministry Meeting Workbook, November-December 2026"
    (issue-level), NWT chapters -> "New World Translation-01_Genesis"
    (book-level) -- exactly the "magazine issue" / "which book" info
    already being tracked separately in folder-naming logic elsewhere
    in this file, but now sourced from the file's own real metadata
    instead of reconstructed by this code.

    NOTE: confirmed live this same session that this is NOT
    universally safe to use for every audio source -- Life Stories'
    album tag is the individual STORY's own title (e.g. LIFE STORIES--
    "My Love for Jehovah Has Sustained Me"), not a stable series-level
    name, so blindly using album for every source would fragment
    Life Stories into one folder per story instead of one shared
    folder. Callers must only use this for sources confirmed to carry
    a stable, shared album name (periodicals and Bible books), not
    apply it universally.

    Returns the decoded album string, or None if the file has no ID3v2
    tag, no TALB frame, or anything about the format doesn't match
    what's expected (never raises -- a missing/malformed tag should
    just mean "fall back to the existing naming", not a hard failure)."""
    try:
        with open(filepath, 'rb') as f:
            header = f.read(10)
            if len(header) < 10 or header[:3] != b'ID3':
                return None
            version = header[3]
            tag_size = _id3_syncsafe_to_int(header[6:10])
            tag_data = f.read(tag_size)
    except OSError:
        return None

    pos = 0
    frame_id_len = 3 if version == 2 else 4
    frame_header_len = 6 if version == 2 else 10
    while pos + frame_header_len <= len(tag_data):
        frame_id_bytes = tag_data[pos:pos + frame_id_len]
        if frame_id_bytes == b'\x00' * frame_id_len:
            break  # padding -- no more real frames
        try:
            frame_id = frame_id_bytes.decode('ascii')
        except UnicodeDecodeError:
            break
        if version == 2:
            frame_size = int.from_bytes(tag_data[pos + 3:pos + 6], 'big')
        elif version == 4:
            frame_size = _id3_syncsafe_to_int(tag_data[pos + 4:pos + 8])
        else:  # version == 3
            frame_size = int.from_bytes(tag_data[pos + 4:pos + 8], 'big')
        frame_start = pos + frame_header_len
        frame_end = frame_start + frame_size
        if frame_size <= 0 or frame_end > len(tag_data):
            break
        if frame_id in ('TALB', 'TAL'):  # TAL is the ID3v2.2 short form
            return _id3_decode_text_frame(tag_data[frame_start:frame_end])
        pos = frame_end
    return None


def classify_audio_folder(folder_name):
    """v26.07.30.30 (Kaleb: "see if we can have a tool migrating files
    if not detects in wrong area"). Given a top-level folder name found
    directly under find_music_dir() (i.e. NOT already nested under
    PLUGIN_NAME -- an old-structure remnant from before this session's
    folder work, or before a later rename), classifies it as one of:
      ("safe", "Group/Category/Leaf")  -- unambiguous, safe to move
      ("ambiguous", reason_string)     -- known, but can't be safely
                                          auto-migrated (ambiguity
                                          explained below)
      ("unknown", None)                -- not recognized at all

    SAFE cases are every source that only ever had ONE possible
    destination even under the old flat structure -- the 7 real Music
    categories, and every Publications entry that isn't per-issue or
    per-book (Life Stories, More Topics, How Your Donations Are Used,
    Bible Verses Explained, From Our Archives, and any individual
    book/brochure/tract title from STATIC_PUBLICATIONS or the
    discovered-pubs cache -- looked up by title, category comes along
    with it).

    AMBIGUOUS cases are Watchtower Study Audio, Meeting Workbook Audio,
    and both Bible editions -- under the OLD flat structure (before
    v26.07.30.24-25's per-book/per-issue subfoldering), every issue's
    or book's files landed in ONE shared folder together with no way
    to tell which issue/book any individual file came from after the
    fact (confirmed this session: different books' same-numbered
    chapters even share the exact same filename, e.g. "Chapter 1.mp3"
    for both Genesis and Exodus -- a real collision bug fixed earlier,
    meaning some of these old files may not even be from the book/
    issue their title implies anymore). Auto-moving these into a
    guessed destination risks silently mislabeling them as the wrong
    issue/book, which is worse than leaving them alone -- these are
    reported for the person's own review instead."""
    music_group = [
        "Original Songs", "\u201cSing Out Joyfully\u201d to Jehovah\u2014Meetings",
        "\u201cSing Out Joyfully\u201d to Jehovah\u2014Vocals",
        "\u201cSing Out Joyfully\u201d to Jehovah\u2014Instrumental",
        "Sing to Jehovah\u2014Chorus", "Children\u2019s Songs", "Kingdom Melodies",
    ]
    for label in music_group:
        if sanitize_folder_name(label) == folder_name:
            return "safe", f"Music/{sanitize_folder_name(label)}"

    flat_publications = ["Life Stories", "More Topics", "How Your Donations Are Used",
                         "Bible Verses Explained", "From Our Archives"]
    for label in flat_publications:
        if sanitize_folder_name(label) == folder_name:
            return "safe", f"Publications/{sanitize_folder_name(label)}"

    ambiguous_labels = {
        "Watchtower Study Audio (This Week)": "mixes every downloaded week's articles together with no way to tell which issue each came from",
        "Watchtower Study Audio": "mixes every downloaded week's articles together with no way to tell which issue each came from",
        "Watchtower Study": "mixes every downloaded week's articles together with no way to tell which issue each came from",
        "Public Watchtower Audio": "mixes every downloaded week's articles together with no way to tell which issue each came from",
        "Public Watchtower": "mixes every downloaded week's articles together with no way to tell which issue each came from",
        "Awake! Audio": "mixes every downloaded week's articles together with no way to tell which issue each came from",
        "Awake!": "mixes every downloaded week's articles together with no way to tell which issue each came from",
        "Meeting Workbook Audio (This Week)": "mixes every downloaded week's articles together with no way to tell which issue each came from",
        "Meeting Workbook Audio": "mixes every downloaded week's articles together with no way to tell which issue each came from",
        "Meeting Workbook": "mixes every downloaded week's articles together with no way to tell which issue each came from",
        "Bible Reading Audio (NWT)": "mixes every downloaded book's chapters together -- different books can even share identical filenames (e.g. \"Chapter 1.mp3\"), so some files here may already be from a different book than their name suggests",
        "New World Translation": "mixes every downloaded book's chapters together -- different books can even share identical filenames (e.g. \"Chapter 1.mp3\"), so some files here may already be from a different book than their name suggests",
        "Bible Reading Audio (1984 Edition)": "mixes every downloaded book's chapters together -- different books can even share identical filenames (e.g. \"Chapter 1.mp3\"), so some files here may already be from a different book than their name suggests",
        "New World Translation (1984 Edition)": "mixes every downloaded book's chapters together -- different books can even share identical filenames (e.g. \"Chapter 1.mp3\"), so some files here may already be from a different book than their name suggests",
    }
    for label, reason in ambiguous_labels.items():
        if sanitize_folder_name(label) == folder_name:
            return "ambiguous", reason

    all_titled_pubs = [(t, c) for _p, t, _e, c in STATIC_PUBLICATIONS]
    all_titled_pubs += [(e.get("title", p), e.get("category")) for p, e in _load_discovered_pubs().items()]
    for title, category in all_titled_pubs:
        if category and sanitize_folder_name(title) == folder_name:
            return "safe", f"Publications/{category}/{sanitize_folder_name(title)}"

    return "unknown", None


def classify_video_folder(folder_name):
    """v26.07.30.30 (Kaleb: "see if we can have a tool migrating files
    if not detects in wrong area" -- same idea as classify_audio_
    folder(), simpler for video). Video never has audio's per-issue/
    per-book ambiguity problem -- VIDEO_SOURCES entries are never
    periodicals with multiple downloadable issues sharing one folder,
    they're just named categories/subcategories, so every genuine old
    video folder maps to exactly one place with total confidence.
    Checks every real top-level AND subcategory label across all of
    VIDEO_SOURCES (103 distinct labels, confirmed live) -- returns
    ("safe", sanitized_label) or ("unknown", None), never "ambiguous"."""
    all_labels = set()
    for src in VIDEO_SOURCES:
        all_labels.add(src["label"])
        for sub in src.get("subcategories", []):
            all_labels.add(sub["label"])
    for label in all_labels:
        if sanitize_folder_name(label) == folder_name:
            return "safe", sanitize_folder_name(label)
    return "unknown", None


def list_local_folder_items(folder_path):
    """v26.07.23.03 (Kaleb's request: "will category pages load with
    the downloaded tracks showing" when there's no internet): scans an
    already-downloaded category subfolder (e.g. ROMS/Music/Kingdom
    Melodies) and returns a synthetic item list built entirely from
    what's actually on the SD card -- no network call at all. Used by
    main.py as a fallback when a live category fetch fails, so a
    category you've already run Download All on (or partly downloaded)
    still shows something useful with zero internet.

    Returned items are shaped compatibly with download_audio()/
    download_video() and _resolve_media_source() (same "title"/
    "filename" keys) but deliberately have NO "_audio_url"/"_video_url"
    -- there's nothing to re-fetch, this IS the local copy. Title is
    just the filename with its extension stripped (no real metadata
    available offline -- durations/track numbers/etc. aren't
    recoverable from a bare .mp3/.mp4 file without a slow audio/video
    header parse, not worth adding for what's meant to be a simple
    fallback listing). Sorted alphabetically since there's no
    publish-date or track-number to sort by here.

    Returns (items, None) -- always succeeds with an empty list rather
    than an error if the folder doesn't exist or has nothing in it, so
    callers can treat "no local copy either" the same as "category was
    never opened before" (both just show 0 items)."""
    if not folder_path or not os.path.isdir(folder_path):
        return [], None
    items = []
    try:
        names = sorted(os.listdir(folder_path))
    except OSError:
        return [], None
    for name in names:
        full = os.path.join(folder_path, name)
        if not os.path.isfile(full):
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext not in (".mp3", ".mp4"):
            continue
        title = os.path.splitext(name)[0]
        try:
            size_mb = os.path.getsize(full) / (1024 * 1024)
        except OSError:
            size_mb = 0
        items.append({
            "title":    title,
            "subtitle": f"{ext[1:].upper()}  ~{size_mb:.1f} MB  (downloaded, offline)",
            "filename": name,
        })
    return items, None


def download_audio(item, dest_dir):
    """Download the MP3 for `item` (from list_audio_items()) into
    dest_dir (normally find_music_dir()'s result). Identical streaming +
    .part-file + atomic-rename pattern as download_video() -- see that
    function's docstring for why each piece matters.

    Returns (ok, message, dest_path) -- same contract as download_video().
    """
    # v26.07.15.16: sanitize with basename() before join -- see the
    # matching comment in download_video() above for why.
    safe_filename = os.path.basename(item["filename"])
    dest_path = os.path.join(dest_dir, safe_filename)
    if os.path.exists(dest_path):
        return False, f'"{safe_filename}" already downloaded', dest_path

    audio_url = item.get("_audio_url")
    if not audio_url:
        return False, "No audio URL resolved for this item", None
    # v26.07.15.17: see matching comment in gutenberg_fetch.py's
    # download().
    if not audio_url.startswith("https://"):
        return False, "Rejected non-https download URL", None

    tmp_path = dest_path + ".part"
    req = urllib.request.Request(audio_url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            with open(tmp_path, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
        os.replace(tmp_path, dest_path)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        return False, f"Download failed: {e}", None

    return True, f'Downloaded "{item["title"]}" to ROMS/Music', dest_path


def download(item, dest_dir):
    """Download the EPUB for `item` into `dest_dir`.

    Two-step process (different from gutenberg_fetch.py's single-step):
      Step 1: call _resolve_download_url() to get a fresh CDN URL from
              GETPUBMEDIALINKS (URLs are time-limited and can change).
      Step 2: stream the EPUB from that URL in 64 KB chunks.

    The streaming + .part temp file pattern is the same as gutenberg_fetch:
    - .part file prevents a corrupt/partial epub appearing in the library
    - 64 KB chunks keep RAM use flat regardless of file size
    - atomic os.replace() is safe even if the process is interrupted

    Called on a background thread by main.py -- never block the UI thread
    with network I/O.

    Returns (ok, message, dest_path) -- same contract as gutenberg_fetch."""
    # v26.07.15.16: sanitize with basename() before join -- see the
    # matching comment in download_video() above for why.
    safe_filename = os.path.basename(item["filename"])
    dest_path = os.path.join(dest_dir, safe_filename)
    if os.path.exists(dest_path):
        return False, f'"{safe_filename}" already in Library', dest_path

    # Step 1: resolve current CDN URL
    epub_url, err = _resolve_download_url(item)
    if err:
        return False, err, None
    if not epub_url:
        return False, "Could not resolve a download link", None
    # v26.07.15.17: see matching comment in gutenberg_fetch.py's
    # download().
    if not epub_url.startswith("https://"):
        return False, "Rejected non-https download URL", None

    # Step 2: stream download
    tmp_path = dest_path + ".part"
    req = urllib.request.Request(epub_url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            with open(tmp_path, "wb") as f:
                while True:
                    chunk = resp.read(65536)  # 64 KB chunks -- flat RAM use
                    if not chunk:
                        break
                    f.write(chunk)
        os.replace(tmp_path, dest_path)  # atomic rename
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        return False, f"Download failed: {e}", None

    # v26.07.30.14: if this pub isn't reachable through the normal
    # category browse yet (came from search or manual code entry),
    # remember it now so it is next time -- best-effort, never blocks
    # or fails the download itself.
    _remember_discovered_pub(item)

    return True, f'Downloaded "{item["title"]}"', dest_path
