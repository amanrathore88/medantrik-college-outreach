# Phase 6 — Outreach Tracking, Recruitment Pipeline & Follow-up Management

## 1. Overview & Objective
Phase 6 enhances the College Outreach Platform from a message dispatcher into a **full campus recruitment CRM**. It provides the Medantrik hiring team with comprehensive tracking of each partner institution's lifecycle, automated follow-up scheduling, reply recording with automatic message suppression, duplicate-contact warnings, and one-click exportable CSV reports.

### Key Capabilities Delivered in Phase 6:
1. **Recruitment Pipeline Funnel (6 Core Stages)**:
   - `not_contacted`: Default state for all directory institutions.
   - `contacted`: Automatically promoted once an outreach email is accepted by the SMTP provider.
   - `replied`: Marked when an official placement response is received.
   - `meeting_arranged`: Scheduled discussion with TPO, Dean, or Placement Committee.
   - `partnership_active`: Successfully finalized MoU / campus drive agreement. Excluded from generic email blasts.
   - `declined`: Institution declined participation or requested no outreach. Safely excluded from sendable lists.

2. **Automated Follow-up Suppression**:
   - When a placement officer replies or an institution transitions to `replied`, `partnership_active`, `declined`, or `do_not_contact`, all pending queued messages for that college in `campaign_queue` are **automatically cancelled** with descriptive cancellation logs.
   - The queue worker verifies the college's current stage right before dispatching each message, preventing accidental automated emails to institutions that already replied.

3. **Unified CRM Activity Timeline**:
   - A dedicated `outreach_notes` table logs phone calls, meetings, internal review notes, stage transitions, and follow-up schedules.
   - Merged with sent and failed email dispatches from `outreach_log` to present a single chronological history feed inside the College Detail Drawer.

4. **Follow-Up Reminders & Deadline Tracking**:
   - Schedule target follow-up dates (`YYYY-MM-DD`) with team member assignment (`assigned_to`).
   - Quick date calculation buttons (+3 Days, +1 Week, +2 Weeks) in IST.
   - Dashboard Overview card categorizes pending tasks into **Overdue**, **Due Today**, and **Upcoming**, with instant 1-click drawer access.

5. **Duplicate-Contact Warnings (`recently_contacted`)**:
   - Colleges contacted within the last 14 days are flagged with a prominent warning badge (`⚠️ Contacted Recently`) in the table and drawer.
   - Prevents duplicate outreach from overlapping campaigns or team members.

6. **Comprehensive Export Suite**:
   - **Recruitment Pipeline CSV** (`/api/export/pipeline`): Complete directory with recruitment stage, follow-up date, assigned team member, and placement contacts.
   - **Outreach & Activity Log CSV** (`/api/export/outreach`): Chronological audit of calls, notes, replies, stage changes, and email dispatches.
   - **Campaign Delivery CSV** (`/api/export/campaign?id=<id>`): Individual campaign recipient status, delivery timestamps, retry counts, and provider error details.

---

## 2. Database Architecture

### `outreach_notes` Table (Created in Phase 6)
Stores internal communications, call logs, meeting notes, and timeline events:
```sql
CREATE TABLE IF NOT EXISTS outreach_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    college_id INTEGER NOT NULL,
    activity_type TEXT NOT NULL,          -- 'note', 'reply', 'call', 'meeting', 'stage_change', 'follow_up'
    notes TEXT NOT NULL,
    author TEXT DEFAULT 'Hiring Team',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(college_id) REFERENCES colleges(id)
);
```

### College Payload Schema Additions
Each college JSON payload record in SQLite `colleges.payload` now contains:
- `recruitment_stage`: Current pipeline status (`not_contacted`, `contacted`, `replied`, `meeting_arranged`, `partnership_active`, `declined`).
- `follow_up_date`: Target follow-up date string (`YYYY-MM-DD`).
- `assigned_to`: Name or email of the team member handling the college.
- `last_reply_at`: ISO timestamp of the most recent reply from the institution.
- `last_reply_notes`: Summary of the institution's reply.

### Sendability Invariant
`record['sendable']` is enforced in `directory.serialize()`:
```python
record['sendable'] = bool(
    record['TPO_Email'] and 
    record['verification_status'] == 'verified' and 
    record['contact_type'] != 'unknown' and 
    not record['do_not_contact'] and
    record['recruitment_stage'] not in ['declined', 'partnership_active']
)
```
Colleges in `partnership_active` or `declined` are preserved in the directory but protected from bulk campaign dispatches.

