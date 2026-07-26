"""
gutenberg_fetch.py

Current version: v26.07.20.03 (matches main.py's date-based scheme,
YY.MM.DD.XX). Inline "# vYY.MM.DD.XX" comments document non-obvious
behavior near the relevant code, same convention as main.py.

Optional PicoReader plugin: browse and download public-domain EPUBs from
Project Gutenberg via Project Gutenberg's OWN official OPDS catalog feed
(www.gutenberg.org/ebooks/search.opds/) -- switched (v0.1.141) from the
earlier Gutendex-based version. See v0.1.141 changelog in main.py for why.

WHY OPDS INSTEAD OF GUTENDEX:
  Gutendex (gutendex.com) is a solid community project, but it's a THIRD
  PARTY host separate from gutenberg.org -- meaning book search depended on
  a completely different service than the one we actually download EPUBs
  from. OPDS (Open Publication Distribution System) is Project Gutenberg's
  own official catalog feed format, served directly from gutenberg.org --
  the same host every EPUB download already comes from. One trusted host
  instead of two. Confirmed live (2026-07-08): search, pagination, and
  per-book acquisition links (with exact byte sizes and multiple EPUB
  variants -- .epub.images, .epub3.images, .epub.noimages) all work.

  TRADE-OFF, worth knowing: OPDS has no subject/topic FILTER param (unlike
  Gutendex's `topic=`). It only offers three sort orders (downloads/
  release_date/random) plus free-text `query=` (matches title, author, AND
  subject/bookshelf text -- confirmed live: query="Mystery" surfaces real
  mystery novels like Dracula and Sherlock Holmes, not just books with the
  literal word "mystery" in the title). So CATEGORY_TOPIC keywords below
  are now fed through the free-text query param instead of a real filter --
  same category list, slightly fuzzier matching, but genuinely tested
  (unlike the old Gutendex topic= list, which was never live-verified).

  ALSO WORTH KNOWING: gutenberg.org throttles/503s on bursts of rapid
  requests from the same client (confirmed live -- several requests inside
  a couple seconds triggered temporary 403/503s that cleared 15-20s later,
  even with a plain browser User-Agent). This isn't a permanent block and
  isn't User-Agent-specific (our honest, descriptive USER_AGENT below
  works fine once request pacing is reasonable) -- just don't hammer it in
  a tight loop. Normal single-request UI interactions on-device are nowhere
  near this threshold.

  OPDS book-listing entries do NOT include direct download links -- only a
  "subsection" link to that book's own .opds detail page, which DOES have
  the real acquisition links. So download() does one extra request (fetch
  the book's own .opds page, then download the EPUB) -- same two-step
  shape as jw_fetch.py's resolve-then-download pattern elsewhere in this
  project.

THIRD-PARTY API -- NOT OUR CODE, but now the OFFICIAL one:
  This calls Project Gutenberg's own public OPDS feed directly. No
  separate third-party service in the loop for search.

LEGAL: Project Gutenberg content is not restricted by U.S. copyright law
(the vast majority of the catalog). Per Project Gutenberg's own policy
(gutenberg.org/policy/permission.html): "No permission is needed for
non-commercial use... you can freely redistribute any eBook, anywhere,
any time, with or without the 'Project Gutenberg' trademark included."
Safe to publish this file publicly.

HOW PLUGIN LOADING WORKS (so you understand the bigger picture):
  main.py scans a fixed list of known plugin filenames at startup using
  a defensive try/except __import__ loop. If this file is present in the
  PicoReader/ app folder, it gets loaded into DOWNLOAD_PLUGINS and the
  "Download Books" option appears in the Library menu automatically.
  If the file is missing or crashes on import, the app silently skips it
  -- no crash, no broken menu. Drop the file back in and restart to
  restore it. No other files need to be changed.

PLUGIN CONTRACT (see main.py's plugin-loading code for how this is used):
  Every downloader plugin must implement:
    PLUGIN_NAME: str
        Shown in the source-picker UI when more than one plugin is present.
    list_items(query=None, page=1) -> (items, has_next, error)
        items: list of dicts, each with at minimum:
            "title": str            -- shown in the browse list
            "subtitle": str         -- shown as a dimmer second line (e.g. author)
            "filename": str         -- suggested local filename, no path
            "_gb_id": int           -- Gutenberg book ID, resolved to a real
                                        download URL by download() itself
        has_next: bool -- True if page+1 has more results
        error: str or None -- human-readable error, or None on success
    download(item, dest_dir) -> (ok: bool, message: str, dest_path: str|None)
        Resolves item["_gb_id"] to a real EPUB URL (one extra request to
        that book's own .opds detail page), then fetches and writes it to
        dest_dir/filename. Returns a short human-readable status message
        either way (shown as an on-screen toast) and the saved path on
        success.

  Optional flags (declare at module level):
    SUPPORTS_SEARCH = True
        Tells main.py to show a Y-button search entry screen. Implement
        list_items(query=...) to handle the typed search string.
    SUPPORTS_CATEGORIES = True
        Tells main.py to show the category-picker screen before browse.

No pip dependencies -- stdlib urllib + xml.etree.ElementTree only, matching
the rest of PicoReader. The target device (Anbernic RG CubeXX-H, muOS) has
no pip available. Every plugin must be self-contained pure Python stdlib.
xml.etree.ElementTree is already a real dependency elsewhere in this
project (epub_engine.py parses XHTML with it), so this isn't new surface
area.
"""

