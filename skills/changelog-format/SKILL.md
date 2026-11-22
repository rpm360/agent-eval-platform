---
name: changelog-format
description: Internal house convention for CHANGELOG.md release entries.
---

# Changelog Format Skill

When asked to write a changelog entry using the house convention, use EXACTLY this layout:

```text
## Release <version> (<DD.MM.YYYY>)
#### Added
- [<TICKET>] <description> (@<author>)
#### Fixed
- [<TICKET>] <description> (@<author>)
```

Rules:
- The date uses day.month.year with dots, e.g. 2026-01-15 -> `15.01.2026`.
- `#### Added` always comes before `#### Fixed`. Omit a section if it has no items.
- Descriptions are copied verbatim; authors are prefixed with `@`.
