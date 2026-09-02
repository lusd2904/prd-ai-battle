---
description: phase=review — advisors see ONLY brief + matrix + chapter_diff
agent: primary
---

Enter **review**. Advisors must not see the repo or the raw tender.

```json
!`python3 -m prd_ai_battle phase review`
```

The JSON `review_packet` is the **entire** advisor input (brief + matrix + chapter_diff). The Python orchestrator already invoked every yaml `advisors[]` entry **in parallel** and folded their findings into the same shared `transcript` (labeled `[agent-id · timestamp]`).

Do this now:
1. Confirm `phase=review` and that primary writes are denied again.
2. Present the shared `transcript` as one chat. Do **not** spawn OpenCode teammates, subagents, or sidecar panes.
3. Do not hardcode advisor names — speakers are the current yaml `advisors[]`.
4. Do not attach any other files. Advisors: tools=[], edit denied, shell denied.
5. If one speaker times out, 402s, hits quota, or fails ping, it was **skipped** — the others already continued. Do not abort review.
6. Summarize their findings for the user. Next step is `/revise`.

$ARGUMENTS
