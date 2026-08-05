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
        neg_ret_draw_reduction=0,
        num_children=0, roth_legacy_per_child=0,
        legacy_years=0, legacy_inflation=0.03,
        legacy_pool_return=0.07, legacy_pool_std=0.12,
        heir_tax_rate=0.24,
        spending_strategy="fixed",
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
    rows, pt, ro, hs, ca, s5, s10, bk, bk_basis = rv.run_accumulation(cfg)
    assert len(rows) == 6
    assert pt > cfg["pretax_401k"]  # grew + received contributions
    assert all(r["Age"] == cfg["current_age"] + i for i, r in enumerate(rows))
    assert bk == 0.0 and bk_basis == 0.0  # no brokerage balance configured


# ============================================================
# Taxable brokerage bucket (Phase 2)
# ============================================================

def test_brokerage_draw_realizes_pro_rated_gain_and_reduces_basis():
    """Isolated, hand-verifiable case: a single retirement year, every other
    bucket at $0, so the whole expense need is forced through the brokerage
    account. 100,000 balance / 40,000 basis = 60% embedded gain; a 30,000
    draw should realize 18,000 of gain and remove 12,000 of basis."""
    cfg = make_cfg(
        current_age=61, retirement_age=61, planning_end_age=61,
        pretax_401k=0, roth_ira=0, hsa=0, cash=0,
        s_plus_5yr=0, s_plus_10yr=0,
        brokerage=100_000, brokerage_basis=40_000,
        ss_annual_amount=0, jss_annual_amount=0, rental_gross=0,
        gifts_annual=0, base_annual_expenses=30_000,
        healthcare_pre_medicare=0, healthcare_post_medicare=0, hdhp_annual=0,
        num_children=0,
    )
    _, df = rv.run_simulation(cfg)
    row = df.iloc[0]
    assert row["Brokerage_Draw"] == pytest.approx(30_000.0)
    assert row["Brokerage_LTCG_Gain"] == pytest.approx(18_000.0)
    assert row["Brokerage_EOY"] == pytest.approx(70_000.0)
    assert row["Brokerage_Basis"] == pytest.approx(28_000.0)


def test_brokerage_basis_never_exceeds_balance_over_many_years():
    cfg = make_cfg(
        planning_end_age=90, brokerage=150_000, brokerage_basis=150_000,
        brokerage_return=0.06, cash=0, pretax_401k=200_000, roth_ira=50_000,
    )
    _, df = rv.run_simulation(cfg)
    assert (df["Brokerage_Basis"] <= df["Brokerage_EOY"] + 1e-6).all()
    assert (df["Brokerage_Basis"] >= 0).all()


def test_calc_ltcg_tax_zero_when_stack_stays_in_zero_bracket():
    # 50,000 ordinary + 20,000 gain = 70,000, entirely under the MFJ 0% LTCG
    # threshold (96,700) -- no federal LTCG tax at all.
    assert rv.calc_ltcg_tax(20_000, 50_000, rv.LTCG_BRACKETS, 0, 0.0) == 0.0


def test_calc_ltcg_tax_splits_across_the_0pct_and_15pct_brackets():
    # 90,000 ordinary + 20,000 gain = 110,000: the first 6,700 of gain fills
    # the remaining 0% room (up to 96,700), the other 13,300 falls in the 15%
    # bracket -- tax = 13,300 * 0.15 = 1,995.
    tax = rv.calc_ltcg_tax(20_000, 90_000, rv.LTCG_BRACKETS, 0, 0.0)
    assert tax == pytest.approx(1_995.0)


def test_calc_ltcg_tax_zero_for_nonpositive_gain():
    assert rv.calc_ltcg_tax(0, 50_000, rv.LTCG_BRACKETS, 0, 0.0) == 0.0
    assert rv.calc_ltcg_tax(-100, 50_000, rv.LTCG_BRACKETS, 0, 0.0) == 0.0


# ============================================================
# Absolute survival floor (absolute_min_annual_expenses)
# ============================================================

def test_absolute_min_floor_disabled_by_default():
    cfg = make_cfg(spending_strategy="fixed")  # absolute_min_annual_expenses not set
    _, df = rv.run_simulation(cfg)
    assert not df["Absolute_Min_Bound_Hit"].any()
    assert (df["Absolute_Min_Inflated"] == 0).all()


# ============================================================
# Variable Percentage Withdrawal (VPW)
# ============================================================

def test_vpw_percentage_matches_hand_computed_amortization_formula():
    # age=65, planning_end_age=90 -> n=26 years remaining (inclusive)
    n = 26
    r = 0.04
    expected = r / (1 - (1 + r) ** (-n))
    assert rv.vpw_percentage(65, 90, r) == pytest.approx(expected)


