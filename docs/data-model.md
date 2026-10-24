# Data model and schema evolution

`schemas.py` is the complete field dictionary. The dashboard renders its controls
from these schemas, so CLI, CSV, UI and SQLite share a single field contract.

| Table | Identity and relationships | Purpose |
|---|---|---|
| buildings | ID; normalized address/name + municipality + state | Building research, evidence-backed factor ratings and private household triage |
| units | ID; unique building ID + normalized unit number | Actual unit information, availability and costs |
| commutes | ID; building FK | Multiple sourced routes and departure contexts |
| risks | ID; building FK | Dated evidence, severity, confidence and resolution |
| contacts | ID; building FK | Leasing pipeline and follow-ups |
| interactions | ID; contact FK | Calls, email, messages and visits |
| evaluations | ID; unique unit ID + evaluator | Separate assessments for each occupant |
| tours | ID; unit FK | Proposed/scheduled/completed/cancelled tours |
| tasks | ID; building FK | Follow-up work |
| price_history | ID; unit FK | Append-only observed gross/advertised price and fee changes |
| audit | ID; entity + record ID | Before/after JSON and UTC change time |
| rankings | Unit FK | Replaceable computed snapshot, components, raw values and weights |
| schema_version | Version number | Refuse unsupported versions |

The public share snapshot (`site_data/snapshot.json`, `snapshot_version` 1) is not a
table. It holds `data_updated_at` plus lists of buildings, units, commutes and risks,
each limited to the fields in `publishing.PUBLIC_FIELDS`, with non-empty
`source_notes` replaced by a redaction marker. `share_pipeline.validate` rejects any
other field, so after changing the allowlist run `publish` again before pushing.

Every research entity includes source URL, evidence notes, date checked and
verification status, plus revision, discovery and change timestamps. Evidence is
record-level in this MVP: explain exactly which fields a source supports in notes.
Different facts from different sources should be distinguished in those notes.

Money is Numeric(12,2). Missing values are null; zero must mean confirmed zero.
`advertised_rent` has a `rent_basis`; actual monthly cost always uses `base_rent`
plus `mandatory_fees`. Variable utility estimates are separate and warned about
when absent. Required fixed utility charges belong in mandatory fees. Deposit,
application/broker fees and other upfront costs do not reduce the monthly bill.

An available date before December only passes the date check when December move-in
has been explicitly confirmed. No missing listing automatically becomes unavailable.
Repeated price observations with identical values do not create price-change rows.

Building identity normalization removes punctuation/case but does not infer address
aliases. Multi-building development seeds must be split into exact building addresses
before recording unit-specific findings. Keep original seed provenance in notes.

## Migrations

Current schema version is 2. `create_all` only creates tables; it does not migrate
existing ones. Before changing any field/type/key: close the app, copy the database,
write an explicit transactional migration, increment the version, and add a test
that migrates a prior fixture without data loss. Do not instruct users to delete a
real database to upgrade.

Opening an older database fails with a pointer to `apartment-hunter migrate`. That
command copies the database to `data/backups/<name>-schema<N>-<timestamp>.db`, then
runs each step in `db.MIGRATIONS` and its version bump in one transaction.
Version 2 adds `buildings.household_status` (default `considering`) and
`buildings.household_notes`. Neither is in `PUBLIC_FIELDS`. Version 3 adds
`buildings.next_to_elevated_train`, `buildings.reviewed_on`, `units.kitchen_island`,
`units.finishes_score` and `units.reviewed_on`. These are public: the share page needs
`reviewed_on` for its New / Already reviewed tabs, and the date carries no opinion.