import os
import re
import urllib.request
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET

# ---------------------------------------------------------------------------
# Plugin identity and capability flags
# ---------------------------------------------------------------------------

PLUGIN_NAME = "Project Gutenberg"

SUPPORTS_SEARCH = True
SUPPORTS_CATEGORIES = True

# ---------------------------------------------------------------------------
# API configuration
# ---------------------------------------------------------------------------

SEARCH_BASE = "https://www.gutenberg.org/ebooks/search.opds/"
PAGE_SIZE = 25

BOOK_DETAIL_URL = "https://www.gutenberg.org/ebooks/{id}.opds"

REQUEST_TIMEOUT = 15

USER_AGENT = "PicoReader/1.0 (muOS EPUB reader; personal, non-commercial)"

NS = {
    "a":    "http://www.w3.org/2005/Atom",
    "opds": "http://opds-spec.org/2010/catalog",
}

_BOOK_HREF_RE = re.compile(r"/ebooks/(\d+)\.opds$")

_EPUB_VARIANT_PREFERENCE = ["EPUB (older E-readers)", "EPUB3 (E-readers incl. Send-to-Kindle)"]

# ---------------------------------------------------------------------------
# Category catalog
# ---------------------------------------------------------------------------

CATEGORY_POPULAR = "Popular"
CATEGORY_LATEST = "Latest"
CATEGORY_RANDOM = "Random"
CATEGORY_ADVENTURE = "Adventure"
CATEGORY_CLASSICS = "Classics"
CATEGORY_SCIFI_FANTASY = "Science Fiction & Fantasy"
CATEGORY_MYSTERY = "Crime, Thrillers & Mystery"
CATEGORY_ROMANCE = "Romance"
CATEGORY_HUMOR = "Humour"
CATEGORY_MYTHOLOGY = "Mythology, Legends & Folklore"
CATEGORY_POETRY = "Poetry"
CATEGORY_PLAYS = "Plays & Drama"
CATEGORY_SHORT_STORIES = "Short Stories"
CATEGORY_CHILDRENS = "Children & Young Adult"
CATEGORY_HISTORY = "History"
CATEGORY_BIOGRAPHIES = "Biographies"
CATEGORY_PHILOSOPHY_RELIGION = "Philosophy & Religion"
CATEGORY_SCIENCE = "Science & Technology"
CATEGORY_TRAVEL = "Travel Writing"

CATEGORIES = [
    CATEGORY_POPULAR, CATEGORY_LATEST, CATEGORY_RANDOM,
    CATEGORY_ADVENTURE, CATEGORY_CLASSICS,
    CATEGORY_SCIFI_FANTASY, CATEGORY_MYSTERY, CATEGORY_ROMANCE,
    CATEGORY_HUMOR, CATEGORY_MYTHOLOGY, CATEGORY_POETRY, CATEGORY_PLAYS,
    CATEGORY_SHORT_STORIES, CATEGORY_CHILDRENS, CATEGORY_HISTORY,
    CATEGORY_BIOGRAPHIES, CATEGORY_PHILOSOPHY_RELIGION, CATEGORY_SCIENCE,
    CATEGORY_TRAVEL,
]

