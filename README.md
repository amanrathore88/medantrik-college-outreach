# College Outreach Platform (Delhi-NCR)

A production-ready internal recruitment and campus outreach platform for hiring teams to discover, verify, contact, and build partnerships with colleges and universities across Delhi-NCR (**Delhi NCT, Noida, Greater Noida, Ghaziabad, and Gurugram**).

---

## 🚀 Quickstart

### Prerequisites
- **Python 3.10+** installed and available on your `PATH`.
- **Windows PowerShell** (for desktop launch scripts).
- Modern web browser (Chrome, Edge, Firefox, Brave).

### Starting the Platform
You have two convenient ways to start the server:

#### Option 1: One-Click Desktop Launcher (Recommended on Windows)
Double-click `Start Dashboard.cmd` in this directory.  
It automatically:
1. Cleans up any orphaned process holding port `5050`.
2. Starts the background outreach server with crash-recovery hooks.
3. Performs a health check against `http://127.0.0.1:5050/api/health`.
4. Opens your default browser directly to the dashboard.

#### Option 2: Direct Command Line
Run PowerShell or Command Prompt in this folder:
```powershell
python dashboard.py
```
Open your browser and navigate to:
```
http://127.0.0.1:5050/
```

---

## 🏛️ Geographic Scope & Directory Inventory

The platform comes pre-loaded with **218 verified and sourced higher-education institutions** across Delhi-NCR:

| Region | Search Boundaries | Institution Categories |
| :--- | :--- | :--- |
| **Delhi** | National Capital Territory (NCT) | Central, State, Private Universities & Premier Affiliated Colleges (DU, IPU, IIT, etc.) |
| **Noida** | Gautam Buddha Nagar (Urban Noida) | Standalone Campuses, Technical Institutions, Universities |
| **Greater Noida** | Knowledge Park & Surrounding Zones | Technical & Engineering Hubs, Private Universities |
| **Ghaziabad** | District Boundaries | Affiliated Engineering/Management Institutes (AKTU), State/Private Campuses |
| **Gurugram** | Gurgaon / Gurugram District | State Universities, Private Universities, Government Colleges (DHE Haryana) |

> [!NOTE]
> Schools and coaching centers are strictly excluded. Distinct physical campuses (e.g. Amity Noida vs. Amity Gurugram) are tracked independently with dedicated placement contacts.

---

## 🏗️ Architecture & Modules

The platform is designed with clean architectural separation and zero external heavy web framework dependencies (built on Python standard library `http.server`, `sqlite3`, `email`, `urllib`):

- **[`dashboard.py`](file:///d:/job%20discription/job%20discription/dashboard.py)**: HTTP server on port `5050`, local-only binding (`127.0.0.1`), REST API router, CSRF protection, and application lifecycle.
- **[`directory.py`](file:///d:/job%20discription/job%20discription/directory.py)**: SQLite database access layer, schema migrations, optimistic concurrency control, search aliases, deduplication, CSV import engine, and audit logging.
- **[`templates.py`](file:///d:/job%20discription/job%20discription/templates.py)**: Email template engine with rich HTML & plaintext alternatives, placeholder substitution (`{{college_name}}`, `{{contact_name}}`, etc.), version history, and snapshotting.
- **[`campaign_queue.py`](file:///d:/job%20discription/job%20discription/campaign_queue.py)**: Durable SQLite-backed message queue, background worker daemon thread, IST business hours windowing (09:00–18:00 IST), working days filter (Mon–Fri), configurable hourly/daily rate caps, crash recovery, and sender rate protection.
- **[`mailer.py`](file:///d:/job%20discription/job%20discription/mailer.py)**: RFC 5322 compliant MIME builder, SMTP TLS transport, recipient format validation, and security sanitization.
- **[`settings.py`](file:///d:/job%20discription/job%20discription/settings.py)**: Non-sensitive configuration manager (`settings.json`).
- **`static/`**: Vanilla JavaScript, CSS, and HTML user interface:
  - `static/dashboard.html`: Single-page app layout (Overview, Directory, Templates, Campaigns, Settings, Direct Send modal, Category modal).
  - `static/dashboard.js`: Reactive frontend controller, Category tabs switcher, live state management, dialog controllers, search filters, and CSV export triggers.
  - `static/dashboard.css`: Clean, accessible enterprise interface theme.

---

## ⚡ Direct Immediate Send & Multi-Category System

1. **Instant Direct Emailing (`⚡ Direct Email`)**: Send an email immediately to **any recipient email address** without adding them to the directory first. Pick an existing template or write a custom message, with instant delivery and persistent audit logging.
2. **Category-Based Organization**: Group contacts into categories like **Colleges**, **Gyms**, **Offices**, and **Households**, or create new custom categories on the fly. Filter directory records by category and launch targeted email campaigns.

---

## 🔒 Security Invariants

1. **Zero Saved Passwords in Storage**: The sender's email password or Google Workspace App Password is **never saved to disk**, never written to `settings.json`, and never stored in SQLite. It is held strictly in volatile server process memory for the active browser session.
2. **Localhost Binding**: Server listens strictly on `127.0.0.1:5050` with Host-header enforcement.
3. **CSRF Tokens**: All mutating state endpoints (POST / PUT / DELETE) require a cryptographically secure `X-CSRF-Token`.
4. **Optimistic Locking**: Directory records and templates track numeric `version` counters to prevent concurrent overwrite collisions.
5. **Accidental Duplicate Dispatch Protection**:
   - Starting up after an abrupt shutdown automatically flags any messages stuck in `sending` status as `needs_review` and pauses the parent campaign until the operator verifies sent items in their email client.
   - Recording an institution's reply automatically suppresses any pending follow-up messages queued for that institution across all campaigns.

---

## 🧪 Automated Test Suite

The project includes an automated test suite with **75 Python unit/integration tests** and **Node.js frontend logic tests**:

### Run All Python Tests:
```powershell
python -m unittest discover -s tests
```

### Run Phase 7 Validation Test Suite:
```powershell
python -m unittest tests/test_phase7_validation.py
```

### Run JavaScript Frontend Tests:
```powershell
node --test tests/selection.test.cjs
```

---

## 📚 Handover Documentation

- **[`USER_GUIDE.md`](file:///d:/job%20discription/job%20discription/USER_GUIDE.md)**: Nontechnical operator guide for hiring managers, recruiters, and placement coordinators.
- **[`OPERATIONS.md`](file:///d:/job%20discription/job%20discription/OPERATIONS.md)**: Technical administrator runbook, Google Workspace App Password setup, SQLite database maintenance, crash recovery, and troubleshooting.
- **`PHASE_1.md` through `PHASE_7.md`**: Chronological implementation logs and verification reports for all completed project milestones.
