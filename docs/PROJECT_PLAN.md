# Overall project plan

Reviewed: 2 November 2026. This is the target specification, not a completion report.
See [implementation status](IMPLEMENTATION_STATUS.md) for delivered behavior.

## Basis and agreed changes

The owner-supplied Word plan dated 29 October 2026 defines a single-owner Indian
intraday breakout platform, thirteen principal interface areas, a broker-neutral
core, and phased validation before live use.

Subsequent owner decisions amend the implementation as follows:

| Area | Agreed direction |
| --- | --- |
| Storage | Use SQLite for the current application. |
| Execution decisions | Support both manual approval and automatic processing. Auto-enabled eligible calls should proceed after server risk checks without a manual approval prompt. |
| Broker order | Prioritize Groww; retain Upstox as a future integration target. |
| Daily capital | Allow a trading allocation separate from the total broker balance, with configurable per-trade risk and daily loss percentage. |
| Visibility | Show stored/live-source data, row and bulk approval/rejection controls, reasons, India timestamps, and a visible candle-capture monitor. |
| Pre-market context | Keep a separate readable daily context module; automate observations where real data is available. |
| UI | Preserve functionality while improving readability, color, and consistency with the supplied mocks. |

Manual/automatic is an approval policy. Paper/live is an execution destination.
The target design must distinguish them. The existing toggle does not yet fully
implement that separation and does not activate live Groww order placement.

The original recommended Next.js/FastAPI/PostgreSQL/Redis stack is a planning
reference. The delivered foundation uses plain browser JavaScript, Python's
HTTP server, and SQLite; migration is not a prerequisite for documenting it.

## Product scope

One owner, one active broker account, NSE cash equities, and one versioned
opening-range breakout strategy. The planned universe is liquid Nifty 200
equities with appropriate liquidity and spread filters. The current capture
universe is six configured symbols, not the complete index.

The eventual system should ingest market data, form validated candles, explain
signals, calculate quantity, enforce account risk, manage broker orders and
protection, reconcile positions, and preserve a decision trail.

Deferred: derivatives, multi-user organizations, strategy marketplaces,
high-frequency execution, and delivery/portfolio investment workflows.

## Strategy specification

All times are Asia/Kolkata.

| Stage | Target rule |
| --- | --- |
| Opening range | High and low from 09:15 inclusive to 09:30 exclusive. |
| Long | Completed five-minute close above opening high, with confirmation. |
| Short | Completed five-minute close below opening low, with confirmation. |
| Confirmation | Correct side of VWAP, relative volume at least 1.8 times its reference, and actual index trend alignment. |
| Entry window | 09:30 inclusive to 14:45 exclusive. |
| Extension | Reject overextended breakouts; current configured guard is 0.25%. |
| Initial stop | Technical invalidation, subject to the permitted stop distance and quantity rules. |
| Profit handling | Optional 50% at 1R, remaining target near 2R; trailing behavior needs an explicit specification before implementation. |
| Time exit | Target mandatory intraday exit at 15:15 or an earlier broker-specific safe time. |
| Size | Floor of allowed rupee risk divided by entry-to-stop distance, followed by funds, exposure, and position-cap checks. |

Sampled LTP candles without volume cannot satisfy the intended VWAP/relative-volume
data requirements. A trained AI model is not required for deterministic ORB
rules. An AI/news component would require its own data, evaluation, and acceptance.

## Risk requirements

| Control | Starting target |
| --- | --- |
| Per-trade risk | 0.25% of allocated trading capital in the current owner workflow. |
| Daily loss stop | 1% of allocated capital, shared across the account's active strategy symbols. |
| Losing trades | Stop new entries after three losses. |
| Concurrent positions | At most three across the active account. |
| Per-symbol exposure | At most 20% of permitted capital. |
| Stop distance | Maximum 0.80%; define rejection versus adjustment consistently. |
| Staleness | Original plan targets five seconds for an execution-quality feed; the current minute-sampled monitor cannot meet this target. |
| Mismatch | Pause new broker orders until reconciled. |
| Emergency | Pause entries; cancel pending entries; controlled exit and reconciliation. |

Limits must be enforced on the server with account-wide state. The browser's
displayed balance is not a substitute for broker funds or margin verification.

## Interface scope

| Area | Target behavior |
| --- | --- |
| Daily session | Daily authorization, context, capital, risk, and explicit readiness. |
| Dashboard | Current account/strategy state with data provenance and timestamps. |
| Scanner | Universe filtering and ranked candidates with rejection reasons. |
| Signal analysis | Price, range, VWAP, volume, and actual rule outcomes. |
| Trade approval | Exact order ticket, risk, expiry, row actions, and bulk actions. |
| Positions and orders | Broker/order lifecycle, protection, exits, and reconciliation. |
| Strategy | Tested immutable versions with controlled activation. |
| Backtest and replay | Period selection, realistic costs, out-of-sample metrics, and trade replay. |
| Risk | Persisted account limits and emergency commands. |
| Connections | Real broker authentication and measured health. |
| Journal | Trade-linked decisions, costs, and analytics. |
| Alerts | Severity, delivery, acknowledgement, and resolution. |
| System health | Measured service health and exportable audit events. |

Live Quotes is an additional current UI entry for the capture monitor.

## Delivery and acceptance

1. Establish local SQLite storage, normalized records, and broker boundaries.
2. Complete reliable OHLCV ingestion, timestamp conventions, gap recovery, and instrument coverage.
3. Validate ORB, risk calculations, historical replay, and realistic costs.
4. Complete continuous paper order, fill, protection, exit, and reconciliation behavior.
5. Finish broker adapters and their approved test paths.
6. Run failure drills and at least twenty observed trading sessions with defect review.
7. Consider restricted production only after recorded acceptance and owner activation.

The original plan's time estimates are planning estimates, not promised delivery
dates. The dependency-ordered [roadmap](VALIDATION_AND_ROADMAP.md) governs next work.

Definition of done includes working broker paths, accurate data and costs,
all interface areas backed by normalized state, tested emergency/recovery
behavior, and documented release gates. Broker/account onboarding requirements
must be confirmed with the provider at implementation time; this document does
not assert current legal or broker approval.
