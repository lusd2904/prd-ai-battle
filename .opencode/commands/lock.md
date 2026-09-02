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
- 对照表 cannot be edited (条款 / 是否响应 / 证据页码 / 意见 / 状态 are frozen)
- Nobody may write draft files yet
- Tell the user to run `/execute` when they want the primary to write v1

If the command failed, explain the error (usually: no brief, empty matrix, or illegal transition) and stop.

$ARGUMENTS
