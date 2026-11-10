# Access matrix: design

Branch: `feature/access-matrix` (cut from `feature/empanelment` at 7133b35, because the Empanelment views that must be gated live there).

## Intent

Today access is a per-person page (`core/access_views.py`) where any office admin ticks sections of a module per company. The sections (`openings`, `candidates`, `interviews`, `assessments`) do not match the real Empanelment tabs, most tabs sit under "candidates", nothing is audited, and the superadmin cannot delegate cleanly.

The superadmin wants one matrix page to decide who works on which tab, a button to give a whole module at once, the ability to name people who look after the matrix, and a full audit trail.

## Goals

1. A single matrix page: people down the side, module tabs across, one switch per cell.
2. Every tab is its own switch. A per-module **All** button gives or removes the whole module for one person.
3. The page is per company. A two-way switch, **Senken | Avris**, with no "all companies" option. Grants live in exactly one company.
4. Only the superadmin and the people they name **matrix managers** can open the page. The managers are named per company.
5. Every change is written to an append-only history, including manager changes and grants removed as a side effect of something else.
6. Denied means denied: direct URLs answer 403, links disappear, exports follow the same rule.

## Non-goals

- The basics (Home, Chat, Tasks, Schedule, Daily plan) are never in the matrix. Everyone has them always.
- No roles or permission templates. Not per-record or per-field permissions.
- Membership (who is in Senken or Avris, designation, who pays) stays on the existing Access page. The matrix only shows people who are members of the selected company.
- No self-service requests ("ask for access").
- HR, Finance and Sales are placeholders with no real pages. They do not appear in the matrix until they have tabs.

## Anti-goals

- Nobody may widen their own access, and a manager may not widen anyone's beyond what a manager is allowed.
- A change that is not in the history must be impossible. A history row that can be edited or deleted is a failure.
- Deploying must not change what anyone can open today.

## The tabs (Empanelment, key `recruitment`)

