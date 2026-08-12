"""
epub_engine.py

Standalone EPUB parsing/navigation engine -- no UI code.
Handles: manifest/spine parsing, table of contents (NCX + nav.xhtml),
internal hyperlink resolution (same-file anchors, cross-file anchors,
footnote/noteref pairs), inline images, and back-stack navigation.

STDLIB ONLY -- no BeautifulSoup/lxml dependency, so this runs on a bare
muOS python3 with zero pip installs. Uses xml.etree.ElementTree, which
handles the well-formed XHTML that real-world EPUB3 files (including JW
publications) produce.

Designed to be UI-agnostic so it can be driven from a terminal or an
SDL2 render loop.

Current version: v26.07.19.01 (matches main.py's date-based scheme,
YY.MM.DD.XX). Non-obvious behavior is explained via inline
"# vYY.MM.DD.XX" comments above the relevant code, same convention as
main.py -- see that file's own AI NOTES header for the full policy.

See main.py's own "CROSS-FILE ARCHITECTURE MAP" for how this file fits
into the whole project -- short version: this is the only file that
parses EPUB structure itself; main.py treats it as a black box that
turns a .epub file into navigable content.
"""

from __future__ import annotations
import zipfile
import posixpath
import bisect
import os
import json
import re
import html
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

NS = {
    "container": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "ncx": "http://www.daisy.org/z3986/2005/ncx/",
    "xhtml": "http://www.w3.org/1999/xhtml",
    "epub": "http://www.idpf.org/2007/ops",
}

# v26.07.15.17: decompression-bomb guard. zipfile.getinfo().file_size is
# read from the zip's central directory (no decompression needed to
# read it), so this check is free. A malicious EPUB could store a tiny
# compressed entry that decompresses to hundreds of MB/GB and exhaust
# the device's 1GB RAM. The largest known REAL single spine file (the
# "Track Your Bible Reading" page, ~4.5M chars) decompresses to well
# under 10MB, so 64MB leaves generous headroom for any real book while
# still refusing anything bomb-sized.
MAX_SINGLE_FILE_DECOMPRESSED_BYTES = 64 * 1024 * 1024

# v0.1.151: populated by main.py at startup (set_active_glyph_subs()),
# after it checks the ACTIVE bundled font's real cmap via
# TTF_GlyphIsProvided32 -- see the call site in main.py right after
# FONT_PATH is resolved for the full reasoning. Starts as an empty dict
# (not a hardcoded per-font table) so that if this module is ever used
# standalone/without main.py calling the setter, text passes through
# unmodified rather than guessing at substitutions for a font state it
# can't actually see.
_ACTIVE_GLYPH_SUBS = {}


def set_active_glyph_subs(subs: dict) -> None:
    """Replace the active glyph-substitution table. Called once by
    main.py at startup with only the entries the active font actually
    needs (i.e. codepoints TTF_GlyphIsProvided32 reported as missing)."""
    global _ACTIVE_GLYPH_SUBS
    _ACTIVE_GLYPH_SUBS = dict(subs)


_LOCAL_TAG_CACHE = {}  # v26.07.11.08: see _local()'s docstring


def _local(tag: str) -> str:
    """v26.07.11.08: memoized. A real book's XML tree has thousands of
    elements but only a few dozen DISTINCT tag names (p, div, span, sup,
    table, tr, td, strong, em, ...) -- profiled at 82,094 calls for the
    real 4.5M-char "Track Your Bible Reading" page, each re-running the
    same split() on a tag string that's almost always been seen before.
    A small dict cache turns nearly all of those into an O(1) lookup
    instead. Same output as before for every input -- pure memoization
    of a deterministic pure function, not a behavior change."""
    cached = _LOCAL_TAG_CACHE.get(tag)
    if cached is not None:
        return cached
    result = tag.split("}", 1)[1] if "}" in tag else tag
    _LOCAL_TAG_CACHE[tag] = result
    return result


def _find_all_local(elem, tagname):
    return [e for e in elem.iter() if _local(e.tag) == tagname]


def _find_local(elem, tagname):
    for e in elem.iter():
        if _local(e.tag) == tagname:
            return e
    return None


def _children_local(elem, tagname):
    return [e for e in elem if _local(e.tag) == tagname]


@dataclass
class TocEntry:
    title: str
    href: str
    level: int
    children: list = field(default_factory=list)


# v26.08.05.01 (Kaleb's request: "listen to this book" audio-EPUB
# linking, built to be reusable by any plugin, not just jw_fetch --
# see main.py's AI NOTES for the fuller design writeup). Deliberately
# a plain module-level function, not a plugin-specific one -- it takes
# and returns generic (title, href-ish) shapes, no jw_fetch/gutenberg_
# fetch coupling, so it can genuinely be reused for a future LibriVox
# chapter-correlation feature without duplicating this logic.
#
# Live-confirmed (real downloaded EPUBs, real GETPUBMEDIALINKS audio
# listings) across three different JW.org publication shapes --
# Watchtower Study (7 articles/7 tracks), Meeting Workbook (9 weeks/9
# tracks), and a Books-category title (6 lessons/6 tracks): the real
# article TOC titles and the real audio track titles are NEVER byte-
# identical (audio adds "(December 7-13)" date suffixes, the EPUB has
# zero-width spaces mid-title, curly vs straight quotes) -- so this
# matches by POSITION after stripping known boilerplate, not by text.
# Each publication's front/back-matter boilerplate count differs (2
# front/1 back for periodicals, 2 front/2 back for the Books title
# tested), so boilerplate is identified by LABEL, not a fixed offset.
NON_CONTENT_TOC_LABELS = {
    "table of contents", "contents", "title page", "title page/publishers\u2019 page",
    "title page/publishers' page", "media", "page navigation",
    "bible navigation", "cover", "inside cover", "back cover", "copyright page",
    "track your bible reading", "maps", "image index", "scripture index",
    "index of illustrations (parables)", "the areas where jesus lived and taught",
    "featured content in jw library and on jw.org",
}

# v26.08.05.04 BUG FIX (found by Kaleb explicitly asking to test more
# titles -- Walk Courageously With God and the full Enjoy Life Forever
# course both silently landed on the WRONG track before this fix, not
# an error, which is worse: "Walk Courageously With God" has an
# "Inside Cover" TOC entry (added to NON_CONTENT_TOC_LABELS above,
# confirmed live: 68 TOC entries - 5 boilerplate = 63, matching 63
# real audio tracks exactly). "Enjoy Life Forever -- An Interactive
# Bible Course" additionally has "Media for Section 1" through "Media
# for Section 4" -- a PER-BOOK, NUMBERED label (not a fixed string, so
# it can't live in the plain set above) -- confirmed live these have
# no matching audio track (72 real audio tracks; "Am I Ready?" and
# "Endnotes" DO have real tracks and must NOT be stripped, only the
# numbered "Media for Section N" pages don't). Matched via regex
# rather than guessing a fixed count of sections, since a future book
# could have any number of them.
NON_CONTENT_TOC_PATTERNS = [
    re.compile(r"^media for section \d+$", re.IGNORECASE),
]


# v26.08.05.06 (Kaleb's idea: "is it possible to get information on
# the chapter title or number to match the track too" -- from within
# the actual page content, not just the TOC label). This is a genuine
# upgrade over correlate_toc_to_audio() above, not a replacement: JW.org
# publications embed a small, structured label on each content page --
# a <p class="contextTtl"> paragraph (numbers for books: "26 NATHAN",
# "SECTION 1", "LESSON 38"; date ranges for Watchtower: "DECEMBER
# 21-27, 2026"), a <p class="featureTtl"> for Awake! articles (the
# shared series theme, e.g. "COPING WITH RISING PRICES"), or for
# Meeting Workbook, the date lives directly in <h1> with no wrapper at
# all -- confirmed live by reading the raw HTML of six real downloaded
# EPUBs (Walk Courageously With God, Draw Close to Jehovah, a
# Watchtower issue, a Meeting Workbook issue, an Awake! issue, and the
# full Enjoy Life Forever course), plus the "Sing Out Joyfully" to
# Jehovah songbook ("SONG N").
#
# Why this matters: correlate_toc_to_audio() only works if the TOC
# label and the audio title agree closely enough in STRUCTURE (same
# count after stripping boilerplate) -- it can't help when a single
# entry's descriptive wording genuinely differs between the print and
# audio editions, which does happen (confirmed live: Draw Close to
# Jehovah's "Section 1" is titled "Awe-Inspiring Power" in the EPUB
# but "Vigorous in Power" in the audio -- a real rename, not a
# formatting difference). A number or date pulled from the page itself
# sidesteps that entirely: "SECTION 1" is "SECTION 1" regardless of
# what the surrounding descriptive title says.
#
# Only ever returns a match when it's UNIQUE (exactly one audio item
# shares the same extracted signal) -- ambiguous or absent signals
# return None so the caller falls back to correlate_toc_to_audio(),
# same never-guess principle as everywhere else in this file.

