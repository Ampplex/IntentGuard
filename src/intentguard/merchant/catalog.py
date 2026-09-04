"""A small catalog for the merchant to quote from.

Deliberately boring. The catalog exists so the merchant has something real to
offer and something real to substitute; it is not the interesting part of the
project and should not grow into one.
"""

from __future__ import annotations

from pydantic import Field

from ..core.base import StrictModel
from ..core.enums import Category, Condition
from ..core.money import from_rupees


class CatalogItem(StrictModel):
    product_id: str
    title: str
    category: Category
    condition: Condition
    price_paise: int = Field(ge=0)
    brand: str | None = None
    colour: str | None = None
    materials: tuple[str, ...] = ()


CATALOG: tuple[CatalogItem, ...] = (
    CatalogItem(
        product_id="sku_shoe_01",
        title="Asics Gel-Contend 9",
        category=Category.FOOTWEAR,
        condition=Condition.NEW,
        price_paise=from_rupees(4200),
        brand="Asics",
        colour="blue",
        materials=("mesh", "rubber"),
    ),
    CatalogItem(
        product_id="sku_shoe_02",
        title="Nike Revolution 7",
        category=Category.FOOTWEAR,
        condition=Condition.NEW,
        price_paise=from_rupees(4100),
        brand="Nike",
        colour="black",
        materials=("mesh",),
    ),
    CatalogItem(
        product_id="sku_shoe_03",
        title="Leather Chelsea Boots",
        category=Category.FOOTWEAR,
        condition=Condition.NEW,
        price_paise=from_rupees(5200),
        brand="Clarks",
        colour="brown",
        materials=("leather",),
    ),
    CatalogItem(
        product_id="sku_lap_01",
        title="Lenovo IdeaPad Slim 3",
        category=Category.ELECTRONICS,
        condition=Condition.NEW,
        price_paise=from_rupees(43000),
        brand="Lenovo",
    ),
    CatalogItem(
        product_id="sku_lap_02",
        title="ThinkPad T480",
        category=Category.ELECTRONICS,
        condition=Condition.REFURBISHED,
        price_paise=from_rupees(37500),
        brand="Lenovo",
    ),
    CatalogItem(
        product_id="sku_aud_01",
        title="boAt Airdopes 141",
        category=Category.ELECTRONICS,
        condition=Condition.NEW,
        price_paise=from_rupees(2999),
        brand="boAt",
    ),
    CatalogItem(
        product_id="sku_bok_01",
        title="Midnight's Children",
        category=Category.BOOKS,
        condition=Condition.NEW,
        price_paise=from_rupees(349),
    ),
    CatalogItem(
        product_id="sku_bok_02",
        title="Ruled Notebook",
        category=Category.BOOKS,
        condition=Condition.NEW,
        price_paise=from_rupees(120),
    ),
    CatalogItem(
        product_id="sku_app_01",
        title="Cotton T-Shirt",
        category=Category.APPAREL,
        condition=Condition.NEW,
        price_paise=from_rupees(700),
        colour="white",
        materials=("cotton",),
    ),
    CatalogItem(
        product_id="sku_hom_01",
        title="Electric Kettle",
        category=Category.HOME_KITCHEN,
        condition=Condition.NEW,
        price_paise=from_rupees(1800),
        brand="Prestige",
    ),
    CatalogItem(
        product_id="sku_spo_01",
        title="Cork Yoga Mat",
        category=Category.SPORTS,
        condition=Condition.NEW,
        price_paise=from_rupees(1150),
        materials=("cork",),
    ),
    CatalogItem(
        product_id="sku_bea_01",
        title="Vitamin C Serum",
        category=Category.BEAUTY,
        condition=Condition.NEW,
        price_paise=from_rupees(1100),
    ),
    CatalogItem(
        product_id="sku_acc_01",
        title="Laptop Backpack",
        category=Category.ACCESSORIES,
        condition=Condition.NEW,
        price_paise=from_rupees(2800),
        materials=("polyester",),
    ),
    CatalogItem(
        product_id="sku_gro_01",
        title="Whey Protein Isolate",
        category=Category.GROCERY,
        condition=Condition.NEW,
        price_paise=from_rupees(2700),
        materials=("whey",),
    ),
    CatalogItem(
        product_id="sku_toy_01",
        title="Wooden Chess Set",
        category=Category.TOYS,
        condition=Condition.NEW,
        price_paise=from_rupees(2500),
        materials=("wood",),
    ),
)


def matching(view) -> list[CatalogItem]:
    """Everything in the catalog that fits the view, cheapest first.

    Note what is not consulted: there is no ceiling to filter against, because
    the merchant was never told one.
    """
    found = [item for item in CATALOG if item.category is view.category]
    if view.condition is not None:
        found = [item for item in found if item.condition is view.condition]
    if view.product_ref:
        wanted = view.product_ref.strip().lower()
        exact = [i for i in found if wanted in (i.title.lower(), i.product_id.lower())]
        if exact:
            return exact
    return sorted(found, key=lambda item: item.price_paise)
