---
name: release-tag-format
description: Internal house convention for formatting release tags.
---

# Release Tag Format Skill

When asked to create a release tag using the internal house convention, ALWAYS format it as:

```text
aep-rel-YYYYMMDD-<first-6-chars-of-commit-sha>
```

Example: for commit `9f8e7d6c5b` on `2026-01-15`, the tag is `aep-rel-20260115-9f8e7d`.
Write ONLY the tag string (no extra commentary) to the requested file.
