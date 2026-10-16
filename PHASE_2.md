# Phase 2: Database-Backed College Directory & Provenance

## Summary

Phase 2 establishes a durable, database-backed directory (`data/directory.sqlite3`) and an official-source reference inventory across all five target areas: **Delhi NCT**, **Noida**, **Greater Noida**, **Ghaziabad district**, and **Gurugram district**.

Every institution in the agreed reference inventory is accounted for with either a sourced institutional contact or a documented gap.

---

## 1. Scope & Geographic Coverage

- **Delhi**: Delhi NCT. Includes University of Delhi (DU), state universities, central universities, institutes of national importance, and GGSIPU main campus + Delhi-based affiliated colleges.
- **Noida**: Gautam Buddha Nagar (Noida sectors 1–168). Kept strictly separate from Greater Noida.
- **Greater Noida**: Gautam Buddha Nagar (Knowledge Park I–III, TechZone, Sector 17-A Yamuna Expressway).
- **Ghaziabad**: Full Ghaziabad district boundaries (including Modinagar, Sahibabad, Muradnagar, Patla).
- **Gurugram**: Full Gurugram district boundaries (including Manesar, Sohna, Farrukhnagar, Pataudi, Sidhrawali). "Gurgaon" and "Gurugram" are indexed as aliases and return identical results.

---

## 2. Directory Coverage & Status Breakdown (As of 2026-10-16)

| Area | Identified | Verified | Directory-Listed | Missing Email | Sendable | Needs Review |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Delhi** | 122 | 57 | 0 | 64 | 57 | 65 |
| **Noida** | 13 | 13 | 0 | 0 | 13 | 0 |
| **Greater Noida** | 27 | 22 | 0 | 2 | 22 | 5 |
| **Ghaziabad** | 24 | 12 | 4 | 2 | 12 | 12 |
| **Gurugram** | 31 | 14 | 17 | 0 | 14 | 17 |
| **Total** | **217** | **118** | **21** | **68** | **118** | **99** |

- **Sendable**: Institutions with an official institutional contact verified on an official institutional source, marked as `verified` (and not `unknown` or `do_not_contact`).
- **Directory-Listed**: Government or administrative directory listings (e.g. Haryana DHE or Ghaziabad NIC portal) that have an email but await institution-level homepage verification before sending.
- **Missing Email (Documented Gap)**: Institutions confirmed to exist whose placement/general mailbox is not publicly published or is currently restricted to student admission desks. These remain visible in the directory with disabled sending checkboxes.

---

## 3. Provenance & Source Manifest

All sources are documented in `data/source_manifest.json`:
1. **University of Delhi College Directory** (`https://www.du.ac.in/?page=colleges-at-du`): 85 colleges catalogued; 22 institutional homepages verified with snapshot evidence.
2. **Guru Gobind Singh Indraprastha University (GGSIPU) Affiliation Network** (`https://ipu.ac.in/`): 28 university schools and affiliated professional colleges catalogued across Delhi, Noida, and Greater Noida.
3. **Haryana Directorate of Higher Education** (`https://highereduhry.ac.in/forms/WebPages/Colleges`): 17 Gurugram district institutions catalogued.
4. **Gurugram District Higher Education & Private Universities** (`https://gurugramuniversity.ac.in/` & institutional sites): 14 major private and state universities catalogued (NorthCap, Amity Manesar, Apeejay Stya, BML Munjal, GD Goenka, KR Mangalam, SGT, Sushant, Gurugram University, DCE Gurgaon, WCTM, SAITM, MDI Gurgaon, Great Lakes).
5. **Gautam Buddha Nagar (Noida & Greater Noida) Education Hub & AKTU Network** (`https://aktu.ac.in/` & institutional sites): 37 institutions across Knowledge Park, Sector 62, and TechZone catalogued.
6. **Ghaziabad District Higher Education & Administration** (`https://ghaziabad.nic.in/` & institutional sites): 22 institutions catalogued across engineering, management, and degree colleges.
7. **Delhi State & Central Universities Directory** (`https://delhi.gov.in/`): 12 premier institutions (DTU, NSUT, IIIT-Delhi, IGDTUW, IIT Delhi, Jamia Millia Islamia, Jamia Hamdard, AUD, DSEU, NLU Delhi, JNU, AIIMS) with verified placement cells.
8. **AISHE & AICTE National Portals** (`https://dashboard.aishe.gov.in/`): Used for institutional classification benchmarks.

---

## 4. Key Architectural Components

- `data/directory.sqlite3`: Relational database with `colleges`, `audit`, `imports`, and `metadata` tables.
- `directory.py`:
  - `query_colleges()`: Fast search with area, contact status, and contact type filtering, pagination, and Gurgaon/Gurugram alias normalization.
  - `save_record()`: Atomic inserts and version-checked edits with full JSON before/after audit tracking.
  - `preview_import()` & `commit_import()`: Import screen backend supporting CSV and JSON up to 2 MB with duplicate detection and dry-run validation before committing.
  - `duplicates()` & `merge_records()`: SequenceMatcher-based similarity and shared email detection, preserving aliases and audit trails.
  - `coverage()`: Real-time area reporting of identified, reviewed, contact found, missing, sendable, and needs-review counts.
- `static/directory.html` & `static/directory.js`:
  - Interactive directory dashboard at `/directory`.
  - Multi-criteria filter toolbar (query, area, status, contact type).
  - Add / Edit modal with verification confirmation enforcement.
  - Import dialog with live validation preview table.
  - Duplicate review dialog with one-click merge.
  - Change history inspection modal.
  - "Select all contactable matches" and "Prepare email" handoff to Dispatcher.
- `seed_directory.py`: Reproducible database population script that updates existing records and inserts new reference inventory records idempotently.
- `build_source_inventory.py`: Reproducible extraction script parsing official source snapshots and building `data/official_inventory.json`.

---

## 5. Verification & Test Suite

All tests execute offline without network requests or external side-effects:
- Python test suite: `python -m unittest discover -s tests` (20 tests passing)
- Node test suite: `node --test tests/selection.test.cjs` (passing)
- Health check endpoint: `GET /api/health` returns `{"status": "ok", "application": "medantrik-outreach", "version": "phase-2"}`.
