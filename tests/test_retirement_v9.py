"""
Baseline regression suite for retirement_v9.py, written before the Phase 1-3
improvement plan (perf/caching, taxable brokerage bucket, GK inflation rule,
tax-year verifier). None of the engine functions exercised here touch
Streamlit (`st.*` only appears inside `main()`), so these import and run the
module directly with no app runtime needed.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import retirement_v9 as rv


def make_cfg(**overrides):
    """A small, fast, fully-populated cfg matching every key run_simulation/
    run_accumulation reads (see the cfg = dict(...) construction in main())."""
    cfg = dict(
        current_age=60, retirement_age=61, planning_end_age=75,
        pretax_401k=800_000, roth_ira=300_000, hsa=60_000,
        s_plus_5yr=0, s_plus_10yr=0, cash=200_000,
        contrib_401k=24_500, contrib_roth401k=8_000, contrib_roth_ira=8_700,
        contrib_hsa=8_700, contrib_mega_backdoor=0, contrib_employer_match=0,
        contrib_cash_annual=50_000, contrib_cash_final_lump=0,
        pretax_return=0.06, roth_return=0.07, hsa_return=0.05, cash_return=0.04,
        ss_start_age=67, ss_annual_amount=40_000, ss_cola=0.02,
        jss_start_age=99, jss_annual_amount=0, jss_cola=0.0, jss_recovery_years=0,
        rental_gross=0, rental_taxable_pct=0.5,
        base_annual_expenses=90_000, inflation_rate=0.03,
        healthcare_pre_medicare=20_000, healthcare_post_medicare=8_000,
        healthcare_inflation=0.05, hdhp_annual=0,
        expense_reduction_post80=0.0,
        gifts_annual=0, lump_sums={},
        standard_deduction=29_200, bracket_inflation=0.025, oregon_resident=True,
        tax_cash_interest=True,
        rmd_start_age=75, draw_order=["pretax", "cash", "roth", "hsa"],
        roth_conversion_enabled=False, roth_conversion_target_bracket="12%",
        roth_conversion_margin=100_000, irmaa_avoidance=True,
        performance_draw_only=False,
        neg_ret_draw_reduction=0,
        num_children=0, roth_legacy_per_child=0,
        legacy_years=0, legacy_inflation=0.03,
        legacy_pool_return=0.07, legacy_pool_std=0.12,
        heir_tax_rate=0.24,
        spending_strategy="fixed",
        guardrail_band_pct=0.20, guardrail_adjustment_pct=0.10,
        guardrail_floor_pct=0.50, guardrail_ceiling_pct=1.50,
        model_widow_scenario=False, first_death_age=999,
        ss_survivor_pct=0.65, jss_survivor_pct=1.0,
        expense_reduction_widowhood=0.0,
    )
    cfg.update(overrides)
    return cfg


# ============================================================
# RMD table (get_rmd)
# ============================================================

def test_get_rmd_known_table_value():
    assert rv.get_rmd(274_000, 72, 72) == pytest.approx(274_000 / 27.4)


def test_get_rmd_matches_table_for_a_later_age():
    assert rv.get_rmd(100_000, 75, 73) == pytest.approx(100_000 / rv.RMD_TABLE[75])


def test_get_rmd_zero_before_start_age():
    assert rv.get_rmd(500_000, 70, 73) == 0.0


def test_get_rmd_zero_for_nonpositive_balance():
    assert rv.get_rmd(0, 80, 73) == 0.0
    assert rv.get_rmd(-100, 80, 73) == 0.0


def test_get_rmd_floors_at_120_plus():
    assert rv.get_rmd(200_000, 125, 73) == pytest.approx(200_000 / rv.RMD_TABLE_FLOOR_FACTOR)
    assert rv.get_rmd(200_000, 120, 73) == pytest.approx(200_000 / rv.RMD_TABLE[120])


# ============================================================
# Social Security taxability (ss_taxable_portion)
# ============================================================

def test_ss_taxable_portion_below_tier1_is_untaxed():
    assert rv.ss_taxable_portion(20_000, 10_000, single=False) == 0.0


def test_ss_taxable_portion_tier1_band_mfj():
    # prov = 20,000 + 30,000*0.5 = 35,000 (between the 32k/44k MFJ tiers)
    assert rv.ss_taxable_portion(30_000, 20_000, single=False) == pytest.approx(1_500.0)


def test_ss_taxable_portion_tier2_mfj():
    # prov = 60,000 + 40,000*0.5 = 80,000 (above the 44k MFJ tier-2 threshold)
    assert rv.ss_taxable_portion(40_000, 60_000, single=False) == pytest.approx(34_000.0)


def test_ss_taxable_portion_tier2_addon_capped_at_half_benefit_not_flat_6000():
    # v6 fix: the addon is min($6,000, 50% of SS) -- for a small SS benefit,
    # 50% of SS is BELOW the flat $6,000 cap, so the cap must bind at the
    # smaller number, not the flat figure.
    result = rv.ss_taxable_portion(6_000, 100_000, single=False)
    assert result == pytest.approx(5_100.0)  # min(85% of ss, ...) binds here


def test_ss_taxable_portion_single_filer_uses_single_thresholds():
    assert rv.ss_taxable_portion(20_000, 10_000, single=True) == 0.0
    # prov = 20,000 + 20,000*0.5 = 30,000 (between the single 25k/34k tiers)
    assert rv.ss_taxable_portion(20_000, 20_000, single=True) == pytest.approx(2_500.0)


# ============================================================
# Tax engine (calc_tax / bracket_ceiling)
# ============================================================

def test_calc_tax_matches_hand_computed_two_bracket_case():
    taxable = 50_000
    expected = 24_800 * 0.10 + (50_000 - 24_800) * 0.12
    assert rv.calc_tax(taxable, rv.FEDERAL_BRACKETS, 0, 0.0) == pytest.approx(expected)


def test_calc_tax_zero_for_nonpositive_income():
    assert rv.calc_tax(0, rv.FEDERAL_BRACKETS, 0, 0.0) == 0.0
    assert rv.calc_tax(-500, rv.FEDERAL_BRACKETS, 0, 0.0) == 0.0


def test_bracket_ceiling_returns_the_named_brackets_own_ceiling():
    assert rv.bracket_ceiling(rv.FEDERAL_BRACKETS, 0.12, 0, 0.0) == pytest.approx(100_800)
    assert rv.bracket_ceiling(rv.FEDERAL_BRACKETS, 0.22, 0, 0.0) == pytest.approx(211_400)


def test_bracket_ceiling_inflates_with_yrs_and_infl():
    infl = 0.03
    expected = 100_800 * (1 + infl) ** 5
    assert rv.bracket_ceiling(rv.FEDERAL_BRACKETS, 0.12, 5, infl) == pytest.approx(expected)


# ============================================================
# Guardrails floor/ceiling (the v8 fix)
# ============================================================

def _flat_return_overrides(num_years, rate):
    return {k: np.full(num_years, rate) for k in ["pretax", "roth", "hsa", "cash", "legacy_pool"]}


def test_guardrail_factor_never_breaches_floor_on_sustained_down_years():
    cfg = make_cfg(
        planning_end_age=90, spending_strategy="guardrails",
        guardrail_floor_pct=0.50, guardrail_ceiling_pct=1.50,
    )
    num_years = cfg["planning_end_age"] - cfg["retirement_age"] + 1
    overrides = _flat_return_overrides(num_years, -0.30)
    _, df = rv.run_simulation(cfg, return_overrides=overrides)
    assert df["Guardrail_Factor"].min() >= cfg["guardrail_floor_pct"] - 1e-9
    assert df["Guardrail_Factor"].max() <= cfg["guardrail_ceiling_pct"] + 1e-9


def test_guardrail_factor_never_breaches_ceiling_on_sustained_up_years():
    cfg = make_cfg(
        planning_end_age=90, spending_strategy="guardrails",
        guardrail_floor_pct=0.50, guardrail_ceiling_pct=1.50,
    )
    num_years = cfg["planning_end_age"] - cfg["retirement_age"] + 1
    overrides = _flat_return_overrides(num_years, 0.35)
    _, df = rv.run_simulation(cfg, return_overrides=overrides)
    assert df["Guardrail_Factor"].min() >= cfg["guardrail_floor_pct"] - 1e-9
    assert df["Guardrail_Factor"].max() <= cfg["guardrail_ceiling_pct"] + 1e-9
    # The sustained-up scenario should actually reach the ceiling, not just
    # stay safely under it -- otherwise this test wouldn't be exercising the
    # v8 bound at all.
    assert df["Guardrail_Factor"].iloc[-1] == pytest.approx(cfg["guardrail_ceiling_pct"])


# ============================================================
# Smoke test / regression pin
# ============================================================

def test_run_simulation_smoke_and_regression_pin():
    """Pins the deterministic (non-MC) output of a known cfg. A change here
    means the engine's numeric output changed -- expected during Phase 2
    feature work, but should never happen silently during Phase 1 (pure
    perf refactor with no intended behavior change)."""
    cfg = make_cfg()
    accum_rows, df = rv.run_simulation(cfg)

    assert len(df) == cfg["planning_end_age"] - cfg["retirement_age"] + 1
    assert df["Age"].is_monotonic_increasing
    assert not df.isna().any().any()

    assert df["Total_Liquid_Assets"].iloc[-1] == pytest.approx(661_968.0460501057)
    assert df["Total_Real"].iloc[-1] == pytest.approx(437_638.86212668434)


def test_run_accumulation_smoke():
    cfg = make_cfg(current_age=55, retirement_age=61)
    rows, pt, ro, hs, ca, s5, s10 = rv.run_accumulation(cfg)
    assert len(rows) == 6
    assert pt > cfg["pretax_401k"]  # grew + received contributions
    assert all(r["Age"] == cfg["current_age"] + i for i, r in enumerate(rows))
