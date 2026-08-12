"""
librivox_fetch.py

Current version: v26.08.07.23 (matches main.py's date-based scheme,
YY.MM.DD.XX). Inline "# vYY.MM.DD.XX" comments document non-obvious
behavior near the relevant code, same convention used throughout this
project.

Companion PicoReader plugin: two phases of matching a Gutenberg-sourced
EPUB already in the Library to a free public-domain audiobook from
LibriVox (librivox.org).

CORRECTION, 2026-08-05: an earlier version of this docstring claimed
this plugin "reuses epub_engine.py's correlate_toc_to_audio()" and
registers into a main.py list called "AUDIO_LINK_PLUGINS". Neither
exists in the actual codebase -- checked directly, not assumed. That
was written without verifying against source first, which is exactly
backwards from this project's stated workflow. Corrected here: there
is no generic chapter-to-audio-track correlation engine anywhere in
this project to reuse. Wiring LibriVox in means building real
integration in main.py (UI, storage, playback), not calling existing
plumbing. Scoped as two phases (Kaleb, 2026-08-05):
  PHASE 1: standalone LibriVox browsing/search/download, independent
  of any EPUB -- this file's list_items()/link() as already built,
  wired into main.py as a DOWNLOAD_PLUGINS-style source with its own
  download step (not yet written -- see PLANNED DOWNLOAD FOLDER
  STRUCTURE below).
  PHASE 2: from an open Gutenberg-sourced EPUB, find and attach the
  matching LibriVox audiobook using find_by_gutenberg_id() below --
  no chapter/TOC-level sync, just "open this book, also get its
  audio version" at the whole-book level. Chapter-synced playback
  (matching a LibriVox track to the exact page being read) is a
  further-out idea, not scoped yet -- there's no existing sync
  infrastructure and LibriVox track boundaries (e.g. "Chapters 1-3"
  as one file) don't line up cleanly with EPUB page/TOC granularity
  anyway.

WHY PHASE 2 IS ID-CONFIRMED, NOT TITLE-GUESSED (revised 2026-08-05):
  Originally assumed LibriVox and Gutenberg share no ID anywhere and
  matching would have to be manual/search-only. Checked directly and
  that's wrong: LibriVox's own url_text_source field contains the
  real Gutenberg book ID when the recording's source text was
  Gutenberg (e.g. "https://www.gutenberg.org/etext/84" or
  ".../ebooks/84" -- both forms confirmed live). find_by_gutenberg_id()
  below uses this: search LibriVox by the Gutenberg book's own title
  to get candidates, then keep ONLY candidates whose url_text_source
  parses to the exact matching Gutenberg ID -- title alone is proven
  untrustworthy (live-verified: two different "Moby Dick" LibriVox
  projects point to two DIFFERENT Gutenberg IDs, 2701 vs 15 --
  different editions). Multiple confirmed matches are still normal
  and expected (different readers/versions of the same exact
  Gutenberg text) -- the person picks among those, same as Phase 1's
  manual search flow. This is NOT a silent auto-pick; it narrows
  "which LibriVox projects are even candidates" down to ID-confirmed
  ones, then still shows a picker if more than one exists.


LIBRIVOX API -- LIVE-VERIFIED 2026-08-05 against real responses:
  Base: https://librivox.org/api/feed/audiobooks
  Params (confirmed via https://librivox.org/api/info, the official
  docs page): id, since, author, title, genre, extended, coverart,
  limit, offset, fields. title/author/genre support ^ anchoring.
  Formats: xml (default), json, jsonp, serialized, php array.
  No sort/popularity param exists at all -- confirmed by reading the
  full param list on that page. Results come back in the API's own
  default order (looks like ascending project id), not alphabetical.

  Confirmed top-level book fields: id, title, description, language,
  copyright_year, num_sections, url_rss, authors[], totaltime,
  url_iarchive, url_librivox, url_zip_file, url_project, url_other,
  genres[].

  Confirmed: with extended=1, reader names live under
  book["sections"][n]["readers"][n]["display_name"] -- NOT top-level.
  NOTE: display_name can carry a lifespan suffix for deceased readers,
  e.g. "Kara Shallenberg (1969-2023)" -- shown raw in subtitles;
  cosmetic only, not stripped (low priority).

  TITLE PARAM -- LIVE-VERIFIED 2026-08-05, IMPORTANT REAL LIMITATION:
  title= is NOT a substring/contains search. Confirmed live:
  title=Pride (no anchor) -> 404 "could not be found", even though
  "Pride and Prejudice" exists. title=Pride and Prejudice (full exact
  title, no anchor) -> 200. title=^Pride (anchored) -> 200 (prefix
  match from the start of the title). title=^Sherlock -> 404 (no
  title starts with "Sherlock" -- "Adventures of Sherlock Holmes"
  does not). title=Holmes / title=Prejudice (mid-title substrings)
  -> 404 every time. There is no way via this API to search for a
  word anywhere inside a title -- only "starts with" (via ^) or exact
  full match. list_items() below auto-prepends ^ to every query
  unless already present, since prefix search is far more useful than
  requiring an exact full title, but this is still a real UX gap
  worth knowing about: searching "Prejudice" or "Holmes" alone will
  never find "Pride and Prejudice" or "Sherlock Holmes" through this
  plugin. A 404 response from the API is a normal "no match" outcome,
  not a network error -- handled as such in list_items() (returns
  empty results, not an error string).

  GENRE PARAM -- RE-VERIFIED 2026-08-05, PREVIOUS "BUG" NOTE WAS
  STALE AND HAS BEEN REMOVED: earlier project notes described genre=
  breaking on spaces/apostrophes/parens in multi-word genre names,
  with a free-text search=/title= workaround. Live-tested this
  directly against genre=Modern (19th C), genre=Social Science
  (Culture & Anthropology), genre=Young's Literal Translation, and
  genre=War & Military Fiction (all via urllib.parse.urlencode) --
  every one returned correctly filtered results (confirmed by
  checking the genres[] field on returned books). The bug does not
  reproduce today, if it ever applied to this exact param path. As a
  result: genre= is now used verbatim for ALL categories, leaf name
  passed as-is, no free-text fallback anywhere. If this regresses on
  LibriVox's end in the future, the symptom would be a genre pick
  returning unfiltered/irrelevant results -- re-test before
  reintroducing a workaround.

  RSS TRACK ORDER -- confirmed 2026-08-05: a real feed (rss/253) lists
  <item> elements in ASCENDING chapter order already (item 1 =
  <itunes:episode>1</itunes:episode> = "Chapters 1-3"). link() sorts
  explicitly by <itunes:episode> when present (robust even if a
  project's feed isn't strictly sequential) and falls back to feed
  order otherwise. No reverse() call.

  NO OFFICIAL POPULARITY/DOWNLOAD-COUNT FIELD in LibriVox's own feed
  -- so unlike Gutenberg's OPDS "Popular" sort, there is no "Top
  Read" category here sourced from LibriVox's own API, and the docs
  confirm no sort param exists to fake one server-side either.
  Deliberately NOT faking one via a third-party mirror (Archive.org
  download counts) to keep this plugin single-source, matching the
  project's "official source only" convention.

CATEGORY TREE -- FULL HIERARCHY, LIVE-VERIFIED 2026-08-05 against
https://wiki.librivox.org/index.php?title=Genres (source of truth,
human-curated by LibriVox's own volunteer project-setup process).
145 categories total across 3 nesting levels max (e.g. Non-fiction >
History > Modern (20th C)), mirrored exactly as LibriVox structures
it -- per Kaleb's instruction (2026-08-05) to preserve the real
hierarchy rather than flattening or curating a subset. Only "Erotica"
is excluded (see ADULT CONTENT BLOCKING below); every other node from
the wiki page is present, verbatim names, verbatim nesting.

ADULT CONTENT BLOCKING (Kaleb's explicit instruction, 2026-08-05):
  1) CATEGORY-LEVEL: "Erotica" is the only genre on LibriVox's own
     official list that is explicitly adult-content. It is omitted
     from CATEGORY_TREE entirely -- not browsable via any menu path.
     _is_adult_genre() below hard-refuses it in list_items() even if
     ever reached directly (e.g. a stale caller/menu state), as a
     second line of defense beyond "just not in the tree".
  2) FREE-TEXT SEARCH: LibriVox search results carry no per-item
     content-warning field, so free-text title/author search (this
     plugin's primary keyword-search path) cannot be filtered
     per-result the way a category pick can. Best-effort mitigation:
     list_items() drops any result whose title, description, or
     genres[] matches ADULT_KEYWORD_PATTERN. Living safeguard, not a
     guarantee -- same honest caveat as the Gutenberg adult-content
     filter (re-sweep on the project's annual maintenance pass).

DOWNLOAD FOLDER STRUCTURE (implemented, see main.py's own
_category_dest_dir() for the real mechanism): downloaded LibriVox
audio is saved per-book, one subfolder per audiobook, under this
plugin's own folder --
  ROMS/Music/LibriVox/<Book Title>/<NN - track title>.mp3
Top-level folder name comes from PLUGIN_NAME dynamically (resolved by
main.py's generic save logic, not hardcoded) so it's always
"LibriVox", matching whatever this plugin's own PLUGIN_NAME says.
Per-book subfolder is REQUIRED, not optional -- track titles like
"Chapter 1" repeat across nearly every LibriVox project, so two books
sharing one folder would collide/overwrite without it.

PLUGIN CONTRACT (companion/audio-link shape, not the download-plugin
one -- see AI NOTES in main.py for the fuller design writeup once
main.py integration lands):
  PLUGIN_NAME: str
  SUPPORTS_SEARCH = True
  SUPPORTS_CATEGORIES = True
  CATEGORY_TREE: nested list of {"name": str, "genre": str,
      "children": [...]} -- see get_category_children()/
      is_leaf_category() below for the traversal API a menu system
      should use. A node with non-empty "children" is a browsable
      folder, but its "genre" is still a usable filter on its own --
      some LibriVox parents (e.g. "Poetry") are valid genres AND
      have children; passing the parent name filters broadly,
      drilling into a child narrows further.
  list_items(query=None, page=1, category=None) -> (items, has_next, error)
      category, if given, must be a "genre" value from CATEGORY_TREE
      (any node, not just leaves).
      items: list of dicts:
          "title": str            -- LibriVox project title
          "subtitle": str         -- reader name(s) + section count
          "_lv_id": int           -- LibriVox project id
          "_lv_rss": str          -- per-project RSS feed URL
  link(item) -> (ok: bool, message: str, tracks: list[dict]|None)
      Resolves item["_lv_rss"] to the real per-chapter track list, in
      correct chapter order. Each track dict: {"title": str, "url":
      str} -- fed directly into epub_engine.py's
      correlate_toc_to_audio() -- CORRECTED: no such function exists.
      Callers get whole-book track lists to play/download standalone
      (see docstring correction above).
  find_by_gutenberg_id(gb_id, title_hint=None) -> (items, error)
      Phase-2 matcher. See function docstring below.

No pip dependencies -- stdlib urllib + json only. LibriVox's API
supports format=json directly (no XML parsing needed here except in
link(), which parses the per-project RSS feed).

ARCHITECTURE -- see main.py's own "CROSS-FILE ARCHITECTURE MAP" (near
the top of that file) for the full picture of what belongs in which
file across the whole project. Short version for this file: it owns
LibriVox's real data (the genre tree, the real API fetch functions,
folder identity, MULTI_FILE download shape) and the shared plugin
functions every source implements the same way. It does NOT own
screens, button handling, playback controls, or how results get drawn
-- that's all main.py's generic layer (and native_media.py for actual
playback), shared with every other plugin. If you're about to add UI/
navigation/playback code here, it almost certainly belongs in one of
those two files instead.
"""