| Tab key | Pages it covers |
|---|---|
| `openings` | requisitions list, detail, edit, post, close/reopen, report |
| `people` | people list and detail (the candidate register) |
| `sourcing` | sourcing, add a number, import |
| `screening` | screening queue and follow-up actions |
| `calling` | calling tab and call log |
| `selecting` | selecting tab, interview record and edit |
| `assessments` | the HR assessment form (today's `assessments` section) |
| `hiring` | offers, rounds, accept/decline |
| `onboarding` | onboarding list and "joined" |

*Builder's call:* the tab list is mine. The superadmin approved the grid layout, not these names, so confirm them when reading this. The report sits under `openings`. Exports follow the tab they export.

## How access is stored

- `AccessGrant` stays as is (user, company, module, section, granted_by, created_at, unique per user/company/module/section). "Section" now means tab. The **whole module** is nothing special: the All button creates every current tab's grant. A tab added later is not auto-granted. That is deliberate, so a new tab never opens by surprise.
- New `AccessManager`: user, company, granted_by, created_at, unique per user/company. A manager is per company.
- New `AccessLog`, append-only: actor (FK, SET_NULL) plus a snapshot of the actor's and subject's names (so the row survives a rename or delete), subject (FK, SET_NULL), company (FK, SET_NULL), module, section (blank for module-level or manager rows), action (`grant`, `revoke`, `grant_module`, `revoke_module`, `manager_add`, `manager_remove`, `membership_removed`), created_at. Model `save()` refuses updates and `delete()` raises. Not registered as editable in admin.
- Changes are written in the same transaction as the grant change, so a grant without a log row cannot exist.

## Who may do what

| Actor | Open page | Flip a tab | All button | Edit own row | Manage managers |
|---|---|---|---|---|---|
| Superadmin | yes, either company | yes | yes | n/a (has everything) | yes |
| Manager of that company | yes, that company only | yes | **no** | **no** | no |
| Office admin who is not a manager | no (403) | no | no | no | no |
| Everyone else | no (403) | no | no | no | no |

- *My reading, please confirm:* "All button: superadmin only" means managers get single-tab switches only.
- A manager cannot edit another manager's row? *My call:* they can edit tabs, since managers hold no module powers by being managers. They cannot add or remove managers.
- The superadmin never appears as a row. Inactive users never appear and their grants count for nothing.
- The matrix rows are the active, non-superuser members of the selected company.
- Office admins lose grant editing. They keep editing memberships on the Access page.

## The page

- Route under `/access/matrix/`, linked from the existing Access area for those allowed in.
- Company switch at the top with exactly Senken and Avris. The choice is in the URL (`?company=`), defaults to the first company the viewer may manage, and an unauthorised company answers 403, never silently falls back.
- Grid per the approved mockup (option A): neo-brutalist styling from the design system, yellow **All** per module row, ink module header. Search box over the people column. Paginated through `core/pagination.py` if rows exceed a page.
- *Builder's call:* cells save instantly (one HTMX POST per cell, idempotent: "set this cell on/off"), not behind a Save button. This is safer under two people editing at once and gives one history row per real change. A POST that changes nothing writes no history.
- The **History** panel under the grid lists the latest changes for that company, newest first. Superadmin sees all; a manager sees their own company's.
- A **Managers** strip, superadmin only: add or remove managers for the company.
- Excel export (built on `core/export.py`) of the matrix and of the history, scoped like the page.

## Enforcing it

- `require_section("recruitment", tab)` on every Empanelment view, matching the table above. The decorator already reads the database per request, so removing a grant takes effect on the next click.
- The sidebar's Empanelment entry shows when the person has any tab, and the tab bars inside Empanelment show only the tabs they hold. `core/command.py` is updated to the new tab keys.
- Landing: someone with `calling` only must not be bounced to a 403 by an Empanelment index that points at `people`. The module's entry link goes to the first tab they hold.

## Migration of today's grants (no one gains or loses anything)

New data migration, reversible:

- `openings` stays `openings`.
- `candidates` becomes `people`, `sourcing`, `screening`, `calling`, `selecting`, `hiring`, `onboarding`, because today `candidates` gates all of them.
- `interviews` has no pages today. It maps to `selecting` only if the person does not already have it. Otherwise it is dropped. *Builder's call.*
- `assessments` stays `assessments`.
- No history rows are written for the conversion except one `grant` row per converted grant with the actor blank and a note ("migrated"), so the history starts complete.

## Edge cases to cover with tests

- Direct URL to every gated view with and without its tab: 200 vs 403, for each tab.
- Removing someone's tab, then their next request to it: 403.
- Deactivated user: no access, not in the grid.
- Manager demoted mid-session loses the page immediately.
- Manager editing own row: 403. Manager pressing All: 403. Manager of Senken editing Avris: 403.
- Posting a nonexistent module, tab or company, or a user outside the company: 404 or 400, no row created.
- Removing a member from a company deletes their grants there and writes `membership_removed` history rows, with the office admin as the actor.
- Two simultaneous "grant" posts for one cell produce one grant and one history row.
- Idempotent re-post writes no history row.
- History rows survive deleting the actor or subject and cannot be edited or deleted.
- Shared people (employee S381 works for both companies) can hold different tabs in each, and the grid shows only the selected company's.
- Superadmin created later, or a manager who becomes superadmin: manager row is harmless.
- Exports for people without access: 403.

## Left to the builder

Template details inside the neo-brutalist rules, the history page size, the exact wording of history lines, and the migration numbering. Screenshot at 1280x800 and 390x844 before calling UI done (CLAUDE.md). The grid scrolls sideways inside its card on a phone, with the person column sticky.

## Out of scope for this branch, but related

The uncommitted Empanelment work in the working tree (`hiring/*`, `tasks/*`, etc.) is not part of this branch. It will modify the same view files, so commit or stash it before the matrix work touches `hiring/*_views.py`.
