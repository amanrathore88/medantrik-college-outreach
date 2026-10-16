# Phase 1: stable local baseline

## Scope assumptions

This release remains a local, single-operator application. These are planning assumptions, not confirmed company requirements:

- Directory expansion will cover Delhi NCT, Noida, Greater Noida, Ghaziabad and Gurgaon/Gurugram.
- Noida and Greater Noida will be separate areas; Gurgaon and Gurugram will be aliases.
- Exact Ghaziabad/Gurugram city-versus-district boundaries remain to be confirmed before collection.
- Proposed categories: universities, affiliated colleges and recognized standalone higher education institutions; exclude schools and coaching centres.
- Whether general enquiry emails are acceptable when placement contacts are missing remains to be confirmed.

The existing 25 records are preserved and labelled **unverified**. Their original `Ready` CSV field is not proof of verification. No new college data has been collected in Phase 1.

## Start and verify

Requires Python 3.10+; no third-party Python packages are needed. Double-click `Start Dashboard.cmd`. It starts a hidden background process, waits for a healthy response, then opens the browser. A healthy existing instance is reused.

Alternatively run `python dashboard.py` from this folder and open http://localhost:5050/. Keep that terminal open. The server binds only to 127.0.0.1.

Health: http://localhost:5050/api/health checks configuration, directory and templates. It does not authenticate email or verify recipients. Logs are `dashboard-output.log` and `dashboard-error.log` when using the launcher. Stop the relevant Python process to stop a background instance. Restart it after backend code changes.

## Settings and passwords

Non-secret sender, subject and SMTP settings live in `config.json`. No saved password is used. Enter the Google App Password in the dashboard only when sending; it is not saved to disk, browser storage or logs. The command-line sender prompts privately or reads `MEDANTRIK_SMTP_PASSWORD` from its environment.

The previous package contained a plaintext credential. If it was real, its account owner should revoke/replace it; removing it from the current files cannot revoke earlier copies.

The script's `test_mode` applies to the command-line script only. In the dashboard, use the separate test button; campaign sending requires recipient selection and confirmation.

## Selection behaviour

No colleges are selected initially. Search changes visibility, not selection. `Select visible` adds the currently displayed colleges. `Clear all` removes every selection, including hidden selections. The master checkbox affects only visible rows. The total includes selected colleges hidden by a filter. Sending uses that complete selected list.

## Components

- `dashboard.py`: HTTP routes and local request protection.
- `static/dashboard.html`, `dashboard.js`, `selection.js`: interface and selection state.
- `settings.py`: configuration and runtime credential lookup.
- `directory.py`: CSV directory loader and unverified status.
- `templates.py`: configured HTML and plain-text loading.
- `mailer.py`: shared validation and SMTP delivery.
- `send_college_campaign.py`: command-line workflow and CSV result logging.

## Remaining phases

The dashboard still sends sequentially from a browser-driven loop; keep the browser open. It is not a durable background queue. Directory database expansion, persistent dashboard history, template creation, reply tracking, shared-user hosting and scheduling remain for later phases. Gmail opens a draft and requires manual sending. SMTP acceptance is not proof of inbox delivery.

## Verification

Run `python -m unittest discover -s tests` and `node --test tests/selection.test.cjs`. Tests simulate delivery; no real mail is sent. Node is only required for the selection test, not for running the dashboard.
