"""
PLUGIN_TEMPLATE.py

Template for writing a custom PicoReader downloader plugin.
Copy this file, rename it (e.g. my_source_fetch.py), fill in the
sections marked TODO, and drop it in the PicoReader/ app folder.
PicoReader will detect and load it automatically on next launch --
no other files need to be changed.

HOW LOADING WORKS:
  main.py scans a fixed list of known plugin filenames at startup via a
  defensive try/except __import__ loop. To have your plugin loaded, its
  filename must be added to that list in main.py. If the file is missing
  or fails to import, the app silently skips it -- no crash, no broken
  menu items. Dropping the file back in and restarting restores it.

  See main.py's own "CROSS-FILE ARCHITECTURE MAP" (near the top of that
  file) for the full picture of what belongs in which file across the
  whole project before you start writing -- short version: your plugin
  owns real data and fetch functions only, never screens, button
  handling, or how results get drawn. If you find yourself wanting to
  add UI/navigation code to your plugin file, that almost certainly
  belongs in main.py's generic layer instead, reachable the same way
  every other plugin's results already are.

REQUIREMENTS:
  - Pure Python stdlib only (no pip/external packages).
    PicoReader runs on muOS (MustardOS) on ARM hardware with no pip.
  - Your plugin must deliver EPUB files. Other formats are not supported.
  - Keep memory use bounded -- the target device has 1GB RAM total.
    Stream downloads in chunks (see the example below); don't load
    entire responses into memory at once.
  - Respect the terms of service of any API or website you query.

PLUGIN CONTRACT -- implement all three required items below:
  PLUGIN_NAME       str
  list_items()      function
  download()        function

OPTIONAL FLAGS (declare these at module level if you want them):
  SUPPORTS_SEARCH = True
      Tells main.py to show a Y-button search option in the browse
      screen. Implement list_items(query=...) to handle the typed query.

  SUPPORTS_MANUAL_CODE = True
      Tells main.py to show a Y-button code-entry screen instead of
      search (used for sources that need a specific publication code
      rather than a free-text search). Implement lookup_pub_code() too.

  MANUAL_CODE_HINT = "short hint string"
      One-line hint shown on the code-entry screen, e.g. which codes
      are valid. Only used when SUPPORTS_MANUAL_CODE = True.
"""

import json
import os
import urllib.request
import urllib.error
import urllib.parse

# ---------------------------------------------------------------------------
# REQUIRED: Plugin display name -- shown in the source-picker UI when more
# than one plugin is installed.
# ---------------------------------------------------------------------------
PLUGIN_NAME = "My Source"  # TODO: replace with your source's name

# ---------------------------------------------------------------------------
# OPTIONAL FLAGS -- uncomment whichever apply to your plugin.
# ---------------------------------------------------------------------------
# SUPPORTS_SEARCH = True
# SUPPORTS_MANUAL_CODE = True
# MANUAL_CODE_HINT = "Enter a code, e.g. ABC123"

# ---------------------------------------------------------------------------
# Internal constants -- adjust to suit your source.
# ---------------------------------------------------------------------------
API_BASE = "https://example.com/api/"         # TODO: your API base URL
REQUEST_TIMEOUT = 15                           # seconds
USER_AGENT = "PicoReader/1.0 (muOS EPUB reader; personal, non-commercial)"


# ---------------------------------------------------------------------------
# REQUIRED: list_items(query=None, page=1)
#
# Called by main.py to populate the browse/search results list.
#
# Parameters:
#   query   str or None -- typed search string, or None for default browse
#   page    int         -- 1-based page number for pagination
#
# Returns:
#   (items, has_next, error)
#   items     list of dicts  -- see item dict format below
#   has_next  bool           -- True if page+1 has more results
#   error     str or None    -- human-readable error string, or None on success
#
# Item dict format (all keys required):
#   "title"          str  -- main line shown in the browse list
#   "subtitle"       str  -- dimmer second line (e.g. author name)
#   "filename"       str  -- suggested local filename, no path, e.g. "book.epub"
#   "_download_url"  str  -- direct URL passed to download() below
#
# Extra keys are fine and ignored by main.py.
# ---------------------------------------------------------------------------
def list_items(query=None, page=1):
    params = {"page": str(page)}
    if query:
        params["search"] = query  # TODO: adjust param name to match your API

    url = API_BASE + "books/?" + urllib.parse.urlencode(params)  # TODO: adjust path

    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return [], False, str(e)

    items = []
    for result in data.get("results", []):   # TODO: adjust to your API's shape
        epub_url = result.get("epub_url")    # TODO: adjust field name
        if not epub_url:
            continue
        items.append({
            "title":         result.get("title", "(untitled)"),
            "subtitle":      result.get("author", "Unknown author"),
            "filename":      _safe_filename(result.get("title", ""), result.get("id")),
            "_download_url": epub_url,
        })

    has_next = bool(data.get("next"))        # TODO: adjust to your API's shape
    return items, has_next, None