# v26.07.23.06 (Kaleb's request: per-category download subfolders for
# EPUBs, same idea as jw_fetch.py's CATEGORIES_NO_FOLDER -- see that
# one's docstring for the full reasoning). Popular/Latest/Random are
# browse VIEWS across every genre at once, not a genre themselves -- a
# random adventure novel landing in a folder literally named "Random"
# would be a meaningless category to browse later. Every real genre
# bookshelf (Adventure, Classics, Mystery, etc.) still gets its own
# subfolder.
CATEGORIES_NO_FOLDER = [CATEGORY_POPULAR, CATEGORY_LATEST, CATEGORY_RANDOM]

# v0.1.143: Kaleb asked to drop the redundant CATEGORY_TOP100 (our own
# invented label) since it was functionally identical to CATEGORY_POPULAR
# (both sort_order=downloads) -- CATEGORY_POPULAR kept as the sole entry,
# using Project Gutenberg's OWN official label. Confirmed live: the
# top-level OPDS root catalog (www.gutenberg.org/ebooks.opds/) itself
# titles these exact three entries "Popular", "Latest", "Random" --
# these aren't names we made up, they're Project Gutenberg's own naming
# for these three sort orders.
CATEGORY_SORT_ORDER = {
    CATEGORY_POPULAR: "downloads",
    CATEGORY_LATEST:  "release_date",
    CATEGORY_RANDOM:  "random",
}

CATEGORY_TOPIC = {
    CATEGORY_ADVENTURE:            "Adventure",
    CATEGORY_CLASSICS:             "Classic",
    CATEGORY_SCIFI_FANTASY:        "Science Fiction",
    CATEGORY_MYSTERY:              "Mystery",
    CATEGORY_ROMANCE:              "Romance",
    CATEGORY_HUMOR:                "Humor",
    CATEGORY_MYTHOLOGY:            "Mythology",
    CATEGORY_POETRY:               "Poetry",
    CATEGORY_PLAYS:                "Drama",
    CATEGORY_SHORT_STORIES:        "Short Stories",
    CATEGORY_CHILDRENS:            "Children",
    CATEGORY_HISTORY:              "History",
    CATEGORY_BIOGRAPHIES:          "Biography",
    CATEGORY_PHILOSOPHY_RELIGION:  "Philosophy",
    CATEGORY_SCIENCE:              "Science",
    CATEGORY_TRAVEL:               "Travel",
}

