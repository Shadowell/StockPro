import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.endpoints import data


class ExtensionDataExchangeApiTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(data.router, prefix="/data")
        self.client = TestClient(app)
        self.patch = patch.object(data, "extension_exchange_service")
        self.service = self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_upload_list_export_and_delete_contract(self):
        self.service.create_import.return_value = {"id": "import-1", "row_count": 1, "status": "staged"}
        self.service.list_imports.return_value = [{"id": "import-1"}]
        self.service.export_import.return_value = ({"id": "import-1"}, b"a,b\n1,2\n")
        self.service.delete_import.return_value = {"id": "import-1", "deleted": True}

        uploaded = self.client.post("/data/exchange/imports", data={"name": "样例"}, files={"file": ("sample.csv", b"a,b\n1,2\n", "text/csv")})
        self.assertEqual(1, uploaded.json()["row_count"])
        self.assertEqual(1, self.client.get("/data/exchange/imports").json()["total"])
        exported = self.client.get("/data/exchange/imports/import-1/export?format=csv")
        self.assertEqual("a,b\n1,2\n", exported.text)
        self.assertTrue(self.client.delete("/data/exchange/imports/import-1").json()["deleted"])

    def test_formula_rejection_is_a_400(self):
        self.service.create_import.side_effect = ValueError("XLSX 公式不允许进入扩展数据暂存")
        response = self.client.post("/data/exchange/imports", files={"file": ("sample.xlsx", b"bytes")})
        self.assertEqual(400, response.status_code)

    def test_http_import_uses_configured_allowlist(self):
        self.service.create_http_import.return_value = {"id": "http-1", "source_type": "http", "status": "staged"}
        with patch.object(data.settings, "EXTENSION_HTTP_ALLOWED_HOSTS", ["data.example.com"]):
            response = self.client.post("/data/exchange/http-imports", json={"name": "远端数据", "url": "https://data.example.com/feed.csv", "format": "csv"})
        self.assertEqual("http", response.json()["source_type"])
        self.assertEqual(["data.example.com"], self.service.create_http_import.call_args.args[3])


if __name__ == "__main__":
    unittest.main()