_CONTEXT_TTL_RE = re.compile(r'<p[^>]*class="[^"]*contextTtl[^"]*"[^>]*>(.*?)</p>',
                              re.IGNORECASE | re.DOTALL)
_FEATURE_TTL_RE = re.compile(r'<p[^>]*class="[^"]*featureTtl[^"]*"[^>]*>(.*?)</p>',
                              re.IGNORECASE | re.DOTALL)
_H1_RE = re.compile(r'<h1[^>]*>(.*?)</h1>', re.IGNORECASE | re.DOTALL)
# v26.08.05.08 (Kaleb's request: test back to 2011). The 2011-2015 era
# EPUBs use a completely different, older markup generation -- no
# <h1> tag at all, no contextTtl/featureTtl classes, confirmed on real
# downloaded issues of both "w" and "g" back to September 2011 (the
# earliest era that exists at all -- see WATCHTOWER_MONTHLY_START/
# AWAKE_MONTHLY_START in jw_fetch.py). The article title instead lives
# in a plain <p class="st"><b>Title</b></p> -- "st" confirmed stable
# across multiple real files from both publications, not a one-off.
_OLD_ERA_TITLE_RE = re.compile(r'<p[^>]*class="st"[^>]*>(.*?)</p>',
                                re.IGNORECASE | re.DOTALL)
# v26.08.05.08 follow-up: "st" alone isn't universal either -- confirmed
# a THIRD old-era variant on feature/travel articles, which split the
# title across TWO separately-classed paragraphs ("s8" then "s9", e.g.
# "Murchison Falls" / "Uganda's Unique Piece of the Nile") instead of
# using "st" at all. Rather than keep chasing one class name at a time,
# this uses a universal fallback instead: the page's own <title> tag
# in <head>, confirmed present with the FULL real article title on
# every era/markup variant tested (current, "st"-era, and the split-
# title "s8"/"s9" era alike) -- because it's part of the EPUB/XHTML
# spec itself, not a styling class that changed between templates.
# Always carries an old-era "D/D " day-prefix (e.g. "9/11 Murchison
# Falls...") the newer eras don't have and the AUDIO title never has
# either -- stripped before use so it doesn't break substring matching.
_HEAD_TITLE_RE = re.compile(r'<title[^>]*>(.*?)</title>', re.IGNORECASE | re.DOTALL)
_DAY_PREFIX_RE = re.compile(r'^\d{1,2}/\d{1,2}\s+')
_TAG_RE = re.compile(r'<[^>]+>')
_WS_RE = re.compile(r'\s+')

# v26.08.05.06: "SONG" added alongside CHAPTER/SECTION/LESSON after
# confirming the songbook's own contextTtl reads "SONG N" -- same
# family, same mechanism, no separate code path needed for the label
# side. _SONG_LIST_NUMBER_RE is separate: the songbook's AUDIO titles
# (from the mediator-category loader, a different lookup than every
# other pub's plain GETPUBMEDIALINKS track list -- see jw_fetch.
# find_audio_for_epub()) come back as "1. Jehovah's Attributes", a
# leading-number-plus-period list style with no "SONG" keyword at all,
# so it needs its own pattern, checked BEFORE the bare-number fallback
# (which would otherwise misread it as an unlabeled chapter number).
_LABELED_NUMBER_RE = re.compile(r'(CHAPTER|SECTION|LESSON|SONG)\s*\u00a0?\.?\s*(\d+)',
                                 re.IGNORECASE)
_SONG_LIST_NUMBER_RE = re.compile(r'^(\d+)\.\s')
_BARE_NUMBER_RE = re.compile(r'^(\d+)\b')
_MONTH_DAY_RE = re.compile(
    r'(january|february|march|april|may|june|july|august|september|'
    r'october|november|december)\s+(\d{1,2})', re.IGNORECASE)


def _clean_html_fragment(fragment):
    """Strip tags, unescape entities, drop zero-width spaces (already
    confirmed to appear mid-title in real JW.org markup -- see the
    correlate_toc_to_audio() docstring above), collapse whitespace."""
    text = _TAG_RE.sub(" ", fragment)
    text = html.unescape(text)
    text = text.replace("\u200b", "")
    return _WS_RE.sub(" ", text).strip()


def _extract_labeled_number(text):
    """Returns (LABEL, number) e.g. ("SECTION", 1), or None. Checked in
    order: an explicit keyword (CHAPTER/SECTION/LESSON/SONG) is the
    most reliable signal; a leading "N. " list style is the songbook
    audio-title convention specifically; a bare leading number with no
    keyword (e.g. a book's own contextTtl reading just "26 NATHAN")
    defaults to CHAPTER, which held true on every real book tested --
    JW.org books that use unlabeled numbering are numbering chapters,
    never sections (sections always carry the explicit word)."""
    if not text:
        return None
    m = _LABELED_NUMBER_RE.search(text)
    if m:
        return (m.group(1).upper(), int(m.group(2)))
    m = _SONG_LIST_NUMBER_RE.match(text)
    if m:
        return ("SONG", int(m.group(1)))
    m = _BARE_NUMBER_RE.match(text)
    if m:
        return ("CHAPTER", int(m.group(1)))
    return None


def extract_labeled_number(text):
    """Public alias for _extract_labeled_number() -- exposed so callers
    outside this module (e.g. main.py's audio-list sorting for the
    songbook, whose track field isn't numeric) can reuse the same
    number extraction without reaching into a private name."""
    return _extract_labeled_number(text)


def _extract_date_anchor(text):
    """Returns a normalized "month day" string (e.g. "december 21")
    from the FIRST month+day found, or None. Deliberately just the
    start day, not the full range -- enough to uniquely identify one
    week/issue among a periodical's handful of others without needing
    to also parse cross-month end dates like "November 30-December
    6" or "December 28-January 3"."""
    if not text:
        return None
    m = _MONTH_DAY_RE.search(text)
    return f"{m.group(1).lower()} {int(m.group(2))}" if m else None


def identify_page_content(raw_html):
    """Extracts whatever structured signal is present on one content
    page: contextTtl/featureTtl/h1 text, plus a derived labeled_number
    and/or date_anchor from whichever of those actually contains one.
    Pure text processing, no I/O -- callers read the raw page HTML
    themselves (EpubDocument.identify_current_page() below is the
    normal entry point, which handles that read)."""
    ctx_m = _CONTEXT_TTL_RE.search(raw_html)
    feat_m = _FEATURE_TTL_RE.search(raw_html)
    h1_m = _H1_RE.search(raw_html)
    ctx_t = _clean_html_fragment(ctx_m.group(1)) if ctx_m else None
    feat_t = _clean_html_fragment(feat_m.group(1)) if feat_m else None
    h1_t = _clean_html_fragment(h1_m.group(1)) if h1_m else None
    if not h1_t:
        # v26.08.05.08: 2011-2015 era pages have no <h1> at all -- see
        # _OLD_ERA_TITLE_RE's comment above. Only used when a real <h1>
        # wasn't found, so this never overrides the newer markup.
        old_m = _OLD_ERA_TITLE_RE.search(raw_html)
        if old_m:
            h1_t = _clean_html_fragment(old_m.group(1))
    if not h1_t:
        # v26.08.05.08 follow-up: neither <h1> nor class="st" found --
        # last resort, the universal <title> tag (see _HEAD_TITLE_RE's
        # comment above for why this catches variants the two more
        # specific patterns above don't).
        head_m = _HEAD_TITLE_RE.search(raw_html)
        if head_m:
            h1_t = _DAY_PREFIX_RE.sub("", _clean_html_fragment(head_m.group(1)))
    labeled_number = _extract_labeled_number(ctx_t) or _extract_labeled_number(h1_t)
    date_anchor = _extract_date_anchor(ctx_t) or _extract_date_anchor(h1_t)
    return {"context": ctx_t, "feature": feat_t, "h1": h1_t,
            "labeled_number": labeled_number, "date_anchor": date_anchor}


