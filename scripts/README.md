# scripts/

Standalone utilities that aren't part of the FastAPI server. Run by hand.

## dedupe_outlook_contacts.applescript

Find and remove duplicate contacts in Microsoft Outlook for Mac.

### What it does

1. Reads every contact from Outlook via AppleScript.
2. Groups them by **primary lowercased email** (default) or **display name**.
3. Shows a dry-run preview dialog with every duplicate group and how many would be deleted.
4. Only deletes if you click **Delete duplicates** in the confirmation dialog.
5. Writes a full audit log to `~/Desktop/outlook_dedupe_<timestamp>.log` listing every contact that was queued and the outcome.

The **first contact in each group is kept**; the rest are deleted. Outlook tends to order contacts by creation date, so this preserves the older copy. If you need different keep-rules (e.g. "keep most complete"), edit the loop near the bottom of `on run`.

### Before you run

```text
Outlook → File → Export → "Outlook for Mac Data File (.olm)"
```

Tick **Contacts** only. Keep the `.olm` somewhere safe. **There is no undo**; the export is your safety net.

### Running it

**Recommended — install into Outlook's Script menu (one-time):**

```bash
bash scripts/install.sh
```

The installer compiles the script into `~/Library/Application Scripts/com.microsoft.Outlook/Dedupe Contacts.scpt` and enables the macOS Script menu so it appears in Outlook's menu bar. After install:

1. Switch to Outlook so it's the foreground app.
2. Click the **scroll icon** in the menu bar (top-right, next to the clock).
3. Choose **Dedupe Contacts**.

Re-run `install.sh` any time the source `.applescript` changes — it overwrites in place.

**Alternative — direct invocation:**

```bash
osascript "scripts/dedupe_outlook_contacts.applescript"
```

Or open in **Script Editor** and click ▶ Run.

The first run will prompt for Automation permission for Outlook and System Events — click _OK_ in the macOS dialog.

### Match mode

Edit the line near the top of the script:

```applescript
property matchMode : "email"   -- or "name"
```

- `"email"` (default) — only groups contacts that share a normalised email. Contacts with no email are left alone. Almost no false positives.
- `"name"` — groups by lowercased trimmed display name. Higher false-positive risk (Jane Doe vs Jane Doe Inc.); use only if your contacts have mostly missing emails.

### Output

After running, you'll get:

- A summary dialog showing how many were deleted and how many failed.
- A log file at `~/Desktop/outlook_dedupe_YYYYMMDD_HHMMSS.log` with one line per contact considered, prefixed `DELETED` or `FAILED`. Keep this if you ever need to remember what was removed.

### Limitations

- **Outlook for Mac only.** The script uses Outlook's AppleScript dictionary; Outlook Web App doesn't expose one.
- **One email per group.** Cards with multiple emails are matched on the _first_ one returned by Outlook. If two contacts share their _second_ email but not their first, they won't be grouped.
- **No fuzzy matching.** `john@example.com` and `john+tag@example.com` are treated as different. Add normalisation in `primaryEmailLower` if you need plus-tag stripping.