# ---------------------------------------------------------------------------
# Adult-content filter (v26.07.20.01) -- always on, no user toggle.
#
# WHY THIS EXISTS: OPDS search.opds results carry only title/author/id per
# entry -- no subject/category tags (confirmed live: a book's own
# {id}.opds detail page DOES carry <category> tags incl. bookshelf/subject
# links, but lightweight search-result entries do not). Per-entry live
# tag-checking isn't possible without an extra request PER RESULT, which is
# both slow on this hardware and against Gutenberg's own ToS ("no more
# requests than a user with a browser would make"). Instead: a static ID
# blocklist snapshotted directly from Gutenberg's own bookshelves/subjects,
# confirmed 2026-07-20, all pages walked until an empty page confirmed the
# end:
#   - Bookshelf 703 "Sexuality & Erotica"        -- 125 IDs
#   - Bookshelf 33  "Erotic Fiction"              -- 16 IDs (overlap)
#   - Subject 10417 "Pornography"                 -- 1 new ID (51015)
#   - All 14 "Erotic *" LCSH subject headings (fiction/literature/poetry,
#     by language: French/Chinese/Latin/Portuguese/American/English, plus
#     "Erotic literature -- History and criticism" and "-- Early works to
#     1800") -- 82 unique IDs, 30 newly found beyond the above
#   - 2 IDs (67025, 29049) found via live "Subject: Erotic literature"
#     per-book tag spot-checks, filed under neither bookshelf nor any of
#     the 14 subject headings above
# 170 unique IDs total, this is now a systematic sweep of every Gutenberg
# LCSH heading with "Erotic" or "Pornography" in the name, not a spot check.
# Backed by a small title/subtitle keyword check as defense-in-depth for
# anything not yet caught by any of the above.
#
# NOTE ON SCOPE -- checked and DELIBERATELY EXCLUDED (legitimate, not
# pornography):
#   - Subject 8217  "Sex instruction" -- historical sex-ed/medical texts
#     (e.g. Margaret Sanger's "What Every Girl Should Know")
#   - Subject 32254 "Sex in literature" -- incl. Jeannette Foster's academic
#     survey "Sex variant women in literature"
#   - Subject 24799 "Sex -- Humor" -- incl. Thurber & E.B. White's classic
#     satire "Is Sex Necessary?"
#   - Subject 33938 "Sex -- Fiction" -- general fiction thematically tagged
#     with sex/relationships (pulp sci-fi, etc.), not erotica
#   - Subject 31474 "Nudity -- Therapeutic use" -- historical German
#     naturism/health-gymnastics text
# A few IDs from subjects 11120 and 15837 (sex-ed/caricature subjects) do
# appear below only because they're independently filed under bookshelf 703
# by Gutenberg itself, not because those subjects were blocked wholesale.
#
# This list is a snapshot, not live -- Gutenberg adds new public-domain
# scans over time. Re-fetch periodically to refresh BLOCKED_GUTENBERG_IDS
# if accuracy drift matters.
BLOCKED_GUTENBERG_IDS = frozenset({
    2959, 2965, 3726, 4300, 5224, 5225, 5325, 6852, 7875, 7889, 13102,
    13161, 13610, 13611, 13612, 13614, 13722, 13971, 13972, 14005, 14323,
    14609, 14969, 15858, 16135, 16820, 16885, 16920, 17707, 17779, 18370,
    18610, 19591, 19924, 20028, 20244, 20568, 21840, 23238, 23609, 23680,
    24156, 24766, 25286, 25305, 25543, 26456, 26562, 26607, 26685, 26739,
    26804, 26806, 26807, 26808, 26809, 26837, 27269, 27827, 28279, 28402,
    28521, 28522, 28718, 28789, 28812, 29049, 29827, 29896, 29903, 30254,
    31284, 31352, 31671, 31732, 36378, 36528, 37356, 37491, 37776, 39220,
    39305, 39938, 40496, 40623, 40877, 40902, 41873, 42075, 42212, 42406,
    42586, 43438, 43712, 43757, 43822, 43823, 44181, 44368, 44877, 45150,
    47482, 47501, 47947, 48943, 49855, 51015, 52059, 52205, 53807, 53823,
    53944, 53964, 54419, 54672, 54713, 56156, 56779, 57284, 57331, 57865,
    57870, 58254, 58475, 58522, 58689, 59827, 60229, 60825, 60827, 60896,
    60918, 60968, 61091, 61162, 61239, 61303, 61408, 61579, 61920, 61980,
    62024, 62120, 62300, 62705, 63246, 63274, 63305, 63329, 63577, 63679,
    64830, 65130, 66565, 66781, 67025, 67026, 67961, 67969, 68400, 69126,
    69311, 69939, 71898, 73144, 76252, 76353, 76646, 76833, 76836,
})

# Keyword backstop -- lowercase substring match against title + subtitle
# (author). Kept short and high-signal on purpose: safety net for gaps in
# the ID snapshot above, not the primary mechanism -- favors precision over
# an exhaustive list that risks false-positives against legitimate
# literature/medical/history titles.
_BLOCKED_KEYWORDS = (
    "erotic", "erotica", "pornograph", "kama sutra",
)


def _is_blocked(item):
    if item.get("_gb_id") in BLOCKED_GUTENBERG_IDS:
        return True
    haystack = f'{item.get("title", "")} {item.get("subtitle", "")}'.lower()
    return any(kw in haystack for kw in _BLOCKED_KEYWORDS)


# v26.07.20.02: live tag check, used only at download time (not display
# time -- see WHY THIS EXISTS above for why display-time results can't
# afford a per-item request). download() already fetches this book's own
# .opds detail page once to resolve the real EPUB URL -- that response DOES
# carry real <category> tags (LCSH subject terms + a "related" link back to
# any bookshelf it's filed under, e.g. title="In Category: Sexuality &
# Erotica..."). Checking those tags here is zero extra network cost and
# catches anything genuinely new that the static snapshot above hasn't seen
# yet -- the live counterpart to the offline blocklist, not a replacement
# for it (still worth having the static list so blocked items never even
# display in the first place).
_LIVE_TAG_KEYWORDS = ("erotic", "pornograph")


