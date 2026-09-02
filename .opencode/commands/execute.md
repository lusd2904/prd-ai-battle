---
description: phase=execute — only the current yaml primary.id may write v1 under write_lock
agent: primary
---

Open write_lock for the **configured primary only**.

```json
!`python3 -m prd_ai_battle phase execute`
```

Rules for this turn:
- You are the current yaml `primary.id`. You MAY write files.
- Advisors remain `tools=[]` / edit+shell denied. Do not ask them to write.
- Write the bid response to `.prd-ai-battle/drafts/v1/response.md`.
- Cover ★ clauses, scoring-point outlines, and 废标规避 from the locked 对照表.
- After a successful write, the overlay hook records `artifact_version`.
- Do not dump the raw tender into the draft; use the brief + locked matrix.

$ARGUMENTS
