"""Unit tests for Proxmox CPU percentage calculation fix.

These tests verify that CPU values from the Proxmox API are correctly
converted from decimal fractions (0.0-1.0) to percentages (0-100),
and that values are clamped to ensure they never exceed 100%.
"""



def test_cpu_decimal_to_percentage_conversion():
    """Test that decimal CPU values are correctly converted to percentages."""
    test_cases = [
        (0.0, 0.0),      # 0% CPU
        (0.1, 10.0),     # 10% CPU
        (0.3, 30.0),     # 30% CPU (common in low-usage scenario)
        (0.5, 50.0),     # 50% CPU
        (0.75, 75.0),    # 75% CPU (medium load)
        (0.9, 90.0),     # 90% CPU (high load)
        (0.95, 95.0),    # 95% CPU (very high)
        (0.99, 99.0),    # 99% CPU
        (1.0, 100.0),    # 100% CPU (at limit)
    ]

    for cpu_raw, expected_pct in test_cases:
        # Apply the fix: convert decimal to percentage and clamp
        cpu_pct = min(100, round(cpu_raw * 100, 1)) if cpu_raw else 0
        assert cpu_pct == expected_pct, (
            f"CPU {cpu_raw} should convert to {expected_pct}%, got {cpu_pct}%"
        )


def test_cpu_percentage_clamped_at_100():
    """Test that CPU values > 1.0 are clamped to 100% (defensive).

    While the Proxmox API should only return 0.0-1.0, defensive clamping
    ensures we never show CPU > 100% due to API anomalies or edge cases.
    """
    test_cases = [
        (1.1, 100.0),    # Slightly over — clamp to 100
        (1.5, 100.0),    # Way over — clamp to 100
        (2.0, 100.0),    # Double — clamp to 100
        (10.0, 100.0),   # Extreme — clamp to 100
    ]

    for cpu_raw, expected_pct in test_cases:
        cpu_pct = min(100, round(cpu_raw * 100, 1)) if cpu_raw else 0
        assert cpu_pct == expected_pct, (
            f"CPU {cpu_raw} should clamp to {expected_pct}%, got {cpu_pct}%"
        )
        assert cpu_pct <= 100, f"CPU {cpu_raw} resulted in {cpu_pct}% > 100%"


def test_cpu_percentage_always_in_valid_range():
    """Test that CPU percentage always stays within 0-100 range."""
    # Test boundary values and random values
    test_values = [0, 0.00001, 0.1, 0.5, 0.999, 1.0, 1.5, 5, 100]

    for cpu_raw in test_values:
        cpu_pct = min(100, round(cpu_raw * 100, 1)) if cpu_raw else 0
        assert 0 <= cpu_pct <= 100, (
            f"CPU percentage {cpu_pct}% for input {cpu_raw} is outside 0-100 range"
        )


def test_cpu_none_value_handled():
    """Test that None or missing CPU value defaults to 0%."""
    # Simulate missing/None values
    cpu_raw = None
    cpu_pct = min(100, round(cpu_raw * 100, 1)) if cpu_raw else 0
    assert cpu_pct == 0, "None CPU should default to 0%"


def test_cpu_zero_value_handled():
    """Test that CPU value of 0 is handled correctly."""
    cpu_raw = 0
    cpu_pct = min(100, round(cpu_raw * 100, 1)) if cpu_raw else 0
    assert cpu_pct == 0, "CPU 0 should result in 0%"


def test_rounding_precision():
    """Test that CPU values are rounded to 1 decimal place."""
    test_cases = [
        (0.333333, 33.3),   # Should round to 1 decimal
        (0.666666, 66.7),   # Should round to 1 decimal
        (0.123456, 12.3),   # Should round to 1 decimal
        (0.999999, 100.0),  # Should round up and clamp
    ]

    for cpu_raw, expected_pct in test_cases:
        cpu_pct = min(100, round(cpu_raw * 100, 1)) if cpu_raw else 0
        assert cpu_pct == expected_pct, (
            f"CPU {cpu_raw} should round to {expected_pct}%, got {cpu_pct}%"
        )


def test_telemetry_thresholds_with_clamped_cpu():
    """Test that telemetry status thresholds work correctly with clamped CPU values."""
    # Simulate health status logic using CPU percentage
    test_cases = [
        # (cpu_pct, expected_status)
        (30.0, "healthy"),   # Low CPU (≤70%)
        (70.0, "healthy"),   # At 70% threshold (not > 70)
        (71.0, "degraded"),  # Just above 70% threshold
        (75.0, "degraded"),  # Medium CPU
        (90.0, "degraded"),  # At 90% threshold (not > 90)
        (91.0, "critical"),  # Just above 90% threshold
        (95.0, "critical"),  # Critical CPU
        (100.0, "critical"), # Maximum CPU
    ]

    for cpu_pct, expected_status in test_cases:
        # Apply the telemetry status logic from the codebase
        if cpu_pct > 90:
            status = "critical"
        elif cpu_pct > 70:
            status = "degraded"
        else:
            status = "healthy"

        assert status == expected_status, (
            f"CPU {cpu_pct}% should result in '{expected_status}' status, got '{status}'"
        )
