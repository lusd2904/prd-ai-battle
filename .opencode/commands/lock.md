---
description: Lock the 响应对照表 → phase=locked (matrix frozen, writes still blocked)
agent: primary
---

Lock the compliance matrix. write_lock stays ON.

```json
!`python3 -m prd_ai_battle phase lock`
```

After this:
- `phase=locked`
- 对照表 clauses cannot be added or removed
- 是否响应 / 证据页码 / 意见 stay empty until the primary writes a draft in `/execute` (then record-draft fills them)
- Nobody may write draft files yet
- Tell the user to run `/execute` when they want the primary to write v1

If the command failed, explain the error (usually: no brief, empty matrix, or illegal transition) and stop.

$ARGUMENTS
