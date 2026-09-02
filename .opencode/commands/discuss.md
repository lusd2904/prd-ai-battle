---
description: Shared multi-model discuss chat — one labeled timeline, tools=[], no writes
agent: primary
---

Drive the product state machine into **discuss** and run the shared-chat orchestrator.

```
!`python3 -m prd_ai_battle discuss --requirement samples/tender.md`
```

That command reads the **current yaml** `primary` + `advisors[]` (do not assume seed names) and runs a **group chat**:

- Round 0: everyone opens **in parallel** on the brief (`tools=[]` for advisors).
- Later rounds: every speaker is given the **FULL** current `timeline[]` (labeled `[agent-id · timestamp]`) plus the brief, then replies — they may agree, disagree, or ask each other.
- Repeat until the user `/lock`. No file writes. `write_lock` stays closed.

Do this now:
1. Confirm `phase=discuss` and `write_lock` is ON (no filesystem writes).
2. Present the printed transcript as **one chat with several mouths**. Do **not** spawn OpenCode teammates, subagents, or sidecar panes — Agent Teams are not the product UX.
3. Speakers are whatever the yaml lists. Do not hardcode advisor names.
4. Advisors have `tools=[]` — they must not edit, write, or run shell. They saw `brief` + draft 对照表 + the full labeled timeline.
5. If one speaker times out or errors, the others continue (do not abort discuss).
6. Cover ★ must-respond clauses, scoring points, and 废标风险, then recommend 对照表 fills (条款 / 是否响应 / 证据页码 / 意见 / 状态).
7. Do not write draft files. When the user is ready they will run `/lock`.

User notes: $ARGUMENTS