# ---------------------------------------------------------------------------
# REQUIRED: download(item, dest_dir)
#
# Called by main.py (on a background thread) when the user confirms a
# download. Fetch the EPUB and write it to dest_dir.
#
# Parameters:
#   item      dict  -- one of the dicts returned by list_items()
#   dest_dir  str   -- absolute path to the PicoReader library folder
#
# Returns:
#   (ok, message, dest_path)
#   ok         bool      -- True on success, False on failure
#   message    str       -- short human-readable status (shown as a toast)
#   dest_path  str|None  -- full path of the saved file on success, else None
# ---------------------------------------------------------------------------
def download(item, dest_dir):
    url = item.get("_download_url")
    if not url:
        return False, "No download URL for this item", None

    dest_path = os.path.join(dest_dir, item["filename"])
    if os.path.exists(dest_path):
        return False, f'"{item["filename"]}" already in Library', dest_path

    tmp_path = dest_path + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            with open(tmp_path, "wb") as f:
                while True:
                    chunk = resp.read(65536)  # 64 KB chunks -- keeps RAM use flat
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

    return True, f'Downloaded "{item["title"]}"', dest_path


# ---------------------------------------------------------------------------
# OPTIONAL: CATEGORIES CONTRACT -- letting people browse by genre/type
# instead of (or in addition to) searching. Everything here is
# optional and works together as one connected feature; you don't
# need any of it for a working plugin.
#
# IN PLAIN ENGLISH: if your source organizes its content into genres,
# subjects, or types (fiction/non-fiction, categories, bookshelves,
# whatever your source calls them), you can let people browse by
# picking one of those instead of typing a search. This is the SIMPLE
# version -- one flat list, pick one, see items in it. If your
# categories nest multiple levels deep (folders inside folders), see
# TREE_CATEGORIES further down this file instead -- that's a separate,
# more advanced feature for that specific case.
#
# SUPPORTS_CATEGORIES = True
#   Turns the category picker on. Without this, main.py skips
#   straight to your item list -- no category screen at all.
#
# CATEGORIES = ["Fiction", "History", "Biography", ...]
#   A plain list of strings -- your category names, in whatever order
#   you want them shown. Only used when SUPPORTS_CATEGORIES = True.
#
# When someone picks one, your list_items(category=...) receives
# whichever exact string they picked, straight from this list --
# handle it there the same way you'd handle a search query.
#
# CATEGORIES_NO_FOLDER = ["Popular", "Latest", "Random", ...]
#   OPTIONAL, only relevant if your download() also organizes saved
#   files into per-category folders (most plugins do this, using
#   CATEGORIES itself as the folder name). Some categories are really
#   "mixed views" that don't represent one single genre -- a "Latest
#   Releases" or "Random Pick" list might contain a history book, a
#   novel, and a biography all together. Saving everything from a view
#   like that into one folder literally named "Latest" would misfile
#   it. List those specific category names here, and main.py will
#   look up EACH ITEM's own real category instead (see resolve_item_
#   category() just below) rather than trusting the mixed view's name.
#
# resolve_item_category(item) -> str or None
#   OPTIONAL, only needed alongside CATEGORIES_NO_FOLDER above. Given
#   one item (the same dict shape list_items() returns), return that
#   ONE item's real, single category -- even though the list it came
#   from was a mixed view. Return None if you genuinely can't tell
#   (main.py then just saves it without a category subfolder, same as
#   if this function didn't exist at all -- never guess). Real
#   working example: gutenberg_fetch.py's "Popular"/"Latest"/"Random"
#   views mix every genre together in the list itself, but each
#   individual book's own detail page still has its real bookshelf
#   tag -- this function looks that up, one extra request per item,
#   only when actually needed.
#
# CATEGORY_VIDEOS = "Videos"   /   CATEGORY_AUDIO = "Audio"
#   OPTIONAL. If two of your CATEGORIES entries are really meant to
#   open the dedicated video/audio browsing screens (see the MEDIA
#   CONTRACT section below) instead of a normal EPUB item list, name
#   them here so main.py can route those two specifically, and leave
#   them out of the plain category list everywhere else (there's no
#   normal EPUB list "under" them to show).
#
# CATEGORY_WHATS_NEW = "New Releases"
#   OPTIONAL, purely cosmetic. If one of your CATEGORIES is powered by
#   a live RSS/new-content feed (rather than your normal catalog), and
#   that feed happens to be empty right now, main.py shows a more
#   accurate "No new publications detected via RSS right now" message
#   instead of a generic "No results" for that specific category.
#   Skip this if none of your categories work that way.
#
# filter_items_with_audio(items) -> filtered list
#   OPTIONAL, only relevant if you ALSO implement the MEDIA CONTRACT
#   below (your plugin has audio). When main.py is specifically
#   browsing your catalog to link items with THEIR OWN audio (not
#   normal EPUB browsing), pass the raw item list through this
#   function to drop anything that doesn't actually have real audio
#   available -- so nothing shown in that specific list fails after
#   someone already picked it. Skip this and nothing gets filtered;
#   only worth adding if you can cheaply tell which of your items have
#   real audio without a slow, individual check per item.
#
# clear_search_token_cache()
#   OPTIONAL, only relevant if your search/list implementation caches
#   some kind of session token, cursor, or credential between calls.
#   main.py calls this (if you define it) whenever someone backs all
#   the way out of your plugin, so the NEXT time they come back it's a
#   clean slate rather than reusing old cached state. Skip this
#   entirely if your list_items()/search doesn't cache anything like
#   that between calls.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# OPTIONAL: lookup_pub_code(code, issue=None)
#
# Only needed if you set SUPPORTS_MANUAL_CODE = True above.
# Called when the user types a code on the manual-entry screen.
#
# Parameters:
#   code   str       -- the typed publication code
#   issue  str|None  -- optional issue identifier (e.g. "202604")
#
# Returns:
#   (item, error)
#   item   dict|None  -- a single item dict (same format as list_items),
#                        or None on failure
#   error  str|None   -- human-readable error, or None on success
# ---------------------------------------------------------------------------
# def lookup_pub_code(code, issue=None):
#     # TODO: look up the code against your API and return one item dict
#     return None, "Not implemented"