def test_vpw_percentage_final_year_clamped_to_100pct():
    # The raw ordinary-annuity formula gives (1+r) > 1.0 at n=1; must clamp.
    assert rv.vpw_percentage(90, 90, 0.04) == pytest.approx(1.0)
    assert rv.vpw_percentage(90, 90, 0.08) == pytest.approx(1.0)


def test_vpw_percentage_zero_return_is_one_over_n():
    assert rv.vpw_percentage(88, 90, 0.0) == pytest.approx(1 / 3)


def test_vpw_percentage_rises_with_age():
    rates = [rv.vpw_percentage(age, 90, 0.04) for age in range(65, 91)]
    assert all(b >= a for a, b in zip(rates, rates[1:]))  # monotonically non-decreasing


def test_vpw_base_expenses_matches_pct_of_pre_draw_balance_in_year_zero():
    """Year 0 has no growth applied yet, and current_age==retirement_age
    means no accumulation phase either, so pre-draw total liquid assets are
    exactly the configured starting balances -- a fully hand-computable case."""
    cfg = make_cfg(spending_strategy="vpw", vpw_real_return_pct=0.04, current_age=61)
    _, df = rv.run_simulation(cfg)
    starting_total = cfg["pretax_401k"] + cfg["roth_ira"] + cfg["hsa"] + cfg["cash"]  # brokerage=0
    expected_pct = rv.vpw_percentage(cfg["retirement_age"], cfg["planning_end_age"], 0.04)
    row0 = df.iloc[0]
    assert row0["VPW_Percentage"] == pytest.approx(expected_pct)
    assert row0["Base_Expenses"] == pytest.approx(starting_total * expected_pct)


def test_vpw_self_corrects_without_a_permanent_step():
    """The core claim behind recommending VPW: a bad year changes next
    year's dollar amount because the portfolio shrank, not because of any
    persistent multiplier -- so a rebound that offsets the loss (relative to
    the flat-return baseline path -- -20% then +40.45% cancels out against
    two years of flat +6%, since 0.8*1.4045=1.06*1.06) restores spending to
    ~parity."""
    cfg = make_cfg(spending_strategy="vpw", vpw_real_return_pct=0.04, planning_end_age=85, current_age=61)
    n = cfg["planning_end_age"] - cfg["retirement_age"] + 1
    down_then_up = np.full(n, 0.06)
    down_then_up[1] = -0.20
    down_then_up[2] = 0.4045
    overrides = {k: down_then_up.copy() for k in ["pretax", "roth", "hsa", "cash", "legacy_pool", "brokerage"]}
    _, df_shock = rv.run_simulation(cfg, return_overrides=overrides)

    flat = np.full(n, 0.06)
    overrides_flat = {k: flat.copy() for k in ["pretax", "roth", "hsa", "cash", "legacy_pool", "brokerage"]}
    _, df_flat = rv.run_simulation(cfg, return_overrides=overrides_flat)

    # Year 1 (the bad year) should show reduced spending vs the flat baseline.
    assert df_shock["Base_Expenses"].iloc[1] < df_flat["Base_Expenses"].iloc[1]
    # By year 3 (one year after the offsetting rebound), VPW should have
    # already closed nearly all of the gap -- no lingering "stuck" reduction.
    ratio = df_shock["Base_Expenses"].iloc[3] / df_flat["Base_Expenses"].iloc[3]
    assert ratio > 0.98


def test_vpw_respects_absolute_min_floor():
    cfg = make_cfg(
        spending_strategy="vpw", vpw_real_return_pct=0.04,
        planning_end_age=90, absolute_min_annual_expenses=50_000,
        pretax_401k=50_000, roth_ira=0, hsa=0, cash=0,  # small balance -> VPW alone would be tiny
    )
    _, df = rv.run_simulation(cfg)
    infl = cfg["inflation_rate"]
    real_base_exp = df["Base_Expenses"] / (1 + infl) ** df["Years_Retired"]
    assert real_base_exp.min() >= 50_000 - 1e-6
    assert df["Absolute_Min_Bound_Hit"].any()


def test_vpw_does_not_affect_other_strategies():
    """Adding VPW as a new opt-in branch must not change Fixed Real Spending
    behavior -- confirmed by the unchanged smoke-test regression pin, and
    directly here too."""
    cfg = make_cfg(spending_strategy="fixed")
    _, df = rv.run_simulation(cfg)
    assert (df["VPW_Percentage"] == 0.0).all()


