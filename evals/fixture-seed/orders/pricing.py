"""Prices lines. Ten or more of one SKU takes 5 percent off. GST is 10 percent."""

from decimal import ROUND_HALF_UP, Decimal

from orders.parse import Line

GST = Decimal("0.10")
BULK_QUANTITY = 10
BULK_DISCOUNT = Decimal("0.05")
CENT = Decimal("0.01")


def line_total(line: Line) -> Decimal:
    """The line's total before GST, after any bulk discount, not rounded."""
    total = line.quantity * line.unit_price
    if line.quantity >= BULK_QUANTITY:
        total -= total * BULK_DISCOUNT
    return total


def order_total(lines: list[Line]) -> Decimal:
    """The order's total including GST, rounded to the cent once, on the whole order."""
    before_gst = sum((line_total(line) for line in lines), Decimal(0))
    return (before_gst * (1 + GST)).quantize(CENT, rounding=ROUND_HALF_UP)
