# Access Matrix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A superadmin-only (plus named managers) per-company matrix that grants Empanelment tabs to people, with a per-module All button and an append-only history.

**Architecture:** Reuse `AccessGrant` (section now means tab). Add `AccessManager` and an append-only `AccessLog`. All grant changes go through one service module, `core/matrix.py`, which checks permission, writes the grant and the log row in one transaction. Views, templates and exports are thin over it. Existing views switch from the `candidates` section to per-tab sections.

**Tech Stack:** Django, HTMX, Alpine, Tailwind v4 (neo-brutalist rules in `CLAUDE.md`), pytest (`uv run pytest`), `core/export.py`, `core/pagination.py`.

**Spec:** `docs/superpowers/specs/2026-11-10-access-matrix-design.md`

## Global Constraints

- Basics (Home, Chat, Tasks, Schedule, Daily plan) are never gated and never in the matrix.
- Grid is per company, switch is exactly Senken | Avris, no "all companies"; `?company=<slug>`; a company the viewer may not manage answers 403.
- Tab keys for module `recruitment`: `openings`, `people`, `sourcing`, `screening`, `calling`, `selecting`, `assessments`, `hiring`, `onboarding`.
- All button: superadmin only. Managers: single tabs only, never their own row, never add/remove managers, only their own company.
- The superadmin is never a row; inactive users are never rows and their grants count for nothing; rows are members of the selected company.
- `AccessLog` rows cannot be updated or deleted (instance or queryset). Every grant change writes its log row in the same transaction. A no-op writes nothing.
- Cells save instantly (one POST per cell, idempotent), no Save button.
- A tab added later is not auto-granted by All.
- Office admins who are not managers lose grant editing; they keep membership editing.
- Deploy changes nobody's effective access (data migration).
- New data features ship with an Excel export built on `core/export.py`, scoped like the page.
- No `Co-Authored-By` or "Generated with" lines in commits or PRs. Run `uv run pytest` before any push. Never start runserver.
- UI follows the neo-brutalist design in `CLAUDE.md`; screenshot at 1280x800 and 390x844 before calling UI done.

## Review Focus

- Someone with only `calling` opens Empanelment: the sidebar entry must lead to a tab they hold, never a 403. (Task 3)
- A person is removed from a company by an office admin: their grants there vanish and the history says who did it. (Task 6)
- A manager is demoted, deactivated, or loses membership between page load and click: the click is refused. (Task 2)
- A POST names a nonexistent tab, module, company, or a user from another company: no row is created. (Task 2, 4)
- A shared employee (S381) holds different tabs in Senken and Avris: the grid shows only the selected company. (Task 4)

---

### Task 1: Models and migration

**Files:**
- Modify: `core/models.py` (append after `AccessGrant`)
- Create: `core/migrations/0011_access_manager_log.py` (via `makemigrations`)
- Test: `core/test_matrix_models.py`

**Interfaces:**
- Produces: `AccessManager(user, company, granted_by, created_at)`, unique `(user, company)`, related name `access_managerships` on user.
- Produces: `AccessLog(actor, actor_name, subject, subject_name, company, module, section, action, note, created_at)`; `AccessLog.Action` choices `grant, revoke, grant_module, revoke_module, manager_add, manager_remove, membership_removed`; ordering `-created_at, -id`. FKs are `SET_NULL`, `related_name="+"`. Custom queryset whose `update()` and `delete()` raise `PermissionError`; `save()` on an existing pk and `delete()` raise `PermissionError`.

