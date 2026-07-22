import pytest

from app.core.hostname_validation import validate_fqdn


@pytest.mark.parametrize(
    "value,expected",
    [
        ("circuitbreaker.example.com", "circuitbreaker.example.com"),
        ("CircuitBreaker.Example.COM", "circuitbreaker.example.com"),
        ("  cb.example.com  ", "cb.example.com"),
        ("a.b.c.example.com", "a.b.c.example.com"),
        ("xn--80akhbyknj4f.example.com", "xn--80akhbyknj4f.example.com"),
    ],
)
def test_validate_fqdn_accepts_valid_hostnames(value, expected):
    assert validate_fqdn(value) == expected


def test_validate_fqdn_accepts_max_length_label():
    label = "a" * 63
    value = f"{label}.example.com"
    assert validate_fqdn(value) == value


def test_validate_fqdn_rejects_label_over_63_chars():
    label = "a" * 64
    with pytest.raises(ValueError, match="Invalid domain label"):
        validate_fqdn(f"{label}.example.com")


def test_validate_fqdn_rejects_total_length_over_253():
    value = ".".join(["a" * 50] * 5) + ".com"
    assert len(value) > 253
    with pytest.raises(ValueError, match="253 characters"):
        validate_fqdn(value)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "no-dot",
        "-leadinghyphen.example.com",
        "trailinghyphen-.example.com",
        "under_score.example.com",
        "has space.example.com",
        "circuitbreaker.local.",  # trailing dot creates an empty label
    ],
)
def test_validate_fqdn_rejects_invalid_syntax(value):
    with pytest.raises(ValueError):
        validate_fqdn(value)


@pytest.mark.parametrize(
    "value",
    [
        "127.0.0.1",
        "192.168.1.10",
        "::1",
        "2001:db8::1",
    ],
)
def test_validate_fqdn_rejects_ip_literals(value):
    with pytest.raises(ValueError, match="IP address literal"):
        validate_fqdn(value)


@pytest.mark.parametrize("value", ["localhost", "foo.localhost"])
def test_validate_fqdn_rejects_localhost(value):
    with pytest.raises(ValueError, match="localhost"):
        validate_fqdn(value)
