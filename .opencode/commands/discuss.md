---
description: Parallel multi-model discussion — brief only, tools=[], no writes
agent: primary
---

Drive the product state machine into **discuss**. Current contract:

```json
!`python3 -m prd_ai_battle phase discuss --requirement samples/tender.md`
```

You are the **lead** of a 3-agent team (OpenCode Agent Teams shape: one primary + two teammates).

Do this now:
1. Read the JSON contract above. Confirm `phase=discuss` and `write_lock` is ON (no filesystem writes).
2. Invoke **advisor-sonnet** and **advisor-grok** IN PARALLEL as subagents/teammates.
3. Give each advisor ONLY the `brief_markdown` and `matrix_markdown` from the contract. Never attach `samples/tender.md`, `requirement.md`, or the git tree.
4. Each advisor has `tools=[]` — they must not edit, write, or run shell.
5. If one advisor times out or errors, continue with the remaining models. Do not abort discuss.
6. Produce a shared discussion covering ★ must-respond clauses, scoring points, and 废标风险, then recommend 对照表 fills (条款 / 是否响应 / 证据页码 / 意见 / 状态).
7. Do not write draft files. When the user is ready they will run `/lock`.

User notes: $ARGUMENTS