def match_page_to_audio(identity, audio_items):
    """Given identify_page_content()'s output and a list of audio items
    (each with a "title" key), returns the matching index into
    audio_items, or None if no signal produced a UNIQUE match. Tries,
    in order of confidence: (1) labeled number -- exact, sidesteps any
    descriptive-title rename entirely; (2) date anchor -- exact, for
    periodicals; (3) h1 EXACT title equality, case-insensitive -- the
    strongest text-based signal, checked before substring containment
    so a real exact match always wins even if some OTHER track's title
    happens to also contain the same words (see the v26.08.05.19 fix
    below); (4) h1 substring containment, normalized -- handles Awake!
    and anything else with no structured wrapper at all, but only
    trusted when it's unambiguous (matches exactly one track)."""
    if not identity or not audio_items:
        return None
    if identity.get("labeled_number") is not None:
        cands = [i for i, a in enumerate(audio_items)
                  if _extract_labeled_number(a.get("title", "")) == identity["labeled_number"]]
        if len(cands) == 1:
            return cands[0]
    if identity.get("date_anchor"):
        cands = [i for i, a in enumerate(audio_items)
                  if _extract_date_anchor(a.get("title", "")) == identity["date_anchor"]]
        if len(cands) == 1:
            return cands[0]
    if identity.get("h1"):
        h1n = identity["h1"].strip().lower()
        if h1n:
            # v26.08.05.19 BUG FIX (found testing "Imitate Their Faith":
            # its real "Conclusion" chapter's h1 is literally "Conclusion",
            # and audio track 26 is titled exactly "Conclusion" too -- a
            # clean, unambiguous exact match -- but track 20's title,
            # "She Drew 'Conclusions in Her Heart'", also happens to
            # CONTAIN "conclusion" as a substring ("Conclusions"), so the
            # substring-containment tier below saw TWO candidates and
            # correctly refused to guess between them, even though one
            # was an exact match and the other only an incidental plural
            # substring collision. Exact equality is strictly stronger
            # evidence than mere containment, so it's now checked FIRST,
            # completely independent of whatever else in the list might
            # coincidentally contain the same words.
            exact_cands = [i for i, a in enumerate(audio_items)
                            if (a.get("title", "") or "").strip().lower() == h1n]
            if len(exact_cands) == 1:
                return exact_cands[0]
            cands = [i for i, a in enumerate(audio_items)
                      if h1n in (a.get("title", "") or "").lower()]
            if len(cands) == 1:
                return cands[0]
    return None


def correlate_toc_to_audio(toc_entries, audio_items, doc_title=None):
    """Positionally correlate a FLAT list of TocEntry objects (caller
    flattens first -- main.py already has flatten_toc() for this, kept
    out of this function so it stays a pure, dependency-free helper)
    against a list of audio items shaped like jw_fetch's (each a dict
    with "title" and "track" keys).

    Strips entries whose title is a known boilerplate label (see
    NON_CONTENT_TOC_LABELS/NON_CONTENT_TOC_PATTERNS above) or exactly
    matches doc_title (JW.org publications repeat their own title as
    the first TOC entry -- confirmed on every publication type
    tested). Whatever remains is assumed to be real chapter/article
    content, in document order.

    Returns a list of (toc_entry, audio_item) tuples, one per real
    article, in track order -- or None if the counts don't match after
    stripping. Never guesses a partial or misaligned mapping: a count
    mismatch means either an unexpected TOC shape (a boilerplate label
    this function doesn't know about yet -- see the v26.08.05.04 fix
    above for how two real ones were found and fixed) or an audio
    listing that doesn't actually correspond to this EPUB, and
    returning None lets the caller fall back to a plain "browse all
    audio" list instead of confidently pointing someone at the wrong
    track, which is worse than no match at all."""
    if not toc_entries or not audio_items:
        return None
    normalized_title = (doc_title or "").strip()
    doc_title_stripped = False  # v26.08.05.07 BUG FIX (found testing a
                                 # real 2016 Awake! issue): this used to
                                 # strip EVERY entry matching doc_title,
                                 # not just the front-matter cover entry
                                 # it's meant for. Confirmed live: that
                                 # issue's first REAL article happens to
                                 # share its exact title with the book's
                                 # own cover ("Attitude Makes a
                                 # Difference!" appears both as the
                                 # cover AND as article 1) -- stripping
                                 # both dropped a real article, throwing
                                 # off the count and failing correlation
                                 # entirely. Now only the FIRST match is
                                 # treated as the cover; any later entry
                                 # with the same text is real content.
    filtered = []
    for entry in toc_entries:
        title = (entry.title or "").strip()
        if title.lower() in NON_CONTENT_TOC_LABELS:
            continue
        if any(p.match(title) for p in NON_CONTENT_TOC_PATTERNS):
            continue
        if normalized_title and not doc_title_stripped and title == normalized_title:
            doc_title_stripped = True
            continue
        filtered.append(entry)
    if len(filtered) != len(audio_items):
        return None
    audio_sorted = sorted(audio_items, key=lambda a: a.get("track") or 0)
    return list(zip(filtered, audio_sorted))


@dataclass
class LinkSpan:
    start: int
    end: int
    target_file: str
    target_anchor: str | None
    kind: str
    href: str = ""  # v0.1.98: raw href, only populated for kind="external"
                    # (internal links already navigate via target_file/
                    # target_anchor and don't need it).


@dataclass
class ImageSpan:
    start: int
    end: int
    src: str
    alt: str


@dataclass
class StyleSpan:
    """A character range that should render bold and/or italic -- from
    <strong>/<b> and <em>/<i> in the source HTML (v0.1.35). Overlapping
    spans (e.g. <strong><em>...) are represented as separate StyleSpan
    entries covering the same range rather than one span with both flags,
    which keeps get_page()'s return shape simple; the renderer merges
    them per character range when building styled runs."""
    start: int
    end: int
    bold: bool
    italic: bool


@dataclass
class ParaSpan:
    """Paragraph-level formatting hint (v0.1.42). Covers an absolute text
    range (start..end) and carries a 'kind' that the renderer uses to
    pick font, colour, and indent. Unlike StyleSpan (character-level
    bold/italic), these are whole-paragraph traits applied once per line
    during draw_reader().

    Kinds:
      superscript  -- <sup> inline marker (v0.1.42)
      caption      -- <figcaption> text below an image (v0.1.42)
      box_rule     -- synthetic rule line emitted around boxSupplement (v0.1.42)
    Note: JW paragraph classes sm/sh/si/sb/sj removed in v0.1.47 --
    they caused unwanted italic, indent, small font and greying.
    """
    start: int
    end: int
    kind: str
    extra: str = ""   # reserved (box rule text)


def collapse_blank_line_runs(text, images, links, styles, para_spans, anchor_offsets):
    """v0.1.118: nested block-tag transitions (a </header> closing while
    <div class="bodyTxt"><div class="section"><div class="pGroup"> all
    open right before the first real <p>, for example) each independently
    call maybe_newline(), and incidental XML pretty-printing whitespace
    between sibling tags gets emitted as its own blank " " line by
    emit_text() -- neither dedupes against the OTHER mechanism, so a
    transition crossing several nested containers with no real content in
    between can stack up 2-4 blank lines where exactly one was intended.
    Confirmed on a real Awake! cover article (Kaleb's report + photos):
    the </header>-to-first-<p> transition alone produced 4 blank lines,
    and every <ul><li> boundary (the Anja/Delina/Gregory bullet list)
    doubled up to 2 blank lines instead of 1, because the <li>'s own
    block-boundary blank line stacked with its child <p>'s.

    This collapses any run of 2+ consecutive whitespace-only lines down to
    exactly 1, and remaps every recorded image/link/style/para/anchor
    offset to match -- safe because no span or anchor is ever placed
    inside pure whitespace, so nothing meaningful can fall inside a
    deleted range."""
    lines = text.split("\n")
    line_spans = []  # (start, end) in the ORIGINAL text; end excludes the "\n"
    pos = 0
    for line in lines:
        start = pos
        end = pos + len(line)
        line_spans.append((start, end))
        pos = end + 1

    is_blank = [line.strip() == "" for line in lines]

    delete_ranges = []
    for i in range(1, len(lines)):
        if is_blank[i] and is_blank[i - 1]:
            # drop this line's own leading "\n" + content: [end of line
            # i-1, end of line i) -- the following "\n" then correctly
            # becomes the sole separator before whatever comes next.
            delete_ranges.append((line_spans[i - 1][1], line_spans[i][1]))

    if not delete_ranges:
        return text, images, links, styles, para_spans, anchor_offsets

    # v26.07.09.16 BUG FIX: same underlying pattern as main.py's
    # style_at()/_compute_line_style_runs() fixes (v26.07.09.15/.16) --
    # remap() used to do a scan over delete_ranges (early-break once past
    # the query offset, but still O(ranges before offset) per call) for
    # EVERY offset being remapped. On Enjoy Life Forever's largest page
    # (4.5M chars, many collapsed-blank-line ranges), this was called
    # 134,097 times (once per image/link/style/anchor offset) and was the
    # single largest remaining cost after the style_at() fix -- confirmed
    # via profiling, ~7 of ~16s total. Fixed with a precomputed cumulative-
    # shift array (delete_ranges is already naturally sorted and non-
    # overlapping, built from sequential line indices) and bisect, giving
    # O(log ranges) per call instead.
    _ends = [de for _ds, de in delete_ranges]
    _cum_shift = []
    _running = 0
    for _ds, _de in delete_ranges:
        _running += (_de - _ds)
        _cum_shift.append(_running)

    def remap(offset):
        idx = bisect.bisect_right(_ends, offset) - 1
        if idx < 0:
            return offset
        shift = _cum_shift[idx]
        # defensive clamp (matches original's "shouldn't occur" case):
        # offset falls INSIDE the next range rather than before/after it
        if idx + 1 < len(delete_ranges):
            nds, nde = delete_ranges[idx + 1]
            if nds < offset < nde:
                shift += (offset - nds)
        return offset - shift

    out = []
    cursor = 0
    for ds, de in delete_ranges:
        out.append(text[cursor:ds])
        cursor = de
    out.append(text[cursor:])
    new_text = "".join(out)

    for im in images:
        im.start, im.end = remap(im.start), remap(im.end)
    for ln in links:
        ln.start, ln.end = remap(ln.start), remap(ln.end)
    for sp in styles:
        sp.start, sp.end = remap(sp.start), remap(sp.end)
    for ps in para_spans:
        ps.start, ps.end = remap(ps.start), remap(ps.end)
    for k in list(anchor_offsets.keys()):
        anchor_offsets[k] = remap(anchor_offsets[k])

    return new_text, images, links, styles, para_spans, anchor_offsets


