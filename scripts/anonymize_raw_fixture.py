import argparse
import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_INPUT_PATH = PROJECT_ROOT / "data" / "demo" / "raw_document_extractions_raw.jsonl"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "demo" / "raw_document_extractions_demo.jsonl"


DEMO_MERCHANTS = [
    "Demo Burger House",
    "Sample Sushi Bar",
    "Example Grocery Market",
    "Test Pizza Kitchen",
    "Demo Coffee Roasters",
    "Sample Vegan Bowl",
    "Example Späti Market",
    "Demo Indian Kitchen",
]

DEMO_CITIES = [
    "Berlin",
    "Munich",
    "Hamburg",
    "Cologne",
]

DEMO_PAYMENT_METHODS = [
    "card",
    "paypal",
    "apple_pay",
]


# Keep this conservative.
# These are exact normalized key names, not broad substring patterns.
# Do not include generic words like:
# - restaurant
# - merchant
# - venue
# - store
# - name
#
# Because fields like contains_restaurant_food must stay boolean.
SENSITIVE_KEY_PATTERNS = {
    "merchant": [
        "merchant_name",
        "merchant_legal_name",
        "venue_name",
        "restaurant_name",
        "store_name",
        "shop_name",
        "vendor_name",
        "seller_name",
        "business_name",
        "legal_name",
    ],
    "order_id": [
        "order_id",
        "orderid",
        "order_number",
        "order_reference",
        "food_delivery_order_key",
        "natural_order_key",
        "transaction_id",
        "payment_id",
        "invoice_id",
        "receipt_id",
        "document_number",
    ],
    "person": [
        "customer_name",
        "user_name",
        "full_name",
        "first_name",
        "last_name",
    ],
    "address": [
        "address",
        "street",
        "house_number",
        "postcode",
        "postal_code",
        "zip",
        "delivery_address",
        "billing_address",
    ],
    "email": [
        "email",
        "mail",
    ],
    "phone": [
        "phone",
        "mobile",
        "telephone",
    ],
    "path": [
        "path",
        "file_path",
        "pdf_path",
        "extraction_file_path",
    ],
    "file_name": [
        "file_name",
        "filename",
        "pdf_file_name",
        "extraction_file_name",
    ],
    "hash": [
        "hash",
        "pdf_hash",
        "json_hash",
    ],
    "city": [
        "residence_city",
        "delivery_city",
    ],
    "payment": [
        "payment_method",
    ],
}


def stable_int(value: str, modulo: int) -> int:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return int(digest[:12], 16) % modulo


def normalize_key(key: str) -> str:
    return key.lower().replace("-", "_").replace(" ", "_")


def key_matches(key: str, patterns: list[str]) -> bool:
    """
    Exact key matching only.

    This prevents fields like contains_restaurant_food from matching
    restaurant/merchant anonymization rules.
    """
    normalized = normalize_key(key)
    return normalized in patterns


def anonymized_hash(value: Any, prefix: str = "demo_hash") -> str:
    raw = str(value)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def is_boolean_like_key(key: str) -> bool:
    normalized_key = normalize_key(key)

    return (
        normalized_key.startswith("contains_")
        or normalized_key.startswith("is_")
        or normalized_key.startswith("has_")
        or normalized_key.endswith("_flag")
    )


def anonymize_scalar(key: str, value: Any, row_index: int) -> Any:
    if value is None:
        return None

    normalized_key = normalize_key(key)

    # Preserve booleans. dbt models rely on these staying boolean.
    if isinstance(value, bool):
        return value

    # Preserve numbers. dbt models rely on amounts, indexes, rates, and counts
    # keeping their original numeric types.
    if isinstance(value, (int, float)):
        return value

    # Preserve business logic flags even if they are stored as strings.
    # Example: contains_restaurant_food should not become "Sample Vegan Bowl".
    if is_boolean_like_key(normalized_key):
        return value

    if key_matches(normalized_key, SENSITIVE_KEY_PATTERNS["merchant"]):
        return DEMO_MERCHANTS[stable_int(str(value), len(DEMO_MERCHANTS))]

    if key_matches(normalized_key, SENSITIVE_KEY_PATTERNS["order_id"]):
        return f"DEMO-ORDER-{row_index + 1:04d}"

    if key_matches(normalized_key, SENSITIVE_KEY_PATTERNS["person"]):
        return "Demo Customer"

    if key_matches(normalized_key, SENSITIVE_KEY_PATTERNS["address"]):
        return "Demo Street 1"

    if key_matches(normalized_key, SENSITIVE_KEY_PATTERNS["email"]):
        return f"demo.customer.{row_index + 1}@example.com"

    if key_matches(normalized_key, SENSITIVE_KEY_PATTERNS["phone"]):
        return "+49 000 000000"

    if key_matches(normalized_key, SENSITIVE_KEY_PATTERNS["path"]):
        return f"data/demo/documents/demo_document_{row_index + 1:04d}.pdf"

    if key_matches(normalized_key, SENSITIVE_KEY_PATTERNS["file_name"]):
        return f"demo_document_{row_index + 1:04d}.pdf"

    if key_matches(normalized_key, SENSITIVE_KEY_PATTERNS["hash"]):
        return anonymized_hash(value)

    if key_matches(normalized_key, SENSITIVE_KEY_PATTERNS["city"]):
        return DEMO_CITIES[stable_int(str(value), len(DEMO_CITIES))]

    if key_matches(normalized_key, SENSITIVE_KEY_PATTERNS["payment"]):
        return DEMO_PAYMENT_METHODS[stable_int(str(value), len(DEMO_PAYMENT_METHODS))]

    if isinstance(value, str):
        return anonymize_text_value(value, row_index)

    return value


