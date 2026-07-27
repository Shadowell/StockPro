import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.endpoints import review


class ReviewApiContractTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(review.router, prefix="/review")
        self.client = TestClient(app)
        self.patch = patch.object(review, "service")
        self.service = self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_dates_endpoint_returns_total(self):
        self.service.available_dates.return_value = ["2025-01-02"]
        self.assertEqual(self.client.get("/review/dates").json()["total"], 1)

    def test_list_endpoint_returns_reviews(self):
        self.service.list_reviews.return_value = [{"id": "review-1"}]
        self.assertEqual(self.client.get("/review").json()["total"], 1)

    def test_context_endpoint_uses_trade_date(self):
        self.service.context.return_value = {"trade_date": "2025-01-02", "items": []}
        self.client.get("/review/2025-01-02")
        self.service.context.assert_called_once_with("2025-01-02")

    def test_assemble_persists_timeline(self):
        self.service.context.return_value = {"status": "draft", "items": []}
        self.client.post("/review/2025-01-02/assemble")
        self.service.context.assert_called_once_with("2025-01-02", persist=True)

    def test_save_forwards_conclusion(self):
        self.service.save.return_value = {"status": "draft"}
        self.client.put("/review/2025-01-02", json={"summary": "复盘"})
        self.assertEqual(self.service.save.call_args.args[1]["summary"], "复盘")

    def test_seal_endpoint(self):
        self.service.seal.return_value = {"status": "sealed"}
        self.assertEqual(self.client.post("/review/2025-01-02/seal").json()["status"], "sealed")

    def test_resolver_endpoint(self):
        self.service.resolve.return_value = {"status": "resolved"}
        self.assertEqual(self.client.get("/review/objects/order/order-1").json()["status"], "resolved")

    def test_value_error_becomes_400(self):
        self.service.context.side_effect = ValueError("invalid date")
        self.assertEqual(self.client.get("/review/not-a-date").status_code, 400)


if __name__ == "__main__":
    unittest.main()
