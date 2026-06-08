def test_dataset_job_query_uses_bound_like_patterns():
    from app.services.data_hub_service import DataHubService

    query = DataHubService()._get_dataset_job_query("stock_history")

    assert 'params_json LIKE %s' in query["where"]
    assert '%"task_type": "history"%' in query["params"]
    assert '%"task_type": "all"%' in query["params"]
