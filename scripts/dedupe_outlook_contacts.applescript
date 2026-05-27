(*
 * dedupe_outlook_contacts.applescript
 *
 * Find and remove duplicate contacts in Microsoft Outlook for Mac.
 *
 * MATCH STRATEGY (set at top below):
 *   "email"  - group by lowercased primary email. Contacts with no
 *              email are skipped entirely (safest default).
 *   "name"   - group by lowercased trimmed display name. Use only
 *              when emails are mostly missing.
 *
 * KEEP RULE: in each group, the FIRST contact encountered is kept,
 * the rest are deleted. Outlook orders contacts roughly by creation,
 * so this preserves the older copy. If you need "keep most complete",
 * back up your contacts first via Outlook -> File -> Export, then
 * extend this script.
 *
 * SAFETY:
 *   1. Always dry-runs first - shows what WOULD be deleted.
 *   2. Requires "Delete duplicates" click to proceed.
 *   3. Writes a log to ~/Desktop/outlook_dedupe_<timestamp>.log
 *
 * BEFORE RUNNING - STRONGLY RECOMMENDED:
 *   Outlook -> File -> Export -> "Outlook for Mac Data File (.olm)"
 *   Tick "Contacts" only. Stash that .olm somewhere safe.
 *
 * USAGE:
 *   osascript scripts/dedupe_outlook_contacts.applescript
 *   ...or open in Script Editor and Run.
 *)

property matchMode : "email"     -- "email" or "name"
property previewMaxGroups : 30

on run
	-- Verify Outlook is running
	tell application "System Events"
		if not (exists process "Microsoft Outlook") then
			set ans to display dialog ¬
				"Microsoft Outlook is not running. Launch it now?" ¬
				buttons {"Cancel", "Launch Outlook"} default button "Launch Outlook"
			if button returned of ans is "Cancel" then return
			tell application "Microsoft Outlook" to launch
			delay 3
		end if
	end tell

	set logPath to my buildLogPath()
	my writeLog(logPath, "=== Outlook dedupe scan started ===")
	my writeLog(logPath, "Match mode: " & matchMode)

	-- Pull all contacts. We only need ids + a key per contact, no
	-- live references, so we grab everything up front in one Apple
	-- Event and operate on plain data afterwards. This avoids the
	-- "stale reference" trap when contacts are deleted mid-loop.
	tell application "Microsoft Outlook"
		try
			set allContacts to every contact
		on error errMsg number errNum
			display dialog "Could not read Outlook contacts." & return & ¬
				"Error " & errNum & ": " & errMsg buttons {"OK"} default button "OK"
			return
		end try
	end tell

	set totalCount to count of allContacts
	my writeLog(logPath, "Total contacts: " & totalCount)

	if totalCount is 0 then
		display dialog "No contacts found in Outlook." buttons {"OK"} default button "OK"
		return
	end if

	-- Snapshot id + key + display label for each contact.
	set snapshots to {}  -- list of {id, key, label}
	set skippedNoKey to 0
	repeat with c in allContacts
		set theKey to my keyForContact(c)
		if theKey is "" then
			set skippedNoKey to skippedNoKey + 1
		else
			set theId to ""
			try
				tell application "Microsoft Outlook" to set theId to id of c
			end try
			set theLabel to my displayLabel(c)
			if theId is not "" then
				set end of snapshots to {theId, theKey, theLabel}
			end if
		end if
	end repeat

	my writeLog(logPath, "Snapshots: " & (count of snapshots))
	my writeLog(logPath, "Skipped (no usable key): " & skippedNoKey)

	-- Build groups: parallel lists keyList and groupList.
	-- groupList[i] is a list of {id, label} entries sharing keyList[i].
	set keyList to {}
	set groupList to {}
	repeat with snap in snapshots
		set k to item 2 of snap
		set entry to {item 1 of snap, item 3 of snap}
		set idx to my indexOfString(keyList, k)
		if idx is 0 then
			set end of keyList to k
			set end of groupList to {entry}
		else
			set existing to item idx of groupList
			set end of existing to entry
			set item idx of groupList to existing
		end if
	end repeat

	-- Pick out duplicate groups (size > 1)
	set dupeKeys to {}
	set dupeGroups to {}
	set toDeleteCount to 0
	repeat with i from 1 to count of keyList
		set g to item i of groupList
		if (count of g) > 1 then
			set end of dupeKeys to item i of keyList
			set end of dupeGroups to g
			set toDeleteCount to toDeleteCount + ((count of g) - 1)
		end if
	end repeat

	my writeLog(logPath, "Duplicate groups: " & (count of dupeGroups))
	my writeLog(logPath, "Would delete: " & toDeleteCount)

	-- Build preview
	set previewLines to {}
	set end of previewLines to "Scanned " & totalCount & " contacts."
	set end of previewLines to "Match mode: " & matchMode
	set end of previewLines to "Duplicate groups: " & (count of dupeGroups)
	set end of previewLines to "Would delete: " & toDeleteCount & " contacts"
	set end of previewLines to "(keeping the FIRST contact in each group)"
	set end of previewLines to ""

	if (count of dupeGroups) is 0 then
		set end of previewLines to "No duplicates found."
		set txt to my joinLines(previewLines)
		my writeLog(logPath, txt)
		display dialog txt buttons {"OK"} default button "OK"
		return
	end if

	set end of previewLines to "First " & previewMaxGroups & " groups:"
	set shown to 0
	repeat with i from 1 to count of dupeKeys
		if shown is greater than or equal to previewMaxGroups then exit repeat
		set end of previewLines to "* " & (item i of dupeKeys)
		repeat with entry in (item i of dupeGroups)
			set end of previewLines to "    - " & (item 2 of entry)
		end repeat
		set shown to shown + 1
	end repeat

	set previewText to my joinLines(previewLines)
	my writeLog(logPath, previewText)

	set confirmText to previewText & return & return & ¬
		"Full log: " & logPath & return & return & ¬
		"Click 'Delete duplicates' to proceed. There is no undo. " & ¬
		"Make sure you exported your contacts to .olm first."

	set dlg to display dialog confirmText ¬
		buttons {"Cancel (dry run)", "Delete duplicates"} ¬
		default button "Cancel (dry run)" ¬
		with title "Outlook dedupe"
	if button returned of dlg is "Cancel (dry run)" then
		my writeLog(logPath, "User cancelled.")
		display dialog "Dry run only. No contacts deleted." & return & ¬
			"Log: " & logPath buttons {"OK"} default button "OK"
		return
	end if

	-- Execute: in each duplicate group, keep [1], delete [2..n] by id
	set deletedCount to 0
	set failedCount to 0
	repeat with g in dupeGroups
		repeat with j from 2 to count of g
			set vid to item 1 of (item j of g)
			set vlabel to item 2 of (item j of g)
			try
				tell application "Microsoft Outlook"
					delete contact id vid
				end tell
				set deletedCount to deletedCount + 1
				my writeLog(logPath, "DELETED " & vlabel & " (id=" & vid & ")")
			on error errMsg
				set failedCount to failedCount + 1
				my writeLog(logPath, "FAILED " & vlabel & " (id=" & vid & ") - " & errMsg)
			end try
		end repeat
	end repeat

	set summary to "Done." & return & ¬
		"Deleted: " & deletedCount & return & ¬
		"Failed: " & failedCount & return & ¬
		"Log: " & logPath
	my writeLog(logPath, "=== Done. Deleted " & deletedCount & ", failed " & failedCount & " ===")
	display dialog summary buttons {"OK"} default button "OK"
