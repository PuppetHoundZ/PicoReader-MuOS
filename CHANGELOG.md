# Changelog

All notable changes to PicoReader are documented here. Entries are
added at release time, not every development session — for the
day-to-day build log, see the AI notes at the top of `main.py`.

## v26.08.11.02

### Maintenance

- **Dead-code cleanup.** Removed several fully unreachable functions
  left behind by earlier refactors (an old sound-engine cleanup method
  that was never wired up, and a couple of image/prerender helpers
  superseded by later, better-performing replacements). No behavior
  change — verified via real execution, not just code inspection.
- **Minor UI consistency fix.** The "Download From" source list now
  truncates long names the same safe way every other list in the app
  already does, closing a small gap that wasn't causing a visible
  problem today but had no margin for error if a future source's name
  ran long.

## v26.08.07.23

### Added

- **LibriVox audiobook downloads now have a real home.** A "Downloaded
  Audiobooks" entry sits at the top of LibriVox's category list,
  showing every audiobook you've downloaded, grouped by book so
  tracks from different titles never mix together. Works fully
  offline — no network call needed to browse what you already have.
- **Delete downloaded audio right from the browser.** A new "Delete"
  option (via the X quick menu) removes a downloaded audiobook — the
  whole book, or just one track — directly from the Downloaded
  Audiobooks list. Two-press confirm, same as every other destructive
  action in the app.
- **The Library's popup menu got reorganized.** New Folder, Move to
  Folder, Delete Folder, and Delete Book — previously scattered
  throughout the menu — now live together in their own "Edit
  Library" submenu, keeping the main Library menu shorter and the
  file-management actions grouped in one place. Settings now sits
  immediately before Back.

### Fixed

- **Category browsing is now always live.** Previously, if a live
  fetch failed, the app could fall back to a cached snapshot of a
  category's contents from a past session — occasionally serving a
  stale or corrupted list (missing details, and in rare cases a crash
  when opening an item from it). Every category is now a fresh fetch,
  every time; the only offline fallback left is showing files you've
  actually already downloaded, which is both safer and matches what
  people actually want when offline.
- **Fixed a folder-naming bug affecting downloaded audio.** Under
  certain conditions, downloaded audio files could be saved into the
  wrong destination folder rather than each source's own folder.
  Fixed — new downloads are now always filed correctly. (If you'd
  downloaded LibriVox audio before this fix, it may be worth checking
  where it landed.)
- **Fixed duplicate books appearing after library cleanup.** The
  "check for files to migrate" tool in Storage could, in some cases,
  create a duplicate copy of a book instead of correctly filing the
  existing one — now it recognizes books it's already placed and
  leaves them alone.
- **Fixed several back-button navigation bugs in the download
  browser.** In a handful of specific spots, pressing Back after
  drilling into a category wouldn't fully "unwind" the list you were
  looking at — the screen would visually change, but the item list
  underneath could still be showing the previous, deeper level. Found
  through a full sweep of every category across every source and
  fixed everywhere it turned up.
- **Fixed the reader's popup menu occasionally showing a shorter list
  than it should**, with rows seeming to "appear" partway through
  scrolling. The menu's visible-row count is now calculated correctly
  regardless of which optional items are hidden for a given book.

## Earlier versions

Released informally prior to this changelog's introduction. See
commit history and `main.py`'s own AI notes for details.
