# Phase 4 — Template Creation, Rich-Text Editing & Live Personalization Preview

## 1. Overview & Objective
Phase 4 elevates the College Outreach Platform from static HTML email files to an interactive, database-backed **Template Library & Management Engine**. Non-technical staff can now compose, edit, duplicate, archive, and version-control professional outreach communications directly from the web interface.

Key accomplishments in Phase 4:
1. **Database-backed Template Management**: Schema in SQLite (`email_templates` and `template_history`) supporting full CRUD operations, multi-version lineage, and soft archiving.
2. **Three Pre-Seeded Starter Templates**:
   - *MedTech Hardware & Biomedical Engineering Placement Partnership (Default)*: High-impact institutional outreach with embedded news clipping asset.
   - *Campus Recruitment & Paid Engineering Internship Opportunity*: Direct student recruitment and R&D internship briefing.
   - *Executive Industry Collaboration & Placement Invitation*: Concise corporate outreach tailored for deans and directors.
3. **Rich-Text WYSIWYG & HTML Dual Editor**:
   - Formatting toolbar: Bold, Italic, Underline, Strikethrough, Headings (H1, H2, H3, Paragraph), Bulleted lists, Numbered lists, Links, Images, and Formatting cleanup.
   - Fast token insertion chips: `{{College_Name}}`, `{{City}}`, `{{Contact_Person}}`, `{{Campus}}`, `{{Website}}`, `{{contact_type}}`.
   - Dual-mode switch: Instant toggle between Visual WYSIWYG and raw HTML source code.
4. **Personalization Engine & Fallback Logic**:
   - Replaces tokens dynamically based on selected college profile.
   - Enforces sensible fallbacks (e.g. `Contact_Person` &rarr; *"Training & Placement Officer"*, `City` &rarr; *"Delhi-NCR"*, `College_Name` &rarr; *"Your Prestigious Institution"*).
   - Zero unparsed `{{...}}` brackets left in outgoing emails or previews.
5. **Live Contextual Preview (Desktop & Mobile)**:
   - Preview iframe dynamically personalizes against any of the 217 colleges in the directory.
   - Device viewport toggling: Desktop (full width) vs. Mobile (375px responsive phone viewport).
   - Plain-text alternative preview with auto-generation from HTML.
   - Direct "Send Test Email to Sender" button.
6. **Campaign Snapshot Immutability**:
   - When a campaign is recorded or scheduled, a frozen JSON snapshot of the template is preserved in the database.
   - Future template edits or deletions will **never** silently alter past or scheduled campaigns.
7. **Version History & One-Click Restore**:
   - Every save increments the template version and writes a changelog entry to `template_history`.
   - Dedicated modal allows viewing previous revisions and restoring them with one click.

---

## 2. Database Architecture

### `email_templates` Table
Stores active and archived templates.
```sql
CREATE TABLE IF NOT EXISTS email_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    subject TEXT NOT NULL,
    html_body TEXT NOT NULL,
    text_body TEXT NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0,
    version INTEGER NOT NULL DEFAULT 1,
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

### `template_history` Table
Immutable audit trail of all template revisions.
```sql
CREATE TABLE IF NOT EXISTS template_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    template_id INTEGER NOT NULL,
    version INTEGER NOT NULL,
    name TEXT NOT NULL,
    subject TEXT NOT NULL,
    html_body TEXT NOT NULL,
    text_body TEXT NOT NULL,
    note TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(template_id) REFERENCES email_templates(id)
);
```

### `campaigns` Table (Updated)
Maintains isolation from subsequent template edits via frozen snapshots.
```sql
ALTER TABLE campaigns ADD COLUMN template_id INTEGER;
ALTER TABLE campaigns ADD COLUMN template_snapshot TEXT;
```

---

## 3. Personalization Engine & Fallback Rules

| Personalization Token | Source Field in Directory | Sensible Fallback if Missing / Empty |
| :--- | :--- | :--- |
| `{{College_Name}}` | `college.College_Name` | *"Your Prestigious Institution"* |
| `{{City}}` | `college.City` / `Location` | *"Delhi-NCR"* |
| `{{Contact_Person}}` | `college.Contact_Person` | *"Training & Placement Officer"* |
| `{{Campus}}` | `college.Campus` | *"" (empty string)* |
| `{{Website}}` | `college.Website` | *"" (empty string)* |
| `{{contact_type}}` | `college.contact_type` | *"Placement Cell"* |

All tokens are case-tolerant (`{{college_name}}`, `{{College_Name}}`, `{{COLLEGE_NAME}}`).

---

## 4. API Endpoints Reference

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/templates` | List all active email templates with metadata. |
| `GET` | `/api/templates/detail?id=:id` | Retrieve full template record including HTML and text bodies. |
| `GET` | `/api/templates/history?id=:id` | Retrieve revision history for a template. |
| `POST` | `/api/templates/save` | Create a new template or save a new version of an existing template. |
| `POST` | `/api/templates/duplicate` | Duplicate an existing template into a new editable template. |
| `POST` | `/api/templates/archive` | Soft-archive a non-default template. |
| `POST` | `/api/templates/restore` | Restore a historical version of a template as the new current version. |
| `POST` | `/api/templates/preview` | Render subject, HTML, and plain text with personalized tokens resolved. |
| `GET` | `/preview?id=:id&college_id=:cid` | Render personalized HTML preview in iframe for a specific college. |
| `GET` | `/api/text-template?id=:id&college_id=:cid` | Render personalized plain-text preview. |

---

## 5. Verification & Testing

### Python Automated Tests
Run: `python -m unittest discover -s tests`
- **Result**: `35 tests ran in 0.821s, OK` (including 9 exhaustive tests in `tests/test_templates.py`).
- **Covered**:
  - Starter template seeding & default assignment.
  - Template CRUD & auto-version incrementation.
  - Mandatory field validation (name, subject, html_body).
  - Duplicate template creation with `(Copy)` suffix.
  - Archive constraints (protecting default template).
  - Version history tracking & revision restoration.
  - Token replacement and sensible fallback rules.
  - Campaign snapshot isolation and freeze.
  - REST endpoints authentication and CSRF checks.

### Node Frontend Tests
Run: `node --test tests/selection.test.cjs`
- **Result**: `2 tests ran, 0 failures, pass 2`.
- **Covered**:
  - DOM selection persistence across multi-page filtering and pagination.
  - Clean execution in Node's VM without unhandled browser globals.

### Live Server Verification
- Server running locally on `http://localhost:5050`
- Verified live responses for `/api/health`, `/api/templates`, and personalized `/preview`.
