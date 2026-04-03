import json
import unittest
import os

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from backend.services import query_router
from backend.services.routing_schema import (
    normalize_classification_payload,
    normalize_odoo_query_type,
    normalize_source_hint,
)


class _FakeMessage:
    def __init__(self, content: str):
        self.content = content


class _FakeChoice:
    def __init__(self, content: str):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, payload: dict):
        self.choices = [_FakeChoice(json.dumps(payload))]


ODOO_QUERY_TYPE_GOLDENS = [
    ("vendors", "vendors"),
    ("vendor", "vendors"),
    ("suppliers", "vendors"),
    ("supplier", "vendors"),
    ("VENDOR", "vendors"),
    ("Supplier", "vendors"),
    ("products", "products"),
    ("product", "products"),
    ("items", "products"),
    ("item", "products"),
    ("catalog", "products"),
    ("PRODUCTS", "products"),
    ("Item", "products"),
    ("purchase_orders", "purchase_orders"),
    ("purchase_order", "purchase_orders"),
    ("po", "purchase_orders"),
    ("view_po", "purchase_orders"),
    ("view_purchase_orders", "purchase_orders"),
    ("list", "purchase_orders"),
    ("read", "purchase_orders"),
    ("fetch", "purchase_orders"),
    ("retrieve", "purchase_orders"),
    ("data", "purchase_orders"),
    ("orders", "purchase_orders"),
    ("current_orders", "purchase_orders"),
    ("", "purchase_orders"),
    ("unknown", "purchase_orders"),
    ("inventory", "purchase_orders"),
    ("status", "purchase_orders"),
    ("purchase", "purchase_orders"),
    ("show products", "purchase_orders"),
    ("show vendors", "purchase_orders"),
    ("po_list", "purchase_orders"),
    ("purchaseorder", "purchase_orders"),
    ("supplier_list", "purchase_orders"),
    ("item_catalog", "purchase_orders"),
    ("vendors_data", "purchase_orders"),
    ("products_data", "purchase_orders"),
    ("all", "purchase_orders"),
    ("everything", "purchase_orders"),
    ("records", "purchase_orders"),
    ("purchases", "purchase_orders"),
    ("order_lines", "purchase_orders"),
    ("latest", "purchase_orders"),
    ("history", "purchase_orders"),
]


class TestRoutingIntelligence(unittest.TestCase):
    def test_normalize_odoo_query_type_golden_aliases(self):
        for raw, expected in ODOO_QUERY_TYPE_GOLDENS:
            self.assertEqual(normalize_odoo_query_type(raw), expected)

    def test_normalize_classification_payload_contract(self):
        cases = [
            ({"data_source": "odoo", "query_type": "vendor", "filters": {}, "confidence": 0.9}, "odoo", "vendors", {}, 0.9),
            ({"data_source": "ODOO", "query_type": "product", "filters": {"search": "laptop"}, "confidence": "0.8"}, "odoo", "products", {"search": "laptop"}, 0.8),
            ({"data_source": "agentic", "query_type": "BUDGET", "filters": None, "confidence": 2}, "agentic", "BUDGET", {}, 1.0),
            ({"data_source": "budget", "query_type": "status", "filters": {}, "confidence": -1}, "budget_tracking", "status", {}, 0.0),
            ({"data_source": None, "query_type": None, "filters": "bad", "confidence": "bad"}, "general", "GENERAL", {}, 0.5),
            ({}, "general", "GENERAL", {}, 0.5),
        ]

        for payload, expected_source, expected_query_type, expected_filters, expected_conf in cases:
            normalized = normalize_classification_payload(payload)
            self.assertEqual(normalized["data_source"], expected_source)
            self.assertEqual(normalized["query_type"], expected_query_type)
            self.assertEqual(normalized["filters"], expected_filters)
            self.assertEqual(normalized["confidence"], expected_conf)

    def test_normalize_source_hint(self):
        cases = [
            ("odoo", "odoo"),
            ("Odoo Service", "odoo"),
            ("agentic", "agentic"),
            ("agent orchestration", "agentic"),
            ("budget", "budget_tracking"),
            ("approval", "approval_chains"),
            ("unknown", "unknown"),
        ]

        for hint, expected in cases:
            self.assertEqual(normalize_source_hint(hint), expected)

    def test_classify_query_intent_applies_odoo_refinement(self):
        calls = {"n": 0}
        original_create = query_router.client.chat.completions.create

        def fake_create(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return _FakeResponse(
                    {
                        "data_source": "odoo",
                        "query_type": "retrieve",
                        "filters": {},
                        "confidence": 0.88,
                    }
                )
            return _FakeResponse({"query_type": "products", "filters": {"search": "laptop"}})

        try:
            query_router.client.chat.completions.create = fake_create
            result = query_router.classify_query_intent("list products")
        finally:
            query_router.client.chat.completions.create = original_create

        self.assertEqual(result["data_source"], "odoo")
        self.assertEqual(result["query_type"], "products")
        self.assertEqual(result["filters"], {"search": "laptop"})
        self.assertEqual(result["confidence"], 0.88)

    def test_followup_llm_resolver_uses_previous_context(self):
        original_create = query_router.client.chat.completions.create

        def fake_create(*args, **kwargs):
            return _FakeResponse(
                {
                    "use_previous_context": True,
                    "data_source": "odoo",
                    "query_type": "vendors",
                    "confidence": 0.92,
                }
            )

        classification = {
            "data_source": "general",
            "query_type": "GENERAL",
            "filters": {},
            "confidence": 0.4,
        }
        pr_data = {"_prev_data_source": "odoo", "_prev_query_type": "vendors"}

        try:
            query_router.client.chat.completions.create = fake_create
            updated = query_router.resolve_followup_context_with_llm("show those again", classification, pr_data)
        finally:
            query_router.client.chat.completions.create = original_create

        self.assertEqual(updated["data_source"], "odoo")
        self.assertEqual(updated["query_type"], "vendors")
        self.assertGreaterEqual(updated["confidence"], 0.92)

    def test_followup_llm_resolver_keeps_current_when_low_confidence(self):
        original_create = query_router.client.chat.completions.create

        def fake_create(*args, **kwargs):
            return _FakeResponse(
                {
                    "use_previous_context": True,
                    "data_source": "odoo",
                    "query_type": "purchase_orders",
                    "confidence": 0.4,
                }
            )

        classification = {
            "data_source": "agentic",
            "query_type": "BUDGET",
            "filters": {},
            "confidence": 0.85,
        }
        pr_data = {"_prev_data_source": "odoo", "_prev_query_type": "purchase_orders"}

        try:
            query_router.client.chat.completions.create = fake_create
            updated = query_router.resolve_followup_context_with_llm("new budget check", classification, pr_data)
        finally:
            query_router.client.chat.completions.create = original_create

        self.assertEqual(updated, classification)


if __name__ == "__main__":
    unittest.main()
