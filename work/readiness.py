"""Release-readiness gate derived from the documented acceptance criteria."""
from __future__ import annotations

from validation import validate


def report(conn, symbol="NIFTY50", groww_token_configured=False, static_ip_confirmed=False, broker_approved=False):
    validation = validate(conn, symbol, 5.0, 20.0, 0.0)
    checks = {
        "paper_sessions_20": validation["gates"]["minimum_20_sessions"],
        "out_of_sample_available": validation["gates"]["oos_available"],
        "cost_model_configured": validation["gates"]["cost_model_configured"],
        "duplicate_orders_clear": validation["safety_checks"]["no_duplicate_orders"],
        "uncertain_orders_clear": validation["safety_checks"]["no_uncertain_orders"],
        "audit_present": validation["safety_checks"]["audit_present"],
        "oos_positive_after_costs": validation["out_of_sample"]["net_pnl_after_costs"] > 0,
        "groww_token_configured": bool(groww_token_configured),
        "static_ip_confirmed": bool(static_ip_confirmed),
        "broker_approved": bool(broker_approved),
    }
    return {"symbol": symbol, "checks": checks,
            "ready_for_assisted": all(checks[name] for name in list(checks)[:7]),
            "ready_for_live": all(checks.values()), "validation": validation}