import json
import os
import re
import urllib.request
import urllib.error
import urllib.parse

# ---------------------------------------------------------------------------
# Plugin identity and capability flags
# ---------------------------------------------------------------------------

PLUGIN_NAME = "LibriVox"

SUPPORTS_SEARCH = True
SUPPORTS_CATEGORIES = True

# v26.08.06.02 (Kaleb's request: real nested drill-down category UI,
# replacing the flat-with-indentation stopgap): tells main.py's
# category picker this plugin's CATEGORY_TREE/get_category_children()
# (both already existed, just unused by the UI until now) can be
# browsed as a real breadcrumb tree instead of the old flat CATEGORIES
# list. CATEGORIES is kept as-is (used by anything not yet updated to
# check this flag, and by _flatten_categories()'s own genre= value
# resolution, which the tree UI also calls into -- see main.py's
# _visible_categories()/open_category() for how the leaf genre value
# is still resolved the same way either path).
TREE_CATEGORIES = True

# v26.08.05.04: tells main.py's download call site this plugin produces
# MANY files per item (a whole audiobook's tracks), not one file
# matching a single item["filename"] like every EPUB plugin -- see the
# MULTI_FILE branch in main.py's start_download()/_do_download(). When
# True, main.py skips its stray-file/migration logic (which assumes
# one file per item) and calls download(item, dest_dir) directly;
# dest_dir is already this plugin's own correct destination folder by
# the time it's passed in, same as any other plugin gets.
MULTI_FILE = True

