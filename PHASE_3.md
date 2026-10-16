# Phase 3: Modern UI Redesign & Unified Workspace

## Summary

Phase 3 redesigns the user interface into a responsive, single-page application with a clear five-tab navigation structure: **Overview**, **Colleges**, **Templates**, **Campaigns**, and **Settings**.

The **Colleges** workspace serves as the primary operational hub, enabling multi-field search, multifaceted filtering (area, institution type, discipline, contact status, contact type), persistent selection across filters and pages, visual provenance inspection via a slideout detail drawer, and one-click campaign launching.

---

## 1. Clear Navigation Structure

The top navigation header (`static/dashboard.html` & `static/dashboard.css`) provides immediate access to all five functional areas:

| Tab | Icon | Purpose | Key Metrics / Indicators |
| :--- | :---: | :--- | :--- |
| **Overview** | 📊 | Operational dashboard, KPI summary, and health monitoring | 5 Area coverage cards, review queue, dispatch log, system health |
| **Colleges** | 🎓 | Main directory workspace, provenance inspection, and selection | Active directory count (`217`), selected count pill |
| **Templates** | ✉️ | Starter template library, responsive preview, and live personalization | Desktop / Mobile toggle, HTML / Text toggle, live college selector |
| **Campaigns** | 🚀 | Recipient review, staggered SMTP dispatch, and 1-click Gmail drafts | Selected recipient chips with removal, progress bar, real-time log |
| **Settings** | ⚙️ | Sender email, session App Password, 2FA guide, and live diagnostics | Live health status dot (`operational` / `degraded`), CSRF status |

---

## 2. Colleges Screen: The Main Workspace

The Colleges screen (`#tabColleges`) delivers a high-density, responsive interface for directory browsing and outreach preparation:

- **Multi-Field Search**: Searches across institution name, campus, alternate names/aliases, locality, address, district, and contact email.
- **Multifaceted Filters**:
  - **Area**: All 5 areas, Delhi NCT, Noida, Greater Noida, Ghaziabad district, Gurugram / Gurgaon.
  - **Institution Type / Discipline**: Engineering & Technology, Management & Business (MBA/BBA), Computer Applications / IT (MCA/BCA), Pharmacy & Medical, Law & Legal Studies, Universities.
  - **Contact Status**: Verified on official site, Official directory only, Unverified, Email missing.
  - **Contact Type**: Placement Cell, General contact.
- **Data Table Display**:
  - `[x]` Select Checkbox: Disabled for unverified/missing/do-not-contact records to enforce data integrity.
  - **Institution / Campus**: Primary name, campus, discipline/type, and official website link (`target="_blank"`).
  - **Area / Locality**: Area pill (`Noida`, `Delhi`, etc.) and full locality/district.
  - **Official Contact**: Verified placement email, contact type badge, contact role/person, and public phone.
  - **Verification & Source**: Status badge (`Verified`, `Official directory only`, `Unverified`, `Email missing`), checked date, and clickable official source evidence link.
  - **Last Outreach**: Displays date of previous outreach or "Never".
  - **Actions**: "Details" button opens the slideout dossier drawer.
- **Pagination & Sizing**: Supports 25, 50, or 100 items per page with clear page indicators.

---

## 3. Persistent Selection & Action Bar

- **Scope-Aware Selection**:
  - **"Select this page"**: Selects only visible, sendable colleges on the current page.
  - **"Select all matching results"**: Selects all sendable colleges matching the active search and filter criteria across **all** pages.
  - **"Clear selection"**: Clears all selected colleges.
  - **Selection Persistence**: Selections survive pagination, search term typing, and filter dropdown adjustments.
- **Persistent Floating Bottom Action Bar (`#floatingActionBar`)**:
  - Automatically slides up from the bottom when `selectedCount > 0`.
  - Displays total selected colleges and verified placement contact count.
  - Offers **"Review Recipients"** (modal inspects exact recipients) and **"Clear"**.
  - Provides prominent primary CTA: **"Create Campaign (X Colleges) →"**, seamlessly transitioning the user to the Campaigns tab with recipients pre-loaded.

