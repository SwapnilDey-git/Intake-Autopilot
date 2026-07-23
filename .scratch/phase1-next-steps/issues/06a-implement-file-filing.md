Type: task
Status: resolved
Blocked by: 06

## Question

Implement the file-filing design from ticket 06: on approval, copy the original uploaded document from flat `/storage/<filename>` into `storage/Clients/{Surname}_{Firstname}_{TaxYear}/original_intake.<ext>`, with the extension sniffed from magic bytes rather than trusted from the source filename, and a new `audit_log` row (`event_type='file'`) recording it.

Concretely, in `backend/main.py`'s `submit_review` (`POST /api/forms/{form_id}/review`, approval branch ~line 261-305):
1. Add a `STORAGE_DIR = Path(os.environ.get("STORAGE_DIR", "/storage"))` constant (mirrors `ai-service`'s existing convention; `backend` only has `CLIENTS_DIR` today).
2. Fetch `forms.filename` for `form_id` (not currently selected anywhere in this handler).
3. Sniff the source file's magic bytes to determine extension (`%PDF` → `.pdf`, `\x89PNG` → `.png`, `\xFF\xD8\xFF` → `.jpg`; fall back sensibly if none match).
4. Copy (not move) `STORAGE_DIR / filename` → `client_dir / f"original_intake{ext}"`, alongside the existing Excel copy/write logic.
5. Insert an `audit_log` row: `event_type='file'`, `actor=review.reviewer_name`, `details` JSON with the destination path — same shape as the existing `'write'` event a few lines above.
6. Update the `event_type` comment in `database/schema.sql` (line 34-35) to list `file` alongside the existing known values (no schema/CHECK-constraint change needed, `event_type` is a plain VARCHAR(50)).

Verify by re-running (or extending) ticket 01's end-to-end test: approve a form, confirm `original_intake.<ext>` lands in the client folder next to `EA_{TaxYear}.xlsx`, and confirm the `audit_log` row.

## Answer

**Implemented and verified.** Changes:

- `backend/main.py`: added `STORAGE_DIR` constant (mirrors `ai-service`'s convention) and `sniff_extension()` (checks `%PDF`/`\x89PNG`/`\xFF\xD8\xFF` magic bytes, falls back to `.bin`). In `submit_review`'s approval branch, right after the existing Excel-write `audit_log` insert: fetches `forms.filename`, and if the source file exists at `STORAGE_DIR/filename`, copies it to `client_dir/original_intake<ext>` and inserts an `audit_log` row (`event_type='file'`, details include the destination path). Best-effort by design — a missing source file logs a warning but doesn't fail the approval, since the Excel write (the critical path) has already succeeded by that point.
- `database/schema.sql`: updated the `audit_log` table's documenting comment to list `file` alongside the other known `event_type` values (no schema/CHECK-constraint change needed).

**Verified live**: restarted `backend`, approved form 32 via a direct `POST /api/forms/32/review` call. Result: `storage/Clients/Person_FilingTest_2026/original_intake.pdf` created (316001 bytes, matching the source PDF exactly, correct extension sniffed), plus an `audit_log` row (`event_type='file'`, `details: {"original_path": ".../original_intake.pdf"}`) alongside the existing `approval` and `write` rows. Left the test approval and client folder in place as evidence, same precedent as ticket 01's verification approvals.
