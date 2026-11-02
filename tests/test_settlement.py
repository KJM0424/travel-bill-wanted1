from datetime import date

from core.schema import FUND_WALLET, Expense, Trip
from core.settlement import (
    Balance,
    Transfer,
    compute_balances,
    plan_transfers,
    readiness_errors,
)


def exp(amount, payer, participants, excluded=False):
    return Expense(
        expense_id=f"e-{amount}-{payer}",
        source="manual",
        merchant_name=f"가게{amount}",
        amount=amount,
        payer=payer,
        participants=list(participants),
        excluded=excluded,
    )


def trip(mode, expenses, fee=0):
    return Trip(
        name="제주",
        members=["A", "B", "C"],
        leader="A",
        mode=mode,
        fund_per_person=fee,
        start_date=date(2026, 10, 10),
        end_date=date(2026, 10, 12),
        expenses=list(expenses),
    )


def by_name(balances):
    return {b.name: b for b in balances}


def test_prepaid_even_split():
    b = by_name(compute_balances(trip("prepaid", [exp(30000, "A", ["A", "B", "C"])])))
    assert (b["A"].net, b["B"].net, b["C"].net) == (20000, -10000, -10000)


def test_absent_member_excluded_from_share():  # 카페에 C가 빠짐
    b = by_name(compute_balances(trip("prepaid", [exp(10000, "A", ["A", "B"])])))
    assert (b["A"].net, b["B"].net, b["C"].net) == (5000, -5000, 0)


def test_payer_not_participant_gets_full_refund():  # Review Focus 3
    b = by_name(compute_balances(trip("prepaid", [exp(9000, "A", ["B", "C"])])))
    assert (b["A"].paid, b["A"].owed, b["A"].net) == (9000, 0, 9000)


def test_remainder_charged_to_payer():
    b = by_name(compute_balances(trip("prepaid", [exp(10000, "B", ["A", "B", "C"])])))
    assert (b["A"].owed, b["B"].owed, b["C"].owed) == (3333, 3334, 3333)


def test_remainder_charged_to_payer_even_if_not_participant():
    b = by_name(compute_balances(trip("prepaid", [exp(11, "A", ["B", "C"])])))
    assert (b["A"].owed, b["B"].owed, b["C"].owed) == (1, 5, 5)


def test_multiple_payers():
    b = by_name(
        compute_balances(
            trip(
                "prepaid",
                [exp(30000, "A", ["A", "B", "C"]), exp(60000, "B", ["A", "B", "C"])],
            )
        )
    )
    assert (b["A"].net, b["B"].net, b["C"].net) == (0, 30000, -30000)


def test_balances_follow_member_order_with_fund_wallet_last():
    balances = compute_balances(trip("fund", [], fee=1000))
    assert [x.name for x in balances] == ["A", "B", "C", FUND_WALLET]


def test_fund_mode_refund_when_underspent():
    b = by_name(
        compute_balances(trip("fund", [exp(60000, FUND_WALLET, ["A", "B", "C"])], fee=30000))
    )
    assert b[FUND_WALLET].net == -30000 and b["A"].net == 10000


def test_fund_mode_shortfall():
    b = by_name(
        compute_balances(trip("fund", [exp(120000, FUND_WALLET, ["A", "B", "C"])], fee=30000))
    )
    assert b[FUND_WALLET].net == 30000 and b["A"].net == -10000


def test_fund_mode_personal_payment():
    b = by_name(
        compute_balances(
            trip(
                "fund",
                [exp(90000, FUND_WALLET, ["A", "B", "C"]), exp(6000, "B", ["A", "B", "C"])],
                fee=30000,
            )
        )
    )
    assert (b["B"].net, b[FUND_WALLET].net) == (4000, 0)


def test_excluded_expense_ignored():
    b = by_name(
        compute_balances(trip("prepaid", [exp(30000, "A", ["A", "B", "C"], excluded=True)]))
    )
    assert all(x.net == 0 for x in b.values())


def test_nets_always_sum_to_zero():
    t = trip(
        "fund",
        [exp(10001, "B", ["A", "C"]), exp(77777, FUND_WALLET, ["A", "B", "C"])],
        fee=25000,
    )
    assert sum(x.net for x in compute_balances(t)) == 0


def test_plan_transfers_settles_everyone():
    bal = compute_balances(
        trip("prepaid", [exp(30000, "A", ["A", "B", "C"]), exp(60000, "B", ["A", "B", "C"])])
    )
    assert plan_transfers(bal) == [Transfer("C", "B", 30000)]


def test_plan_transfers_skips_zero_and_is_deterministic():
    bal = [Balance("A", 0, 0, 0), Balance("B", 0, 5000, -5000), Balance("C", 5000, 0, 5000)]
    assert plan_transfers(bal) == plan_transfers(list(reversed(bal))) == [Transfer("B", "C", 5000)]


def test_readiness_errors():  # Review Focus 5 + 빈 상태
    assert readiness_errors(trip("prepaid", [])) == ["결제 건이 없어요."]
    errs = readiness_errors(trip("prepaid", [exp(0, "A", ["A"]), exp(5000, "A", [])]))
    assert any("금액" in e for e in errs) and any("함께한 사람" in e for e in errs)


def test_readiness_rejects_payer_outside_trip():
    errs = readiness_errors(trip("prepaid", [exp(5000, "D", ["A"])]))
    assert errs == ["'가게5000' 결제한 사람이 이 여행에 없어요."]


def test_readiness_allows_fund_wallet_payer_in_fund_mode():
    assert readiness_errors(trip("fund", [exp(5000, FUND_WALLET, ["A"])], fee=1000)) == []


def test_readiness_ignores_excluded():
    assert (
        readiness_errors(trip("prepaid", [exp(5000, "A", ["A"]), exp(0, "A", [], excluded=True)]))
        == []
    )


def test_readiness_rejects_participant_outside_trip():
    errs = readiness_errors(trip("prepaid", [exp(9000, "A", ["B", "D"])]))
    assert errs == ["'가게9000' 함께한 사람 중 이 여행에 없는 사람이 있어요: D"]


def test_readiness_rejects_fund_wallet_as_participant():
    errs = readiness_errors(trip("fund", [exp(9000, "A", [FUND_WALLET])], fee=1000))
    assert errs == [f"'가게9000' 함께한 사람 중 이 여행에 없는 사람이 있어요: {FUND_WALLET}"]
