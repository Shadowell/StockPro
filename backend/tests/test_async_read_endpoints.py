import asyncio
import threading
import unittest
from unittest.mock import patch

from app.api.endpoints import (
    backtest,
    data,
    data_hub,
    factor_research,
    market,
    monitor_runtime,
    paper,
    pools,
    review,
    strategy,
    watch,
)


class AsyncReadEndpointSafetyTests(unittest.TestCase):
    def test_paper_instance_list_runs_blocking_service_off_event_loop(self):
        async def exercise():
            event_loop_thread = threading.get_ident()

            def blocking_read():
                return [{"worker_thread": threading.get_ident()}]

            with patch.object(paper.runtime_service, "list_instances", side_effect=blocking_read):
                payload = await paper.list_instances()
            return event_loop_thread, payload["items"][0]["worker_thread"]

        event_loop_thread, worker_thread = asyncio.run(exercise())
        self.assertNotEqual(worker_thread, event_loop_thread)

    def test_watch_context_runs_blocking_service_off_event_loop(self):
        async def exercise():
            event_loop_thread = threading.get_ident()

            def blocking_read():
                return {"worker_thread": threading.get_ident()}

            with patch.object(watch.service, "watch_context", side_effect=blocking_read):
                payload = await watch.watch_context()
            return event_loop_thread, payload["worker_thread"]

        event_loop_thread, worker_thread = asyncio.run(exercise())
        self.assertNotEqual(worker_thread, event_loop_thread)

    def test_monitor_health_runs_blocking_service_off_event_loop(self):
        async def exercise():
            event_loop_thread = threading.get_ident()

            def blocking_read():
                return {"worker_thread": threading.get_ident()}

            with patch.object(monitor_runtime.service, "health", side_effect=blocking_read):
                payload = await monitor_runtime.monitor_health()
            return event_loop_thread, payload["worker_thread"]

        event_loop_thread, worker_thread = asyncio.run(exercise())
        self.assertNotEqual(worker_thread, event_loop_thread)

    def test_review_dates_runs_blocking_service_off_event_loop(self):
        async def exercise():
            event_loop_thread = threading.get_ident()

            def blocking_read(_limit):
                return [{"worker_thread": threading.get_ident()}]

            with patch.object(review.service, "available_dates", side_effect=blocking_read):
                payload = await review.review_dates(limit=1)
            return event_loop_thread, payload["items"][0]["worker_thread"]

        event_loop_thread, worker_thread = asyncio.run(exercise())
        self.assertNotEqual(worker_thread, event_loop_thread)

    def test_data_config_runs_blocking_builder_off_event_loop(self):
        async def exercise():
            event_loop_thread = threading.get_ident()

            def blocking_read(_db):
                return {"worker_thread": threading.get_ident()}

            with patch.object(data, "_config_payload", side_effect=blocking_read):
                payload = await data.data_config()
            return event_loop_thread, payload["worker_thread"]

        event_loop_thread, worker_thread = asyncio.run(exercise())
        self.assertNotEqual(worker_thread, event_loop_thread)

    def test_data_hub_dataset_list_runs_blocking_service_off_event_loop(self):
        async def exercise():
            event_loop_thread = threading.get_ident()

            def blocking_read():
                return [{"worker_thread": threading.get_ident()}]

            with patch.object(
                data_hub.data_hub_service,
                "list_datasets",
                side_effect=blocking_read,
            ):
                payload = await data_hub.list_datasets()
            return event_loop_thread, payload["data"][0]["worker_thread"]

        event_loop_thread, worker_thread = asyncio.run(exercise())
        self.assertNotEqual(worker_thread, event_loop_thread)

    def test_factor_library_runs_blocking_service_off_event_loop(self):
        async def exercise():
            event_loop_thread = threading.get_ident()

            def blocking_read():
                return [{"worker_thread": threading.get_ident()}]

            with patch.object(
                factor_research.service,
                "list_library",
                side_effect=blocking_read,
            ):
                payload = await factor_research.factor_research_library()
            return event_loop_thread, payload["items"][0]["worker_thread"]

        event_loop_thread, worker_thread = asyncio.run(exercise())
        self.assertNotEqual(worker_thread, event_loop_thread)

    def test_pool_list_runs_blocking_service_off_event_loop(self):
        async def exercise():
            event_loop_thread = threading.get_ident()

            def blocking_read():
                return [{"worker_thread": threading.get_ident()}]

            with patch.object(pools.service, "list_pools", side_effect=blocking_read):
                payload = await pools.list_pools()
            return event_loop_thread, payload["items"][0]["worker_thread"]

        event_loop_thread, worker_thread = asyncio.run(exercise())
        self.assertNotEqual(worker_thread, event_loop_thread)

    def test_market_research_context_runs_blocking_service_off_event_loop(self):
        async def exercise():
            event_loop_thread = threading.get_ident()

            def blocking_read(*_args):
                return {"worker_thread": threading.get_ident()}

            with patch.object(
                market.research_service,
                "research_context",
                side_effect=blocking_read,
            ):
                payload = await market.get_research_context()
            return event_loop_thread, payload["worker_thread"]

        event_loop_thread, worker_thread = asyncio.run(exercise())
        self.assertNotEqual(worker_thread, event_loop_thread)

    def test_market_concept_leaders_run_blocking_database_read_off_event_loop(self):
        async def exercise():
            event_loop_thread = threading.get_ident()

            def blocking_read(_name, _limit):
                return [{"worker_thread": threading.get_ident()}]

            with (
                patch.object(market.db, "get_concept_leaders_cache", side_effect=blocking_read),
                patch.object(market.db, "get_concept_leaders_cache_updated_at", return_value=None),
            ):
                payload = await market.get_hot_concept_leaders(name="probe", limit=1)
            return event_loop_thread, payload[0]["worker_thread"]

        event_loop_thread, worker_thread = asyncio.run(exercise())
        self.assertNotEqual(worker_thread, event_loop_thread)

    def test_strategy_list_runs_blocking_service_off_event_loop(self):
        async def exercise():
            event_loop_thread = threading.get_ident()

            def blocking_read():
                return [{"name": "thread probe", "worker_thread": threading.get_ident()}]

            with patch.object(
                strategy.strategy_execution_service,
                "get_strategies",
                side_effect=blocking_read,
            ):
                payload = await strategy.get_strategies()
            return event_loop_thread, payload[0]["worker_thread"]

        event_loop_thread, worker_thread = asyncio.run(exercise())
        self.assertNotEqual(worker_thread, event_loop_thread)

    def test_backtest_run_list_runs_blocking_service_off_event_loop(self):
        async def exercise():
            event_loop_thread = threading.get_ident()

            def blocking_read(_limit):
                return [{"worker_thread": threading.get_ident()}]

            with patch.object(backtest.service, "list_runs", side_effect=blocking_read):
                payload = await backtest.list_runs(limit=5)
            return event_loop_thread, payload["items"][0]["worker_thread"]

        event_loop_thread, worker_thread = asyncio.run(exercise())
        self.assertNotEqual(worker_thread, event_loop_thread)

    def test_backtest_configuration_runs_blocking_service_off_event_loop(self):
        async def exercise():
            event_loop_thread = threading.get_ident()

            def blocking_read():
                return {"worker_thread": threading.get_ident()}

            with patch.object(backtest.service, "configuration", side_effect=blocking_read):
                payload = await backtest.get_configuration()
            return event_loop_thread, payload["worker_thread"]

        event_loop_thread, worker_thread = asyncio.run(exercise())
        self.assertNotEqual(worker_thread, event_loop_thread)


if __name__ == "__main__":
    unittest.main()