end run


-- ─── Helpers ────────────────────────────────────────────────────────

-- Returns the grouping key for a contact based on matchMode.
on keyForContact(c)
	if matchMode is "email" then
		return my primaryEmailLower(c)
	else
		return my displayNameLower(c)
	end if
end keyForContact

-- Primary email address of a contact, lowercased; "" if none.
on primaryEmailLower(c)
	set raw to ""
	try
		tell application "Microsoft Outlook"
			set ems to email addresses of c
			if (count of ems) > 0 then set raw to address of (item 1 of ems)
		end tell
	end try
	return my normLower(raw)
end primaryEmailLower

-- Display name of a contact, lowercased; "" if missing.
on displayNameLower(c)
	set raw to ""
	try
		tell application "Microsoft Outlook" to set raw to display name of c
	end try
	if raw is missing value then set raw to ""
	return my normLower(raw)
end displayNameLower

-- A human-friendly label for the contact (display name + first email).
on displayLabel(c)
	set nm to ""
	try
		tell application "Microsoft Outlook" to set nm to display name of c
	end try
	if nm is missing value or nm is "" then set nm to "(no name)"
	set em to ""
	try
		tell application "Microsoft Outlook"
			set ems to email addresses of c
			if (count of ems) > 0 then set em to address of (item 1 of ems)
		end tell
	end try
	if em is "" or em is missing value then return nm as string
	return (nm as string) & " <" & (em as string) & ">"
end displayLabel

on normLower(s)
	if s is missing value then return ""
	try
		set s to s as string
	on error
		return ""
	end try
	if s is "" then return ""
	return do shell script ¬
		"/usr/bin/printf '%s' " & quoted form of s & ¬
		" | /usr/bin/tr '[:upper:]' '[:lower:]'" & ¬
		" | /usr/bin/tr -s '[:space:]' ' '" & ¬
		" | /usr/bin/sed 's/^ //;s/ $//'"
end normLower

on indexOfString(theList, target)
	repeat with i from 1 to count of theList
		if (item i of theList) as string is equal to (target as string) then return i
	end repeat
	return 0
end indexOfString

on joinLines(theList)
	set out to ""
	repeat with i from 1 to count of theList
		if i > 1 then set out to out & return
		set out to out & (item i of theList) as string
	end repeat
	return out
end joinLines

on buildLogPath()
	set ts to do shell script "/bin/date +%Y%m%d_%H%M%S"
	return (POSIX path of (path to desktop folder)) & "outlook_dedupe_" & ts & ".log"
end buildLogPath

on writeLog(p, msg)
	try
		do shell script "/bin/echo " & quoted form of (msg as string) & " >> " & quoted form of p
	end try
end writeLog
