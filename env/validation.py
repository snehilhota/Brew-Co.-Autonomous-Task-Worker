from datetime import date, datetime, timedelta
from typing import Any


DATE_FORMAT_ERROR = "Delivery date must be in DD/MM/YYYY format."
WEEKEND_ERROR = "We cannot receive deliveries on Saturday or Sunday."
EMPTY_LINES_ERROR = "Add at least one line with a positive whole quantity."


def validate_delivery_date(
    delivery_date_text: str,
    today: date,
    supplier_name: str,
    lead_time_days: int,
    check_supplier_timing: bool = True,
) -> list[str]:
    """Return V1–V3 delivery-date errors."""
    try:
        parsed_date = datetime.strptime(
            delivery_date_text,
            "%d/%m/%Y",
        ).date()
    except ValueError:
        return [DATE_FORMAT_ERROR]

    if parsed_date.strftime("%d/%m/%Y") != delivery_date_text:
        return [DATE_FORMAT_ERROR]

    if not check_supplier_timing:
        return []

    errors = []
    earliest_date = today + timedelta(days=lead_time_days)

    if parsed_date < earliest_date:
        errors.append(
            f"Earliest delivery from {supplier_name} is "
            f"{earliest_date.strftime('%d/%m/%Y')} "
            f"(lead time {lead_time_days} days)."
        )

    if parsed_date.weekday() >= 5:
        errors.append(WEEKEND_ERROR)

    return errors


def is_positive_whole_quantity(value: object) -> bool:
    """Accept positive integers and digit-only form values such as '12'."""
    if isinstance(value, bool):
        return False

    if isinstance(value, int):
        return value > 0

    if isinstance(value, str) and value.isdigit():
        return int(value) > 0

    return False


def validate_purchase_order(
    delivery_date_text: str,
    today: date,
    supplier: dict[str, Any],
    lines: list[dict[str, Any]],
    order_total: int,
    submit: bool = True,
) -> list[str]:
    """Return the purchase-order validation errors required by the handoff."""
    supplier_name = supplier["name"]

    errors = validate_delivery_date(
        delivery_date_text=delivery_date_text,
        today=today,
        supplier_name=supplier_name,
        lead_time_days=supplier["lead_time_days"],
        check_supplier_timing=submit,
    )

    valid_quantities = [
        is_positive_whole_quantity(line.get("quantity"))
        for line in lines
    ]

    if submit:
        # V4: A quantity must be a whole number of supplier cases.
        for line, quantity_is_valid in zip(lines, valid_quantities):
            case_size = line.get("case_size")

            if quantity_is_valid and case_size is not None:
                quantity = int(line["quantity"])
                if quantity % case_size != 0:
                    errors.append(
                        f"Quantity for {line['item_name']} must be a "
                        f"multiple of {case_size} {line['unit']}."
                    )

        # V5: A supplier on hold cannot receive submitted orders.
        if supplier["status"] == "hold":
            errors.append(
                f"{supplier_name} is on hold: "
                f"{supplier['hold_reason']}. Orders cannot be submitted."
            )

        # V6: The supplier must currently have the item available.
        for line in lines:
            if (
                line.get("case_size") is not None
                and line.get("available") in (False, 0)
            ):
                errors.append(
                    f"{supplier_name} cannot currently supply "
                    f"{line['item_name']} (out of stock)."
                )

        # V7: The total must meet the supplier's minimum order value.
        minimum = supplier["min_order_value"]
        if order_total < minimum:
            errors.append(
                f"Order total ₹{order_total} is below {supplier_name}'s "
                f"minimum order value ₹{minimum}."
            )

        # V8: The supplier must have an offer for every requested item.
        for line in lines:
            if line.get("case_size") is None:
                errors.append(
                    f"{supplier_name} does not sell {line['item_name']}."
                )

    # V9 applies to both drafts and submitted orders.
    if not lines or not all(valid_quantities):
        errors.append(EMPTY_LINES_ERROR)

    return errors