# College outreach: operating guide

See [Phase 1 baseline](PHASE_1.md) for scope, components and limitations.

## Dashboard

1. Double-click `Start Dashboard.cmd` and wait for the browser to open.
2. Confirm the sender and subject, loaded from `config.json`.
3. Enter the sender's Google App Password. It is held for this page session, not saved.
4. Review the live preview and use **Send test email to sender**.
5. Check the test in the sender mailbox before starting a live campaign.
6. Search and select colleges. Selection persists across filters; the selected count includes hidden selections. The supplied contacts have not yet been verified.
7. Click the SMTP dispatch action and review the recipient count before confirming. Keep the page open until completion.

The Gmail action creates a plain-text draft with selected addresses in BCC; it does not send automatically and does not use the SMTP pacing.

## Command-line alternative

Keep `test_mode` set to `true` in `config.json` for testing, then run `python send_college_campaign.py`. The program prompts for an App Password without displaying or saving it. It also accepts the `MEDANTRIK_SMTP_PASSWORD` environment variable.

For an authorized live campaign, set `test_mode` to `false`. The script also requires typing `SEND` before dispatch. It saves results in `campaign_send_log.csv` and uses the configured interval between emails (minimum two seconds).

Do not put passwords in `config.json` or source files. A normal account password may not work; App Password availability depends on the company's Google account policy. Contact the account administrator if it is unavailable.

## Troubleshooting

- Connection refused: launch the dashboard; the browser URL alone does not start it.
- Port already occupied: check `/api/health`; stop the earlier dashboard instance before restarting updated code.
- Invalid or missing files: inspect `/api/health` and restore the indicated configuration, directory or template.
- Authentication failure: verify the sender account and App Password with the administrator.
- Uncertain send result: check the sender's Sent mailbox before retrying to avoid duplicates.

The health endpoint does not send mail. No delivery, bounce or reply tracking is provided in this phase.
