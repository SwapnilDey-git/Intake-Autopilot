Type: grilling
Status: resolved
Blocked by: 01

## Question

`create_client_folder` already creates `storage/Clients/{Surname}_{Firstname}_{TaxYear}/` on first approval, but the original uploaded form (PDF/image) is never filed into it — only the generated Excel file lands there. Design: where does the original upload currently live on disk post-ingestion (n8n webhook temp storage vs. dashboard manual-upload path vs. Gmail attachment path — three different intake routes per `CLAUDE.md`), what naming convention avoids collisions/overwrites on a second approval for the same client+year, and does this get wired into the existing approval flow in `backend/main.py` or need a separate step?

## Answer

**Design settled, confirmed with user. Implementation is a separate ticket (06a — see below), since this map plans rather than executes.**

**Where originals currently live** (investigated in `ai-service/main.py`): every intake path — dashboard manual upload, n8n webhook, n8n Gmail — already converges on the same save, in `ai-service`'s `/extract` handler: `file_path = os.path.join(STORAGE_DIR, filename)` where `STORAGE_DIR = "/storage"` (the same bind mount `backend` also has as `./storage:/storage`). So nothing new needs to be built to get the original file onto disk — it's already there, flat, keyed by whatever `filename` ended up in the `forms` table. Two real gaps found along the way, both relevant to the design:
- **Filename collisions**: multiple forms sharing the same original filename (e.g. repeated test uploads of the same PDF) silently overwrite each other's copy in `/storage` — the extraction JSON in Postgres is unaffected (it already ran before the overwrite), but the raw source file for the earlier form is gone.
- **No extension on the n8n-webhook path**: `ai-service`'s raw-binary-body branch (used when n8n's HTTP Request node sends without a filename) defaults to hardcoded `"raw_upload.pdf"` only in the truly-bodyless case; in practice n8n's webhook capture assigns its own generated name with no reliable extension (observed: form 75's filename was a bare UUID, no extension at all).

**Design**:
1. **Destination naming**: fixed name + sniffed extension, mirroring the existing `EA_{TaxYear}.xlsx` pattern — e.g. `original_intake.pdf`. Extension determined by sniffing magic bytes (`%PDF` / `\x89PNG` / `\xFF\xD8\xFF`) rather than trusted from the arriving filename, since that's demonstrably unreliable across the three intake paths.
2. **Copy, not move**: leave the source file in flat `/storage/` untouched, copy it into the client folder. Favors not losing tax data over saving a few hundred KB-MB of duplicate storage per form.
3. **Audit log**: new `event_type = 'file'` row on `audit_log`, same shape as the existing `'write'` event (form_id, actor = reviewer_name, details JSON with the destination path). `database/schema.sql`'s audit_log comment (line 34-35) lists known event_type values and needs `file` added to that list — no CHECK constraint exists, so this is documentation-only, not a migration.
4. **Wired into the same handler**: `backend/main.py`'s `submit_review` (the `POST /api/forms/{form_id}/review` handler, approval branch starting ~line 261) already does `client_dir.mkdir(...)` and the Excel copy/write synchronously in the same request — filing the original belongs right alongside that, not a separate async step. Concretely needs: (a) a `SELECT filename FROM forms WHERE id = :form_id` query, since the handler doesn't currently fetch that column at all; (b) a `STORAGE_DIR = Path(os.environ.get("STORAGE_DIR", "/storage"))` constant mirroring `ai-service`'s convention (backend doesn't have one yet, only `CLIENTS_DIR`); (c) the sniff-extension + copy + audit_log-insert logic, right after the existing Excel write block (~line 305).

**Not addressed by this design, left as-is**: the collision bug in flat `/storage/` itself (two forms with the same original filename still clobber each other there) is out of scope — the client-folder filing step reads whatever's currently at that path at approval time, which is correct for the common case (idempotency already blocks a second *approval* for the same client+year, so there's normally at most one original per client folder) but wouldn't help if the flat-storage copy was already overwritten by an unrelated form before approval happened. Worth a separate ticket if it turns out to matter in practice; not chasing it now since idempotency mostly covers the scenario that would trigger it.

## Answer (implementation ticket)

Spun off as a `task` ticket rather than implementing inline, since resolving a `grilling` ticket is design work, not code — see the new ticket this creates (06a-implement-file-filing.md).
