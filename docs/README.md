# Breakout OS documentation

Reviewed: 2 November 2026, Asia/Kolkata. Code baseline: `f06c21c`.

| Document | What it answers |
| --- | --- |
| [Project plan](PROJECT_PLAN.md) | What are we building, and what is the agreed scope? |
| [Implementation status](IMPLEMENTATION_STATUS.md) | What exists now, what is partial, and what blocks completion? |
| [Architecture](ARCHITECTURE.md) | Where do the UI, API, strategy, data, and broker code live? |
| [Operations](OPERATIONS.md) | How do I start, authorize, monitor, and troubleshoot the app? |
| [Validation and roadmap](VALIDATION_AND_ROADMAP.md) | What must be tested or implemented next? |

These documents summarize the owner-supplied *Automated Intraday Breakout
Trading Platform* plan dated 29 October 2026, subsequent owner requests, and
inspection of the checked-in source. The original Word document and its mock
images have not been published as part of this documentation update.

Status terms:

- **Implemented:** a code path exists; read its stated limits and evidence.
- **Partial:** some required behavior exists, but the complete workflow does not.
- **Prototype:** presentation or sample data without the corresponding finished workflow.
- **Pending:** no completed implementation or acceptance evidence.

Current stage: local Groww price capture and SQLite paper/replay development.
Production live trading has not passed acceptance. Green UI badges or passing
unit tests alone do not establish live readiness.

When behavior changes, update the relevant status row and roadmap item, record
verification evidence, and advance the review date. Do not put tokens, account
details, live databases, or private trading reports into these Markdown files.
