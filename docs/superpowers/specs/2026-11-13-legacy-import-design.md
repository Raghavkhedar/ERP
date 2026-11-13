# Legacy import: design

Status: approved in conversation, 2026-11-13. Code: `hiring/legacy_import.py`, run with
`python manage.py import_legacy <export.zip>` (dry run) and `--apply`.

## Intent
Bring the old system's data into the Empanelment models so the team can work from the ERP the
next day. Rows are written directly (never through `source_number()`), so nothing gets a
"call tomorrow". Normal number entry is unchanged.

## Rules
- Every candidate becomes a card (`candidate_id` = the WJ number, `legacy_id` = the earlier id),
  sourced under the requisition "Data 13th Nov 26" (closed), source "Data 13th Nov 26".
- Status: the preference level is the truth (closed, ODB, do not call, hold-FF -> contact status;
  open, semi, preferred, least -> priority). Dates of 1-7 Jan 2000 are dropped.
- The card also keeps department, sub-department (before and after the call), source, keyword,
  free/paid, belongs to, lead date, skills, assessor comments and resignation. New numbers copy
  department, sub-department and source from their requisition.
- Phones: the first number is the phone, the second the alternate phone.
- Several cards on one number: the card already in the ERP leads, else the one with a live dated
  call, else the most call logs. The rest are archived and shown on the main card; their
  interviews and whereabout forms move to the main card.
- Pending calls: the dated cards, with their assignee (Nitin when none), on active main cards.
  Done assignments are kept as completed follow-ups.
- Calls: every call log. The caller is the name signed at the end of the note (common
  signatures only, misspellings matched), else the login. Bulk shifts and parking notes are
  left out (unless the log carries a whereabout form). People with no account get an inactive user (shown as "Former employee").
- Whereabout forms sit on the call flagged for them, else on a call of their own.
- Interviews keep their answers, tables, HR assessment and files; the interview wins over the card.
- Joined and offered candidates get an offer.
- Candidate timeline and reschedule history are not imported: the timeline is built from records.

## Safety
One transaction; a dry run rolls back and writes a review list. Refuses to run twice.
