import logging
import time
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import httpx

logger = logging.getLogger(__name__)

GEO_TAX_CONFIG: Dict[str, Any] = {
    "citation": "Georgian Tax Code Article 90 (Small Business Status)",
    "effective_as_of": "2026-01-01",
    "disclaimer": "Informational estimate only — not legal or tax advice. Consult a licensed Georgian CPA.",
    "small_business_cap_gel": 500_000.0,
    "small_business_rate_under_cap": 0.01,
    "small_business_rate_over_cap": 0.03,
    "labor_pit_rate": 0.20,
    "labor_employee_pension_rate": 0.02,
}

DEFAULT_FX_TO_GEL: Dict[str, float] = {
    "GEL": 1.0,
    "USD": 2.70,
    "EUR": 2.90,
    "GBP": 3.45,
}

NBG_RATES_URL = "https://nbg.gov.ge/gw/api/ct/monetarypolicy/currencies/en/json/"
_FX_CACHE: Dict[str, Any] = {
    "rates": dict(DEFAULT_FX_TO_GEL),
    "source": "default_fallback",
    "fetched_at": 0.0,
    "as_of": None,
}
_FX_CACHE_TTL_SEC = 4 * 3600


def _ingest_nbg_payload(payload: Any, now: float) -> Optional[Dict[str, Any]]:
    if not isinstance(payload, list) or not payload:
        return None
    block = payload[0]
    currencies = block.get("currencies") or []
    parsed: Dict[str, float] = {"GEL": 1.0}
    for item in currencies:
        code = str(item.get("code") or "").upper()
        qty = float(item.get("quantity") or 1)
        rate = float(item.get("rate") or 0)
        if code in ("USD", "EUR", "GBP") and rate > 0 and qty > 0:
            parsed[code] = round(rate / qty, 4)
    if len(parsed) >= 3:
        _FX_CACHE["rates"] = parsed
        _FX_CACHE["source"] = "nbg_live"
        _FX_CACHE["fetched_at"] = now
        _FX_CACHE["as_of"] = str(block.get("date") or datetime.now(UTC).date().isoformat())[:10]
        return dict(_FX_CACHE)
    return None


async def get_cached_nbg_rates_async(allow_network: bool = True) -> Dict[str, Any]:
    """Single non-blocking async NBG FX rate fetcher with 4h TTL cache and offline fallback."""
    now = time.time()
    if now - _FX_CACHE["fetched_at"] < _FX_CACHE_TTL_SEC and _FX_CACHE["source"] == "nbg_live":
        return dict(_FX_CACHE)
    if not allow_network:
        return dict(_FX_CACHE)
    try:
        async with httpx.AsyncClient(timeout=3.5) as client:
            resp = await client.get(NBG_RATES_URL)
        if resp.status_code == 200:
            updated = _ingest_nbg_payload(resp.json(), now)
            if updated is not None:
                return updated
    except Exception as exc:
        logger.debug("Async NBG live FX rate fetch skipped (using fallback): %s", exc)
    return dict(_FX_CACHE)


def _compute_annual_projection(ytd_gel: float, monthly_gross_gel: float) -> Dict[str, Any]:
    cap = float(GEO_TAX_CONFIG["small_business_cap_gel"])
    r_low = float(GEO_TAX_CONFIG["small_business_rate_under_cap"])
    r_high = float(GEO_TAX_CONFIG["small_business_rate_over_cap"])

    projected_annual_gross_gel = monthly_gross_gel * 12.0
    projected_cumulative_gel = ytd_gel + projected_annual_gross_gel
    projected_exceeds = projected_cumulative_gel > cap

    crossing_month: Optional[int] = 0 if ytd_gel > cap else None
    if crossing_month is None and monthly_gross_gel > 0 and projected_exceeds:
        for m_idx in range(1, 13):
            if ytd_gel + (monthly_gross_gel * m_idx) > cap:
                crossing_month = m_idx
                break

    annual_tax = sum(
        monthly_gross_gel * (r_low if (ytd_gel + monthly_gross_gel * m_idx) <= cap else r_high)
        for m_idx in range(1, 13)
    )
    eff_rate = round((annual_tax / projected_annual_gross_gel) * 100.0, 2) if projected_annual_gross_gel > 0 else 1.0
    return {
        "projected_annual_gross_gel": projected_annual_gross_gel,
        "projected_cumulative_gel": projected_cumulative_gel,
        "projected_exceeds_500k_cap": projected_exceeds,
        "threshold_crossing_month": crossing_month,
        "projected_annual_tax_gel": annual_tax,
        "projected_effective_tax_rate_pct": eff_rate,
    }