class EpubDocument:
    def __init__(self, path: str, anchor_cache_path: str | None = None,
                 opf_cache_path: str | None = None):
        self.path = path
        self.zip = zipfile.ZipFile(path, "r")
        self.opf_cache_path = opf_cache_path
        # v26.07.19.XX (Kaleb's request, after profiling confirmed
        # ET.fromstring() on the OPF is the real cost -- 34.55ms of a
        # 48.94ms _parse_opf() on nwt_E.epub's 526KB/4040-item OPF,
        # ~70% of the total, scaling to ~142ms of ~201ms on real ARM
        # hardware per this project's confirmed 4.1x factor. Unlike
        # _parse_toc() (profiled the same session: only ~10ms/~40ms
        # scaled for NWT -- genuinely small, NOT the bottleneck a prior
        # hypothesis this session assumed it was), this OPF-manifest
        # parse is real, repeat, avoidable cost: the OPF never changes
        # between opens of the same unchanged book file, so re-parsing
        # its full XML tree from scratch every single open is pure
        # waste after the first time. Cached to disk (mtime-fingerprint
        # invalidated, identical pattern to _build_anchor_index()'s
        # existing anchor_cache_path mechanism below) rather than kept
        # only in RAM, so the saving persists across app restarts too,
        # not just within one session.
        cached = self._load_opf_cache()
        if cached is not None:
            (self.opf_path, self.opf_dir, self.manifest,
             self.spine, self.ncx_path, self.nav_path) = cached
        else:
            self.opf_path, self.opf_dir = self._find_opf()
            self.manifest, self.spine, self.ncx_path, self.nav_path = self._parse_opf()
            self._save_opf_cache()
        self.toc: list[TocEntry] = self._parse_toc()
        # v26.07.12.12: values can be EITHER set[str] (freshly built this
        # session, from the regex/XML-parse path) or list[str] (loaded
        # straight from the JSON disk cache, no conversion -- see
        # _build_anchor_index()'s cache-hit branch for why that's safe).
        # Every real consumer only ever does `x in ids` or iterates --
        # both forms behave identically for that, so this dict is
        # deliberately never normalized to one type or the other.
        self._anchor_index: dict[str, set[str] | list[str]] | None = None
        self.anchor_cache_path = anchor_cache_path

    def _load_opf_cache(self):
        """Returns (opf_path, opf_dir, manifest, spine, ncx_path,
        nav_path) from disk if a valid, up-to-date cache exists, else
        None (caller falls through to the real _find_opf()/_parse_opf()
        parse -- identical behavior to today whenever this misses).
        Same mtime-fingerprint invalidation as _build_anchor_index()'s
        existing anchor_cache_path mechanism: if the EPUB file's mtime
        doesn't match what's recorded, the cache is stale (book was
        replaced/updated) and is silently ignored rather than trusted."""
        if not self.opf_cache_path or not os.path.exists(self.opf_cache_path):
            return None
        try:
            mtime = os.path.getmtime(self.path)
        except OSError:
            return None
        try:
            with open(self.opf_cache_path) as f:
                cached = json.load(f)
        except Exception:
            return None
        if cached.get("mtime") != mtime:
            return None
        try:
            return (cached["opf_path"], cached["opf_dir"], cached["manifest"],
                    cached["spine"], cached["ncx_path"], cached["nav_path"])
        except KeyError:
            return None  # malformed/old-format cache -- fall through to real parse

    def _save_opf_cache(self):
        if not self.opf_cache_path:
            return
        try:
            mtime = os.path.getmtime(self.path)
        except OSError:
            return
        try:
            os.makedirs(os.path.dirname(self.opf_cache_path), exist_ok=True)
            payload = {
                "mtime": mtime,
                "opf_path": self.opf_path,
                "opf_dir": self.opf_dir,
                "manifest": self.manifest,
                "spine": self.spine,
                "ncx_path": self.ncx_path,
                "nav_path": self.nav_path,
            }
            with open(self.opf_cache_path, "w") as f:
                json.dump(payload, f)
        except Exception:
            pass  # non-fatal -- worst case, next open just re-parses same as today

    def _read(self, path: str) -> str:
        # v26.07.15.17: check the (free, no-decompression) declared
        # size before actually decompressing -- see
        # MAX_SINGLE_FILE_DECOMPRESSED_BYTES's comment for why.
        try:
            declared_size = self.zip.getinfo(path).file_size
        except KeyError:
            declared_size = 0
        if declared_size > MAX_SINGLE_FILE_DECOMPRESSED_BYTES:
            raise ValueError(
                f"{path} declares {declared_size} bytes uncompressed, "
                f"exceeding the {MAX_SINGLE_FILE_DECOMPRESSED_BYTES}-byte safety cap"
            )
        with self.zip.open(path) as f:
            return f.read().decode("utf-8", errors="replace")

    def _parse_xml(self, text: str):
        # v26.07.15.16: stdlib ElementTree doesn't guard against XML
        # entity-expansion ("billion laughs") bombs -- a tiny malicious
        # container.xml/opf/ncx/nav file could define nested custom
        # entities that expand to gigabytes and hang/crash the app on
        # 1GB RAM. Real EPUBs never define custom ENTITYs in these
        # files, so refusing any DOCTYPE with an ENTITY declaration is
        # a safe, zero-cost guard -- cheap substring check, no real
        # book affected. Raises ValueError, which existing callers
        # already handle the same way a malformed-XML ParseError would.
        if "<!ENTITY" in text:
            raise ValueError("XML entity declarations are not permitted in EPUB metadata files")
        return ET.fromstring(text.encode("utf-8"))

    def _resolve(self, base_dir: str, href: str) -> str:
        href = href.split("#")[0]
        if not href:
            return ""
        return posixpath.normpath(posixpath.join(base_dir, href))

    def _find_opf(self):
        container = self._read("META-INF/container.xml")
        root = self._parse_xml(container)
        rootfile = _find_local(root, "rootfile")
        opf_path = rootfile.get("full-path")
        opf_dir = posixpath.dirname(opf_path)
        return opf_path, opf_dir

    def _parse_opf(self):
        opf_text = self._read(self.opf_path)
        root = self._parse_xml(opf_text)

        # v26.07.12.21 (Kaleb's loading-optimization request): this used
        # to call _find_all_local(root, "item") TWICE -- once to build
        # `manifest`, again further down just to find whichever item has
        # properties="nav". _find_all_local() does a full elem.iter()
        # walk of the whole OPF tree every time it's called, so that was
        # two full tree walks over the same set of elements for every
        # single book open. Merged into one pass: nav_item_id is
        # recorded inline while building the manifest, same result.
        manifest = {}
        nav_item_id = None
        for item in _find_all_local(root, "item"):
            item_id = item.get("id")
            href = item.get("href")
            manifest[item_id] = posixpath.normpath(posixpath.join(self.opf_dir, href))
            props = item.get("properties") or ""
            if "nav" in props.split():
                nav_item_id = item_id

        spine = []
        spine_tag = _find_local(root, "spine")
        if spine_tag is not None:
            for itemref in _children_local(spine_tag, "itemref"):
                idref = itemref.get("idref")
                if idref in manifest:
                    spine.append(manifest[idref])

        ncx_path = None
        nav_path = manifest.get(nav_item_id) if nav_item_id else None
        if spine_tag is not None:
            toc_attr = spine_tag.get("toc")
            if toc_attr and toc_attr in manifest:
                ncx_path = manifest[toc_attr]

        return manifest, spine, ncx_path, nav_path

    def _get_text(self, elem, tagname):
        found = _find_local(elem, tagname)
        return "".join(found.itertext()).strip() if found is not None else ""

    def _parse_toc(self) -> list[TocEntry]:
        if self.ncx_path:
            return self._parse_ncx(self.ncx_path)
        if self.nav_path:
            return self._parse_nav(self.nav_path)
        return [TocEntry(title=posixpath.basename(f), href=f, level=0) for f in self.spine]

    def _parse_ncx(self, ncx_path: str) -> list[TocEntry]:
        ncx_text = self._read(ncx_path)
        root = self._parse_xml(ncx_text)
        ncx_dir = posixpath.dirname(ncx_path)

        def walk(nav_point_container, level):
            entries = []
            for np in _children_local(nav_point_container, "navPoint"):
                title = self._get_text(np, "text")
                content_tag = _find_local(np, "content")
                src = content_tag.get("src") if content_tag is not None else ""
                href = self._resolve(ncx_dir, src)
                anchor = src.split("#", 1)[1] if "#" in src else None
                full_href = href + (f"#{anchor}" if anchor else "")
                entry = TocEntry(title=title or "(untitled)", href=full_href, level=level)
                entry.children = walk(np, level + 1)
                entries.append(entry)
            return entries

        nav_map = _find_local(root, "navMap")
        return walk(nav_map, 0) if nav_map is not None else []

    def _parse_nav(self, nav_path: str) -> list[TocEntry]:
        nav_text = self._read(nav_path)
        root = self._parse_xml(nav_text)
        nav_dir = posixpath.dirname(nav_path)

        toc_nav = None
        for nav_el in _find_all_local(root, "nav"):
            attrs = {k.split("}")[-1]: v for k, v in nav_el.attrib.items()}
            if attrs.get("type") == "toc":
                toc_nav = nav_el
                break
        if toc_nav is None:
            toc_nav = _find_local(root, "nav")
        if toc_nav is None:
            return []

        def walk(ol, level):
            entries = []
            if ol is None:
                return entries
            for li in _children_local(ol, "li"):
                a = None
                for child in li:
                    if _local(child.tag) == "a":
                        a = child
                        break
                if a is None:
                    continue
                title = "".join(a.itertext()).strip()
                href_raw = a.get("href", "")
                path = self._resolve(nav_dir, href_raw)
                anchor = href_raw.split("#", 1)[1] if "#" in href_raw else None
                full_href = path + (f"#{anchor}" if anchor else "")
                entry = TocEntry(title=title, href=full_href, level=level)
                sub_ol = None
                for child in li:
                    if _local(child.tag) == "ol":
                        sub_ol = child
                        break
                entry.children = walk(sub_ol, level + 1)
                entries.append(entry)
            return entries

        top_ol = None
        for child in toc_nav:
            if _local(child.tag) == "ol":
                top_ol = child
                break
        return walk(top_ol, 0)

    def probe_chapter_anchor_count(self, min_needed=5):
        """v26.07.12.10: cheap pre-check for whether this book uses the
        chapterN anchor convention (Bible-style books: nwt_E.epub,
        bi12_E.epub) BEFORE paying for the full _build_anchor_index()
        scan -- Kaleb noticed book-open is much slower than a chapter
        turn, and profiling confirmed why: _build_chapter_nav_points()
        unconditionally called _build_anchor_index() (full XML parse of
        EVERY spine file) on every book open, just to check whether the
        chapterN heuristic applies. Checked across all 9 real JW books:
        only 2 (the actual Bible editions) ever have >=5 matches -- the
        other 7 built the complete index and then threw it away in favor
        of the TOC-based fallback path, which never needed it at all.
        For nwt_E.epub (3941 spine files) that wasted scan was 1.55s of
        a 1.85s cold book-open, on THIS book alone.

        Does a raw-bytes regex count (id="chapterN") instead of a real
        XML parse -- no ElementTree construction, no _parse_xml() call
        per file. Verified byte-for-byte identical counts against the
        real XML-parsed ground truth across all 9 real JW books tested
        (nwt_E/bi12_E: 1189 matches each way; the other 7: 0 matches each
        way) -- and 3.7-5.7x faster than the real scan even as a
        standalone probe, on top of skipping the real scan entirely when
        it isn't needed. Stops counting as soon as min_needed is reached
        -- doesn't need an exact count, only "at least this many," so a
        book that clearly qualifies (like nwt_E.epub, matches from very
        early in the spine) doesn't need every remaining file probed.

        Deliberately biased toward false POSITIVES over false NEGATIVES:
        a book that's actually borderline just falls through to the
        real, exact _build_anchor_index() path (identical to today's
        behavior, zero risk of regression) -- the only thing this can
        get "wrong" is occasionally doing the full scan when it turns
        out not to be needed, never the reverse (skipping a real
        chapterN book). Regex matches literal id="chapterN" (double-
        quoted, as every real EPUB tested uses) -- doesn't need to
        handle single-quotes or attribute whitespace variants some
        obscure generator might produce, since the worst case for a
        format this probe doesn't recognize is just falling through to
        the always-correct real scan, same as before this existed."""
        pattern = re.compile(rb'id="chapter\d+"')
        count = 0
        for fname in self.spine:
            try:
                raw = self.zip.read(fname)
            except Exception:
                continue
            if len(pattern.findall(raw)) == 1:
                count += 1
                if count >= min_needed:
                    return count
        return count

    def _build_anchor_index(self):
        if self._anchor_index is not None:
            return

        mtime = None
        try:
            mtime = os.path.getmtime(self.path)
        except OSError:
            pass

        if self.anchor_cache_path and os.path.exists(self.anchor_cache_path):
            try:
                with open(self.anchor_cache_path) as f:
                    cached = json.load(f)
                if cached.get("mtime") == mtime:
                    # Kept as list[str] rather than converted to set(v)
                    # -- the conversion alone measured ~14ms for
                    # nwt_E.epub's 3941-entry cache, roughly doubling the
                    # warm-cache-load cost. Every real consumer
                    # (find_file_for_anchor()'s membership checks,
                    # _build_chapter_nav_points()'s regex-match iteration)
                    # only does membership testing/iteration, which lists
                    # support identically to sets -- the only real cost
                    # difference is O(n) "in" instead of O(1). Safe trade:
                    # real per-file id counts top out around 617 (nwt_E.epub,
                    # the largest real index available), and
                    # find_file_for_anchor() already has a same-file
                    # hint_file fast path that skips the cross-file scan
                    # for the common case. JSON already deserializes list
                    # values directly, so this uses cached["index"] as-is.
                    self._anchor_index = cached["index"]
                    return
            except Exception:
                pass  # corrupt/stale cache -- fall through and rebuild

        # Extracted via direct regex on the already-decoded text rather
        # than a full ET.fromstring() + root.iter() walk -- id VALUES
        # only are needed here, no other DOM structure. Verified EXACT
        # (byte-for-byte identical id SETS, not just counts) against the
        # real ET-parsed ground truth across 6991 real spine files (27
        # books) -- this index also serves find_file_for_anchor() for
        # real footnote/cross-reference resolution, not just a nav-point
        # heuristic with a safe fallback, so it needed exact verification.
        #
        # The regex uses a negative lookbehind so a naive id="..." match
        # can'''t pick up false positives like data-pid="1" as a
        # spurious id "1" -- it requires id="... to NOT be immediately
        # preceded by a word character or hyphen, matching ElementTree'''s
        # .get("id") behavior exactly (only the literal unprefixed "id"
        # attribute). Falls back to a real XML parse per-file on any
        # regex-path exception.
        id_re = re.compile(r'(?<![\w-])id="([^"]*)"')
        self._anchor_index = {}
        for name in self.zip.namelist():
            if name.lower().endswith((".xhtml", ".html", ".htm")):
                try:
                    text = self._read(name)
                    ids = {m for m in id_re.findall(text) if m}
                except Exception:
                    try:
                        root = self._parse_xml(self._read(name))
                        ids = {e.get("id") for e in root.iter() if e.get("id")}
                    except (ET.ParseError, ValueError):
                        # v26.07.15.16: _parse_xml's entity-bomb guard
                        # raises ValueError (not ET.ParseError) -- must
                        # be caught here too, or a malicious file turns
                        # this "skip and continue" fallback into an
                        # uncaught crash instead.
                        continue
                self._anchor_index[name] = ids

        if self.anchor_cache_path:
            try:
                os.makedirs(os.path.dirname(self.anchor_cache_path), exist_ok=True)
                with open(self.anchor_cache_path, "w") as f:
                    json.dump({
                        "mtime": mtime,
                        "index": {k: list(v) for k, v in self._anchor_index.items()},
                    }, f)
            except Exception:
                pass  # caching is an optimization, not a correctness requirement

    def find_file_for_anchor(self, anchor: str, hint_file: str | None = None) -> str | None:
        self._build_anchor_index()
        if hint_file and anchor in self._anchor_index.get(hint_file, set()):
            return hint_file
        for fname, ids in self._anchor_index.items():
            if anchor in ids:
                return fname
        return None

    def resolve_href(self, href: str, current_file: str) -> tuple[str | None, str | None]:
        if href.startswith("http://") or href.startswith("https://"):
            return None, None

        if href.startswith("#"):
            anchor = href[1:]
            found = self.find_file_for_anchor(anchor, hint_file=current_file)
            return (found or current_file), anchor

        if "#" in href:
            file_part, anchor = href.split("#", 1)
        else:
            file_part, anchor = href, None

        base_dir = posixpath.dirname(current_file)
        target = posixpath.normpath(posixpath.join(base_dir, file_part))
        return target, anchor

    def identify_current_page(self, file_path: str) -> dict | None:
        """v26.08.05.06: reads file_path's raw HTML and returns identify_
        page_content()'s structured signal for it -- see that function's
        docstring for what it extracts and why. Returns None (not an
        empty dict) if the page can't be read at all, so callers can
        tell "genuinely no signal" apart from "file error" the same way
        every other read-based method in this file does."""
        try:
            raw = self._read(file_path)
        except (KeyError, ValueError):
            return None
        return identify_page_content(raw)

    def get_bible_chapter_files(self, book_entry: "TocEntry") -> list[str] | None:
        """v26.08.05.01: for a Bible book's TOC entry (e.g. "Genesis"),
        returns the ordered list of content-file paths for each chapter,
        chapter 1 first.

        Genesis (and every NWT book, confirmed on the one live-tested)
        is a single FLAT TocEntry, not 50 nested chapter entries -- the
        real per-chapter split lives one level deeper, in a small JW.org-
        generated chapter-picker page. The useful discovery: book_entry.
        href ALREADY IS that page for JW.org's NWT EPUBs (Genesis's TOC
        entry href resolved to "biblechapternav1.xhtml" on a real
        downloaded nwt_E.epub) -- this isn't a separate lookup, it's the
        exact same href normal TOC navigation already uses.

        Parses that page's own `<a href="...">N</a>` chapter links (a
        small, well-understood JW-generated table, not general HTML --
        regex is safe here for the same reason it's already used
        elsewhere in this file for narrow known page shapes) and sorts
        by the chapter NUMBER text rather than trusting document order,
        as a safety net against a future template change (today's real
        template is already in order -- confirmed on Genesis's full 50-
        chapter table -- this just makes that an explicit guarantee
        instead of an assumption).

        Returns None if the target file doesn't parse as a chapter-nav
        page (no numbered links found) -- callers should treat that as
        "this TOC entry isn't a Bible book with the expected structure"
        and fall back to normal single-entry navigation rather than
        guessing at a chapter number."""
        # v26.08.05.01 BUG FIX (caught immediately by this function's
        # own live test): book_entry.href is ALREADY an absolute, zip-
        # root-relative path (TocEntry hrefs are pre-joined with the
        # NCX's own directory in _parse_ncx()) -- calling resolve_href()
        # on it a second time here double-joined the directory
        # ("OEBPS/OEBPS/biblechapternav1.xhtml") and 404'd on every real
        # book. Use it directly; resolve_href() is still the right tool
        # below for the chapter links found INSIDE that page, since
        # those really are relative to it.
        target = book_entry.href
        if not target:
            return None
        try:
            html = self._read(target)
        except (KeyError, ValueError):
            return None
        links = re.findall(r'<a\s+href="([^"]+)">\s*(\d+)\s*</a>', html)
        if links:
            links.sort(key=lambda pair: int(pair[1]))
            chapter_files = []
            for href, _num in links:
                tgt, _anch = self.resolve_href(href, target)
                if tgt:
                    chapter_files.append(tgt)
            return chapter_files or None

        # v26.08.05.17 FALLBACK (built after confirming live: the 1984
        # Edition Bible has NO chapter-nav page at all -- book_entry.href
        # points straight at chapter 1's own content file). Original
        # assumption going in ("whole book packed into one file with
        # in-page chapter anchors") was WRONG -- checked the raw spine
        # directly instead of guessing further: it's actually near-
        # identical to the 2013 Revision's structure, just not exposed
        # via a picker page. Each chapter is genuinely its own spine
        # file (e.g. "05_BI12_.GE.xhtml", "05_BI12_.GE-split2.xhtml",
        # "05_BI12_.GE-split3.xhtml", ...), each containing EXACTLY ONE
        # "chapterN" anchor -- confirmed against the real EPUB, all 50
        # Genesis files in sequence, N incrementing by exactly 1 every
        # file, correctly stopping at Exodus's own chapter1 (which
        # breaks the +1 sequence, not just the anchor count). Walk
        # forward from book_entry's own spine position collecting that
        # exact pattern; stop the moment a spine file doesn't match
        # (wrong anchor count, or N breaks sequence) -- same "stop
        # rather than guess" contract as every other structural
        # detection in this file.
        start_idx = self.spine_index(target)
        if start_idx == -1:
            return None
        single_chapter_re = re.compile(r'id="chapter(\d+)"')
        chapter_files = []
        expected = 1
        i = start_idx
        while i < len(self.spine):
            fname = self.spine[i]
            try:
                fhtml = self._read(fname)
            except (KeyError, ValueError):
                break
            matches = single_chapter_re.findall(fhtml)
            if len(matches) != 1 or int(matches[0]) != expected:
                break
            chapter_files.append(fname)
            expected += 1
            i += 1
        return chapter_files or None

    def peek_raw_size(self, file_path: str) -> int:
        """v26.07.11.06: near-instant size estimate for file_path via the
        zip's central directory (zipfile.getinfo() -- no decompression,
        no XML parse), used by main.py's _ensure_page_built() to decide
        whether to show an "Opening page..." frame BEFORE starting the
        actual parse (which itself has no progress feedback and, for a
        genuinely huge page, was measured taking ~10s on-device with the
        screen showing nothing at all -- Kaleb's report). Returns the
        raw (uncompressed) XHTML byte size, always >= the eventual
        extracted text char count (markup only ever ADDS bytes -- ratio
        checked at 1.36-1.57 on real large JW pages), so comparing it
        against the same LARGE_PAGE_LOADING_THRESHOLD used elsewhere can
        never MISS a page that's actually going to be slow; it can only
        ever show the early frame on a page that turns out smaller than
        its raw markup suggested, which just costs one harmless extra
        frame. Returns 0 on any error (missing entry, corrupt zip, etc)
        so a failure here never blocks the real get_page() call right
        after it -- this is purely an early hint, not load-bearing."""
        try:
            return self.zip.getinfo(file_path).file_size
        except Exception:
            return 0

    def get_page(self, file_path: str):
        raw = self._read(file_path)
        try:
            root = self._parse_xml(raw)
        except ET.ParseError as e:
            raise ValueError(f"could not parse {file_path}: {e}")

        body = _find_local(root, "body")
        if body is None:
            body = root

        text_parts = []
        links: list[LinkSpan] = []
        images: list[ImageSpan] = []
        styles: list[StyleSpan] = []
        para_spans: list[ParaSpan] = []
        anchor_offsets: dict[str, int] = {}
        cursor = [0]
        last_image_end = [None, 0]  # v0.1.93: [text_parts index, cursor pos]
                                     # right after the most recent image's
                                     # own trailing "\n" -- see the img
                                     # handler in walk() for why

        STYLE_TAGS = {"strong": "bold", "b": "bold", "em": "italic", "i": "italic"}
        # h2/ol added v0.1.42: h2 for be_E subheadings; ol so ordered-list
        # items get proper newlines (noMarker lists inside boxSupplement).
        BLOCK_TAGS = {"p", "div", "li", "h1", "h2", "h3", "h4", "aside", "br", "ol"}

        # JW paragraph-style classes (sm/sh/si/sb/sj) are intentionally
        # not mapped -- they caused italic, indent, small font and grey
        # colour that conflicted with plain readable body text rendering
        # (v0.1.47 removal). Bold still comes through naturally from
        # <strong> tags in the source HTML.

        # Collapses runs of whitespace -- including the "\r\n" + indentation
        # that XML pretty-printing leaves between tags like </tr> and <tr> --
        # down to a single space, matching normal HTML whitespace handling.
        # Without this, that incidental source formatting was being emitted
        # as literal hard line breaks, so a table like the Psalms chapter
        # grid (5 links per <tr>) rendered as one forced line per row no
        # matter how much screen width was actually available.
        _WS_RE = re.compile(r"[ \t\r\n]+")

        # v0.1.151: substitution table is now DYNAMIC, computed once by
        # main.py at startup via a real TTF_GlyphIsProvided32 check
        # against whichever font is actually bundled (see
        # set_active_glyph_subs() below and the call site in main.py,
        # right after FONT_PATH is resolved). This function no longer
        # hardcodes an assumption about which font is active -- it just
        # applies whatever _ACTIVE_GLYPH_SUBS currently holds, which may
        # be empty (e.g. DejaVu Sans, as of v0.1.151, has every one of
        # these natively, so nothing gets substituted and the real
        # glyphs render untouched).
        def _sub_missing_glyphs(s: str) -> str:
            for bad, good in _ACTIVE_GLYPH_SUBS.items():
                if bad in s:
                    s = s.replace(bad, good)
            return s

        _glyph_subs_active = bool(_ACTIVE_GLYPH_SUBS)  # v26.07.11.08

        def emit(s: str):
            if not s:
                return
            text_parts.append(s)
            cursor[0] += len(s)

        def emit_text(s: str):
            """For elem.text / child.tail specifically -- collapses internal
            whitespace runs to a single space before emitting. Explicit
            structural newlines (from maybe_newline()/BLOCK_TAGS/[IMG]) are
            added separately and are never passed through this.

            Also collapses ACROSS fragment boundaries, not just within a
            single fragment: without this, one element's trailing
            whitespace-only tail followed by the next element's leading
            whitespace each independently collapse to one space, but
            concatenated they form a double-space in the final text. That
            double-space later gets silently re-collapsed to a single
            space when main.py word-wraps the line (joining words with
            " ".join, which drops the empty string a double-space
            produces on split) -- permanently desyncing character offsets,
            and therefore link/image span positions, from that point
            forward in the paragraph. Confirmed via a real Bible chapter-
            grid page: this caused chapter-number links to lose their
            highlight (or highlight the wrong character) starting right
            after each <tr> row boundary, worsening with each subsequent
            row as the drift compounded."""
            if not s:
                return
            # v26.07.11.08: skip the _sub_missing_glyphs() call entirely
            # when the table is empty (the common case -- DejaVu Sans has
            # every glyph these substitutions exist for, natively, so
            # _ACTIVE_GLYPH_SUBS is usually {}). Checked once per
            # fragment via a hoisted local bool instead of calling into
            # the function (which would just iterate an empty dict and
            # return `s` unchanged) -- same output, skips 80,511 no-op
            # function calls on the real 4.5M-char page.
            s = _sub_missing_glyphs(s) if _glyph_subs_active else s
            # v26.07.11.07: fast path -- skip the regex entirely when `s`
            # provably has nothing for it to collapse. _WS_RE only ever
            # touches runs containing \t, \r, \n, or 2+ consecutive plain
            # spaces; a fragment with none of those is returned UNCHANGED
            # by _WS_RE.sub() every time, so checking for their absence
            # first (four cheap C-level substring searches) and skipping
            # straight to `s` is byte-identical output to always calling
            # .sub() -- NOT a behavior change, just skipped redundant
            # work. Real-world payoff: most XHTML text nodes are plain
            # prose with single spaces and no embedded tabs/newlines (the
            # only source of \n here is inter-tag pretty-printing
            # whitespace, which shows up in TAIL text, not node text).
            # Motivated by Kaleb's request to look at speeding up the
            # pre-wrap XML-parse step, after profiling showed emit_text()
            # -> _WS_RE.sub() as the single largest cost inside
            # get_page()'s XML walk on the real 4.5M-char "Track Your
            # Bible Reading" page.
            if ("\t" not in s and "\r" not in s and "\n" not in s
                    and "  " not in s):
                collapsed = s
            else:
                collapsed = _WS_RE.sub(" ", s)
            if collapsed.startswith(" ") and text_parts and text_parts[-1].endswith(" "):
                collapsed = collapsed[1:]
            emit(collapsed)

        def maybe_newline():
            if text_parts and not text_parts[-1].endswith("\n"):
                emit("\n")

        def walk(elem):
            tag = _local(elem.tag)

            node_id = elem.get("id")
            if node_id:
                anchor_offsets.setdefault(node_id, cursor[0])

            # v0.1.120 added a skip here for screen-reader-only text
            # (class="dc-screenReaderText", aria-hidden="true") after
            # finding "Your answer" fill-in-the-blank labels cluttering
            # meeting workbooks. v0.1.121: Kaleb decided he wants that
            # text visible at all times instead (not conditional on the
            # images toggle, just always shown) -- reverted. No render-
            # time filtering needed either since there's nothing to filter.

            if tag == "img":
                src = elem.get("src")
                if src:
                    alt = (elem.get("alt") or "").strip()
                    base_dir = posixpath.dirname(file_path)
                    resolved = posixpath.normpath(posixpath.join(base_dir, src))
                    # v0.1.93 fix: two images back-to-back (each commonly
                    # wrapped in its own <div><figure>, e.g. a thin chapter-
                    # header banner immediately followed by a full photo --
                    # Courage/Enjoy Life Forever) picked up a full BLANK
                    # LINE of gap from the block-tag-boundary/whitespace
                    # machinery below (maybe_newline() + emit_text()'s
                    # tail-whitespace collapsing) even though the source
                    # XHTML has nothing but incidental indentation between
                    # them -- no caption, no real text. That wasted 2 rows
                    # of page budget with zero visual content, which only
                    # became visible as the second image getting pushed to
                    # the next page once larger Font Sizes shrank the
                    # per-page row budget (Kaleb, 28pt/32pt on Courage).
                    # Matches JW Library's own rendering (Kaleb's reference
                    # screenshot) of no gap between back-to-back images.
                    # Deliberately narrow: only triggers when EVERYTHING
                    # since the immediately preceding image was pure
                    # whitespace (no real text/caption in between) -- any
                    # actual content between two images is left completely
                    # untouched, and this has zero effect on ordinary
                    # paragraph-to-paragraph spacing elsewhere.
                    if last_image_end[0] is not None:
                        since = "".join(text_parts[last_image_end[0]:])
                        if since.strip() == "":
                            del text_parts[last_image_end[0]:]
                            cursor[0] = last_image_end[1]
                    img_start = cursor[0]
                    emit("[IMG]")
                    images.append(ImageSpan(start=img_start, end=cursor[0], src=resolved, alt=alt))
                    emit("\n")
                    last_image_end[0] = len(text_parts)
                    last_image_end[1] = cursor[0]
                return

            # SVG <image> (v0.1.56): newer Project Gutenberg "ebookmaker"
            # covers wrap the cover picture as <svg><image xlink:href="..."/>
            # </svg> instead of a plain <img>, so the img-only check above
            # silently produced a blank page for the whole cover spine
            # entry. xlink:href is the correct SVG1.1 attribute name; some
            # tools drop the xlink: prefix per SVG2, so fall back to a bare
            # "href" too. Confirmed against a real Gutenberg epub (The
            # Adventures of Sherlock Holmes, gutenberg.org/1661) -- see
            # wrap0000.xhtml in that file for the exact markup.
            if tag == "image":
                href = elem.get("{http://www.w3.org/1999/xlink}href") or elem.get("href")
                if href:
                    base_dir = posixpath.dirname(file_path)
                    resolved = posixpath.normpath(posixpath.join(base_dir, href))
                    img_start = cursor[0]
                    emit("[IMG]")
                    images.append(ImageSpan(start=img_start, end=cursor[0], src=resolved, alt=""))
                    emit("\n")
                return

            if tag in ("script", "style"):
                return

            # <sup> inline superscript (v0.1.42): smaller font, COL_DIM in renderer.
            if tag == "sup":
                sup_start = cursor[0]
                if elem.text:
                    emit_text(elem.text)
                for child in elem:
                    walk(child)
                    if child.tail:
                        emit_text(child.tail)
                if cursor[0] > sup_start:
                    para_spans.append(ParaSpan(start=sup_start, end=cursor[0],
                                               kind="superscript"))
                return

            # <figcaption> caption text below an image (v0.1.42).
            if tag == "figcaption":
                maybe_newline()
                cap_start = cursor[0]
                if elem.text:
                    emit_text(elem.text)
                for child in elem:
                    walk(child)
                    if child.tail:
                        emit_text(child.tail)
                if cursor[0] > cap_start:
                    para_spans.append(ParaSpan(start=cap_start, end=cursor[0],
                                               kind="caption"))
                maybe_newline()
                return

            # <span class="pageNum"> print-page markers are silently skipped --
            # they're invisible in the digital reading context and injecting
            # them mid-sentence caused surrounding text to render in small/dim
            # font (v0.1.46 fix).
            elem_classes = set((elem.get("class") or "").split())
            if tag == "span" and "pageNum" in elem_classes:
                return

            # boxSupplement: emit rule lines around the box (v0.1.42).
            # The box title (boxTtl) gets bold via StyleSpan naturally since
            # it's usually wrapped in <strong>. We add blank-line + rule
            # before and after the entire div.
            is_box = tag == "div" and "boxSupplement" in elem_classes
            if is_box:
                maybe_newline()
                rule_start = cursor[0]
                emit("─" * 32)
                para_spans.append(ParaSpan(start=rule_start, end=cursor[0],
                                           kind="box_rule"))
                emit("\n")

            if tag in BLOCK_TAGS:
                maybe_newline()



            # h2 bold: emit StyleSpan for the whole h2 content (v0.1.42).
            is_h2 = (tag == "h2")
            h2_start = cursor[0] if is_h2 else None

            # A <tr> that reads like a list of distinct records -- one
            # chapter title per row, whether that's ONE cell (a Project
            # Gutenberg TOC: <tr><td><a>Chapter title</a></td></tr>) or TWO
            # (another common Gutenberg TOC pattern: a chapter-number link
            # cell plus a separate title cell) -- should get its own line,
            # same as any other block element. A <tr> that's really a
            # compact GRID of short items (the JW Bible's book-navigation
            # table: 5 short book-abbreviation links per row, meant to flow
            # and wrap together, not one-per-line -- see the whitespace-
            # collapse comment above BLOCK_TAGS for why that exact case was
            # deliberately fixed to flow naturally) must NOT be forced onto
            # separate lines. Cell COUNT alone isn't a reliable enough
            # signal (both known Gutenberg TOC patterns and the JW grid can
            # all have "a few" cells) -- average TEXT LENGTH per cell is:
            # short abbreviations average ~4 chars/cell in the JW grid,
            # versus ~18-35 chars/cell for real chapter titles. Threshold
            # picked from those real, measured numbers, not a guess.
            is_row_of_records = False
            if tag == "tr":
                cells = [ch for ch in elem if _local(ch.tag) in ("td", "th")]
                if cells:
                    total_len = sum(len("".join(ch.itertext())) for ch in cells)
                    avg_len = total_len / len(cells)
                    is_row_of_records = avg_len > 10
                if is_row_of_records:
                    maybe_newline()

            is_link = tag == "a" and elem.get("href")
            link_start = cursor[0] if is_link else None

            # <strong>/<b> -> bold, <em>/<i> -> italic (v0.1.35). Nested/
            # overlapping combinations (e.g. <strong><em>...) naturally
            # produce two separate StyleSpans covering overlapping ranges
            # -- one bold, one italic -- rather than trying to merge them
            # here; see StyleSpan's docstring for why that's deliberate.
            style_kind = STYLE_TAGS.get(tag)
            style_start = cursor[0] if style_kind else None

            if elem.text:
                emit_text(elem.text)

            for child in elem:
                walk(child)
                if child.tail:
                    emit_text(child.tail)

            if style_kind and cursor[0] > style_start:
                styles.append(StyleSpan(
                    start=style_start, end=cursor[0],
                    bold=(style_kind == "bold"), italic=(style_kind == "italic"),
                ))

            # h2 bold: wrap entire h2 text in a bold StyleSpan (v0.1.42).
            if is_h2 and cursor[0] > h2_start:
                styles.append(StyleSpan(start=h2_start, end=cursor[0],
                                        bold=True, italic=False))

            if is_link:
                href = elem.get("href")
                target_file, target_anchor = self.resolve_href(href, file_path)
                epub_type = (elem.get("{http://www.idpf.org/2007/ops}type")
                             or elem.get("epub:type"))
                # v0.1.98: external http(s) links (e.g. a "Watch the video"
                # link to jw.org from inside a publication) used to
                # resolve_href() to (None, None) and get lumped in as
                # "internal" -- selectable/highlighted like any other link,
                # but follow_selected() only acts when target_file is set,
                # so pressing A on one silently did nothing. Give them their
                # own kind and keep the raw href so the reader can actually
                # do something with it.
                if href and (href.startswith("http://") or href.startswith("https://")):
                    kind = "external"
                else:
                    kind = "noteref" if epub_type == "noteref" else "internal"
                links.append(LinkSpan(
                    start=link_start, end=cursor[0],
                    target_file=target_file, target_anchor=target_anchor,
                    kind=kind, href=(href if kind == "external" else ""),
                ))

            if is_row_of_records:
                maybe_newline()

            if tag in BLOCK_TAGS:
                maybe_newline()

            # boxSupplement closing rule (v0.1.42).
            if is_box:
                rule_start = cursor[0]
                emit("─" * 32)
                para_spans.append(ParaSpan(start=rule_start, end=cursor[0],
                                           kind="box_rule"))
                emit("\n")

        node_id = body.get("id")
        if node_id:
            anchor_offsets.setdefault(node_id, cursor[0])
        if body.text:
            emit_text(body.text)
        for child in body:
            walk(child)
            if child.tail:
                emit_text(child.tail)

        text = "".join(text_parts)
        text, images, links, styles, para_spans, anchor_offsets = collapse_blank_line_runs(
            text, images, links, styles, para_spans, anchor_offsets)
        return text, links, images, anchor_offsets, styles, para_spans

    def get_image_bytes(self, image_path: str) -> bytes:
        return self.zip.read(image_path)

    def spine_index(self, file_path: str) -> int:
        try:
            return self.spine.index(file_path)
        except ValueError:
            return -1

    def next_in_spine(self, file_path: str) -> str | None:
        i = self.spine_index(file_path)
        if i == -1 or i + 1 >= len(self.spine):
            return None
        return self.spine[i + 1]

    def prev_in_spine(self, file_path: str) -> str | None:
        i = self.spine_index(file_path)
        if i <= 0:
            return None
        return self.spine[i - 1]


