"""Locally confirmed game product mappings."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProductSpec:
    product_id: str
    price: int
    quantity: int
    title: str
    description: str
    first_purchase_bonus: int


PRODUCTS_BY_AMOUNT: dict[int, ProductSpec] = {
    60: ProductSpec("4000001", 60, 20, "光棱20", "钻石20", 20),
    300: ProductSpec("4000002", 300, 110, "光棱110", "钻石110", 110),
    1980: ProductSpec("4000003", 1980, 780, "光棱780", "钻石780", 780),
    3280: ProductSpec("4000004", 3280, 1400, "光棱1400", "钻石1400", 1400),
    6480: ProductSpec("4000005", 6480, 2900, "光棱2900", "钻石2900", 2900),
    12800: ProductSpec("4000006", 12800, 6000, "光棱6000", "钻石6000", 6000),
}


def resolve_product(amount: object) -> ProductSpec | None:
    """Resolve the APK's G-point amount to a confirmed product."""
    try:
        price = int(str(amount).strip())
    except (TypeError, ValueError):
        return None
    return PRODUCTS_BY_AMOUNT.get(price)


def resolve_game_product(goods_id: object, amount: object) -> ProductSpec | None:
    """Resolve a game order only when its goods id matches the known catalog.

    The six product ids are confirmed by the local payment analysis.  A game
    order is never resolved by price alone; callers must supply the goods id
    observed in CSOrderNoReq(377).
    """
    product = resolve_product(amount)
    if product is None:
        return None
    try:
        normalized_goods_id = int(str(goods_id).strip())
    except (TypeError, ValueError):
        return None
    return product if normalized_goods_id == int(product.product_id) else None


def resolve_product_by_goods_id(goods_id: object) -> ProductSpec | None:
    try:
        normalized_goods_id = int(str(goods_id).strip())
    except (TypeError, ValueError):
        return None
    for product in PRODUCTS_BY_AMOUNT.values():
        if normalized_goods_id == int(product.product_id):
            return product
    return None
