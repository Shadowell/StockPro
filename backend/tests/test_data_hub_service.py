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
