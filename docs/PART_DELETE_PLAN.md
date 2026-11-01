# Part and component delete

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Let a project drop a saved part or design, and drop a component file inside a design, including an empty `components/*.py` that nothing else can remove today.

**Architecture:** One server module owns both operations. Document delete stays the existing soft trash and gains the permanent purge the Trash screen already calls. Component-file delete is a new saved revision of that design, not a second trash. The desktop UI and `cad_delete` share the file-removal and trash/restore functions. Purge and empty-trash are human actions only.

**Tech Stack:** Local catalog in `src/steve_desktop` (FastAPI), design UI in `cad-web`, MCP tools in `cad_tools`.

## Global Constraints

- Implement only what this plan names. Do not take the branch from `macos-step1`. Do not commit or push `main`. Do not force-push.
- Do not put an upstream product name or logo in new UI copy. Say "part", "design", and "component".
- Document trash is soft. Component files are removed from the design's `files` map. Do not invent a file trash.
- A delete must not require a successful geometry build.
- Git sync never pushes by itself and never force-pushes.

---

## Where each piece lives

Saved CAD lives in the profile directory `data_directory()/` (`src/steve_desktop/vault.py`), in the `cad/` folder opened by `LocalCadWeb` (`src/steve_desktop/app.py`). The catalog is `cad/catalog.json` (`LocalCadServer` in `src/steve_desktop/cad_server.py`).

| What | Where |
| --- | --- |
| Document record | `catalog.json` → `documents[<uuid>]`. Fields that matter: `id`, `name`, `kind` (`part`, `design`, or `blender`), integer `revision` (starts at 1), `code` (the text of `main.py`), `files` (relative path → text), `links`, `updated_at`, `preview_build_id`, `message`, `folder_id`. |
| Component file | A key of `files`, conventionally `components/<id>.py`. The id is the module stem. There is no separate component row in the catalog. |
| Design / assembly | A document with `kind: "design"`. There is no assembly kind. A legacy assembly is `cq.Assembly` written in `code`. |
| Part | A document with `kind: "part"`. One file: `code`. `files` is empty. |
| Cross-document link | `links[<alias>] = {document_id, revision, component?}`. `component` pins one file, `components/<component>.py`, of that design. |
| Revision history | `catalog.json` → `history[<uuid>]`, a list of full previous document snapshots. `update_document` appends the old record and increments `revision` (`cad_server.py`). |
| Soft trash | `deleted_at` and `deleted_by` on the live record. `GET /v1/documents` hides those records. Implemented in `src/steve_desktop/cad_documents.py` (`POST /v1/trash`, `GET /v1/trash`, `POST /v1/trash/restore`). |
| Per-document folder | `cad/documents/<uuid>/project.steve` plus `revisions/`, created empty by `CadProject.create` (`cad_service.py`). The live source of truth is the catalog, not these folders. |
| Build copies | `catalog.json` → `builds`, and `cad/builds/<build-id>/`. |
| Offline cursor history | `CadProject` hex revision ids, `parent`, and `cursor`, with `undo` / `redo`. Used only when no live server is registered. The desktop and MCP use `LiveProject` (`cad_live.py`), whose undo is "build this old snapshot as a new revision". |
| Git mirror | `local_git.py`. On push, each document becomes `<repo>/<document-id>/main.py`, `steve.json`, and every `files` entry. `steve.json` stores `{steve, id, kind, name, links}`. Links point at the other document's folder id. |
| UI draft | `localStorage` via `saveDraft` (`cad-web/src/state/actions.ts`). Not the catalog. |
| In-session undo | `cad-web/src/localHistory.ts`, up to 50 source snapshots, Ctrl+Z outside the editor. |

Create, rename, and edit today:

- Create a part or design: `POST /v1/documents` (`create_document`). Create a component: UI only, `addComponent` → `withComponent` in `cad-web/src/state/design.ts` (writes `components/<id>.py`, an import, and `design.add`).
- Rename a part or design: `renameDocument` in `cad-web/src/lib/library.ts` does `PUT /v1/documents/{id}` and bumps the revision. `POST /v1/files/{id}/rename` is not implemented on this server.
- Edit source: the editor, then `PUT` on save, or MCP `cad_build` (`cad_service.py`), which replaces the open document when the build succeeds.
- MCP tools (`cad_tools`): `cad_read`, `cad_inspect`, `cad_build`, `cad_set_parameters`, `cad_export`, `cad_revisions`, `cad_restore`, `cad_api_reference`, `cad_source_package`, `cad_import_package`, `cad_find_parts`, `cad_import_catalog_part`, `blender_render`, and `cad_delete` (`trash`, `restore`, `remove_file` only).