# v26.08.06.01 (Kaleb's request: "streaming should be the primary
# function... work just like [an]other audio downloader/streamer works
# with mpv"): tells main.py this plugin's book-level items can be resolved
# to a real streamable track list (see list_book_tracks() below) and
# should route through the SAME generic Stream/Play All/Shuffle All/
# Download audio UI other audio-capable plugins in this project use
# (open_plugin_audio_list() + SCREEN_DOWNLOAD_BROWSE with
# dl_is_audio=True) rather than a download-only flow. main.py checks
# this flag before treating a MULTI_FILE audio plugin as download-only.
SUPPORTS_STREAMING = True

API_BASE = "https://librivox.org/api/feed/audiobooks"
USER_AGENT = "PicoReader/muOS (+https://github.com/PuppetHoundZ/PicoReader-MuOS)"
REQUEST_TIMEOUT = 15
PAGE_SIZE = 20

# v26.08.06.01: real track-file hosts, live-confirmed (see the archive.
# org re-test note above list_book_tracks()) -- registered into
# native_media.py's plugin-agnostic streaming allowlist at import time
# so mpv/ffplay are actually allowed to open these URLs directly,
# same registration pattern every streaming-capable plugin in this
# project uses.
STREAM_DOMAINS = ("archive.org", "librivox.org")
try:
    import native_media as _native_media_for_domains
    _native_media_for_domains.register_stream_domains(STREAM_DOMAINS)
except Exception:
    # Streaming module not present/importable on this device (e.g. no
    # mpv/ffplay) -- Download still works via download() below, same
    # graceful-degradation pattern used elsewhere in this project.
    pass

ITUNES_NS = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"

# ---------------------------------------------------------------------------
# Adult-content blocking -- see "ADULT CONTENT BLOCKING" in module
# docstring.
# ---------------------------------------------------------------------------

ADULT_GENRE_BLOCKLIST = {"Erotica"}

