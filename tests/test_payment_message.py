from datetime import date

from core.payment_message import build_message, format_won
from core.schema import FUND_WALLET, PayoutInfo, Trip
from core.settlement import Transfer


def trip_with_payout(name, payout, mode="prepaid"):
    return Trip(
        name="제주",
        members=["A", "B", "C"],
        leader="A",
        mode=mode,
        fund_per_person=10000 if mode == "fund" else 0,
        start_date=date(2026, 10, 10),
        end_date=date(2026, 10, 12),
        payout={name: payout},
    )


def test_format_won():
    assert format_won(12345) == "12,345원"


def test_message_includes_amount_and_all_payout_channels():
    t = trip_with_payout(
        "A",
        PayoutInfo(
            bank_account="카카오뱅크 3333-01-1234567",
            toss_link="https://toss.me/minsu",
            kakaopay_link="https://qr.kakaopay.com/abc",
        ),
    )
    msg = build_message(Transfer("B", "A", 15000), t)
    for part in [
        "B",
        "A",
        "15,000원",
        "3333-01-1234567",
        "https://toss.me/minsu",
        "https://qr.kakaopay.com/abc",
    ]:
        assert part in msg


def test_message_first_line_names_trip_sender_receiver_and_amount():
    msg = build_message(Transfer("B", "A", 15000), trip_with_payout("A", PayoutInfo()))
    assert msg.splitlines()[0] == "[제주] B님 → A님 15,000원"


def test_message_without_payout_info():  # Review Focus 4
    msg = build_message(Transfer("B", "C", 5000), trip_with_payout("A", PayoutInfo()))
    assert "5,000원" in msg and "받는 분께 계좌를 확인하세요" in msg


def test_message_only_lists_present_channels():
    t = trip_with_payout("A", PayoutInfo(toss_link="https://toss.me/minsu"))
    msg = build_message(Transfer("B", "A", 5000), t)
    assert "https://toss.me/minsu" in msg
    assert "계좌" not in msg and "카카오페이" not in msg


def test_fund_wallet_receiver_uses_leader_payout():
    t = trip_with_payout("A", PayoutInfo(toss_link="https://toss.me/minsu"), mode="fund")
    msg = build_message(Transfer("B", FUND_WALLET, 7000), t)
    assert "https://toss.me/minsu" in msg and "회비 지갑(대표 A)" in msg


def test_fund_wallet_sender_is_refund_message():
    msg = build_message(
        Transfer(FUND_WALLET, "B", 7000), trip_with_payout("A", PayoutInfo(), mode="fund")
    )
    assert "환급" in msg and "A" in msg
    assert msg.splitlines()[0] == "[제주] 대표 A님이 B님께 회비 7,000원을 환급합니다."
