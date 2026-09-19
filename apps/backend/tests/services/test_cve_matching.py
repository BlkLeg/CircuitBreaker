from app.services.intelligence.cve_matching import (
    compare_versions,
    evaluate_applicability,
    flatten_applicability,
)


def _configuration(**match):
    return [{"nodes": [{"operator": "OR", "cpeMatch": [match]}]}]


def test_dotted_numeric_comparison_does_not_use_lexical_order():
    assert compare_versions("dotted_numeric", "1.10", "1.9") == 1
    assert compare_versions("dotted_numeric", "1.9", "1.10") == -1
    assert compare_versions("dotted_numeric", "1.9.0", "1.9") == 0
    assert compare_versions("dotted_numeric", "1.9rc1", "1.9") is None


def test_exclusive_upper_bound_is_not_treated_as_inclusive():
    config = _configuration(
        criteria="cpe:2.3:a:acme:widget:*:*:*:*:*:*:*:*",
        vulnerable=True,
        versionStartIncluding="1.9",
        versionEndExcluding="1.10",
    )
    assert (
        evaluate_applicability(
            config,
            {
                "vendor": "acme",
                "product": "widget",
                "version": "1.9",
                "version_scheme": "dotted_numeric",
            },
        ).result
        == "true"
    )
    assert (
        evaluate_applicability(
            config,
            {
                "vendor": "acme",
                "product": "widget",
                "version": "1.10",
                "version_scheme": "dotted_numeric",
            },
        ).result
        == "false"
    )


def test_all_applicability_alternatives_and_escaped_cpe_values_are_retained():
    configurations = [
        {
            "nodes": [
                {
                    "operator": "OR",
                    "cpeMatch": [
                        {
                            "criteria": "cpe:2.3:a:vendor\\:inc:first:*:*:*:*:*:*:*:*",
                            "vulnerable": True,
                        },
                        {
                            "criteria": "cpe:2.3:a:acme:second:*:*:*:*:*:*:*:*",
                            "vulnerable": True,
                        },
                    ],
                }
            ]
        }
    ]
    flattened = flatten_applicability(configurations)
    assert len(flattened) == 2
    assert flattened[0]["vendor"] == "vendor:inc"
    assert flattened[1]["product"] == "second"


def test_unknown_environment_prerequisite_prevents_false_clean_result():
    config = [
        {
            "nodes": [
                {
                    "operator": "AND",
                    "cpeMatch": [
                        {
                            "criteria": "cpe:2.3:a:acme:widget:*:*:*:*:*:*:*:*",
                            "vulnerable": True,
                        },
                        {
                            "criteria": "cpe:2.3:o:other:operating_system:*:*:*:*:*:*:*:*",
                            "vulnerable": False,
                        },
                    ],
                }
            ]
        }
    ]
    result = evaluate_applicability(
        config,
        {
            "vendor": "acme",
            "product": "widget",
            "version": "2.0",
            "version_scheme": "dotted_numeric",
        },
    )
    assert result.result == "unknown"
    assert "environment_prerequisite_unknown" in result.limitations