ADULT_KEYWORD_PATTERN = re.compile(r"\berotic(a|ism)?\b", re.IGNORECASE)


def _is_adult_genre(genre):
    return bool(genre) and genre in ADULT_GENRE_BLOCKLIST


def _is_adult_result(title, description, genres):
    text = f"{title or ''} {description or ''} {' '.join(genres or [])}"
    return bool(ADULT_KEYWORD_PATTERN.search(text))


# ---------------------------------------------------------------------------
# Category tree -- full LibriVox genre hierarchy, verbatim names and
# nesting from https://wiki.librivox.org/index.php?title=Genres
# (live-verified 2026-08-05). "genre" is the exact string sent to the
# API's genre= param. "Erotica" omitted per ADULT_GENRE_BLOCKLIST.
# ---------------------------------------------------------------------------

def _n(name, children=None):
    return {"name": name, "genre": name, "children": children or []}


CATEGORY_TREE = [
    _n("Children's Fiction", [
        _n("Action & Adventure"), _n("Animals & Nature"),
        _n("Myths, Legends & Fairy Tales"), _n("Family"), _n("General"),
        _n("Historical"), _n("Poetry"), _n("Religion"), _n("School"),
        _n("Short works"),
    ]),
    _n("Children's Non-fiction", [
        _n("Arts"), _n("General"), _n("Reference"), _n("Religion"),
        _n("Science"), _n("History"), _n("Biography"),
    ]),
    _n("Action & Adventure Fiction"),
    _n("Classics (Greek & Latin Antiquity)", [_n("Asian Antiquity")]),
    _n("Crime & Mystery Fiction", [_n("Detective Fiction")]),
    _n("Culture & Heritage Fiction"),
    _n("Dramatic Readings"),
    _n("Epistolary Fiction"),
    _n("Travel Fiction"),
    _n("Family Life"),
    _n("Fantastic Fiction", [
        _n("Myths, Legends & Fairy Tales"), _n("Horror & Supernatural Fiction"),
        _n("Gothic Fiction"), _n("Science Fiction"), _n("Fantasy Fiction"),
    ]),
    _n("Fictional Biographies & Memoirs"),
    _n("General Fiction", [
        _n("Published before 1800"), _n("Published 1800 -1900"),
        _n("Published 1900 onward"),
    ]),
    _n("Historical Fiction"),
    _n("Humorous Fiction"),
    _n("Literary Fiction"),
    _n("Nature & Animal Fiction"),
    _n("Nautical & Marine Fiction"),
    _n("Plays", [
        _n("Comedy", [_n("Satire")]),
        _n("Drama", [_n("Tragedy")]),
        _n("Romance"),
    ]),
    _n("Poetry", [
        _n("Anthologies"), _n("Single author"), _n("Ballads"),
        _n("Elegies & Odes"), _n("Epics"), _n("Free Verse"), _n("Lyric"),
        _n("Narratives"), _n("Sonnets"),
        _n("Multi-version (Weekly and Fortnightly poetry)"),
    ]),
    _n("Religious Fiction", [_n("Christian Fiction")]),
    _n("Romance"),
    _n("Sagas"),
    _n("Satire"),
    _n("Short Stories", [_n("Anthologies"), _n("Single Author Collections")]),
    _n("Sports Fiction"),
    _n("Suspense, Espionage, Political & Thrillers"),
    _n("War & Military Fiction"),
    _n("Westerns"),
    _n("Non-fiction", [
        _n("War & Military"), _n("Animals"), _n("Art, Design & Architecture"),
        _n("Bibles", [
            _n("American Standard Version"), _n("World English Bible"),
            _n("King James Version"), _n("Weymouth New Testament"),
            _n("Douay-Rheims Version"), _n("Young's Literal Translation"),
        ]),
        _n("Biography & Autobiography", [_n("Memoirs")]),
        _n("Business & Economics"), _n("Crafts & Hobbies"),
        _n("Education", [_n("Language learning")]),
        _n("Essays & Short Works"), _n("Family & Relationships"),
        _n("Health & Fitness"),
        _n("History", [
            _n("Antiquity"), _n("Middle Ages/Middle History"),
            _n("Early Modern"), _n("Modern (19th C)"), _n("Modern (20th C)"),
        ]),
        _n("House & Home", [_n("Cooking"), _n("Gardening")]),
        _n("Humor"), _n("Law"),
        _n("Literary Collections", [
            _n("Essays"), _n("Short non-fiction"), _n("Letters"),
        ]),
        _n("Literary Criticism"), _n("Mathematics"), _n("Medical"),
        _n("Music"), _n("Nature"), _n("Performing Arts"),
        _n("Philosophy", [
            _n("Ancient"), _n("Medieval"), _n("Early Modern"), _n("Modern"),
            _n("Contemporary"), _n("Atheism & Agnosticism"),
        ]),
        _n("Political Science"), _n("Psychology"), _n("Reference"),
        _n("Religion", [
            _n("Christianity - Commentary"), _n("Christianity - Biographies"),
            _n("Christianity - Other"), _n("Other religions"),
        ]),
        _n("Science", [
            _n("Astronomy, Physics & Mechanics"), _n("Chemistry"),
            _n("Earth Sciences"), _n("Life Sciences"),
        ]),
        _n("Self-Help"), _n("Social Science (Culture & Anthropology)"),
        _n("Sports & Recreation", [_n("Games")]),
        _n("Technology & Engineering", [_n("Transportation")]),
        _n("Travel & Geography", [_n("Exploration")]),
        _n("True Crime"), _n("Writing & Linguistics"),
    ]),
]