- [ ] **Step 1: Write failing tests** in `core/test_matrix_models.py`: `test_log_row_cannot_be_edited` (create, change `note`, `save()` raises `PermissionError`), `test_log_row_cannot_be_deleted` (instance `delete()` and `AccessLog.objects.all().delete()` and `.update(note="x")` each raise), `test_log_survives_deleting_actor` (delete actor user, row remains, `actor` is None, `actor_name` kept), `test_manager_unique_per_company` (second identical row raises `IntegrityError`).
- [ ] **Step 2: Run** `uv run pytest core/test_matrix_models.py -q`. Expected: FAIL (names not defined).
- [ ] **Step 3: Implement** the two models in `core/models.py` as specified. Append-only is enforced in model methods and the manager's queryset, not admin. Do not register `AccessLog` in admin as editable (leave unregistered).
- [ ] **Step 4: Generate migration** `uv run python manage.py makemigrations core -n access_manager_log`; confirm it is `0011`.
- [ ] **Step 5: Run** the test file. Expected: PASS.
- [ ] **Step 6: Commit** `git add core/models.py core/migrations/0011_* core/test_matrix_models.py && git commit -m "Access matrix: manager and history models"`

### Task 2: The matrix service

**Files:**
- Create: `core/matrix.py`
- Test: `core/test_matrix.py`

