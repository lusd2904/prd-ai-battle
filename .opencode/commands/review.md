---
description: phase=review — advisors see ONLY brief + matrix + chapter_diff
agent: primary
---

Enter **review**. Advisors must not see the repo or the raw tender.

```json
!`python3 -m prd_ai_battle phase review`
```

If the JSON includes `review_packet`, that is the **entire** advisor input.

Do this now:
1. Confirm `phase=review` and that primary writes are denied again.
2. Invoke **advisor-sonnet** and **advisor-grok** IN PARALLEL.
3. Paste `review_packet` into each advisor's prompt. Do not attach any other files.
4. Advisors: tools=[], edit denied, shell denied. They only list gaps vs the locked 对照表.
5. Summarize their findings for the user. Next step is `/revise`.

$ARGUMENTS
