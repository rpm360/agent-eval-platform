---
name: commit-message-format
description: Internal house convention for git commit messages.
---

# Commit Message Format Skill

Commit messages MUST follow this exact structure:

```text
<TICKET> | <type>(<scope>): <summary>

Why: <one sentence explaining the motivation>

Signed-off-by: aep-bot
```

Rules:
- `<type>` is one of: feat, fix, chore, docs, refactor, test.
- `<summary>` is lowercase, imperative mood, no trailing period.
- The whole first line is at most 60 characters.
- Line 2 is blank. The last line is always `Signed-off-by: aep-bot`.
