# Operating guide

## Add and edit

Use Add / edit, choose an entity and Create new. Fields with * are required.
Reference IDs shows buildings, units and contacts for relationships. Save validates
the record and reports errors without partial changes. To edit, select an existing
ID; optimistic revision checks prevent overwriting a newer edit.

Record sources and dates carefully. `source_checked` means you inspected evidence,
not that every building claim is independently confirmed. `manually_verified` is
for your stronger verification. Lower-confidence/staler updates are refused.
Use source notes for private call evidence or a detailed list of supported facts.

For an unavailable unit change status instead of deleting it. Contacts can be
archived; tasks marked done; tours cancelled. Reopen the page after saving to reload
the latest revision before editing the same record again.

## CSV examples

First get the real building ID from Buildings or `apartment-hunter list buildings`.
This example contains fabricated values and must not be imported as a real offer:

```csv
building_id,unit_number,base_rent,mandatory_fees,bedrooms,status
1,EXAMPLE-ONLY,3500,100,1,unknown
```

Prefer the separate demo database to experiment. Download the entity CSV to edit
existing records: it includes ID and revision plus validated fields. Omit columns
you do not want to change. Blank nullable cells clear fields to unknown. Do not
leave defaulted non-null fields blank: choose a valid status or omit the column.
Use ISO dates, `true`/`false` booleans, plain USD numbers and exact status enums.

An unchanged re-import does nothing. A changed natural-key match requires ID and
revision rather than silently replacing a manually entered record. One invalid row
rejects the entire batch with its row number. Do not upload application documents
or PDFs to the CSV uploader. Excel exports are snapshots and have no import path.

## Research and contact flow

Keep one contact record per leasing relationship; log each call/email/visit as an
interaction with a timezone-aware ISO timestamp. Suggested follow-up: a few business
days after an inquiry, adjusted to the leasing office's response. Enter the date
explicitly. Download/edit the inquiry draft, review it and send it yourself only
when ready. The app has no Gmail permissions, send button or scheduling integration.

Tour records track your arrangements; they do not book a tour. Evaluations store
likes, dislikes, scores and deal breakers separately for `me` and `girlfriend`.

## Export and backups

Export on demand. Each workbook is rebuilt, so repeated exports do not append
duplicates or mutate research. Long notes remain available in the database and
may require expanding rows/columns in Excel. Dates/numbers remain typed; URLs are
hyperlinks; headers freeze and filters/conditional formats are included.

Close the app before copying SQLite for backup. Never commit a database or a
private export. The app only binds to localhost; do not expose it publicly without
adding authentication and reconsidering personal-data handling.

## Sharing the search

The public share page (see README, "Share the results") is a read-only view. It shows
buildings, units, costs, commutes and freshness, but never evaluations, contacts,
tours, tasks or notes. Record your partner's likes, dislikes and deal breakers in the
app yourself. A deal breaker removes the unit from the next `publish`.

## Working with Codex

Open this project folder, not the parent document folder. Example requests:

- “Research these three StreetEasy links. Keep fees and December availability
  unknown unless supported; enter reviewed results through the service or CSV.”
- “Check the research queue and propose five highest-value verification steps.”
- “Draft inquiries for these buildings; do not send anything.”
- “Compare these unit IDs and explain missing evidence and both occupants' views.”

An agent must read AGENTS.md and the relevant workflow. Never give an agent blanket
permission to attach identity/financial documents to leasing inquiries.