**Interfaces:**
- Consumes: `AccessGrant`, `AccessManager`, `AccessLog`, `Membership`, `MODULES` (Task 3 changes its sections; this task's tests use whatever `MODULES["recruitment"].sections` holds, via `TABS = list(MODULES["recruitment"].sections)`).
- Produces:
  - `class MatrixError(ValueError)`: bad module, tab, company mismatch, or ineligible subject.
  - `can_manage(user, company) -> bool`: active and (superuser, or has an `AccessManager` row for the company).
  - `eligible(subject, company) -> bool`: active, not superuser, member of company.
  - `set_tab(actor, subject, company, module, tab, on: bool) -> bool` returns True if something changed. Raises `PermissionDenied` when `not can_manage(actor, company)`, or `subject == actor` and actor is not superuser. Raises `MatrixError` for unknown module/tab or ineligible subject.
  - `set_module(actor, subject, company, module, on: bool) -> int` superuser only (`PermissionDenied` otherwise); returns number of tabs changed; logs one `grant_module`/`revoke_module` row per call if anything changed, and no per-tab rows.
  - `add_manager(actor, subject, company) -> bool` / `remove_manager(...)`, superuser only; subject must be `eligible`; log `manager_add` / `manager_remove`.
  - `drop_company_grants(actor, subject, company) -> int`: deletes the person's grants in the company and writes one `membership_removed` row per grant (used in Task 6).
  - `rows(company) -> list[dict]`: `{"user": User, "held": set[(module, tab)]}` for eligible members, ordered by first_name, username.

- [ ] **Step 1: Write failing tests** in `core/test_matrix.py`, each asserting both the grant state and the `AccessLog` rows: `test_superadmin_grants_and_revokes_a_tab`, `test_repeat_grant_writes_one_log_row` (call twice → one row), `test_manager_can_flip_tab_in_own_company`, `test_manager_cannot_use_all_button`, `test_manager_cannot_edit_own_row`, `test_manager_of_senken_cannot_edit_avris`, `test_demoted_manager_is_refused_next_call`, `test_deactivated_manager_is_refused`, `test_unknown_tab_module_raises_and_writes_nothing`, `test_subject_outside_company_is_refused`, `test_superadmin_subject_is_refused`, `test_set_module_gives_every_tab_and_logs_once`, `test_only_superadmin_manages_managers`, `test_grant_and_log_are_one_transaction` (patch `AccessLog.objects.create` to raise; grant must not exist afterwards), `test_double_submit_makes_one_grant` (second call after first returns False).
- [ ] **Step 2: Run** `uv run pytest core/test_matrix.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `core/matrix.py` per Interfaces. Each mutating function runs in `transaction.atomic()`, creates the grant with `get_or_create` (log only when created) and deletes with `filter().delete()` (log only when count > 0). Snapshot `actor_name` and `subject_name` from `display_name`.
- [ ] **Step 4: Run** the file. Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "Access matrix: grant service with history"` (add both files).

### Task 3: Tabs, migration of grants, and gating the views

**Files:**
- Modify: `core/access.py` (`MODULES["recruitment"]`, drop placeholder `hr`, `finance`, `sales` only if no test needs them: check `grep -rn '"hr"\|"finance"\|"sales"' --include=test_*.py`; otherwise keep them out of the matrix with a `Module.in_matrix: bool = True` flag set False and list only `in_matrix` modules there)
- Modify: `hiring/views.py`, `hiring/source_views.py`, `hiring/screening_views.py`, `hiring/selecting_views.py`, `hiring/offer_views.py`, `people/views.py`, `core/command.py`
- Modify: `templates/people/base_people.html`, `templates/_sidebar.html`
- Create: `core/migrations/0012_access_tabs.py`
- Modify tests: every test that creates `AccessGrant(... module="recruitment", section=...)` (grep `section=`), listed: `hiring/test_sourcing.py`, `test_selecting.py`, `test_screening.py`, `test_report.py`, `test_card.py`, `test_offers.py`, `test_hiring.py`, `test_callops.py`, `people/test_people.py`, `people/test_phone_widget.py`, `core/test_command.py`, `core/test_access.py`.
- Test: `core/test_tabs.py`

**Interfaces:**
- Consumes: `require_section(module, section)` from `core/access.py`.
- Produces: `MODULES["recruitment"].sections` equals the nine tab keys in Global Constraints, with labels `Preparing, People, Sourcing, Screening, Calling, Selecting, HR assessments, Hiring, On-Boarding` (use the labels the tab bar shows, `openings` → "Preparing").
- Produces: template filter `can_tab` in `core/templatetags/access_tags.py`: `{% if user|can_tab:"calling" %}` → `has_section(user, "recruitment", tab)`; and `core/access.py: has_section(user, module, section) -> bool` (active, superuser or any grant).
- Produces: `core/access.py: first_tab_url(user) -> str | None`, the URL of the first Empanelment tab the user holds, in tab order, using the url names in `PAGES` of `core/command.py`.

View-to-tab mapping (replace the single `section = require_section(...)` with one decorator per tab used in that file):
- `hiring/views.py`: all views → `openings` (incl. report and exports).
- `hiring/source_views.py`: all → `sourcing`.
- `hiring/screening_views.py`: `calling`, `export_calling`, `call_new`, `calling_people` → `calling`; every other view → `screening`.
- `hiring/selecting_views.py`: `selecting`, `export_interviews`, `record`, `edit` → `selecting`; `assess` → `assessments` (also the `_has_hr` check).
- `hiring/offer_views.py`: `onboarding_page`, `joined`, `export_onboarding` → `onboarding`; the rest → `hiring`.
- `people/views.py`: all → `people`; the assessments check at line ~51 stays `assessments`.
- `core/command.py` `PAGES`: map Sourcing/Screening/Selecting/Hiring/On-Boarding/Candidates/New candidate to their own tabs, add Calling → `calling`; `scope(... "candidates")` for candidate search → `people`.

Data migration `0012_access_tabs` (reversible, reverse is a no-op with a comment): for each grant with `module="recruitment"`: `openings` stays; `candidates` → `people, sourcing, screening, calling, selecting, hiring, onboarding`; `interviews` → `selecting` (skip if held); `assessments` stays. Then delete the old `candidates` and `interviews` rows. Write one `AccessLog` `grant` row per created grant with actor blank, `actor_name="migrated"`, note `"migrated"`. Use `get_or_create` so rerunning is safe.

- [ ] **Step 1: Write failing tests** in `core/test_tabs.py`: `test_each_tab_url_is_403_without_its_tab_and_200_with_it` (parametrized over `(tab, url name)` pairs for every list page: `hiring:list`, `people:list`, `hiring:sourcing`, `hiring:screening`, `hiring:calling`, `hiring:selecting`, `hiring:offers`, `hiring:onboarding`), `test_calling_only_user_cannot_open_screening`, `test_sidebar_link_leads_to_a_held_tab` (user with only `calling` → `first_tab_url` is the calling URL and the Empanelment sidebar link uses it), `test_no_tab_user_has_no_empanelment_link`, `test_tab_bar_hides_tabs_not_held`, `test_migration_converts_candidates_to_seven_tabs` (use `MigrationExecutor` or call the migration function directly with `apps`), `test_migration_is_idempotent`, `test_interviews_maps_to_selecting_without_duplicate`.
- [ ] **Step 2: Run** `uv run pytest core/test_tabs.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the tab registry, helpers, per-view decorators, command bar, sidebar link (`href` = `first_tab_url`) and tab-bar `{% if user|can_tab:"..." %}` wrappers (the Report link follows `openings`).
- [ ] **Step 4: Write migration `0012_access_tabs`.**
- [ ] **Step 5: Update the existing tests** to grant the tabs their views now need (mapping above; where a test touches several tabs, loop over `list(MODULES["recruitment"].sections)`). Do not weaken any assertion.
- [ ] **Step 6: Run the full suite** `uv run pytest -q`. Expected: all PASS.
- [ ] **Step 7: Commit** `git commit -m "Access matrix: per-tab sections, grant conversion"`.

### Task 4: The matrix page

**Files:**
- Create: `core/matrix_views.py`, `templates/core/access_matrix.html`, `templates/core/_matrix_cell.html`, `templates/core/_matrix_row.html`
- Modify: `config/urls.py` (add after the `access/` routes: `access/matrix/` name `access_matrix`, `access/matrix/cell/` name `access_matrix_cell`, `access/matrix/module/` name `access_matrix_module`), `templates/base.html` (link "Access matrix" for those who `can_manage` any company), `templates/core/access_people.html` (link)
- Test: `core/test_matrix_views.py`

**Interfaces:**
- Consumes: `core.matrix` functions (Task 2), `core.access.MODULES`, `core.pagination.paginate`.
- Produces: `matrix(request)` GET: `?company=<slug>` and `?q=` search; 403 for non-managers and for a company the viewer cannot manage; default company is the first the viewer can manage; companies offered in the switch are exactly the ones they can manage (superadmin sees Senken and Avris). `cell(request)` POST: fields `user`, `company`, `module`, `tab`, `on` (`1`/`0`); returns the re-rendered row partial. `module(request)` POST: fields `user`, `company`, `module`, `on`; superadmin only; returns the row partial. Both map `PermissionDenied` → 403, `MatrixError` → 400, unknown pks → 404, and require login and POST.

- [ ] **Step 1: Write failing tests** in `core/test_matrix_views.py`: `test_non_manager_gets_403` (office admin, plain user), `test_superadmin_sees_company_switch_with_exactly_two_options`, `test_unmanaged_company_is_403_not_fallback`, `test_manager_sees_only_their_company_rows`, `test_shared_employee_grid_shows_only_selected_company_tabs` (grant S381 `calling` at Avris only; Senken grid cell off), `test_cell_post_flips_and_logs`, `test_cell_post_nonexistent_tab_is_400_and_no_row`, `test_cell_post_user_from_other_company_is_400`, `test_manager_post_to_all_button_is_403`, `test_get_on_cell_endpoint_is_405`, `test_superadmin_not_in_rows_inactive_not_in_rows`, `test_search_filters_people`.
- [ ] **Step 2: Run** `uv run pytest core/test_matrix_views.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** views and templates. Grid per the approved mockup: ink module header, one `th` per tab, yellow All cell per module (rendered only for superadmin; managers see no All button). Cells are buttons with `hx-post`, `hx-target="closest tr"`, `hx-swap="outerHTML"`, CSRF header via the existing HTMX setup (check `base.html`). The wrapper scrolls horizontally inside its card with the name column sticky. Use existing neo-brutalist classes only.
- [ ] **Step 4: Run** the file. Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "Access matrix: the grid page"`.

### Task 5: Managers, history and exports

**Files:**
- Modify: `core/matrix_views.py`, `templates/core/access_matrix.html`, `config/urls.py` (`access/matrix/managers/` name `access_matrix_managers`, `access/matrix/export/` name `access_matrix_export`, `access/matrix/history/export/` name `access_matrix_history_export`)
- Create: `core/matrix_export.py`, `templates/core/_matrix_history.html`, `templates/core/_matrix_managers.html`
- Test: `core/test_matrix_extras.py`

**Interfaces:**
- Consumes: `core.export.workbook_response`, `stamp`, `core.matrix.add_manager/remove_manager`, `AccessLog`.
- Produces: `managers(request)` POST (superadmin only): `user`, `company`, `action` in `add|remove`. `matrix_workbook(company, rows) -> HttpResponse` (sheet: person, then one column per tab with Yes/blank) and `history_workbook(company, logs) -> HttpResponse` (when, who, whom, tab/module, action, note). History is paginated (`paginate(request, logs, per=25)`), newest first; superadmin sees the selected company's rows, a manager sees only their company's rows.

- [ ] **Step 1: Write failing tests**: `test_manager_strip_visible_only_to_superadmin`, `test_add_manager_logs_and_gives_page_access`, `test_remove_manager_removes_page_access_immediately`, `test_manager_cannot_add_manager`, `test_history_lists_newest_first_and_pages`, `test_manager_history_only_own_company`, `test_history_lines_survive_deleted_users`, `test_export_matches_grid` (load workbook, compare a row), `test_exports_403_for_non_managers`, `test_export_cells_escape_formulas` (person named `=cmd`).
- [ ] **Step 2: Run** `uv run pytest core/test_matrix_extras.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** views, partials and workbooks; add Export buttons next to the page heading.
- [ ] **Step 4: Run** the file. Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "Access matrix: managers, history, exports"`.

### Task 6: Retire the old grant editor and log membership removals

**Files:**
- Modify: `core/access_views.py` (`person`, `_save_grants`, `_save_memberships`, `can_grant` use), `core/access.py` (remove `can_grant` and `superadmin_only` if now unused), `templates/core/access_person.html`, `core/access_export.py` (labels still resolve), `core/test_access.py`, `core/test_office_admin.py`
- Test: `core/test_membership_removal.py`

**Interfaces:**
- Consumes: `core.matrix.drop_company_grants(actor, subject, company)`.
- Produces: the person page keeps only company membership editing; the grants block is replaced by a link to the matrix for those who `can_manage`. `_save_memberships` calls `drop_company_grants` for every company removed, inside the existing `transaction.atomic()`; it no longer filters by `can_grant`, because removing someone from a company removes all their grants there.

- [ ] **Step 1: Write failing tests**: `test_removing_member_deletes_their_grants_in_that_company_only`, `test_removal_writes_membership_removed_rows_with_office_admin_as_actor`, `test_office_admin_post_with_grant_field_changes_nothing`, `test_removing_member_also_removes_manager_row` (log `manager_remove`), `test_person_page_has_no_grant_checkboxes`.
- [ ] **Step 2: Run** the file. Expected: FAIL.
- [ ] **Step 3: Implement.** Also delete a removed member's `AccessManager` row for that company via `remove_manager`-style logging (add this to `drop_company_grants`, or call a sibling helper from `core/matrix.py`; the tests above decide).
- [ ] **Step 4: Fix up** `core/test_access.py` and `core/test_office_admin.py` assertions that depended on office admins granting sections; assert the new refusal instead.
- [ ] **Step 5: Run the full suite** `uv run pytest -q`. Expected: PASS.
- [ ] **Step 6: Commit** `git commit -m "Access matrix: retire grant editor, log membership removals"`.

### Task 7: Visual check and wrap-up

**Files:** none new; fixes as needed.

- [ ] **Step 1:** Build CSS `./bin/tailwindcss -i static/css/input.css -o static/css/app.css`.
- [ ] **Step 2:** Ask the user to start runserver (never start it). With it up, screenshot the matrix at 1280x800 and 390x844 using `uv run --with playwright python`, as a superadmin and as a manager. Fix horizontal overflow, sticky column, and contrast issues.
- [ ] **Step 3:** `uv run pytest -q` and `uv run ruff check . && uv run ruff format --check .`. Expected: clean.
- [ ] **Step 4:** Report to the user: deploy needs migrations `core 0011`, `0012`. Confirm before any push or PR.
