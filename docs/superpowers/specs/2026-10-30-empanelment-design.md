# Empanelment: design

Status: draft for approval, 2026-10-30. Builds on `senken-erp-empanelment-decisions.md` (Downloads) and the Zoho export `Empanelment_Report-development(1).ds`.

## Intent

Replace the Zoho "Empanelment Report" with six sections that one candidate walks through: Preparing, Sourcing, Screening, Selecting, Hiring, On-Boarding. Everything is linked (requisition -> sourced number -> person -> calls -> interview -> offer -> assessment) so requisition-level analysis falls out for free. The user types only what a human must; everything else is derived or pre-filled.

## Goals

- A candidate's stage is **calculated** from what exists (calls, interview, offer, assessment), never typed and never stored.
- Counts per requisition (sourced, duplicates, screened, interviewed, selected, offered, joined) are calculated on demand.
- Screening is a fast call-follow-up queue: overdue / today / upcoming, one-tap outcomes, cancel / reschedule / reassign.
- Simple UI. Hallmark for layout and interaction, inside the project's neo-brutalist tokens (`static/css/input.css`); this is our call, not agreed.
- Every new data page ships with an Excel export (core/export.py), scoped like the page.

## Non-goals

- Offboarding, calling from the ERP, Zoho migration, skills ratings, Android app. Separate projects.
- Onboarding checklists beyond joining date and the assessment.

## Anti-goals

- Storing derived values (last call, stage, counts).
- Blocking or silently merging duplicate numbers.
- Making the user retype anything already on the card.

## The six sections

The candidate is a `people.Person` (already has phone_key, history, version, import, export). New models live in a new `hiring` app; business logic in `hiring/services.py`.

1. **Preparing**: `Requisition` (superadmin only): department, profile, headcount, site, needed-by date, status (open / closed), opened-by. Form is the only typing here.
2. **Sourcing**: `SourcedNumber`: requisition (required), person, source, date, `is_duplicate`. Added by form or Excel import. Phone matched on last 10 digits: no match creates a Person; a match creates no card and marks the row duplicate of the existing person. Duplicates list = rows marked duplicate (rate per source and per requisition).
3. **Screening**: `FollowUp` task (person, due, owner, purpose Call/Interview/Offer/Joining/Assessment/Update, status Pending/Completed/Not Done/Cancelled, reschedule count, reason, original due, reassigned-from) and `CallLog` (one per call: outcome, notes, caller, time, `not_a_call` flag). Logging a call closes the task and can open the next. Reschedule reasons: Staff Shortage, High Volume, Holiday, Redistribution, Other, Mistake. The caller's queue shows only their own tasks; supervisors see all. Existing alarm/notification code is reused for reminders.
4. **Selecting**: `Interview` (pre-filled from the card; date, questions asked, result Selected/Hold/Rejected, next follow-up date, closed + reason) and a separate `HRAssessment` (decision, level Expert/Intermediate/Beginner/Helper, hold tenure, comments), readable by HR only.
5. **Hiring**: `Offer` (one per person per requisition) with `OfferRound` rows (amount offered, candidate's counter, response, date). Final state Offered / Accepted / Declined; accepted sets the joining date.
6. **On-Boarding**: joining date, then a **three-day assessment**. Its fields are **left empty for now** (user's call); the section ships with a placeholder and the model is added when the form is provided.

Derived stage: Hiring (until offer accepted or closed), Onboarding (accepted until assessment done), then Working. Stage ties to the decisions doc's list.

## Constraints (from the decisions doc, apply to every model)

- django-simple-history on every model; `version` field with stale-save rejection; archive, never delete; FKs PROTECT.
- Money as Decimal; UTC stored, IST shown.
- Rules as DB constraints (unique sourced number per requisition+person, one open FollowUp per person+purpose).
- Roles via groups, checked in the view: admin, supervisor, BO Caller.
- Tests for each service; `uv run pytest` before every push. Screenshots at 1280x800 and 390x844 before UI is called done.

## Build order (small PRs, each with export + tests)

1. `hiring` app + Requisition (Preparing).
2. SourcedNumber, duplicates list, Excel import (Sourcing).
3. FollowUp + CallLog + caller queue (Screening).
4. Interview + HRAssessment (Selecting).
5. Offer + rounds (Hiring).
6. On-Boarding shell; assessment fields when provided.
7. Per-requisition funnel report.

## Left to the builder

Exact field widths, picklist spellings (fix "Dimploma"-style typos), sub-department lists, import column mapping, queue layout.

## Open

- Three-day assessment fields (deferred by the user).
- Call outcome list (channel + result) is "proposed" in the decisions doc.
- Sources list, "Touch"/"DR" meanings, nightly rules.
