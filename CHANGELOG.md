# Changelog

All notable changes to PicoReader are documented here. Entries are
added at release time, not every development session — for the
day-to-day build log, see the AI notes at the top of `main.py`.

## v26.08.27.07

### Fixed

- **LibriVox author searches now actually find the author's work.**
  Searching a name like "Lovecraft" used to return almost nothing —
  LibriVox's search only matches book titles, not authors, so a
  search for an author's name only ever caught the rare book whose
  *title* happened to start with that word. Author search now falls
  back automatically when a title search comes up thin, merging in
  the real author-matched results.
- **LibriVox searches no longer time out on "no results."** A
  genuine no-match search from LibriVox's own server was
  measured taking 11–25 seconds to respond — well past the app's old
  15-second timeout, which made a real (if slow) "nothing found"
  answer look like a network failure. Timeout raised with real
  margin above the worst measured case.
- **A stale search title no longer lingers on screen.** Using Find
  Audiobook on one book, then a different book right after, could
  leave the *first* book's title sitting in the LibriVox screen's
  header even though the results below were for the second book.
- **Fixed a real freeze risk on the Library screen.** Sorting by
  "Last Read," or just having the Library or Library Menu screen
  open, was silently re-reading and re-parsing your entire
  bookmarks file from disk once *per book, every single frame* —
  scaling directly with library size. Now loaded once per screen
  update instead of once per book.

### Performance

- **Chapter navigation and the Chapters screen are now measurably
  faster to open**, especially on very large books (a full Bible
  edition's internal chapter/spine lookup went from a linear scan to
  a constant-time lookup).
- Removed several long-standing inefficiencies in LibriVox audiobook
  browsing and playback: duplicate library-scan imports, a
  redundant duplicate implementation of a network-error-handling
  path, and repeated filesystem probing for the installed media
  player on every track of a queue instead of once per session.

### Maintenance

- Removed several genuinely dead functions (never called from
  anywhere) found via real cross-file reference checking, not just
  code reading: an orphaned JW Broadcasting category handler, an
  unused category-tree counter, and a couple of small pass-through
  wrapper functions.
- Corrected a few stale code comments that no longer matched current
  behavior (leftover from earlier, smaller versions of a couple of
  screens).

## v26.08.11.04

### Changed

- **The two-press exit confirmation now requires a real pause between
  presses.** A fast reflexive double-tap of B no longer counts as
  confirming — it's ignored, and the "Press B again to exit" prompt
  stays up so a genuinely-paused second press still works normally.

## v26.08.11.03

### Added

- **Confirm before quitting.** The Library screen now asks you to
  press B a second time before actually closing the app — the first
  press shows a "Press B again to exit" prompt, and any other button
  cancels it. Only applies at the library's top level; B while
  browsing into a folder still just goes up a level, as before.

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
