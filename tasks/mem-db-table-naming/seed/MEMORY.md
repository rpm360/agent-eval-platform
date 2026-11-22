# Database Conventions

- Table names MUST follow `tbl_<domain>__<entity_plural>` (note the DOUBLE underscore),
  e.g. `tbl_billing__invoices`.
- Every table MUST include an audit column `created_at TIMESTAMP NOT NULL`.
