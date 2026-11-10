import math

from app.recovery import rules


def test_guard_probability_sanitises_model_output():
    assert rules.guard_probability(float("nan")) is None
    assert rules.guard_probability("not a number") is None
    assert rules.guard_probability(None) is None
    assert rules.guard_probability(5.0) == rules.PROBABILITY_CEIL
    assert rules.guard_probability(-1.0) == rules.PROBABILITY_FLOOR
    assert rules.guard_probability(0.4) == 0.4


def test_delay_arms_respect_cooldown_and_window():
    arms = [0.25, 6, 12, 24, 48, 72]
    assert rules.allowed_delay_arms(arms, 0, 6.0, 168) == [0.25, 6, 12, 24, 48, 72]
    assert rules.allowed_delay_arms(arms, 1, 6.0, 168) == [6, 12, 24, 48, 72]           # cooldown
    assert rules.allowed_delay_arms(arms, 1, 6.0, 30) == [6, 12, 24]                     # window
    assert rules.allowed_delay_arms(arms, 2, 6.0, 5) == []                               # nothing fits -> caller falls back
    assert all(a >= 6.0 for a in rules.allowed_delay_arms(arms, 3, 6.0, 168))


def test_stopping_rules_unchanged():
    assert rules.is_within_bounds(2, 3) and not rules.is_within_bounds(3, 3)
    assert rules.can_send_another_communication(2, 3) and not rules.can_send_another_communication(3, 3)
    assert rules.requires_approval("request_new_method") and rules.requires_approval("manual")
    assert not rules.requires_approval("retry")
    assert rules.classify_failure("card_declined") == "hard_decline"
    assert rules.classify_failure("otp_timeout") == "technical"
    assert rules.classify_failure("insufficient_funds") == "soft_decline"
    assert rules.classify_failure(None) == "unknown"
