"""Authors the substitution calibration set.

CLAUDE.md's stage 7 gate says the gold substitution cases should be classified
correctly. SPEC-DECISIONS.md holds gold out until the final run and wins on
contradiction, so the threshold is derived here instead, on pairs written for
the purpose. Gold stays untouched.

SAME means two descriptions of one product: a different listing, a punctuation
difference, a year suffix, a retailer's extra words. DIFFERENT means the thing
being sold changed, including the cases that differ by one character, because a
model number is not decoration.

Imports nothing from intentguard, like every other dataset here.
"""

from __future__ import annotations

import json
from pathlib import Path

PAIRS: list[dict] = []


def pair(negotiated: str, delivered: str, verdict: str, why: str) -> None:
    assert verdict in {"SAME", "DIFFERENT"}
    PAIRS.append({"negotiated": negotiated, "delivered": delivered, "verdict": verdict, "why": why})


# --- the same product, described differently -------------------------------
pair("Asics Gel-Contend 9", "Asics Gel Contend 9", "SAME", "hyphen only")
pair("Asics Gel-Contend 9", "ASICS GEL-CONTEND 9", "SAME", "case only")
pair("Asics Gel-Contend 9", "Asics Gel-Contend 9 (2024)", "SAME", "year suffix on the listing")
pair("Lenovo IdeaPad Slim 3", "Lenovo IdeaPad Slim 3 laptop", "SAME", "retailer adds a noun")
pair("Electric Kettle", "Electric Kettle, stainless steel", "SAME", "material described")
pair("boAt Airdopes 141", "boAt Airdopes 141 Bluetooth earbuds", "SAME", "category words added")
pair("Cotton T-Shirt", "Cotton T Shirt", "SAME", "spacing only")
pair("Midnight's Children", "Midnight's Children by Salman Rushdie", "SAME", "author appended")
pair("Cork Yoga Mat", "Yoga Mat, Cork", "SAME", "word order")
pair("Vitamin C Serum", "Vitamin C Face Serum", "SAME", "one clarifying word")
pair("Laptop Backpack", "Laptop Backpack 25L", "SAME", "capacity on the same bag")
pair("Wooden Chess Set", "Wooden Chess Set - Handcrafted", "SAME", "marketing suffix")

# --- a different product ---------------------------------------------------
pair("Asics Gel-Contend 9", "Nike Revolution 7", "DIFFERENT", "different brand and model")
pair("Lenovo IdeaPad Slim 3", "HP 15s", "DIFFERENT", "different make entirely")
pair("Midnight's Children", "The Satanic Verses", "DIFFERENT", "same author, different book")
pair(
    "Sony WH-1000XM5",
    "Sony WH-1000XM4",
    "DIFFERENT",
    "one character apart and a different generation; the hard case for any lexical scorer",
)
pair(
    "Electric Kettle",
    "Electric Kettle 1.5L Pro",
    "DIFFERENT",
    "a different model in the same line, which is a different SKU and a different price",
)
pair("Asics Gel-Contend 9", "Asics Gel-Kayano 30", "DIFFERENT", "same brand, different shoe")
pair("Cork Yoga Mat", "PVC Yoga Mat", "DIFFERENT", "different material is a different product")
pair("Cotton T-Shirt", "Polyester T-Shirt", "DIFFERENT", "different fabric")
pair("boAt Airdopes 141", "boAt Rockerz 255", "DIFFERENT", "different line from one brand")
pair("Laptop Backpack", "Leather Messenger Bag", "DIFFERENT", "different article")
pair("Wooden Chess Set", "Magnetic Travel Chess", "DIFFERENT", "different object")
pair("Vitamin C Serum", "Retinol Serum", "DIFFERENT", "different active ingredient")

if __name__ == "__main__":
    out = Path(__file__).parent / "substitutions.json"
    out.write_text(json.dumps(PAIRS, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    same = sum(1 for p in PAIRS if p["verdict"] == "SAME")
    print(f"wrote {len(PAIRS)} pairs: {same} same, {len(PAIRS) - same} different")
