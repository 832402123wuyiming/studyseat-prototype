"""One accepted rules schema for administration, booking and stored snapshots."""

RULE_LIMITS = {
    "max_duration_minutes": (1, 1440),
    "max_advance_days": (1, 30),
    "check_in_early_minutes": (0, 240),
    "check_in_late_minutes": (0, 240),
    "leave_limit_minutes": (1, 240),
}


def valid_settings(settings):
    return (
        isinstance(settings, dict)
        and set(settings) == set(RULE_LIMITS)
        and all(
            type(settings[key]) is int and low <= settings[key] <= high
            for key, (low, high) in RULE_LIMITS.items()
        )
    )