def _detail_page_is_blocked(root):
    for cat in root.findall(".//a:entry/a:category", NS):
        term = (cat.get("term") or "").lower()
        if any(kw in term for kw in _LIVE_TAG_KEYWORDS):
            return True
    for link in root.findall(".//a:entry/a:link[@rel='related']", NS):
        title = (link.get("title") or "").lower()
        if any(kw in title for kw in _LIVE_TAG_KEYWORDS):
            return True
    return False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_xml(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/atom+xml",
    })
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        body = resp.read()
    return ET.fromstring(body)


def _safe_filename(title, book_id):
    cleaned = re.sub(r"[^\w\s-]", "", title or "", flags=re.UNICODE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        cleaned = f"gutenberg-{book_id}"
    return f"{cleaned[:80]}.epub"


def _entry_to_item(entry):
    sub = entry.find("a:link[@rel='subsection']", NS)
    href = sub.get("href") if sub is not None else None
    m = _BOOK_HREF_RE.search(href or "")
    if not m:
        return None
    book_id = int(m.group(1))

    title_el = entry.find("a:title", NS)
    title = (title_el.text if title_el is not None else None) or "(untitled)"
    content_el = entry.find("a:content", NS)
    author = (content_el.text if content_el is not None else None) or "Unknown author"

    return {
        "title":    title,
        "subtitle": author,
        "filename": _safe_filename(title, book_id),
        "_gb_id":   book_id,
    }


def _resolve_download_url(book_id):
    url = BOOK_DETAIL_URL.format(id=book_id)
    try:
        root = _get_xml(url)
    except (urllib.error.URLError, TimeoutError, ET.ParseError, OSError) as e:
        return None, str(e)

    # v26.07.20.02: live check against this response's real category/
    # subject tags -- see _detail_page_is_blocked() above. Checked before
    # the static blocklist even matters here, since this catches items the
    # static snapshot doesn't know about yet.
    if _detail_page_is_blocked(root):
        return None, "Can't download this content"

    candidates = {}
    for entry in root.findall("a:entry", NS):
        for link in entry.findall("a:link", NS):
            if (link.get("type") == "application/epub+zip"
                    and link.get("rel") == "http://opds-spec.org/acquisition"):
                candidates[link.get("title", "")] = link.get("href")
    if not candidates:
        for link in root.findall("a:link", NS):
            if (link.get("type") == "application/epub+zip"
                    and link.get("rel") == "http://opds-spec.org/acquisition"):
                candidates[link.get("title", "")] = link.get("href")
    if not candidates:
        return None, "No EPUB available for this book"

    for preferred in _EPUB_VARIANT_PREFERENCE:
        if preferred in candidates:
            return candidates[preferred], None
    return next(iter(candidates.values())), None


# v26.07.23.10 BUG FIX (found immediately after the .09 fix above, while
# spot-checking more books): matching Gutenberg's raw bookshelf text
# against this app's own CATEGORY_* labels via CATEGORY_FOLDER_
# PREFERENCE was too brittle -- Gutenberg's real text often differs
# from this app's simplified wording in small ways ("Children & Young
# Adult READING" vs this app's "Children & Young Adult"; "SCIENCE-
# FICTION & Fantasy" vs "Science Fiction & Fantasy") that a plain
# normalized-string-equality check couldn't see past, silently falling
# through to "first tag anyway" for those books -- the exact bug this
# was supposed to fix, just not caught until testing more than one
# book. Replaced with a simpler, more robust approach: don't try to
# force Gutenberg's own real category text to match this app's browse-
# category wording at all -- just deprioritize a small set of known
# FORMAT categories (short stories, poetry, plays, essays, letters --
# these describe a book's STRUCTURE, not its subject) and use the
# first remaining tag, verbatim, as the folder name. Solves the
# original Sherlock Holmes case (Short Stories filtered out, Crime/
# Mystery kept) without needing any of Gutenberg's real text to
# exactly match anything hardcoded here.
# v26.07.23.11 BUG FIX (found during end-to-end migration testing,
# right after the .10 fix): resolve_item_category() returning
# Gutenberg's raw bookshelf text VERBATIM caused a real fragmentation
# bug -- browsing the real "Crime, Thrillers & Mystery" category (this
# app's own CATEGORY_MYSTERY, with "&") creates one folder, but the
# SAME book auto-resolved from a Popular/Latest/Random mixed view
# returns Gutenberg's raw "Crime, Thrillers and Mystery" (with "and")
# and creates a SECOND, different folder for what's really the same
# genre -- exactly the kind of duplicate-location mess Kaleb's
# migration feature is supposed to prevent, not cause. Fixed by fuzzy-
# matching a resolved raw name back to this app's own CATEGORIES list
# (token-overlap, not exact string equality -- exact matching is too
# brittle against Gutenberg's real wording, see the format-keyword
# filter's own history above) and using the app's canonical label
# whenever there's a strong match, so both code paths always agree on
# one folder name for one real genre. Falls back to Gutenberg's raw
# text only when nothing in CATEGORIES is a good match.
_CATEGORY_STOPWORDS = {"and", "the", "of", "a", "an"}


def _tokenize_category_name(name):
    words = re.findall(r"[a-z0-9]+", name.lower())
    return set(words) - _CATEGORY_STOPWORDS


_CATEGORY_TOKENS = {cat: _tokenize_category_name(cat) for cat in CATEGORIES}


def _match_to_app_category(raw_name):
    """Returns the CATEGORIES entry whose own words are ALL found in
    raw_name's words (extra words in raw_name, like "Reading" tacked
    onto "Children & Young Adult", don't prevent a match) -- or None if
    no category is a strong enough match. Confirmed live this correctly
    unifies: "Crime, Thrillers and Mystery" -> CATEGORY_MYSTERY,
    "Science-Fiction & Fantasy" -> CATEGORY_SCIFI_FANTASY, "Children &
    Young Adult Reading" -> CATEGORY_CHILDRENS, "Classics of
    Literature" -> CATEGORY_CLASSICS."""
    raw_tokens = _tokenize_category_name(raw_name)
    if not raw_tokens:
        return None
    for cat, tokens in _CATEGORY_TOKENS.items():
        if tokens and tokens.issubset(raw_tokens):
            return cat
    return None


_FORMAT_CATEGORY_KEYWORDS = ("short stories", "poetry", "poems", "plays",
                             "drama", "essays", "speeches", "letters")


def resolve_item_category(item):
    """v26.07.23.08/.10 (Kaleb's request: "New Issues, Popular, Latest,
    Random should show category markers from the Gutenberg [detail
    page's] json file" -- Popular/Latest/Random mix every genre
    together, so main.py calls this ONLY for those views to recover
    the book's own real bookshelf instead of leaving it flat.

    List-view results (what populates the browse screen) carry NO
    subject/bookshelf tags at all -- confirmed live, see the CATEGORIES_
    NO_FOLDER comment below and _resolve_download_url()'s own v26.07.20.02
    comment. Only a book's own {id}.opds DETAIL page has them, as
    real <category> LCSH terms plus rel='related' links -- some of
    those links are titled "In Category: <bookshelf name>..." (a real
    ellipsis character, not truncation) when the book is filed under
    one of Gutenberg's own curated bookshelves; others are titled
    differently ("By <author>...", "On <subject>...", or a bookshelf
    name with no "Category:" prefix at all, e.g. "In Detective
    Fiction...") and aren't used here -- only an exact "In Category:"
    prefix is treated as a real genre bookshelf worth a folder.

    Among a book's "In Category:" tags, the first one NOT matching
    _FORMAT_CATEGORY_KEYWORDS is used, verbatim (Gutenberg's own real
    text, not forced onto this app's differently-worded CATEGORIES
    list) -- confirmed live across several books:
      Sherlock Holmes (1661): Short Stories, Crime Thrillers and
        Mystery, British Literature -> "Crime, Thrillers and Mystery"
        (Short Stories filtered out as a format, not a genre)
      Pride and Prejudice (1342) -> "Romance"
      Alice in Wonderland (11)   -> "Children & Young Adult Reading"
      Frankenstein (84)          -> "Science-Fiction & Fantasy"
    Falls back to the first tag found (even if it IS a format category)
    only when every tag on the book is format-only -- still a useful
    folder rather than nothing.

    This is a SEPARATE detail-page fetch from the one download() makes
    moments later to resolve the actual EPUB URL -- an accepted extra
    network round-trip (not the "zero extra cost" reuse the adult-
    content filter gets, since that check runs INSIDE download()'s own
    existing fetch) in exchange for keeping main.py's calling code
    simple: it can call this before deciding on a destination folder,
    independently of whether the download itself later succeeds.
    Returns None (stay flat) on any fetch failure or if the book isn't
    filed under any real "In Category:" bookshelf -- never raises."""
    book_id = item.get("_gb_id")
    if not book_id:
        return None
    url = BOOK_DETAIL_URL.format(id=book_id)
    try:
        root = _get_xml(url)
    except (urllib.error.URLError, TimeoutError, ET.ParseError, OSError):
        return None
    prefix = "In Category:"
    found = []
    for entry in root.findall("a:entry", NS):
        for link in entry.findall("a:link[@rel='related']", NS):
            title = (link.get("title") or "").strip()
            if title.startswith(prefix):
                name = title[len(prefix):].strip().rstrip("\u2026").strip()
                if name:
                    found.append(name)
        break  # OPDS detail pages repeat the same single entry's links
               # across the feed (confirmed live: identical link set
               # appeared twice for id 1661) -- only the first <entry>
               # needs checking, not every one.
    if not found:
        return None
    for name in found:
        if not any(kw in name.lower() for kw in _FORMAT_CATEGORY_KEYWORDS):
            return _match_to_app_category(name) or name
    return _match_to_app_category(found[0]) or found[0]


# ---------------------------------------------------------------------------
# Required plugin functions
# ---------------------------------------------------------------------------

def list_items(query=None, page=1, category=None):
    parts = []
    if query:
        parts.append(query)
    topic = CATEGORY_TOPIC.get(category) if category else None
    if topic:
        parts.append(topic)
    combined_query = " ".join(parts) if parts else None

    params = {}
    if combined_query:
        params["query"] = combined_query
    sort_order = CATEGORY_SORT_ORDER.get(category, "downloads" if category is None else None)
    if sort_order:
        params["sort_order"] = sort_order
    start_index = (page - 1) * PAGE_SIZE + 1
    if start_index > 1:
        params["start_index"] = str(start_index)

    url = SEARCH_BASE + "?" + urllib.parse.urlencode(params)
    try:
        root = _get_xml(url)
    except (urllib.error.URLError, TimeoutError, ET.ParseError, OSError) as e:
        return [], False, str(e)

    items = []
    for entry in root.findall("a:entry", NS):
        item = _entry_to_item(entry)
        if item and not _is_blocked(item):
            items.append(item)
    has_next = root.find("a:link[@rel='next']", NS) is not None
    return items, has_next, None


def download(item, dest_dir):
    book_id = item.get("_gb_id")
    if not book_id:
        return False, "No book ID for this item", None

    # v26.07.20.01: belt-and-suspenders -- list_items() already filters
    # blocked items out of every browse/search/category result, so this
    # should never trigger in normal use. Kept here as a hard backstop in
    # case download() is ever reached some other way with a stale item.
    if _is_blocked(item):
        return False, "Can't download this content", None

    # v26.07.15.16: sanitize with basename() before join -- filename
    # comes from the Gutenberg API response, which is trusted, but
    # this is a cheap defense-in-depth guard against a spoofed/MITM'd
    # response trying to write outside dest_dir via "../" segments.
    # basename() also strips any leading path, so real filenames
    # (always a plain "title.epub" string) are completely unaffected.
    safe_filename = os.path.basename(item["filename"])
    dest_path = os.path.join(dest_dir, safe_filename)
    if os.path.exists(dest_path):
        return False, f'"{safe_filename}" already in Library', dest_path

    url, err = _resolve_download_url(book_id)
    if not url:
        return False, err or "Could not resolve a download link", None

    # v26.07.15.17: gutenberg.org's own OPDS response supplies `url`
    # unvalidated -- if that response were ever spoofed/MITM'd, a
    # non-https URL (e.g. file:// for local-file disclosure) could
    # otherwise be handed straight to urlopen(). Real Gutenberg links
    # are always https, so this costs nothing for legitimate downloads.
    if not url.startswith("https://"):
        return False, "Rejected non-https download URL", None

    tmp_path = dest_path + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
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

    return True, f'Downloaded "{item["title"]}"', dest_path