What already deletes, and why empty component files stay:

- Parts and designs move to the Trash from File → Open (`cad-web/src/state/trash.ts` → `POST /v1/trash`). Undo is a 9s toast (`UNDO_MS`) plus Trash → Restore. Permanent delete is `POST /v1/trash/purge` and `POST /v1/trash/empty` (`cad-web/src/lib/trash.ts`), used only by the Trash screen. A live link skips the document. There is no force-purge.
- A component row has "Delete component" (`ItemMenu.tsx`, `removeComponent` in `actions.ts`). It only rewrites the in-memory draft. It does not `PUT` a new revision. The file switcher (`FileSwitcher.tsx`) can add a component and cannot delete one.
- `withoutComponent` (`design.ts`) strips a single-line `from components.<id> import …` and a single-line `.add(name)`. Any other hit of that word, including `design.pattern`, a joint, or the same name in another component file, disables the command. Two empty hardware files that import each other can never be deleted, because each is the other's "user". A batch delete does not exist.
- `removeComponent` then calls `updateModel`. That returns without building when `hasContent` is false (`store.ts`), and a finished preview only calls `saveDraft`, not `saveDocument`. Git export reads the catalog, so a draft-only delete is still pushed.

## How references are found

Document → document. `references()` in `cad_documents.py` scans every live `documents` value and keeps those whose `links` contain this `document_id`. It does not read `history`, and it does not care about `component`. `GET /v1/documents/{id}` adds `link_status`: `latest`, `name`, `kind`, and `trashed` when `deleted_at` is set (`cad_server.py`). `resolve_links` loads the pinned `(document_id, revision)` from the live record or from `history`, including a trashed target. A missing id yields `latest: null` (`tests/test_cad_links.py`).

File → file, inside one design. The build order walker is `closure` (`vendor/steve/cachekeys.py`): `from components.<id> import …` maps to `components/<id>.py`. `component_plan` (`cad_dependencies.py`) uses that closure. The UI walker is the word scan in `withoutComponent`, which is stricter than real use and is the reason empty files get stuck.

File → other document. Another document's link with this design's id and `component` equal to this file's stem. Nothing in the UI checks that before offering Delete component.

The new finder parses Python with `ast`. It does not search for the component's name as a word, so a comment or a string cannot pin a file in place. A placement, which is removed with the file and does not block, is this file's own import and a top-level `design.add`, `design.pattern`, or `result.add` of that import, including a call split across lines. Anything else that loads the imported name (a joint, a mate, another component file) is a reference. A reference that exists only inside another path in the same delete call does not count.

## Design choices

**Soft trash vs hard delete.** Recommendation: keep both, for different objects. A part or design goes to the Trash (already implemented) and can be restored. Add purge and empty-trash so a trashed part can actually leave the project. A component file, empty or not, is hard-removed from `files` in one new revision. It does not enter the Trash. The previous snapshot in `history` is the recovery copy.

**Revision history.** Recommendation: keep it. Trash does not bump `revision` and does not touch `history` (current behavior; keep it). Purge deletes `documents[id]`, `history[id]`, and the `cad/documents/<id>/` folder. It does not scan `builds`. A file delete goes through `update_document`: the pre-delete document is appended to `history`, `revision` increments, `message` is `Removed components/<id>.py` (truncate to 200 characters when several paths are named).

**Undo of a delete.** Recommendation: do not add a third undo stack. Trash undo stays the toast and `POST /v1/trash/restore`. A file delete is saved immediately; the toast Undo calls the existing `POST /v1/documents/{id}/history/restore` for the pre-delete revision, which writes that source again as a newer revision, and the open editor adopts that restored document. Ctrl+Z (`localHistory.ts`) still rewinds the open editor before the next unrelated edit. Purge has no undo; the Trash view already asks first.

**Referenced: refuse, warn, or force.** Recommendation: warn, then refuse, with an explicit force.

- Trash of a document: warn when `references()` is non-empty (the Open dialog already does this) and still trash. Pinned revisions keep building. Do not change this.
- Purge: human only (`POST /v1/trash/purge` and `POST /v1/trash/empty`, which the Trash screen already calls). Refuse when any non-trashed document links this id. Return that list in `skipped`, which `TrashView` already renders. There is no force-purge. A `force` field on those routes is ignored. Do not edit the linking design.
- One component file: refuse when a reference remains after its import and placements are ignored. The response lists file and line. The menu and the file switcher show that list and "Delete anyway" (`force` on the HTTP route only). Force still strips the import and the placements, deletes the file, and returns the leftover lines as `warnings`. It does not rewrite joints and does not edit other documents. A file that is only placed with `design.add` or `design.pattern` is not a refusal; those calls are placements and are removed with the file. `cad_delete` has no force parameter.
- Several component files in one call: a reference that lives only in another path in the same call does not count. That is what removes a set of empty hardware files that only mention each other.

