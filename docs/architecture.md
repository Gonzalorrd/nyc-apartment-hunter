# Architecture

Pydantic input models define fields and validation. SQLAlchemy Core derives entity
columns from their JSON schemas, with explicit relational keys, money types,
uniqueness and metadata columns in `db.py`. There is no dynamic SQL built from user
input. SQLite foreign keys are enabled on every connection.

CLI/dashboard -> service validation -> SQLite -> scoring/export/dashboard.
Provider adapters return data through the same transactional import service.
The common adapter interface returns a status, message and changed-record count.
Website adapters currently return `manual_required` without making requests.

The nine research entities are relational. Audit snapshots and ranking components
use JSON because they are immutable explanations rather than join targets.
Each unit belongs to one building. Commutes/risks/contacts belong to buildings;
interactions belong to contacts; tours/evaluations belong to units. Tasks belong to
buildings. Ranking and price histories retain unit IDs.

Writes validate full records; CSV edits merge supplied columns with existing values
before validating. Changes use optimistic revision checks and preserve before/after
audit records. CSV batches use savepoints, so one bad row rolls back the whole batch.
No hard-delete UI is provided: use unavailable, archived or completed statuses.

The UI owns display/session state only. A future frontend can call the same service
functions. PostgreSQL will require testing identity/schema-version handling and
types, but core acquisition/scoring will not need replacement.