# v26.08.07.18 (Kaleb's request: "we would really need a way to access
# them [downloaded audiobooks]... since they are audio books"). A
# pseudo-category, same pattern used elsewhere in this project for
# special "Downloaded" entries -- main.py's category picker intercepts
# this by identity BEFORE calling open_category()/list_items() at all
# (see main.py's SCREEN_DOWNLOAD_CATEGORIES button handler), routing to a
# local folder scan instead (list_local_book_folders()) -- this
# module never needs filesystem access of its own, keeping the
# plugin-isolation boundary every other plugin already respects.
CATEGORY_DOWNLOADED = "Downloaded Audiobooks"


def _flatten_categories(tree, depth=0, out=None):
    """v26.08.05.04: main.py's standard category picker (_visible_
    categories(), open_category()) is a FLAT single-level list of
    plain strings -- it has no concept of nested drill-down. Rather
    than build a whole new nested-screen system in main.py right now
    (real scope, flagged separately), CATEGORIES below flattens
    CATEGORY_TREE into one indented list so all 145 categories are
    reachable today through the existing generic picker, with visual
    nesting via indentation. list_items() strips the indentation
    before using the string as the genre= value (see there)."""
    if out is None:
        out = []
    for node in tree:
        out.append(("  " * depth) + node["name"])
        _flatten_categories(node["children"], depth + 1, out)
    return out


# NOTE: two different tree branches can share the same leaf name (e.g.
# "General"/"Religion" appear under both Children's Fiction and
# Children's Non-fiction) -- this reflects LibriVox's OWN flat genre
# taxonomy (both resolve to the same genre= value server-side), not an
# ambiguity introduced here. Not treated as a bug.
CATEGORIES = [CATEGORY_DOWNLOADED] + _flatten_categories(CATEGORY_TREE)


def _count_nodes(tree):
    total = 0
    for node in tree:
        total += 1
        total += _count_nodes(node["children"])
    return total


CATEGORY_COUNT = _count_nodes(CATEGORY_TREE)  # 145, live-verified 2026-08-05


def get_category_children(path):
    """path: list of node names from root to a node (e.g.
    ["Non-fiction", "History"]). Empty list/None = root level.
    Returns the list of child node dicts, or None if path not found."""
    nodes = CATEGORY_TREE
    if not path:
        return nodes
    for name in path:
        match = next((n for n in nodes if n["name"] == name), None)
        if match is None:
            return None
        nodes = match["children"]
    return nodes


def is_leaf_category(path):
    children = get_category_children(path)
    return not children


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _api_get(params):
    params = dict(params)
    params.setdefault("format", "json")
    url = API_BASE + "/?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8", errors="replace"))


def _reader_names(book):
    try:
        names = set()
        for section in book.get("sections", []) or []:
            for reader in section.get("readers", []) or []:
                name = reader.get("display_name")
                if name:
                    names.add(name)
        return ", ".join(sorted(names))
    except (AttributeError, TypeError):
        return ""


def _author_names(book):
    # v26.08.07.01 BUG FIX (Kaleb's report: "I see the readers names
    # in the books but it doesn't display the author"). Live-verified
    # 2026-08-07 against the real API (extended=1, already requested
    # by every call site here): book["authors"] is a list of dicts
    # with "first_name"/"last_name" (NOT a single "author" string) --
    # e.g. {"id": "114", "first_name": "Oscar", "last_name": "Wilde",
    # "dob": "1854", "dod": "1900"}. This field was already present in
    # every response this file fetches; it just wasn't read anywhere.
    try:
        names = []
        for author in book.get("authors", []) or []:
            first = (author.get("first_name") or "").strip()
            last = (author.get("last_name") or "").strip()
            full = f"{first} {last}".strip()
            if full and full not in names:
                names.append(full)
        return ", ".join(names)
    except (AttributeError, TypeError):
        return ""


def _book_genres(book):
    out = []
    for g in book.get("genres", []) or []:
        name = g.get("name") if isinstance(g, dict) else g
        if name:
            out.append(name)
    return out


def _book_to_item(book):
    try:
        lv_id = int(book.get("id"))
    except (TypeError, ValueError):
        return None
    title = (book.get("title") or "").strip()
    if not title or not lv_id:
        return None
    genres = _book_genres(book)
    if _is_adult_result(title, book.get("description"), genres):
        return None
    num_sections = book.get("num_sections") or "?"
    author = _author_names(book)
    readers = _reader_names(book)
    # v26.08.07.01 BUG FIX: author now shown ahead of reader(s) --
    # previously subtitle was reader-only, so there was no way to see
    # who wrote the book, only who narrated it.
    bits = []
    if author:
        bits.append(f"by {author}")
    if readers:
        bits.append(f"read by {readers}")
    bits.append(f"{num_sections} sections")
    subtitle = " — ".join(bits)
    return {
        "title": title,
        "subtitle": subtitle,
        "_lv_author": author,
        "_lv_id": lv_id,
        "_lv_rss": book.get("url_rss") or f"https://librivox.org/rss/{lv_id}",
    }


