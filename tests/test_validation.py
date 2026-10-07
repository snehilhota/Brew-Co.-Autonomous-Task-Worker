from datetime import date

from env.validation import (
    validate_delivery_date,
    validate_purchase_order,
)


TODAY = date(2026, 10, 5)

ACTIVE_SUPPLIER = {
    "name": "FreshFarm",
    "status": "active",
    "hold_reason": None,
    "lead_time_days": 1,
    "min_order_value": 0,
}

VALID_LINE = {
    "item_name": "Whole milk",
    "unit": "L",
    "quantity": 12,
    "case_size": 12,
    "available": 1,
}


def validate(lines=None, supplier=None, total=0, submit=True, delivery="06/10/2026"):
    return validate_purchase_order(
        delivery_date_text=delivery,
        today=TODAY,
        supplier=supplier or ACTIVE_SUPPLIER,
        lines=lines if lines is not None else [VALID_LINE],
        order_total=total,
        submit=submit,
    )


def test_v1_rejects_iso_date_format():
    errors = validate_delivery_date(
        "2026-10-06", TODAY, "FreshFarm", 1
    )

    assert errors == ["Delivery date must be in DD/MM/YYYY format."]


def test_v2_rejects_delivery_before_lead_time():
    errors = validate_delivery_date(
        "06/10/2026", TODAY, "GreenLeaf", 2
    )

    assert errors == [
        "Earliest delivery from GreenLeaf is 07/10/2026 "
        "(lead time 2 days)."
    ]


def test_v3_rejects_weekend_delivery():
    errors = validate_delivery_date(
        "10/10/2026", TODAY, "FreshFarm", 1
    )

    assert errors == [
        "We cannot receive deliveries on Saturday or Sunday."
    ]


def test_v4_requires_quantity_to_be_case_multiple():
    line = {**VALID_LINE, "quantity": 6, "case_size": 4}

    assert validate(lines=[line]) == [
        "Quantity for Whole milk must be a multiple of 4 L."
    ]


def test_v5_rejects_supplier_on_hold():
    supplier = {
        **ACTIVE_SUPPLIER,
        "name": "BeanBros",
        "status": "hold",
        "hold_reason": "Unpaid invoice INV-2291",
    }

    assert validate(supplier=supplier) == [
        "BeanBros is on hold: Unpaid invoice INV-2291. "
        "Orders cannot be submitted."
    ]


def test_v6_rejects_unavailable_supplier_item():
    line = {**VALID_LINE, "available": 0}

    assert validate(lines=[line]) == [
        "FreshFarm cannot currently supply Whole milk (out of stock)."
    ]


def test_v7_requires_supplier_minimum_order_value():
    supplier = {**ACTIVE_SUPPLIER, "min_order_value": 1500}

    assert validate(supplier=supplier, total=1000) == [
        "Order total ₹1000 is below FreshFarm's minimum order value ₹1500."
    ]


def test_v8_rejects_item_not_sold_by_supplier():
    line = {**VALID_LINE, "case_size": None, "available": None}

    assert validate(lines=[line]) == [
        "FreshFarm does not sell Whole milk."
    ]


def test_v9_requires_at_least_one_line():
    assert validate(lines=[]) == [
        "Add at least one line with a positive whole quantity."
    ]


def test_v9_requires_positive_whole_quantity():
    line = {**VALID_LINE, "quantity": 0}

    assert validate(lines=[line]) == [
        "Add at least one line with a positive whole quantity."
    ]


def test_draft_checks_v1_and_v9_but_skips_submit_rules():
    supplier = {
        **ACTIVE_SUPPLIER,
        "status": "hold",
        "hold_reason": "Unpaid invoice",
        "min_order_value": 5000,
    }
    line = {**VALID_LINE, "available": 0}

    errors = validate(
        lines=[line],
        supplier=supplier,
        total=0,
        submit=False,
        delivery="10/10/2026",
    )

    assert errors == []