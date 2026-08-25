"""将 PostgreSQL 封存的 A 股日线导出为 Microsoft Qlib 二进制格式。

输出布局（Qlib 标准结构）::

    {export_dir}/
    ├── calendars/day.txt                 # 全体交易日（升序，YYYY-MM-DD）
    ├── instruments/all.txt               # SYMBOL\\t首日\\t末日
    └── features/{SH600000}/
        ├── open.{first}.{last}.bin       # float32 数组，首元素为日历起始索引
        ├── high|low|close|volume|turnover ...

事实来源只有已发布（``status='published'``）的 ``daily_bars``
``dataset_partition_records``，不回退 SQLite、不读取未封存行、不合成缺失值。
标的未交易的交易日写入 ``NaN``，与 Qlib ``dump_bin`` 的语义一致。
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("stockpro.qlib")

FIELDS = ("open", "high", "low", "close", "volume", "turnover")
DEFAULT_EXPORT_DIR = Path(__file__).resolve().parents[3] / "data" / "qlib" / "cn_data"


def qlib_symbol(symbol: str) -> str:
    """``SH_600000`` -> ``SH600000``（Qlib 目录命名约定）。"""
    return str(symbol).replace("_", "").strip().upper()


class QlibExportService:
    def __init__(self, database, export_dir: Optional[str | Path] = None):
        self.database = database
        from app.core.config import settings

        configured = getattr(settings, "QLIB_EXPORT_DIR", "") or str(DEFAULT_EXPORT_DIR)
        self.export_dir = Path(export_dir or configured)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        """Read-only view of the current on-disk export."""
        root = self.export_dir
        calendar_path = root / "calendars" / "day.txt"
        instruments_path = root / "instruments" / "all.txt"
        features_root = root / "features"
        dates: List[str] = []
        if calendar_path.exists():
            dates = [line for line in calendar_path.read_text().splitlines() if line.strip()]
        instruments = 0
        if instruments_path.exists():
            instruments = sum(1 for line in instruments_path.read_text().splitlines() if line.strip())
        symbol_dirs = sorted({p.name for p in features_root.iterdir()} if features_root.exists() else [])
        return {
            "format": "qlib-bin-v1",
            "export_dir": str(root.resolve()),
            "exists": calendar_path.exists(),
            "calendar_days": len(dates),
            "calendar_first": dates[0] if dates else None,
            "calendar_last": dates[-1] if dates else None,
            "instruments": instruments,
            "symbol_dirs": len(symbol_dirs),
            "fields": list(FIELDS),
            "updated_at": (
                datetime.fromtimestamp(calendar_path.stat().st_mtime).isoformat(timespec="seconds")
                if calendar_path.exists()
                else None
            ),
        }

    def export_incremental(self, force: bool = False) -> Dict[str, Any]:
        """Rebuild calendars/instruments; refresh only symbols with newer data."""
        result = self._run_export(force=force)
        logger.info(
            "Qlib export finished: %s symbols written (%s)",
            result.get("symbols_written"),
            result.get("status"),
        )
        return result

    def export_full(self) -> Dict[str, Any]:
        return self._run_export(force=True)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _load_published_rows(self):
        """Stream published daily-bar rows oldest-first via a server-side cursor."""
        sql = """
            SELECT DISTINCT
                   r.payload->>'symbol'      AS symbol,
                   r.payload->>'trade_date'  AS trade_date,
                   (r.payload->>'open')::float8      AS open,
                   (r.payload->>'high')::float8      AS high,
                   (r.payload->>'low')::float8       AS low,
                   (r.payload->>'close')::float8     AS close,
                   (r.payload->>'volume')::float8    AS volume,
                   (r.payload->>'turnover')::float8  AS turnover
            FROM dataset_partition_records r
            JOIN dataset_partitions p ON p.id = r.partition_id
            JOIN dataset_definitions d ON d.id = p.dataset_id
            WHERE d.code = 'daily_bars'
              AND p.status = 'published'
              AND r.payload->>'symbol' IS NOT NULL
              AND r.payload->>'trade_date' IS NOT NULL
            ORDER BY 2, 1
        """
        with self.database.get_connection() as connection:
            with connection.cursor(name="qlib_export_stream") as cursor:
                cursor.itersize = 100_000
                cursor.execute(sql)
                while True:
                    batch = cursor.fetchmany(100_000)
                    if not batch:
                        break
                    for row in batch:
                        yield row

    def _existing_symbol_end_dates(self) -> Dict[str, str]:
        """Parse `{field}.{first}.{last}.bin` names into per-symbol freshness markers."""
        ends: Dict[str, str] = {}
        features_root = self.export_dir / "features"
        if not features_root.exists():
            return ends
        marker = f"{FIELDS[0]}."  # use the open field as the freshness marker
        for symbol_dir in features_root.iterdir():
            if not symbol_dir.is_dir():
                continue
            for path in sorted(symbol_dir.glob(f"{marker}*.bin")):
                parts = path.stem.split(".")
                if len(parts) >= 3:
                    ends[symbol_dir.name] = parts[-1]
                break
        return ends

    def _read_existing_instruments(self) -> Dict[str, Tuple[str, str]]:
        path = self.export_dir / "instruments" / "all.txt"
        table: Dict[str, Tuple[str, str]] = {}
        if not path.exists():
            return table
        for line in path.read_text().splitlines():
            parts = line.split("\t")
            if len(parts) == 3 and parts[0].strip():
                table[parts[0].strip()] = (parts[1].strip(), parts[2].strip())
        return table

    def _run_export(self, force: bool) -> Dict[str, Any]:
        started_at = datetime.now()

        # Pass 1: full trading calendar from published partitions.
        with self.database.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT DISTINCT r.payload->>'trade_date'
                    FROM dataset_partition_records r
                    JOIN dataset_partitions p ON p.id = r.partition_id
                    JOIN dataset_definitions d ON d.id = p.dataset_id
                    WHERE d.code='daily_bars' AND p.status='published'
                      AND r.payload->>'trade_date' IS NOT NULL
                    """
                )
                dates = sorted(str(row[0])[:10] for row in cursor.fetchall())
        if not dates:
            raise ValueError("没有已发布的日线分区，拒绝导出空的 Qlib 数据集")
        date_index = {value: idx for idx, value in enumerate(dates)}
        latest_date = dates[-1]

        existing_ends = {} if force else self._existing_symbol_end_dates()

        # Pass 2: stream rows; aggregate per symbol into {date_index: value}.
        series: Dict[str, Dict[str, Dict[int, float]]] = {}
        row_count = 0
        for symbol, trade_date, *values in self._load_published_rows():
            idx = date_index.get(str(trade_date)[:10])
            qsym = qlib_symbol(symbol)
            if idx is None or not qsym:
                continue
            bucket = series.setdefault(qsym, {field: {} for field in FIELDS})
            for field, value in zip(FIELDS, values):
                if value is not None:
                    bucket[field][idx] = float(value)
            row_count += 1

        if not series:
            raise ValueError("已发布分区里没有可用行情行，拒绝导出空 Qlib 特征")

        calendars_dir = self.export_dir / "calendars"
        instruments_dir = self.export_dir / "instruments"
        features_dir = self.export_dir / "features"
        calendars_dir.mkdir(parents=True, exist_ok=True)
        instruments_dir.mkdir(parents=True, exist_ok=True)
        features_dir.mkdir(parents=True, exist_ok=True)
        (calendars_dir / "day.txt").write_text("\n".join(dates) + "\n", encoding="utf-8")

        last_index = date_index[latest_date]
        written = 0
        first_dates: Dict[str, str] = {}
        for qsym in sorted(series):
            end_marker = existing_ends.get(qsym)
            if not force and end_marker == latest_date:
                continue  # already fresh
            bucket = series[qsym]
            close_map = bucket[FIELDS[3]]  # close defines the valid span
            if not close_map:
                continue
            start_idx = min(close_map)
            symbol_dir = features_dir / qsym
            symbol_dir.mkdir(exist_ok=True)
            length = last_index - start_idx + 1
            for field in FIELDS:
                payload_values = np.full(length + 1, np.nan, dtype="<f4")
                payload_values[0] = np.float32(start_idx)  # Qlib start-index header
                for idx, value in bucket[field].items():
                    offset = idx - start_idx
                    if 0 <= offset < length:
                        payload_values[1 + offset] = np.float32(value)
                target = symbol_dir / f"{field}.{dates[start_idx]}.{latest_date}.bin"
                tmp = target.with_suffix(".tmp")
                tmp.write_bytes(payload_values.tobytes())
                tmp.replace(target)
            # remove stale bins left by previous runs with different ranges
            for stale in symbol_dir.glob(f"*.{latest_date}.tmp"):
                stale.unlink(missing_ok=True)
            first_dates[qsym] = dates[start_idx]
            written += 1

        # instruments/all.txt must cover every exported symbol (fresh or rewritten).
        all_symbols = sorted(set(series) | set(self._read_existing_instruments()))
        instrument_lines: List[str] = []
        for qsym in all_symbols:
            if qsym in first_dates:
                instrument_lines.append(f"{qsym}\t{first_dates[qsym]}\t{latest_date}")
            elif qsym in series and qsym in existing_ends:
                instrument_lines.append(f"{qsym}\t{existing_ends[qsym]}\t{existing_ends[qsym]}")
            elif qsym in existing_ends:
                instrument_lines.append(f"{qsym}\t{dates[0]}\t{existing_ends[qsym]}")
        (instruments_dir / "all.txt").write_text(
            "\n".join(sorted(instrument_lines)) + "\n", encoding="utf-8"
        )

        finished_at = datetime.now()
        return {
            "status": "success",
            "format": "qlib-bin-v1",
            "export_dir": str(self.export_dir.resolve()),
            "calendar_days": len(dates),
            "calendar_first": dates[0],
            "calendar_last": latest_date,
            "symbols_total": len(all_symbols),
            "symbols_written": written,
            "rows_read": row_count,
            "fields": list(FIELDS),
            "started_at": started_at.isoformat(timespec="seconds"),
            "finished_at": finished_at.isoformat(timespec="seconds"),
            "duration_seconds": round((finished_at - started_at).total_seconds(), 1),
        }