**Empty files.** Recommendation: same operation as any other `components/*.py`. Empty means the text is blank, or it is only comments, imports, and a `Component(...)` assignment with no feature calls. If the only mentions are its import and placements, delete with no dialog. Do not call the geometry builder. `hasContent` must not be on this path.

**Git sync on.** Recommendation: local delete does not push. The next manual push is a normal non-force push.

- `export_sources` skips documents with `deleted_at` and skips ids that were purged (they are already gone). Paths previously listed in `owned_files` and no longer written are unlinked, which is existing behavior, so a removed `components/*.py` disappears on the next push. Remove the document directory when it is empty afterward.
- Pull and import stay copy-only. They do not delete local documents missing from the remote, and they do not recreate a purged id.
- Sync off: delete is only the local catalog.

Out of scope: `params.py`, `main.py`, tables, logos, helper modules, feature-level Delete (that already rewrites code), folder delete (already implemented in `cad_folders.py`).

## Planned changes

### Task 1: Shared delete operations

**Files:**

- Create: `src/steve_desktop/cad_delete.py`
- Modify: `src/steve_desktop/cad_documents.py`
- Test: `tests/test_cad_delete.py`

**Produces:**

- `delete_files(server, document_id, paths, revision, force=False, code=None, files=None) -> dict` (`force` is the human Delete-anyway path)
- `purge_documents(server, ids) -> dict` (no force argument)
- `empty_trash(server) -> dict`

`delete_files` accepts only existing keys under `components/` ending in `.py` that pass the path checks in `cad_document.validate`. Base source is the saved document, or `code`/`files` when the client sends its unsaved editor state. `revision` must equal the saved integer revision or the result is HTTP 409 and no write. If this document is the open one, the live context fingerprint differs from the saved source, and the body did not send `code`/`files`, return 409 and do not write.

Success returns `{document, removed, warnings, references}` and has called `update_document`. Refusal returns HTTP 422 `{detail: {message, references}}` and does not write. A reference item is `{document_id, name, path, line, detail}`.

Wire:

- `POST /v1/documents/{id}/files/delete` with `{paths, revision, force, code?, files?}`
- `POST /v1/trash/purge` with `{ids}` → `{purged: [{id, name}], skipped: [{id, name, reason, references?}]}`. A live link skips the document.
- `POST /v1/trash/empty` with the same response. These two routes are what the Trash screen calls. They are not MCP tools.

- [x] **Step 1:** Add `tests/test_cad_delete.py` covering the cases in the test plan below. Run `PYTHONPATH=src python -m unittest tests.test_cad_delete -v` and confirm failure.
- [x] **Step 2:** Implement `cad_delete.py` and the three routes. Re-run that module and confirm pass.
- [x] **Step 3:** Commit the server change.

### Task 2: Git export follows trash and purged files

**Files:**

- Modify: `src/steve_desktop/local_git.py` (`export_sources`)
- Test: `tests/test_cad_delete.py` (no network; call `export_sources` with a temp repo and `subprocess` patched, as `tests/test_launch_services.py` does)

- [x] **Step 1:** Assert a trashed document is omitted and a removed component path is unlinked from `owned_files`.
- [x] **Step 2:** Implement the skip and the empty-directory removal. Confirm the test passes.
- [x] **Step 3:** Commit.

### Task 3: MCP tool `cad_delete`

**Files:**

- Modify: `src/steve_desktop/cad_service.py` (`cad_tools`)
- Modify: `src/steve_desktop/runtime.py` (one sentence: `cad_delete` trashes, restores, or removes a component file; it cannot purge; do not claim a file is gone unless the tool result says so)
- Test: `tests/test_cad_delete.py` calls the tool function. Extend `tests/test_local_mcp.py` only if the tool list assertion needs the new name.

**Signature:**

```python
def cad_delete(
    mode: Literal['trash', 'restore', 'remove_file'],
    document_id: str | None = None,
    path: str | None = None,
    paths: list[str] | None = None,
    expected_revision: int | None = None,
) -> dict:
```

`mode` is only `trash`, `restore`, or `remove_file`. The schema has no `purge`, `empty`, `empty_trash`, or `force` parameter. `remove_file` always refuses while a real use remains; files named in the same request do not count as uses of each other. `document_id` defaults to the open document. `remove_file` requires `expected_revision` (the integer catalog revision). Errors are returned as data. A `mode` of `purge` or `empty_trash` is rejected by the schema and, if called anyway, returns `ok: false` without writing.