---

## 3. Backend Implementation & SQLite Concurrency

### SQLite WAL Mode & Timeout Optimization
To prevent database locks between the background campaign worker thread and concurrent HTTP API write requests on Windows, SQLite is configured in `directory.connect()` with:
```python
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=30000;
sqlite3.connect(..., timeout=30.0)
```
Additionally, transaction scopes in `campaign_queue.py` are strictly decoupled so write transactions are committed and closed before invoking email network operations.

---

## 4. REST API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/pipeline` | Aggregate counts for all 6 stages, urgent overdue/today reminders, and upcoming follow-ups. |
| `GET` | `/api/college/activities?id=<id>` | Unified chronological CRM feed (notes, calls, replies, emails) for a college. |
| `POST` | `/api/college/stage` | Advance or change recruitment stage (`college_id`, `stage`, `notes`, `assigned_to`). |
| `POST` | `/api/college/reply` | Record an official reply, set stage to `replied`, and halt pending queued emails. |
| `POST` | `/api/college/follow-up` | Schedule or reschedule a follow-up date (`date` as `YYYY-MM-DD`, `assigned_to`, `notes`). |
| `POST` | `/api/college/note` | Append internal note, phone call summary, or meeting log (`activity_type`, `content`). |
| `GET` | `/api/export/campaign?id=<id>` | Download CSV delivery report for a specific campaign. |
| `GET` | `/api/export/pipeline` | Download CSV report of all colleges with recruitment stages & follow-ups. |
| `GET` | `/api/export/outreach` | Download complete CSV log of all outreach activities, calls, and email events. |

---

## 5. User Interface (UI) Updates

1. **Overview Tab**:
   - **Recruitment Pipeline Funnel Card**: Visual stage tiles (`Not Contacted`, `Contacted`, `Replied`, `Meeting Arranged`, `Partnership Active`, `Declined`) with live counts. Clicking any tile filters the workspace.
   - **Follow-up Reminders Card**: Actionable table of institutions with reminders due today or overdue, with a direct "Action" button opening the drawer.
   - **Export Action Buttons**: One-click download of the Pipeline CSV and Outreach Log CSV.

2. **Colleges Workspace**:
   - **Recruitment Stage Filter** (`#filterStage`): Filter directory instantly by stage.
   - **Visual Stage Badges**: Distinct color-coded pills for each pipeline state.
   - **Duplicate Outreach Alerts**: `⚠️ Contacted Recently` warning pill when outreach was sent within 14 days.
   - **Follow-up Due Indicators**: `⏰ Due: YYYY-MM-DD` displayed in the outreach column.

3. **College Detail Drawer**:
   - **Recruitment Stage Manager**: Interactive stage dropdown and transition notes with immediate database persistence.
   - **Follow-up Date Picker**: Native calendar date input with quick `+3 Days`, `+1 Week`, `+2 Weeks` helper buttons and team member assignment.
   - **Record Reply Section**: Dedicated reply form that advances stage and cancels pending queued messages.
   - **Log Activity / Call Form**: Quick entry for phone calls, meeting summaries, or internal remarks.
   - **Unified Activity Timeline**: Chronological CRM activity feed with distinct icons (✉️ Email, 💬 Reply, 📞 Call, 🤝 Meeting, 🔄 Stage, ⏰ Follow-up, 📝 Note).

4. **Campaigns Tab**:
   - Added **📥 Export CSV** button on every persistent campaign monitor card to download individual delivery reports.

---

## 6. Verification & Automated Test Suite

A comprehensive test suite was implemented in [`tests/test_tracking_followups.py`](file:///d:/job%20discription/job%20discription/tests/test_tracking_followups.py), covering:
- Default `not_contacted` pipeline state for new institutions.
- Stage transition updates and audit logging.
- Gating and protection of `partnership_active` and `declined` institutions from `sendable`.
- Automated follow-up cancellation upon reply recording.
- Overdue, today, and upcoming deadline categorization in pipeline stats.
- Date format validation (`YYYY-MM-DD`).
- Multi-activity timeline unification (emails, calls, notes, replies).
- 14-day `recently_contacted` duplicate warning calculation.
- Pipeline, Outreach, and Campaign CSV export generation.

### Full Test Suite Results
```bash
python -m unittest discover -s tests
# Ran 55 tests in 1.882s — OK (55/55 passed)

node --test tests/selection.test.cjs
# 2/2 tests passed — OK (0 regressions)
```

System diagnostics report healthy operation (`version: phase-6`, all checks passing).
