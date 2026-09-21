"""Catalog floor uses Bitrix MIN_PRICE type, not retail/BASE."""

from decimal import Decimal

from app.integrations.bitrix import (
    price_amount_for_catalog_group,
    resolve_catalog_min_price_type_id,
)


def test_resolve_min_price_type_prefers_xml_id():
    types = [
        {"id": 1, "name": "Retail", "xmlId": "BASE", "base": "Y"},
        {"id": 5, "name": "Minimum", "xmlId": "MIN_PRICE", "base": "N"},
    ]
    assert (
        resolve_catalog_min_price_type_id(
            types,
            xml_ids="MIN_PRICE",
            names="Minimum",
        )
        == 5
    )


def test_resolve_min_price_type_falls_back_to_name():
    types = [
        {"id": 1, "name": "BASE", "xmlId": "BASE"},
        {"id": 9, "name": "Min price", "xmlId": "something_else"},
    ]
    assert (
        resolve_catalog_min_price_type_id(
            types,
            xml_ids="MIN_PRICE",
            names="MIN_PRICE,Min price,Minimum",
        )
        == 9
    )


def test_resolve_min_price_type_ignores_retail_base():
    types = [
        {"id": 1, "name": "Retail price", "xmlId": "BASE", "base": "Y"},
    ]
    assert (
        resolve_catalog_min_price_type_id(
            types,
            xml_ids="MIN_PRICE",
            names="MIN_PRICE,Minimum",
        )
        is None
    )


def test_price_amount_uses_only_min_price_group():
    prices = [
        {"catalogGroupId": 1, "price": "9000"},  # retail
        {"catalogGroupId": 5, "price": "6500"},  # MIN_PRICE
        {"catalogGroupId": 5, "price": "6400"},
    ]
    assert price_amount_for_catalog_group(prices, 5) == Decimal("6400")
    assert price_amount_for_catalog_group(prices, 1) == Decimal("9000")
    assert price_amount_for_catalog_group(prices, 99) is None