**Return:**

```python
{
  "ok": bool,
  "action": "trashed" | "restored" | "file_removed" | "refused",
  "document_id": str | None,
  "revision": int | None,       # new revision after a file delete; unchanged for trash
  "removed": list[str],         # document ids or component paths
  "references": list[dict],     # {document_id, name, path, line, detail}
  "warnings": list[str],
  "error": str | None,
}
```

Refusal is `ok: false`, `action: "refused"`, `references` filled, catalog unchanged.

- [x] **Step 1:** Test that `remove_file` refuses a joint, that `trash` and `restore` round-trip, and that a purge or empty-trash call is rejected with none of those parameters in the schema.
- [x] **Step 2:** Register `cad_delete` on the toolset. Re-run `tests.test_cad_delete` and `tests.test_local_mcp`.
- [x] **Step 3:** Commit.

### Task 4: UI

**Files:**

- Modify: `cad-web/src/state/actions.ts` (`removeComponent` posts the delete, then adopts the saved document the way `saveDocument` does)
- Modify: `cad-web/src/workspaces/design/ItemMenu.tsx` (when the server returns references, confirm with "Delete anyway")
- Modify: `cad-web/src/panels/source/FileSwitcher.tsx` (a delete control on each Components row, including a file that is not placed)
- Modify: `cad-web/src/lib/api.ts` (client for `POST /v1/documents/{id}/files/delete`)

Empty and unreferenced: no dialog, toast with Undo. Referenced: dialog listing the references, then force. The file switcher and the tree menu call the same action. Do not delete from the switcher unless the path is under `components/` and ends in `.py`.

No new Trash screen. Purge and empty-trash start working because Task 1 adds the routes `TrashView` already calls.

- [x] **Step 1:** Point `removeComponent` at the route and add the switcher control.
- [x] **Step 2:** There is no frontend unit runner in this repo. Verify by API tests plus a manual pass: delete an empty `components/*.py` from the tree and from the file switcher, undo from the toast, and permanently empty a trashed part.
- [x] **Step 3:** Commit.

## Test plan

Run `PYTHONPATH=src python -m unittest tests.test_cad_delete tests.test_cad_links tests.test_cad_history tests.test_cad_local tests.test_local_mcp -v`.

`tests/test_cad_delete.py` must cover:

1. Trash still hides a part from `GET /v1/documents`, and restore brings it back (do not regress `tests/test_cad_local.py`).
2. `POST /v1/trash/purge` removes the record and `history`. A second purge skips it. `POST /v1/trash/empty` purges only trashed ids.
3. Purge of a linked part is skipped even when the body contains `force`. The part stays in the Trash and `link_status.trashed` stays true.
4. Delete `components/screw.py` whose text is only `screw = Component("screw", name="Screw")`, with a one-line import and `design.add(screw)` in `main.py`. The key is gone, those lines are gone, `revision` is +1, and `history` still contains the file.
5. The same for a zero-length `components/washer.py`.
6. `components/nut.py` and `components/screw.py` import each other and have no other geometry. One call with both paths removes both. Deleting only one returns 422 and changes nothing.
7. `design.pattern(screw, count=4, axis="Z")` on its own does not refuse: the file and the pattern call are both gone. Add a joint line that names `screw`: without `force`, 422 and that line number is in `references`; with `force`, the file and the pattern call are gone and the joint line is in `warnings`.
8. Wrong `revision` returns 409 and the file is still there.
9. Open document with a different unsaved context, and no `code`/`files` in the body, returns 409.
10. `cad_delete(mode="remove_file")` refuses a joint and does not delete. `mode="trash"` sets `deleted_at` without bumping the revision; `mode="restore"` clears it. `mode="purge"` and `mode="empty_trash"` are rejected. The tool schema has no `force`, `purge`, `empty`, or `empty_trash` parameter.
11. Git export omits a trashed document and unlinks a removed component path. No `git push` is invoked.

## Phase 2 decision

Delete-forever is human-only. `cad_delete` exposes `trash`, `restore`, and `remove_file`. It does not purge, empty the Trash, or force a file removal. "Delete anyway" is the app UI, via `force` on `POST /v1/documents/{id}/files/delete`.

## Open questions

- The six empty hardware files are not in this repository. The tests cover mutual imports, a `design.pattern` placement, and a joint that the UI can override and MCP cannot.
- Purge does not scrub source copies stored inside `builds`.
- Local history is main-only (`cad_documents.py` rejects any other branch). Trash is per document id.
