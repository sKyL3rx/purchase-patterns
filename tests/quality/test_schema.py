from purchase_patterns.quality.schema import (
    EXCLUSION_CODES,
    NON_PRODUCT_STOCK_CODES,
    RULE_VERSION,
    is_non_product_stock_code,
)


def test_rule_version():
    assert RULE_VERSION == "quality_v1"


def test_exclusion_codes_include_planned_set():
    assert "not_canonical" in EXCLUSION_CODES
    assert "cancellation" in EXCLUSION_CODES
    assert "missing_customer_id" in EXCLUSION_CODES
    assert "non_product_stock_code" in EXCLUSION_CODES
    assert "ambiguous_cancellation" in EXCLUSION_CODES


def test_is_non_product_stock_code():
    assert is_non_product_stock_code("POST")
    assert is_non_product_stock_code("m")
    assert is_non_product_stock_code("GIFT_0001_10")
    assert is_non_product_stock_code("TEST001")
    assert is_non_product_stock_code("DCGS0058")
    assert not is_non_product_stock_code("85123A")
    assert not is_non_product_stock_code(None)
    assert "BANK CHARGES" in NON_PRODUCT_STOCK_CODES