def find_by_gutenberg_id(gb_id, title_hint=None):
    """Phase-2 matching: find LibriVox recordings of a specific
    Gutenberg book, confirmed by exact Gutenberg ID -- not just a
    fuzzy title match. Live-verified 2026-08-05: LibriVox's own
    url_text_source field contains the real Gutenberg ID when the
    text source was Gutenberg (e.g. "https://www.gutenberg.org/
    etext/84" or ".../ebooks/84" -- both forms seen live). This is
    NOT queryable directly via the API (no url_text_source filter
    param exists), so the approach is: search by title_hint (the
    title already known from the open Gutenberg EPUB) to get a
    candidate list, then confirm each candidate against the exact
    gb_id by parsing its url_text_source -- title alone is NOT
    trustworthy, confirmed live: two different "Moby Dick" LibriVox
    projects pointed to two DIFFERENT Gutenberg IDs (2701 vs 15,
    different editions). Only exact-ID-confirmed candidates are
    returned; title-only matches are discarded rather than guessed.

    Returns: (confirmed_items: list, error: str|None)
    """
    if not gb_id:
        return [], "No Gutenberg ID provided"
    try:
        gb_id = int(gb_id)
    except (TypeError, ValueError):
        return [], "Invalid Gutenberg ID"

    query = f"^{_normalize_title_query(title_hint)}" if title_hint else None
    params = {"extended": "1", "limit": str(PAGE_SIZE)}
    if query:
        params["title"] = query

    try:
        data = _api_get(params)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return [], None
        return [], str(e)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
        return [], str(e)

    books = data.get("books") if isinstance(data, dict) else None
    if not books:
        return [], None

    confirmed = []
    for book in books:
        src = book.get("url_text_source") or ""
        m = _GUTENBERG_ID_RE.search(src)
        if not m:
            continue
        if int(m.group(1)) != gb_id:
            continue
        item = _book_to_item(book)
        if item:
            confirmed.append(item)
    return confirmed, None


_GUTENBERG_ID_RE = re.compile(r"gutenberg\.org/(?:etext|ebooks|files)/(\d+)")


# ---------------------------------------------------------------------------
# Required plugin functions
# ---------------------------------------------------------------------------

def _normalize_title_query(title):
    """v26.08.06.12 (Kaleb's request: apply the same title-normalization
    to LibriVox manual search via "Discover More", not just the reader
    screen's Find Audiobook flow). LibriVox systematically drops
    leading articles ("The"/"A"/"An") from its own project titles even
    when the source text keeps one, AND uses a comma where a source
    title uses a colon-introduced subtitle -- both confirmed live
    across 10+ real books this session (Wizard of Oz, Sherlock Holmes,
    Time Machine, Great Gatsby, Picture of Dorian Gray, Hound of the
    Baskervilles, Christmas Carol, Tale of Two Cities, Study in
    Scarlet, Modest Proposal all 404 WITH a leading article, all
    return real hits without one; "The Man Who Was Thursday: A
    Nightmare" 404s, "Man Who Was Thursday" returns 3 real ID-
    confirmed hits). Was originally only applied in main.py's
    _start_find_audiobook() (auto-derived title_hint only); moved here
    so EVERY caller of list_items()/find_by_gutenberg_id() gets it for
    free, including a person's own typed manual search -- no reason to
    make them learn LibriVox's naming quirks by hand. Safe to apply
    unconditionally: a query with no leading article or colon passes
    through completely unchanged (confirmed no real LibriVox title
    ever keeps a leading article, checked across 8 different "The"/"A"
    titles this session), and find_by_gutenberg_id()'s own exact-ID
    check still gates every result regardless of how the search string
    got there."""
    if not title:
        return title
    normalized = re.sub(r"^(The|A|An)\s+", "", title.strip(), flags=re.IGNORECASE)
    if ":" in normalized:
        normalized = normalized.split(":", 1)[0].strip()
    return normalized