# ---------------------------------------------------------------------------
# OPTIONAL: MEDIA CONTRACT -- audio/video download support (Music/Video
# menus), on top of the EPUB contract above.
#
# main.py detects a media-capable plugin by CAPABILITY, not by filename:
# it picks the first DOWNLOAD_PLUGINS module that has list_video_items OR
# AUDIO_SOURCES (see MEDIA_PLUGIN in main.py). Only one media plugin is
# active at a time. Implement whichever of video/audio you support --
# they're independent (a plugin can do audio only, video only, or both).
#
# VIDEO_SOURCES / AUDIO_SOURCES   list of dicts, each:
#   {"label": "Category shown in menu", "loader": "list_video_items",
#    "issue_loader": "list_watchtower_study_audio"}  # issue_loader optional
#   main.py calls getattr(MEDIA_PLUGIN, loader_name)(**kwargs) generically.
#
# list_video_items(pub, issue=None, quality=None) -> (items, error)
# list_audio_items(pub, issue=None, booknum=None) -> (items, error)
#   Same item-dict shape as list_items() above, plus "_download_url" or
#   a link your resolve_*_item()/resolve_*_link() functions can turn into one.
#
# download_video(item, dest_dir) -> (ok, message, dest_path)
# download_audio(item, dest_dir) -> (ok, message, dest_path)
#   Same shape as download() above.
#
# resolve_video_link(href, quality=None) -> (item, error)
# resolve_search_video_item(item, quality=None) -> (item, error)
# resolve_search_audio_item(item) -> (item, error)
# parse_video_link(href) -> (video_kind, ident, issue, track)
#   Needed only if your source resolves playable links lazily (e.g. from
#   search results or in-EPUB links) rather than having a direct URL upfront.
#
# find_movies_dir() / find_music_dir() -> str
#   Return the shared SD-card content folder for video/audio (mirror
#   jw_fetch.py's SD1/SD2-aware logic).
#
# sanitize_folder_name(label) -> str
#   Turns a display label into a filesystem-safe folder name. Used for
#   PLUGIN_NAME's own top-level folder too, so every plugin's downloads
#   land under ROMS/Music/<PLUGIN_NAME>/... and ROMS/movies/<PLUGIN_NAME>/...
#   automatically -- no main.py changes needed for a new plugin's folder.
#
# classify_audio_folder(folder_name) / classify_video_folder(folder_name)
#   -> bool or category label; used by the passive migration check to
#   decide whether an old flat-structure file belongs to your plugin.
#
# list_local_folder_items(folder_path) -> (items, error)
#   Lists already-downloaded files in a folder for offline browsing.
#   This is the OLDER, simpler offline-fallback mechanism -- only
#   consulted automatically when a live category fetch fails. See
#   DOWNLOADED CONTENT below for the newer, always-reachable pattern
#   (a real "Downloaded" entry point, not just a failure fallback).
#
# DOWNLOADED CONTENT (v26.08.07.18-.20) -- OPTIONAL, but recommended
# for any plugin that downloads real files to the device.
#   Two things make this work, and main.py's generic code needs no
#   changes for a new plugin to get it "for free":
#
#   1. A way to REACH the Downloaded view. For an audio/video-capable
#      plugin (VIDEO_SOURCES/AUDIO_SOURCES-shaped), add an entry with
#      "downloaded": True (see jw_fetch.py's AUDIO_SOURCES/
#      VIDEO_SOURCES for the exact shape) -- main.py's button handler
#      checks for this marker BEFORE the normal loader dispatch and
#      routes to a local recursive scan instead
#      (list_local_media_recursive()). For an EPUB/book-shaped plugin
#      with MULTI_FILE downloads (like LibriVox), add a pseudo-
#      category to your CATEGORIES list and intercept it by identity
#      in your own list_items() (or let main.py's category-picker
#      dispatch intercept it before ever calling list_items() at all
#      -- see librivox_fetch.py's CATEGORY_DOWNLOADED for the working
#      example) to return a local folder-folder scan instead of a
#      network fetch.
#
#   2. Item dicts marked so main.py's generic Play/Stream/Delete code
#      recognizes them as already-local, no resolution needed:
#        "_local_path": the file's real absolute path -- checked
#          FIRST by main.py's _resolve_media_source(), before any
#          filename-guessing against the current category context.
#        "_local_folder" / "_local_book_folder": marks a NAVIGABLE
#          folder-level entry (e.g. one category, or one audiobook)
#          rather than a single playable file -- selecting it opens
#          that folder's own contents; deleting it (X quick menu ->
#          Delete) removes the whole folder via shutil.rmtree, not
#          just one file. Both keys are treated identically by the
#          generic delete code (_delete_current_download_item()) --
#          use whichever name reads more naturally for your plugin's
#          own shape (LibriVox uses "_local_book_folder" since each
#          folder really is one book; a plain category folder uses
#          "_local_folder").
#   Once an item carries one of these markers, Play/Stream/Delete all
#   work with zero additional main.py code -- that's the whole rule.
#
# read_mp3_album_tag(filepath) -> str or None
#   OPTIONAL. Only needed if you want album-name subfoldering like
#   Watchtower/Meeting Workbook audio uses; safe to omit otherwise.
#
# search_media(query, filter="all"/"videos"/"audio", limit=25) -> (items, error)
#   OPTIONAL. Only wired up if SUPPORTS_SEARCH-style search into media
#   (not just EPUBs) is desired -- fully generic, any plugin can
#   implement it (renamed from search_jw in v26.08.06.27, since it was
#   already usable by any plugin and the old name was just historical).
#
# BIBLE_BOOKS
#   JW.org-specific (Bible per-book audio nav). Not part of the generic
#   contract -- only relevant if your source has an analogous structure.
#
# parse_epub_filename(filename) -> dict or None
#   OPTIONAL. Given a filename YOUR plugin's own download() produced
#   (e.g. "w_E_202610.epub"), returns a dict describing what it is, or
#   None if the filename doesn't match your naming pattern at all
#   (e.g. it came from a different plugin, or was hand-renamed). This
#   is exact parsing, not a guess -- you control your own naming
#   convention on the way out, so reading it back is deterministic.
#   Powers "Listen to this Book" (main.py's reader-menu feature that
#   offers to find matching audio for whatever EPUB is currently
#   open) -- entirely optional, main.py checks for this attribute via
#   getattr before ever calling it, so omitting it just means your
#   plugin's EPUBs never offer that reader-menu item.
#
#   v26.08.07.05 WARNING (real bug this exact collision caused --
#   see main.py's own v26.08.07.05 changelog entry): this name is
#   ALSO duck-type-checked, together with resolve_item_category()
#   below, by main.py's library-cleanup migration tool for a totally
#   DIFFERENT, STRICTER contract: {"_pub": code} in, real category
#   string out, used to bulk-reclassify old flat-structure EPUBs.
#   If your plugin implements parse_epub_filename()/
#   resolve_item_category() for THIS "Listen to this Book" feature
#   with any other return shape (as gutenberg_fetch.py does -- int
#   book ID, not a dict), you MUST NOT also set
#   SUPPORTS_LOCAL_PUB_CATEGORY_LOOKUP = True (see jw_fetch.py for
#   the one real implementation of that stricter contract) -- doing
#   so tells the migration tool your functions are safe to call with
#   {"_pub": code}-shaped input, which they aren't. Leaving the flag
#   unset/False (the default) is correct and safe for this feature.
#
# find_audio_for_epub(filename, book_title=None, audio_variant=None)
#   -> (audio_items, error)
#   OPTIONAL, only meaningful alongside parse_epub_filename() above.
#   Given a filename your plugin produced (and, for a book with
#   internal chapter/book structure like a Bible, the title of
#   whichever section is currently on screen), return the matching
#   audio track list in the same shape list_audio_items() uses, or
#   (None, "reason") if this specific EPUB has no audio. audio_variant
#   is optional context from get_audio_variants() below -- ignore it
#   entirely if your plugin never returns variant choices.
#
# SUBBOOK_NUM_BY_NAME = {"Genesis": 1, "Exodus": 2, ...}
#   OPTIONAL, only relevant if your source has a Bible (or any other
#   book with the same "one big EPUB containing many separately-
#   titled, individually-numbered sub-books" shape -- named for that
#   pattern itself, not for size or for the Bible specifically) AND
#   you implement find_audio_for_epub() above. When someone's reading
#   one of those sub-books and asks to find its audio, main.py only
#   knows the section's on-screen TITLE (e.g. "Genesis") -- it doesn't
#   know your catalog's own internal numbering scheme for looking that
#   sub-book's audio up. This dict is the translation table: real
#   title (exactly as your own EPUB's table of contents spells it) ->
#   whatever internal number/key your own find_audio_for_epub() needs.
#   If your source has no such numbered-sub-book structure, skip this
#   entirely.
#
# get_audio_variants(pub) -> list of (key, label) pairs, or None
#   OPTIONAL (added v26.08.06.22, generalized from jw_fetch.py's
#   songbook-specific Vocals/Meetings/Instrumental picker -- see that
#   file's own SONGBOOK_PUB_TO_CATEGORY/get_audio_variants() for the
#   reference implementation). Implement this if some of your EPUBs
#   have more than one real, separately-browsable audio rendition to
#   choose between (e.g. a hymnal with vocal/instrumental/rehearsal
#   versions) -- return None for every ordinary pub with just one
#   normal track list (the overwhelmingly common case).
#
#   When main.py's "Listen to this Book" flow calls parse_epub_
#   filename() and gets a real pub code back, it ALSO checks for this
#   optional hook via getattr(MEDIA_PLUGIN, "get_audio_variants",
#   None) -- if you implement it and it returns a non-empty list for
#   that pub, a small generic picker screen (SCREEN_LISTEN_AUDIO_
#   VARIANT) shows your (key, label) pairs verbatim, no plugin- or
#   publication-specific string anywhere in main.py itself, then
#   passes back whichever key was chosen as find_audio_for_epub()'s
#   audio_variant kwarg. A plugin with no need for this just omits the
#   function entirely -- find_audio_for_epub() gets called directly
#   with audio_variant=None, same as before this capability existed.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# OPTIONAL: ADVANCED CAPABILITIES -- nested categories, multi-file
# downloads, streaming, and cross-plugin matching.
#
# Everything below is OPTIONAL and each piece is independent -- use
# only the ones your own source actually needs, in any combination.
# None of this is required to have a working plugin; list_items(),
# download(), and PLUGIN_NAME (further up this file) are enough on
# their own for a normal "browse a list, download one file" plugin.
#
# WHAT "CAPABILITY-BASED" MEANS (read this if you're new to Python or
# to this codebase): main.py never hardcodes "if this is jw_fetch, do
# X" or "if this is my_source_fetch, do Y". Instead, before calling an
# OPTIONAL function, it checks whether your plugin module actually HAS
# that function defined, using Python's built-in hasattr()/getattr():
#
#     if hasattr(my_plugin, "some_optional_function"):
#         result = my_plugin.some_optional_function(...)
#
# This means: if you don't write a function, main.py simply never
# calls it, and the feature it powers is silently unavailable for your
# plugin -- no error, no crash, nothing to configure or turn off. If
# you DO write it (matching the name and arguments described below
# exactly), main.py picks it up automatically the next time the app
# starts. You never edit main.py itself to "turn on" any of these.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# TREE_CATEGORIES = True   (module-level flag)
# + get_category_children(path) -> list of node dicts, or None
#
# IN PLAIN ENGLISH: PicoReader's normal category picker shows a single
# flat list you scroll through top to bottom. If your source's own
# categories naturally NEST -- the way folders can contain folders on
# a computer, e.g. "Non-fiction" contains "History" contains "Ancient
# History" -- you can offer a real drill-down browser instead: the
# person picks "Non-fiction", sees just its children, picks "History",
# sees just ITS children, and so on, with a Back button to go up one
# level at a time. LibriVox's own genre list (145 categories, several
# levels deep) is the real, working example this was built for --
# read librivox_fetch.py's CATEGORY_TREE/get_category_children() for
# the full reference implementation.
#
# If your categories are naturally FLAT (most sources), you don't need
# any of this -- just keep using the plain CATEGORIES list the basic
# contract already supports, and skip this whole section entirely.
#
# HOW TO IMPLEMENT IT:
#   1. Set the flag so main.py knows to use the tree UI instead of the
#      flat one:
#         TREE_CATEGORIES = True
#
#   2. Store your categories as a tree instead of a flat list. A
#      minimal shape (each "node" is just a dict):
#         CATEGORY_TREE = [
#             {"name": "Fiction", "children": [
#                 {"name": "Mystery", "children": []},
#                 {"name": "Science Fiction", "children": []},
#             ]},
#             {"name": "Non-fiction", "children": [
#                 {"name": "History", "children": [
#                     {"name": "Ancient History", "children": []},
#                 ]},
#             ]},
#         ]
#      A node with an empty "children" list (or no real children) is a
#      LEAF -- something the person can actually open and browse
#      items in, like a normal category. A node WITH children is a
#      FOLDER -- picking it just drills one level deeper, it doesn't
#      open a list of downloadable items itself.
#
#   3. Write get_category_children(path):
#         def get_category_children(path):
#             """path: a list of node names from the root down to
#             where the person currently is, e.g. ["Non-fiction",
#             "History"] after they've drilled in twice. An empty
#             list (or None) means "show me the top level"."""
#             nodes = CATEGORY_TREE
#             if not path:
#                 return nodes
#             for name in path:
#                 match = next((n for n in nodes if n["name"] == name), None)
#                 if match is None:
#                     return None  # path no longer valid (e.g. you
#                                  # changed your category list since
#                                  # the person started browsing)
#                 nodes = match["children"]
#             return nodes
#
#   4. Your list_items(category=...) still receives a plain STRING --
#      whichever leaf node's "name" the person picked -- exactly the
#      same way it would if you were only using the flat picker. The
#      tree is purely a NAVIGATION aid; it doesn't change what
#      list_items() itself receives or returns.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# MULTI_FILE = True   (module-level flag)
#
# IN PLAIN ENGLISH: normally, one item in your browse list = one
# downloaded file (one EPUB). Set MULTI_FILE = True if a single item
# in your list actually needs MULTIPLE files saved -- the clearest
# real example is an audiobook, where "one book" means downloading a
# separate audio file for every chapter/track. LibriVox uses this: one
# browse-list entry is a whole audiobook, and download() for it saves
# every track into its own folder.
#
# WHAT CHANGES IF YOU SET THIS:
#   Without MULTI_FILE, main.py expects download(item, dest_dir) to
#   save exactly ONE file and return its path in the 3rd slot of
#   (ok, message, dest_path). With MULTI_FILE = True, main.py instead
#   expects dest_path to be a FOLDER containing every file you saved,
#   and it skips some bookkeeping that only makes sense for a single
#   file (checking for stray leftover files from an old app version,
#   for example -- that logic assumes "one file per item" and would
#   misbehave against a folder of many files).
#
#   dest_dir passed into your download() is already the correct,
#   ready-to-use folder for this item (main.py builds the path, you
#   just create it if needed and save files inside).
#
#   Minimal shape:
#       def download(item, dest_dir):
#           os.makedirs(dest_dir, exist_ok=True)
#           for i, track_url in enumerate(item["_tracks"], start=1):
#               # ... stream track_url into dest_dir/f"Track {i}.mp3" ...
#               pass
#           return True, f'Downloaded "{item["title"]}"', dest_dir
#                                            #  ^ note: the FOLDER,
#                                            #    not one file's path
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# SUPPORTS_STREAMING = True   (module-level flag)
#
# IN PLAIN ENGLISH: "streaming" means the person can start listening/
# watching right away, over the network, without waiting for a full
# download to finish first -- the same way JW.org audio/video already
# works in this app. Set this flag if your source's items can be
# played this way. Without it, your plugin is DOWNLOAD-ONLY: a person
# has to wait for the whole file (or, with MULTI_FILE, all the files)
# to finish saving before they can listen/watch.
#
# WHAT YOU NEED FOR THIS TO WORK: an item shape where each track
# carries a real, ready-to-play URL under the key "_audio_url" (for
# audio) or "_video_url" (for video) -- the exact same field names
# jw_fetch.py's own audio/video items already use, so main.py's
# existing player code works completely unchanged for your plugin
# too. If your source is track-based (like LibriVox, one book = many
# tracks), you'll usually pair this with a function shaped like:
#
#     def list_book_tracks_for_ui(item):
#         """Returns (items, error) -- items is a list of dicts, each
#         with at least "title" and "_audio_url". This is the exact
#         shape main.py's generic audio-list screen expects, so
#         Stream / Play All / Shuffle All / Download all work
#         automatically once this function exists -- no new UI code
#         needed on main.py's side."""
#         ok, msg, tracks = your_real_track_fetch_function(item)
#         if not ok:
#             return [], msg
#         return tracks, None
#
# You don't have to build any player UI yourself -- setting this flag
# (plus supplying real "_audio_url"/"_video_url" values) is the whole
# job. The existing Stream/Play/Download screen handles the rest.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# register_stream_domains(domains)   -- a function YOU CALL, not one
# you implement for main.py to call. Different shape from every other
# capability on this page, so read carefully.
#
# IN PLAIN ENGLISH: this app's media player has a built-in safety
# allowlist -- a list of internet domains (like "archive.org" or
# "jw-cdn.org") it's specifically been told are legitimate media
# sources. This exists so the player never gets silently pointed at
# some arbitrary, unverified URL. If SUPPORTS_STREAMING = True and
# your "_audio_url"/"_video_url" values point at a domain that ISN'T
# already allowed, streaming will be blocked even though everything
# else about your plugin is correct.
#
# The fix is one function call, made ONCE, right when your plugin
# module is first imported (not inside a function -- at the top
# level of your file, so it runs automatically at startup):
#
#     STREAM_DOMAINS = ("archive.org", "librivox.org")
#     try:
#         import native_media
#         native_media.register_stream_domains(STREAM_DOMAINS)
#     except Exception:
#         # native_media isn't available on every device (e.g. no
#         # mpv/ffplay installed) -- that's fine, streaming just won't
#         # be offered there. Download-only still works normally, so
#         # don't let this failure stop your plugin from loading.
#         pass
#
# Only needed if SUPPORTS_STREAMING = True. A download-only plugin
# never touches this at all.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# find_by_gutenberg_id(gb_id, title_hint=None) -> (matches, error)
#
# THIS IS A VERY SPECIFIC, NICHE FEATURE -- skip this section entirely
# unless your source has real audio/video recordings of the SAME
# public-domain books Project Gutenberg's EPUB catalog already
# contains (this app's built-in gutenberg_fetch.py plugin). If that
# doesn't describe your source, you don't need this function.
#
# IN PLAIN ENGLISH: this powers a "Find Audiobook" button that appears
# in the reader when someone's currently reading a book that came from
# Project Gutenberg. Pressing it asks YOUR plugin: "does your catalog
# have an audio recording of this exact book?" main.py finds your
# plugin for this automatically (same capability-detection pattern as
# everywhere else -- whichever loaded plugin has a function with this
# exact name gets used, no naming your plugin a specific thing
# required).
#
# THE ONE RULE THAT MATTERS: a match must be CONFIRMED by a real,
# unique identifier -- Project Gutenberg's own book ID number -- not
# just a similar-looking title. This was a real, live-caught mistake
# during development: two completely different audio recordings of
# "Moby Dick" existed with the SAME title but pointed at two DIFFERENT
# actual Gutenberg source books (different editions/translations).
# Matching by title alone would have confidently linked someone to the
# WRONG audio. If your source can't verify a true ID match somehow
# (for example, by reading it out of the source text's own URL, like
# librivox_fetch.py's reference implementation does), it's better to
# return no results than to guess.
#
# Parameters:
#   gb_id        the Gutenberg book's ID number (e.g. 84 for
#                Frankenstein) -- a string or int, always convert/
#                validate it yourself since it comes from another
#                plugin's data, not something you control
#   title_hint   the book's title, optional -- useful as a first-pass
#                search filter if your source lets you search by
#                title, but never trust it alone for the final match
#
# Returns:
#   (matches, error)
#   matches   list of item dicts, same shape list_items() itself
#             returns -- empty list [] if nothing confirmed, never a
#             guess
#   error     str or None -- a real fetch/network problem, not just
#             "nothing found" (that's an empty list with error=None)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# OPTIONAL: CHECKER CONTRACT -- "new content" checkers, entirely optional,
# entirely capability-based (main.py detects these the exact same way it
# detects everything else in this file: hasattr(plugin, "check_..."), no
# name-lock to any specific plugin, JW-related or otherwise). Implement
# any subset of the three -- each one you add unlocks its own Settings
# action automatically, with zero main.py changes needed:
#
#   check_new_categories()    -> "Check for New Categories" action
#   check_curated_categories() -> "Verify Curated Categories" action
#   check_new_publications()  -> "Check for New Publications" action
#
# Implementing check_new_categories() OR check_new_publications() (either
# one, not both required) also unlocks "Check Reminder" -- a small
# Settings toggle (7d/14d/30d/Manual Only) controlling a quiet
# "[check recommended]" hint next to your checker's own last-checked
# timestamp, and a one-time silent auto-follow-up (fires at most once
# EVER, and only after the person has manually run your checker
# themselves at least once -- this can never make main.py talk to your
# source on its own for someone who's never touched the feature). None of
# that needs building on your end; it's all generic main.py plumbing that
# just needs your checker functions to exist.
#
# check_new_categories() -> (added, removed, error)
#   added/removed   int          -- counts from THIS run
#   error            str|None    -- human-readable error, or None
#   No required behavior beyond the return shape, but the reference
#   implementation (jw_fetch.py) is worth following if your source has
#   an analogous "browsable category tree" concept: walk your source's
#   live category listing, diff against whatever your plugin's own
#   equivalent of VIDEO_SOURCES/AUDIO_SOURCES already hand-curates,
#   and merge only genuinely new entries into a clearly-separate
#   bucket (jw_fetch.py's convention: a "New Categories (...)"
#   top-level entry) -- never silently blend auto-found entries into
#   your hand-reviewed lists. Re-validate previously-found entries
#   each run too if you can (confirmed-gone -> drop, renamed -> sync
#   the label) -- see jw_fetch.py's _revalidate_discovered_cache() for
#   the pattern, including its careful distinction between a
#   confirmed-gone result (safe to prune) and a mere network hiccup
#   (never prune on an inconclusive error).
#
# check_curated_categories()
#   Returns a list of (label, key) pairs for anything in your OWN
#   hand-curated lists that a live check couldn't confirm still
#   exists. Read-only by design -- never auto-edit hand-curated data,
#   just report what looks gone so a human decides. Expect this to be
#   the heaviest of the three (a full sweep of your curated tree) --
#   fine to be noticeably slower than the other two; main.py already
#   labels it as such in its own status message.
#
# check_new_publications()  -> (added, error)
#   Same shape/spirit as check_new_categories() but for individual
#   downloadable items (not categories) -- e.g. new books/titles your
#   source has added. jw_fetch.py's reference implementation scrapes a
#   handful of "what's available" listing pages and verifies each
#   candidate against a real per-item existence check before adding it
#   (the actual "only real, downloadable items" filter) -- adapt
#   "listing page" and "existence check" to whatever your own source
#   actually offers.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _safe_filename(title, book_id):
    """Strips characters that are unsafe in filenames, caps length."""
    import re
    cleaned = re.sub(r"[^\w\s-]", "", title, flags=re.UNICODE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        cleaned = f"book-{book_id}"
    return f"{cleaned[:80]}.epub"
