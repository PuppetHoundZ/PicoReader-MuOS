## 🚀 Release Highlights (v26.07.29.13 – v26.07.30.31)

### 📁 File & Folder Management

* **Passive Folder Migration:** Replaced the manual migration tool. The app now passively detects and safely migrates legacy flat audio/video folders to structured locations during download checks without re-fetching content.
* **Plugin Directory Isolation:** Audio and Video downloads are now nested under dynamic plugin wrappers (`ROMS/Music/<PLUGIN_NAME>/...` and `ROMS/movies/<PLUGIN_NAME>/...`) to keep media separated from other apps.
* **Collision-Proof Subfolding:**
* Added per-item subfolders so identical chapter filenames no longer overwrite each other.
* **Periodicals & Publications:** Added per-issue subfolders (e.g., `.../202610/`) and category subfolders (`.../Publications/Books/<Title>/`).



---

### 🎧 Audio System Overhaul

* **Music vs. Publications Restructuring:** Audio navigation is now cleanly split into **Music** and **Publications** groups at the top level.
* **Full Audio Backlog Browsing:** Added full back-issue browsing for primary periodical and workbook audio (matching historical depth back to 2016).
* **Audio Availability Filtering:** Added persistent caching for MP3 availability checks—publications lacking audio are cleanly filtered out without repeating live network queries.
* **Article Series Audio Support:** Added support for audio-enabled article series, including legacy archives, life stories, additional topics, and docid-range probing for specific study series.

---

### 📚 Catalog & Content Expansion

* **Search Discovery Caching:** Items discovered via live search or manual code entries are now permanently cached and seamlessly merged into normal category browsing.
* **New EPUB Catalog Additions:** Live-verified and added two new publications to the main catalog.
* **Multi-Year Gap Backfill:** Updated periodical issue generators to automatically scan and backfill multi-year gaps if maintenance was missed across multiple calendar years.

---

### ⚡ Navigation, UI & Async Fixes

* **Quick Menu Overlay Fix:** Fixed a freeze where opening the Quick Menu (X) while loading audio issues broke the loader permanently.
* **Race Condition Guards:** Updated async completion guards to check exact source identity rather than just screen state, preventing stale background requests from clobbering newly selected views.
* **B-Button Routing Fixes:** Corrected back-button navigation hierarchy across multi-level audio pickers, content lists, and publication categories.
* **Metadata Extraction:** Integrated `epub_engine` to parse downloaded EPUB metadata on the fly, auto-populating missing cover themes into issue lists.
  `theme_red_shift.png`, `theme_adventure.png`.
