"""A plain text summary of an order."""

from decimal import Decimal

from orders.parse import Line


def summary(lines: list[Line]) -> str:
    """One row per line, then the total before GST. Prices each line itself."""
    rows, total = [], Decimal(0)
    for line in lines:
        amount = line.quantity * line.unit_price
        rows.append(f"{line.sku} x{line.quantity} {amount:.2f}")
        total += amount
    rows.append(f"TOTAL {total:.2f}")
    return "\n".join(rows)