---

## 4. Slideout Detail Drawer (`#collegeDrawer`)

Clicking any institution row or the "Details" button slides open a comprehensive offcanvas drawer from the right without navigating away:

1. **Official Placement Contact**: Sourced email, contact role, phone, and website.
2. **Provenance & Evidence**: Verification status badge, date checked, email evidence source URL, and directory source URL.
3. **Institution Profile**: Area, district, locality, type/disciplines, and alternate names/aliases.
4. **Review Notes & Gaps**: Sourced notes explaining any documented limitations (e.g. why an admissions helpline was excluded).
5. **Outreach History**: Chronological log of previous outreach messages sent to this institution.
6. **Audit Trail**: View change history from the SQLite audit table.
7. **Interactive Actions**:
   - "Select for Campaign" / "Remove from Selection"
   - "Edit / Verify Record" (opens modal with required verification confirmation check)
   - "Do Not Contact" toggle

---

## 5. Overview Screen: Operational Intelligence

The Overview screen (`#tabOverview`) surfaces high-level operational intelligence:

- **Top KPI Cards**: Total Directory Inventory (217), Verified & Sendable (118), Official Directory Only (21), Records Needing Review (99), Missing Placement Email Gaps (68).
- **Interactive Area Coverage Breakdown**: 5 cards (Delhi, Noida, Greater Noida, Ghaziabad, Gurugram) detailing identified, verified, directory listed, missing, and sendable counts. Clicking an area card instantly opens the Colleges workspace pre-filtered to that area.
- **Directory Records Needing Review**: Interactive queue showing top institutions needing human review or gap verification.
- **Recent Dispatches & Attention Items**: Log of recent messages with error reasons (e.g. SMTP connection failures or auth warnings).
- **Staggered Queue & Sending Guard**: Highlights sender rate limiting (2-second delay per recipient) and do-not-contact protection.
- **Duplicate Inventory Manager**: Highlights candidate duplicate pairs with one-click inspection and safe merging.

---

## 6. Templates & Campaigns Screens

- **Templates (`#tabTemplates`)**:
  - Desktop view vs. Mobile view (375px responsive smartphone container).
  - HTML formatted view vs. Plain-text alternative view.
  - **Live College Personalization Dropdown**: Pick any college in the directory to see template variables (`{{College_Name}}`, `{{City}}`, etc.) populated live in the preview!
  - "Send Test Email to Sender" button directly accessible.
- **Campaigns (`#tabCampaigns`)**:
  - **Recipient Review**: Shows exact chips for every institution entering the campaign, each with an instant remove button (`×`).
  - **Staggered SMTP Sending**: Automated send with real-time progress bar (percentage & count), and live execution activity log.
  - **1-Click Gmail Draft**: Opens Gmail in BCC with all selected verified emails and automatically copies full personalized text to the clipboard.
  - **Campaign Dispatch History**: Relational table logging all campaign batches, dates, recipient counts, and completion statuses.

---

## 7. Verification & Test Suite

All tests pass with zero regressions:

```powershell
python -m unittest discover -s tests
# Ran 26 tests in 0.453s - OK

node --test tests/selection.test.cjs
# ✔ UI selection survives filtering, visible selection and clear-all behave correctly
# ✔ Phase 3: selectThisPage and selectAllMatches distinguish pagination scope
# 2 tests passed, 0 failed
```

Live HTTP route verification confirmed:
- `GET /` -> 200 OK (Serves redesigned platform)
- `GET /overview` -> 200 OK
- `GET /colleges` -> 200 OK
- `GET /templates` -> 200 OK
- `GET /campaigns` -> 200 OK
- `GET /settings` -> 200 OK
- `GET /api/overview` -> 200 OK
- `GET /api/college-detail?id=1` -> 200 OK
- `GET /api/campaigns` -> 200 OK
- `GET /static/dashboard.css` -> 200 OK
- `GET /static/dashboard.js` -> 200 OK