def compute_georgia_b2b_net(
    *,
    amount: float,
    currency: str,
    billing_period: str,
    hours_per_month: int,
    fx: float,
    fx_source: str,
    fx_as_of: Optional[str],
    include_pension_for_labor: bool,
    transfer_fee_pct: float,
    ytd_revenue_gel: float,
) -> Dict[str, Any]:
    """Calculates Georgia IE 1%/3% Small Business B2B net vs standard 20% PIT + 2% pension labor contract."""
    cur = currency.upper()
    cap = float(GEO_TAX_CONFIG["small_business_cap_gel"])
    r_low = float(GEO_TAX_CONFIG["small_business_rate_under_cap"])
    r_high = float(GEO_TAX_CONFIG["small_business_rate_over_cap"])

    if billing_period == "hourly":
        monthly_orig = amount * hours_per_month
    elif billing_period == "annual":
        monthly_orig = amount / 12.0
    else:
        monthly_orig = amount

    monthly_gross_gel = monthly_orig * fx
    ytd_gel = float(ytd_revenue_gel or 0.0)
    actual_cumulative_gel = ytd_gel + monthly_gross_gel
    actual_under_cap = actual_cumulative_gel <= cap
    b2b_tax_rate = r_low if actual_under_cap else r_high
    b2b_tax_gel = monthly_gross_gel * b2b_tax_rate
    transfer_fee_gel = monthly_gross_gel * (transfer_fee_pct / 100.0) if cur != "GEL" else 0.0
    b2b_net_gel = monthly_gross_gel - b2b_tax_gel - transfer_fee_gel
    b2b_net_orig = b2b_net_gel / fx

    proj = _compute_annual_projection(ytd_gel, monthly_gross_gel)
    pension_gel = monthly_gross_gel * (GEO_TAX_CONFIG["labor_employee_pension_rate"] if include_pension_for_labor else 0.0)
    pit_gel = (monthly_gross_gel - pension_gel) * GEO_TAX_CONFIG["labor_pit_rate"]
    labor_net_gel = monthly_gross_gel - pension_gel - pit_gel
    cap_usage_pct = round(min(999.0, (actual_cumulative_gel / cap) * 100.0), 1)

    return {
        "currency": cur,
        "fx_to_gel": round(fx, 4),
        "fx_source": fx_source,
        "fx_as_of": fx_as_of,
        "tax_rule_source": GEO_TAX_CONFIG["citation"],
        "tax_rule_as_of": GEO_TAX_CONFIG["effective_as_of"],
        "disclaimer": GEO_TAX_CONFIG["disclaimer"],
        "monthly_gross_orig": round(monthly_orig, 2),
        "monthly_gross_gel": round(monthly_gross_gel, 2),
        "ytd_revenue_gel": round(ytd_gel, 2),
        "actual_cumulative_gel": round(actual_cumulative_gel, 2),
        "under_500k_cap": actual_under_cap,
        "actual_cap_usage_pct": cap_usage_pct,
        "annual_gross_gel": round(proj["projected_annual_gross_gel"], 2),
        "cumulative_annual_gel": round(proj["projected_cumulative_gel"], 2),
        "projected_annual_gross_gel": round(proj["projected_annual_gross_gel"], 2),
        "projected_cumulative_gel": round(proj["projected_cumulative_gel"], 2),
        "projected_exceeds_500k_cap": proj["projected_exceeds_500k_cap"],
        "threshold_crossing_month": proj["threshold_crossing_month"],
        "projected_annual_tax_gel": round(proj["projected_annual_tax_gel"], 2),
        "projected_effective_tax_rate_pct": proj["projected_effective_tax_rate_pct"],
        "projected_cap_usage_pct": round(min(999.0, (proj["projected_cumulative_gel"] / cap) * 100.0), 1),
        "b2b_small_business": {
            "tax_rate_pct": round(b2b_tax_rate * 100, 1),
            "tax_gel": round(b2b_tax_gel, 2),
            "transfer_fee_gel": round(transfer_fee_gel, 2),
            "net_gel": round(b2b_net_gel, 2),
            "net_orig": round(b2b_net_orig, 2),
            "hourly_net_orig": round(b2b_net_orig / max(hours_per_month, 1), 2),
        },
        "standard_labor_contract": {
            "pension_gel": round(pension_gel, 2),
            "income_tax_gel": round(pit_gel, 2),
            "net_gel": round(labor_net_gel, 2),
            "net_orig": round(labor_net_gel / fx, 2),
        },
        "monthly_b2b_advantage_gel": round(max(0.0, b2b_net_gel - labor_net_gel), 2),
        "cap_usage_pct": cap_usage_pct,
        "notes": [
            f"{GEO_TAX_CONFIG['citation']} (as of {GEO_TAX_CONFIG['effective_as_of']}): Small Business 1% rate applies while actual cumulative calendar-year turnover stays at or below 500,000 GEL; the 3% rate starts in the month the threshold is exceeded.",
            "Scope: models the standard 500,000 GEL Small Business threshold only (specialized exceptions such as the 700,000 GEL wine-/agro-tourism cap are excluded).",
            "Projected 12-month totals are estimates only and do not apply the 3% rate before the threshold is actually crossed.",
            GEO_TAX_CONFIG["disclaimer"],
        ],
    }