# ============================================================
# Spending ceiling (max_annual_expenses)
# ============================================================

def test_max_expenses_caps_vpw_force_spending():
    """Regression test for the exact problem this was built to fix: VPW's
    withdrawal percentage accelerates near the plan's end and, uncapped,
    can force-spend (and draw) far more than a realistic budget -- a large
    enough portfolio can even go temporarily insolvent once other expense
    categories stack on top of a 100%-of-portfolio VPW draw. The ceiling
    should prevent both."""
    cfg = make_cfg(
        spending_strategy="vpw", vpw_real_return_pct=0.04, planning_end_age=89, current_age=61,
        pretax_401k=4_000_000, roth_ira=1_500_000, max_annual_expenses=168_000,
    )
    _, df = rv.run_simulation(cfg)
    infl = cfg["inflation_rate"]
    real_base_exp = df["Base_Expenses"] / (1 + infl) ** df["Years_Retired"]
    assert real_base_exp.max() <= 168_000 + 1e-6
    assert df["Max_Expenses_Bound_Hit"].any()
    assert df["Total_Liquid_Assets"].iloc[-1] > 0  # stays solvent once capped

    uncapped_cfg = {**cfg, "max_annual_expenses": 0}
    _, df_uncapped = rv.run_simulation(uncapped_cfg)
    assert df_uncapped["Base_Expenses"].iloc[-1] > df["Base_Expenses"].iloc[-1]
    assert df.iloc[-1]["Total_Liquid_Assets"] > df_uncapped.iloc[-1]["Total_Liquid_Assets"]


def test_max_expenses_disabled_by_default():
    cfg = make_cfg(spending_strategy="fixed")  # max_annual_expenses not set
    _, df = rv.run_simulation(cfg)
    assert not df["Max_Expenses_Bound_Hit"].any()
    assert (df["Max_Annual_Expenses_Inflated"] == 0).all()


def test_max_expenses_is_a_no_op_for_fixed_spending():
    """Fixed Real Spending never exceeds its own planned (inflated) amount,
    so setting the ceiling exactly at that plan should never bind."""
    cfg = make_cfg(spending_strategy="fixed", base_annual_expenses=90_000, max_annual_expenses=90_000)
    _, df = rv.run_simulation(cfg)
    assert not df["Max_Expenses_Bound_Hit"].any()


def test_max_expenses_and_absolute_min_floor_both_respected():
    """A sane configuration (floor well below ceiling) must keep spending
    inside [floor, ceiling] at all times."""
    cfg = make_cfg(
        spending_strategy="vpw", vpw_real_return_pct=0.04, planning_end_age=90, current_age=61,
        pretax_401k=4_000_000, roth_ira=1_500_000,
        absolute_min_annual_expenses=50_000, max_annual_expenses=168_000,
    )
    _, df = rv.run_simulation(cfg)
    infl = cfg["inflation_rate"]
    real_base_exp = df["Base_Expenses"] / (1 + infl) ** df["Years_Retired"]
    assert real_base_exp.min() >= 50_000 - 1e-6
    assert real_base_exp.max() <= 168_000 + 1e-6


# ============================================================
# Tax-year governance (Phase 3)
# ============================================================
# Tests the verify_tax_constants() MECHANISM (does it correctly compare
# TAX_YEAR to the real current year), not a claim that the tax-law
# constants themselves stay eternally fresh -- that still requires an
# annual human check. TAX_YEAR is monkeypatched (and restored) rather than
# faking "today", since the function only ever reads date.today().year.

def test_verify_tax_constants_silent_when_current_or_future():
    orig = rv.TAX_YEAR
    try:
        rv.TAX_YEAR = rv.date.today().year
        assert rv.verify_tax_constants() is None
        rv.TAX_YEAR = rv.date.today().year + 1
        assert rv.verify_tax_constants() is None
    finally:
        rv.TAX_YEAR = orig


def test_verify_tax_constants_warns_when_stale():
    orig = rv.TAX_YEAR
    try:
        rv.TAX_YEAR = rv.date.today().year - 2
        msg = rv.verify_tax_constants()
        assert msg is not None
        assert "2 years stale" in msg
        assert "FEDERAL_BRACKETS" in msg  # names what actually needs checking
    finally:
        rv.TAX_YEAR = orig


def test_verify_tax_constants_singular_year_wording():
    orig = rv.TAX_YEAR
    try:
        rv.TAX_YEAR = rv.date.today().year - 1
        msg = rv.verify_tax_constants()
        assert "1 year stale" in msg  # not "1 years stale"
    finally:
        rv.TAX_YEAR = orig
