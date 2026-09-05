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


from .search import DenseRetriever, distinctive, search  # noqa: E402  (after CatalogItem)

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


def search_names_a_product(query: str, category_value: str | None) -> bool:
    """Did the query name a product, as opposed to a kind of thing?

    Only a named product earns an empty answer. "running shoes" names a kind,
    and the merchant is right to offer what it has in that category.
    """
    return bool(distinctive(query, category_value))


def matching_detail(view, dense: DenseRetriever | None = None) -> tuple[list[CatalogItem], bool]:
    """What the catalog offers for a view, and whether retrieval is sure of it.

    The flag is the difference between a hit that shares a distinctive word with
    the query and one only the embedding arm reached. Both are worth returning;
    only the first is worth acting on without asking.
    """
    items = matching(view, dense=dense)
    if not view.product_ref or not items:
        return items, True
    category_value = view.category.value if view.category else None
    hits = search(view.product_ref, items, category_value=category_value, dense=dense)
    if not hits:
        # The reference named a kind of thing, so the category listing stands.
        return items, True
    return items, any(hit.grounded for hit in hits)


def matching(view, dense: DenseRetriever | None = None) -> list[CatalogItem]:
    """Everything in the catalog that fits the view, cheapest first.

    Note what is not consulted: there is no ceiling to filter against, because
    the merchant was never told one.

    Where the view names a product, hybrid retrieval answers instead of an exact
    title match, and is allowed to answer with nothing. That last part is the
    change that matters: the previous lookup fell through to "cheapest in the
    category" on a miss, so a request for a MacBook was answered with earbuds
    and a request for Chelsea Boots with a different shoe. A merchant that
    cannot say "we do not stock that" will always say something else instead.
    """
    found = [item for item in CATALOG if item.category is view.category]
    if view.condition is not None:
        found = [item for item in found if item.condition is view.condition]

    if view.product_ref:
        category_value = view.category.value if view.category else None
        hits = search(view.product_ref, found, category_value=category_value, dense=dense)
        grounded = [hit.item for hit in hits if hit.grounded]
        if grounded:
            return grounded
        if hits:
            # Only the dense arm reached these: a paraphrase, not a shared word.
            # Returned so a reranker can confirm or reject them, never acted on
            # by similarity alone.
            return [hit.item for hit in hits]
        if search_names_a_product(view.product_ref, category_value):
            # A named product, and nothing in the catalog answers to it. Offering
            # the cheapest alternative here is the substitution this project
            # exists to catch, performed by the seller's own search.
            return []

    return sorted(found, key=lambda item: item.price_paise)
