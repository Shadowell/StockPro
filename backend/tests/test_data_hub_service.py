def test_dataset_job_query_uses_bound_like_patterns():
    from app.services.data_hub_service import DataHubService

    query = DataHubService()._get_dataset_job_query("stock_history")

    assert 'params_json LIKE %s' in query["where"]
    assert '%"task_type": "history"%' in query["params"]
    assert '%"task_type": "all"%' in query["params"]


def test_market_job_defaults_to_latest_open_trade_date(monkeypatch):
    from app.services.data_hub_service import DataHubService

    calendar = type("Calendar", (), {"resolve_market_data_date": lambda self, value: "2026-08-07"})()
    service = DataHubService(trading_dates=calendar)
    inserted = {}

    def insert_job(**kwargs):
        inserted.update(kwargs)
        return "job-1"

    monkeypatch.setattr(service, "_insert_job", insert_job)
    monkeypatch.setattr(service, "_append_job_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "get_job", lambda key: {"job_key": key})
    monkeypatch.setattr("app.services.data_hub_service.asyncio.create_task", lambda coroutine: coroutine.close())

    service.create_job("import_daily_data", {"task_type": "history"})

    assert inserted["params"]["date"] == "2026-08-07"
    assert service._cancel_flags["job-1"] is False
    assert service._active_tasks["job-1"] is None


def test_job_payload_labels_maintenance_separately_from_market_data():
    from app.services.data_hub_service import DataHubService

    service = DataHubService()

    assert service._job_kind("run_quality_checks") == "maintenance"
    assert service._job_kind("import_daily_data") == "market_data"


def test_quality_report_exposes_failed_rules_and_supported_remediation(monkeypatch):
    from app.services.data_hub_service import DataHubService

    service = DataHubService()
    saved = {}
    monkeypatch.setattr(
        "app.services.data_hub_service.db_instance.check_stock_history_quality",
        lambda: {
            "exists": True,
            "metrics": {
                "total": 100,
                "duplicates": 0,
                "null_ohlc": 0,
                "invalid_ohlc": 0,
                "invalid_close": 0,
                "latest_date": "2020-01-01",
                "date_rows": ["2020-01-01", "2019-12-20"],
            },
        },
    )
    monkeypatch.setattr(
        "app.services.data_hub_service.db_instance.save_data_hub_quality_report",
        lambda **kwargs: saved.update(kwargs),
    )

    report = service.run_quality_checks(["stock_history"])

    check = report["checks"][0]
    assert check["status"] == "red"
    assert {finding["rule_id"] for finding in check["findings"]} == {"date_continuity", "freshness"}
    assert all(finding["status"] in {"yellow", "red"} for finding in check["findings"])
    assert {finding["remediation"]["kind"] for finding in check["findings"]} == {"heal_missing_data"}
    assert all(finding["remediation"]["supported"] is True for finding in check["findings"])
    assert "findings" in saved["checks_json"]


def test_latest_quality_report_enriches_legacy_checks_without_claiming_unsafe_auto_fix(monkeypatch):
    from app.services.data_hub_service import DataHubService

    monkeypatch.setattr(
        "app.services.data_hub_service.db_instance.get_latest_quality_report",
        lambda: {
            "report_key": "dq_legacy",
            "scope": '["stock_fundamentals"]',
            "status": "red",
            "summary_json": '{"total_checks":1,"green":0,"yellow":0,"red":1,"status":"red"}',
            "checks_json": (
                '[{"dataset_id":"stock_fundamentals","status":"red",'
                '"title":"基本面快照质量","detail":"重复主键 3","metrics":'
                '{"rows":100,"duplicates":3,"null_ratio_pct":0,"invalid_ratio_pct":0,'
                '"latest_updated_at":"2026-08-10","freshness_days":0}}]'
            ),
            "created_at": "2026-08-10T09:00:00+08:00",
        },
    )

    report = DataHubService().get_latest_quality_report()

    finding = report["checks"][0]["findings"][0]
    assert finding["rule_id"] == "pk_uniqueness"
    assert finding["status"] == "red"
    assert finding["remediation"] == {
        "kind": "manual_review",
        "label": "检查并去重主键",
        "supported": False,
    }
