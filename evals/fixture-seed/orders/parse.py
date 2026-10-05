"""Parses an order CSV with the header sku,quantity,unit_price and no blank lines."""

import csv
import io
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class Line:
    sku: str
    quantity: int
    unit_price: Decimal


class InvalidOrders(ValueError):
    """Raised with every bad line's number, counting the header as line 1."""

    def __init__(self, line_numbers: list[int]) -> None:
        self.line_numbers = line_numbers
        super().__init__("invalid lines: " + ", ".join(map(str, line_numbers)))


def parse_orders(text: str) -> list[Line]:
    lines, bad = [], []
    for number, row in enumerate(csv.DictReader(io.StringIO(text)), start=2):
        try:
            lines.append(
                Line(row["sku"].strip(), int(row["quantity"]), Decimal(row["unit_price"]))
            )
        except (ValueError, InvalidOperation, TypeError, AttributeError):
            bad.append(number)
    if bad:
        raise InvalidOrders(bad)
    return lines
