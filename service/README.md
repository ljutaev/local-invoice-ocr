# Running the worker as a launchd service (macOS)

This keeps `invoiceflow work` running in the background so dropped/emailed
invoices get processed automatically.

## Setup

1. Edit `com.ljutaev.invoiceflow.work.plist`:
   - replace `/ABSOLUTE/PATH/TO/local-invoice-ocr` with the repo path,
   - replace `YOUR_USER` with your macOS username,
   - adjust env vars (model, OLLAMA_URL) if needed.

2. Install and start:
   ```bash
   cp service/com.ljutaev.invoiceflow.work.plist ~/Library/LaunchAgents/
   launchctl load   ~/Library/LaunchAgents/com.ljutaev.invoiceflow.work.plist
   launchctl start  com.ljutaev.invoiceflow.work
   ```

3. Logs: `~/.invoiceflow/worker.out.log` and `worker.err.log`.

## Stop / remove
```bash
launchctl stop   com.ljutaev.invoiceflow.work
launchctl unload ~/Library/LaunchAgents/com.ljutaev.invoiceflow.work.plist
```

## Ingestion sources
- **Folder:** also run `invoiceflow watch` (or add a second LaunchAgent for it) to pick up files dropped into `~/.invoiceflow/inbox`.
- **Email:** run `invoiceflow fetch-email` on a schedule (cron / a periodic LaunchAgent) with `INVOICEFLOW_IMAP_HOST/USER/PASS` set.

> Prerequisite: Ollama running with the configured model (`ollama pull qwen2.5:14b`).