def list_items(query=None, page=1, category=None):
    if _is_adult_genre(category):
        return [], False, None

    params = {"extended": "1", "limit": str(PAGE_SIZE)}
    offset = (page - 1) * PAGE_SIZE
    if offset:
        params["offset"] = str(offset)

    if query:
        query = query.strip()
        # v26.08.06.12: normalize BEFORE the ^ auto-anchor below --
        # see _normalize_title_query()'s own docstring. A caller who
        # already typed a leading "^" (an explicit prefix search) is
        # respected as-is; the strip only touches the anchor-less,
        # "just search for this" case every manual search box and
        # Find Audiobook use.
        if not query.startswith("^"):
            query = _normalize_title_query(query)
        # v26.08.05.04: title= only supports "starts with" (via ^) or
        # exact full match -- no substring search exists in this API
        # (see module docstring). Auto-anchor so typed queries behave
        # as prefix search rather than requiring an exact full title.
        params["title"] = query if query.startswith("^") else f"^{query}"
    if category:
        # v26.08.05.04: category may arrive with leading indentation
        # from the flattened CATEGORIES list (see _flatten_categories())
        # -- strip before use. genre= confirmed live to work correctly
        # for every tested multi-word/punctuated genre name, passed
        # verbatim otherwise (see module docstring).
        params["genre"] = category.strip()

    try:
        data = _api_get(params)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            # v26.08.05.04: confirmed live -- a 404 here means "no
            # matching audiobooks", the API's normal empty-result
            # signal for title=/genre= misses, not a real network/
            # server error. Surface as zero results, not an error.
            return [], False, None
        return [], False, str(e)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
        return [], False, str(e)

    books = data.get("books") if isinstance(data, dict) else None
    if books is None:
        return [], False, None

    items = []
    for book in books:
        item = _book_to_item(book)
        if item:
            items.append(item)

    has_next = len(books) >= PAGE_SIZE
    return items, has_next, None


def sanitize_folder_name(label):
    """v26.08.06.24 (Kaleb's request: "anything else we can make
    generic" -- real coupling found during that sweep, not by
    inspection alone). Turns a title/label into a filesystem-safe
    name: strips characters that are risky across filesystems (/, :,
    ?, *, etc.) and typographic punctuation (em dash, curly quotes),
    collapses repeated spaces, and trims to a sane length. Never
    returns an empty string -- falls back to "Untitled" if sanitizing
    would strip everything.

    This used to be borrowed from another plugin in this project via a
    runtime import (with a WEAKER local fallback -- no curly-quote/
    dash normalization -- if that import ever failed) instead of being
    implemented locally like the PLUGIN_TEMPLATE.py contract actually
    documents every plugin doing. Real problem with that: LibriVox is
    meant to be a fully public, independent plugin -- it shouldn't
    depend on any other plugin for anything -- but its OWN downloaded
    folder names were quietly getting LESS robust sanitization
    specifically in a public-only build (where that other plugin isn't
    present at all), the one situation this kind of cross-plugin
    dependency breaks in the first place. Character-safety logic is
    small and completely generic (nothing plugin-specific about
    stripping filesystem-unsafe characters or normalizing curly
    quotes), so it's simply duplicated here now, self-contained, the
    real full implementation, unconditionally, every time -- not the
    weaker fallback."""
    cleaned = label or ""
    cleaned = cleaned.replace("\u2014", "-").replace("\u2013", "-")
    cleaned = cleaned.replace("\u2018", "'").replace("\u2019", "'")
    cleaned = cleaned.replace("\u201c", '"').replace("\u201d", '"')
    bad_chars = '/\\:*?"<>|'
    cleaned = "".join(c for c in cleaned if c not in bad_chars)
    cleaned = " ".join(cleaned.split())  # collapse whitespace runs
    cleaned = cleaned.strip(" .")       # trailing dot/space breaks on some FSes
    if len(cleaned) > 120:
        cleaned = cleaned[:120].rstrip()
    return cleaned or "Untitled"


def _sanitize_name(name):
    # v26.08.05.04: was a runtime import of another plugin's own
    # sanitize_folder_name(), with a weaker local fallback -- see
    # sanitize_folder_name() above (v26.08.06.24) for why that cross-
    # plugin dependency was removed. Now just calls this file's own
    # real implementation directly, no import, no fallback needed
    # (there's nothing that can fail here anymore).
    return sanitize_folder_name(name)


def list_book_tracks(item):
    """v26.08.06.01 (Kaleb's request: streaming as the primary action,
    same as this project's other audio-capable plugins). Wraps link() --
    which already returns real
    per-track dicts with "title"/"url" -- and reshapes them to
    "_audio_url" instead of "url", the exact field name main.py's
    generic audio browse/play code (open_plugin_audio_list(),
    native_media.play_audio_queue()) already expects for every other
    audio plugin. This is the ONLY reshaping needed: no new playback
    code required, the existing Stream/Play All/Shuffle All/Download
    quick-menu and A=Stream button work unchanged once main.py calls
    this instead of download() first for a LibriVox book selection.

    Returns (ok, msg, items) -- items is a list of dicts each with
    "title" and "_audio_url", numbered to preserve LibriVox's own
    chapter order (same sort link() already applies). Empty/failure
    cases mirror link()'s own (ok=False, msg, None)."""
    ok, msg, tracks = link(item)
    if not ok:
        return False, msg, None
    out = []
    for i, t in enumerate(tracks, start=1):
        # v26.08.07.01 BUG FIX (Kaleb's report: "I can't tell what
        # chapter or track I'm on, it's just a list of titles"). A
        # LibriVox section's own "title" (e.g. "Chapters 1 to 3") gives
        # no reliable indication of position in the book -- some are
        # duplicated across very similarly-named books, and no track
        # NUMBER is shown anywhere in the list, unlike some other
        # sources' own lists (which are inherently ordered/numbered
        # content, e.g. Bible chapters). Track number now always prefixed, live-
        # verified against a real multi-section book (Canterville
        # Ghost, LibriVox id 71) so this doesn't just look right in
        # theory.
        raw_title = t.get("title") or f"Track {i}"
        out.append({
            "title": f"{i}. {raw_title}",
            "_audio_url": t.get("url"),
            # v26.08.06.01: carried through so a Download from inside
            # this track-list screen can still land in the same real
            # per-book subfolder download() uses -- main.py's download
            # call site for this plugin reads _lv_book_title/_lv_book
            # the same way it already reads other plugins' per-item
            # download-path hints.
            "_lv_book_title": item.get("title") or "Untitled",
            "_lv_book": item,
        })
    return True, f'{len(out)} tracks', out