class ReaderState:
    def __init__(self, doc: EpubDocument, start_file: str):
        self.doc = doc
        self.current_file = start_file
        self.current_anchor: str | None = None
        # v0.1.39: exact character offset into the page's plain text,
        # used instead of current_anchor when restoring a bookmark or
        # resume-reading position. current_anchor only ever holds a value
        # briefly (cleared to None once a page finishes loading -- see
        # App._ensure_page_built()), so a bookmark saved after scrolling
        # past that point had nothing to restore to and always reopened
        # at the top of the chapter. char_off is captured fresh every
        # time (see App._current_char_offset()), so it survives exactly
        # where the user actually was, mid-paragraph included.
        self.current_char_off: int | None = None
        self.back_stack: list[tuple[str, str | None]] = []

    def goto(self, file_path: str, anchor: str | None = None, push_history=True,
             char_off: int | None = None):
        if push_history:
            self.back_stack.append((self.current_file, self.current_anchor))
        self.current_file = file_path
        self.current_anchor = anchor
        self.current_char_off = char_off

    def follow_link(self, link: LinkSpan):
        if link.target_file:
            self.goto(link.target_file, link.target_anchor)

    def go_back(self) -> bool:
        if not self.back_stack:
            return False
        self.current_file, self.current_anchor = self.back_stack.pop()
        return True