def _resolve_tz_offset_hours(tz_name: str, fallback_offset: int) -> tuple[int, bool]:
    try:
        now_local = datetime.now(ZoneInfo(tz_name))
        utc_off = now_local.utcoffset()
        dst_off = now_local.dst()
        offset_h = int(round(utc_off.total_seconds() / 3600)) if utc_off is not None else fallback_offset
        return offset_h, bool(dst_off and dst_off.total_seconds() != 0)
    except (ZoneInfoNotFoundError, ValueError):
        return fallback_offset, False


def _format_wrapped_overlap(hours: List[int]) -> str:
    if not hours:
        return "Async handoff only"
    runs: List[List[int]] = []
    for h in sorted(hours):
        if not runs or h != runs[-1][-1] + 1:
            runs.append([h])
        else:
            runs[-1].append(h)
    return ", ".join(f"{r[0]:02d}:00–{(r[-1] + 1) % 24:02d}:00 GET" for r in runs)


def compute_timezone_matrix(work_start_get: int = 11, work_end_get: int = 19) -> Dict[str, Any]:
    """Computes exact DST-aware working-hour overlap between Georgia Time (UTC+4) and global hubs."""
    start_get = max(0, min(23, int(work_start_get)))
    end_get = max(1, min(24, int(work_end_get)))
    if end_get <= start_get:
        end_get = min(24, start_get + 8)

    ge_hours = set(range(start_get, end_get))
    tbilisi_offset, _ = _resolve_tz_offset_hours("Asia/Tbilisi", 4)
    regions = [
        {"region": "UAE / Gulf (Dubai GST)", "tz": "Asia/Dubai", "fallback_offset": 4},
        {"region": "Central Europe (Berlin / Warsaw)", "tz": "Europe/Berlin", "fallback_offset": 1},
        {"region": "United Kingdom (London)", "tz": "Europe/London", "fallback_offset": 0},
        {"region": "US East Coast (New York)", "tz": "America/New_York", "fallback_offset": -5},
        {"region": "US West Coast (San Francisco)", "tz": "America/Los_Angeles", "fallback_offset": -8},
    ]

    matrix: List[Dict[str, Any]] = []
    for reg in regions:
        cur_offset, dst_active = _resolve_tz_offset_hours(reg["tz"], reg["fallback_offset"])
        diff = tbilisi_offset - cur_offset
        c_start, c_end = 9 + diff, 17 + diff
        overlap = sorted(ge_hours & {h % 24 for h in range(c_start, c_end)})
        rec_start = max(8, min(16, c_start % 24))
        matrix.append({
            "region": f"{reg['region']}{' · DST' if dst_active else ''}",
            "hours_behind_tbilisi": diff,
            "client_hours_tbilisi_time": f"{c_start % 24:02d}:00–{c_end % 24:02d}:00 GET{' (+1d)' if c_end > 24 else ''}",
            "overlap_hours_count": len(overlap),
            "overlap_window_get": _format_wrapped_overlap(overlap),
            "recommended_shift_get": f"{rec_start:02d}:00–{(rec_start + 8) % 24:02d}:00 GET",
        })

    return {
        "base_timezone": "Asia/Tbilisi (GET, UTC+4, No DST)",
        "selected_shift_get": f"{start_get:02d}:00–{end_get:02d}:00 GET",
        "regions": matrix,
    }
