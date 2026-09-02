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
- Address the latest review comments. Keep the locked 对照表 unchanged.
- After write, user can `/review` again.

$ARGUMENTS