def list_book_tracks_for_ui(item):
    """v26.08.06.01: thin adapter for main.py's open_plugin_audio_list(),
    which calls every loader as loader(**kwargs) and expects a plain
    (items, err) two-tuple -- the SAME shape every other audio-capable
    plugin's own list_*_items() functions already return.
    list_book_tracks() above keeps the (ok, msg, items) three-tuple
    shared with link()/download() for direct callers; this just
    reshapes that for the one call site that needs the other contract,
    so neither existing convention has to change."""
    ok, msg, items = list_book_tracks(item)
    if not ok:
        return [], msg
    return items, None


def download(item, dest_dir):
    """MULTI_FILE contract (see MULTI_FILE flag above): dest_dir is
    already this plugin's own real destination folder (main.py's
    _category_dest_dir() -- ROMS/Music/LibriVox/ in practice) by the
    time main.py calls this. Creates a per-book subfolder inside it
    (REQUIRED, not optional -- track filenames like "Chapter 1" repeat
    across nearly every LibriVox project and would collide/overwrite
    otherwise, same per-book-subfolder reasoning used elsewhere in
    this project for the same collision risk) and downloads every
    track into it. Skips tracks whose target filename already exists
    (resumable / re-download-safe, same convention used elsewhere in
    this project) rather than re-fetching everything on a retry after
    a partial failure.

    Returns (ok, msg, path) -- path is the per-book folder itself
    (not a single file), matching what a MULTI_FILE plugin has to
    offer in that slot of the standard plugin contract.
    """
    title = item.get("title") or "Untitled"
    ok, msg, tracks = link(item)
    if not ok:
        return False, msg, None
    if not tracks:
        return False, f'No audio tracks found for "{title}"', None

    book_dir = os.path.join(dest_dir, _sanitize_name(title))
    try:
        os.makedirs(book_dir, exist_ok=True)
    except OSError as e:
        return False, f"Could not create folder: {e}", None

    downloaded = 0
    skipped = 0
    failed = 0
    for i, track in enumerate(tracks, start=1):
        url = track.get("url")
        track_title = track.get("title") or f"Track {i}"
        if not url:
            failed += 1
            continue
        ext = os.path.splitext(urllib.parse.urlparse(url).path)[1] or ".mp3"
        fname = f"{i:02d} - {_sanitize_name(track_title)}{ext}"
        fpath = os.path.join(book_dir, fname)
        if os.path.exists(fpath) and os.path.getsize(fpath) > 0:
            skipped += 1
            continue
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
            with open(fpath, "wb") as f:
                f.write(data)
            downloaded += 1
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            failed += 1
            # v26.08.05.04: one bad track must not abort the whole
            # book -- keep going, report the count at the end. A
            # partial book is still useful; a silent full-abort on
            # track 3 of 22 over a flaky connection would not be.
            continue

    if downloaded == 0 and skipped == 0:
        return False, f'Failed to download any tracks for "{title}"', None

    parts = [f"{downloaded} downloaded"]
    if skipped:
        parts.append(f"{skipped} already present")
    if failed:
        parts.append(f"{failed} failed")
    return True, f'"{title}": ' + ", ".join(parts), book_dir


def link(item):
    rss_url = item.get("_lv_rss")
    if not rss_url:
        return False, "No feed URL for this item", None

    import xml.etree.ElementTree as ET

    req = urllib.request.Request(rss_url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            raw = resp.read()
        root = ET.fromstring(raw)
    except (urllib.error.URLError, TimeoutError, ET.ParseError, OSError) as e:
        return False, f"Could not load track list: {e}", None

    tracks = []
    for item_el in root.findall(".//item"):
        title_el = item_el.find("title")
        enclosure_el = item_el.find("enclosure")
        if title_el is None or enclosure_el is None:
            continue
        url = enclosure_el.get("url")
        if not url:
            continue
        ep_el = item_el.find(f"{ITUNES_NS}episode")
        ep_num = None
        if ep_el is not None and ep_el.text:
            try:
                ep_num = int(ep_el.text.strip())
            except ValueError:
                ep_num = None
        tracks.append({
            "title": (title_el.text or "").strip(),
            "url": url,
            "_ep": ep_num,
        })

    if not tracks:
        return False, "No audio tracks found in feed", None

    if all(t["_ep"] is not None for t in tracks):
        tracks.sort(key=lambda t: t["_ep"])
    for t in tracks:
        t.pop("_ep", None)

    return True, f'Linked "{item["title"]}" ({len(tracks)} tracks)', tracks