def anonymize_text_value(value: str, row_index: int) -> str:
    """
    Conservative text anonymization.

    This only replaces obvious sensitive patterns inside free text:
    - emails
    - phone-like values
    - long hashes
    - explicit order/invoice/receipt/transaction identifiers

    It does not replace normal business categories or component names.
    """
    anonymized = value

    anonymized = re.sub(
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        f"demo.customer.{row_index + 1}@example.com",
        anonymized,
    )

    anonymized = re.sub(
        r"\+?\d[\d\s().-]{7,}\d",
        "+49 000 000000",
        anonymized,
    )

    anonymized = re.sub(
        r"\b[A-Fa-f0-9]{24,64}\b",
        lambda match: anonymized_hash(match.group(0)),
        anonymized,
    )

    anonymized = re.sub(
        r"\b(?:order|invoice|receipt|transaction)[-_:\s]*[A-Za-z0-9-]+\b",
        f"DEMO-ORDER-{row_index + 1:04d}",
        anonymized,
        flags=re.IGNORECASE,
    )

    return anonymized


def anonymize_nested(value: Any, row_index: int, parent_key: str = "") -> Any:
    if isinstance(value, dict):
        return {
            key: anonymize_nested(child_value, row_index, key)
            for key, child_value in value.items()
        }

    if isinstance(value, list):
        return [
            anonymize_nested(item, row_index, parent_key)
            for item in value
        ]

    return anonymize_scalar(parent_key, value, row_index)


def anonymize_record(record: dict[str, Any], row_index: int) -> dict[str, Any]:
    anonymized = deepcopy(record)

    anonymized["document_id"] = f"demo_document_{row_index + 1:04d}"
    anonymized["run_id"] = "demo_run"
    anonymized["pdf_hash"] = anonymized_hash(
        record.get("pdf_hash", row_index),
        "demo_pdf_hash",
    )
    anonymized["json_hash"] = anonymized_hash(
        record.get("json_hash", row_index),
        "demo_json_hash",
    )
    anonymized["pdf_file_name"] = f"demo_document_{row_index + 1:04d}.pdf"
    anonymized["pdf_path"] = f"data/demo/documents/demo_document_{row_index + 1:04d}.pdf"
    anonymized["extraction_file_name"] = f"demo_document_{row_index + 1:04d}.json"
    anonymized["extraction_file_path"] = (
        f"data/demo/extractions/demo_document_{row_index + 1:04d}.json"
    )

    raw_json = anonymized.get("raw_json")

    if isinstance(raw_json, str):
        try:
            raw_json = json.loads(raw_json)
        except json.JSONDecodeError:
            raw_json = {"raw_text": raw_json}

    anonymized["raw_json"] = anonymize_nested(raw_json, row_index)

    return anonymized


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Anonymize a raw DuckDB extraction fixture into a safe demo fixture."
    )
    parser.add_argument(
        "--input-path",
        default=str(DEFAULT_INPUT_PATH),
        help="Path to private raw fixture JSONL.",
    )
    parser.add_argument(
        "--output-path",
        default=str(DEFAULT_OUTPUT_PATH),
        help="Path to anonymized demo fixture JSONL.",
    )
    args = parser.parse_args()

    input_path = Path(args.input_path)
    output_path = Path(args.output_path)

    if not input_path.exists():
        raise FileNotFoundError(
            f"Private raw fixture not found: {input_path}. "
            "Run scripts/export_raw_fixture.py first."
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    row_count = 0

    with input_path.open("r", encoding="utf-8") as input_file, output_path.open(
        "w", encoding="utf-8"
    ) as output_file:
        for row_index, line in enumerate(input_file):
            if not line.strip():
                continue

            record = json.loads(line)
            anonymized_record = anonymize_record(record, row_index)

            output_file.write(
                json.dumps(anonymized_record, ensure_ascii=False) + "\n"
            )

            row_count += 1

    print(f"Anonymized {row_count} rows")
    print(f"Safe demo fixture written to: {output_path}")


if __name__ == "__main__":
    main()