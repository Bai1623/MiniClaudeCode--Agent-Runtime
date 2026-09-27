"""Small pricing helpers."""


def subtotal(prices: list[float]) -> float:
    return sum(prices)


def total_with_tax(prices: list[float], tax_rate: float) -> float:
    base = subtotal(prices)
    tax = round(base * tax_rate)
    return base + tax
