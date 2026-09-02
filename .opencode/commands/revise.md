---
description: phase=revise — primary writes the next artifact_version
agent: primary
---

Open write_lock for the **primary only** (revision).

```json
!`python3 -m prd_ai_battle phase revise`
```

Rules:
- Only you (primary) may write. Advisors stay tools=[].
- Write `.prd-ai-battle/drafts/v2/response.md` (or the next version).
- Address the latest review comments. Do not add or remove 对照表 clauses; response flags update from this draft.
- After write, user can `/review` again.

$ARGUMENTS
