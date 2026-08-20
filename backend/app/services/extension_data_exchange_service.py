"""Isolated file exchange for extension data; never maps into core research tables."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import ipaddress
import socket
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence
from urllib.parse import urlparse

import httpx
import psycopg2.extras
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill


class ExtensionDataExchangeService:
    MAX_BYTES = 5 * 1024 * 1024
    MAX_ROWS = 10_000
    MAX_COLUMNS = 200
    FORMULA_PREFIXES = ("=", "+", "-", "@")

    def __init__(self, database):
        self.database = database

    @classmethod
    def parse_bytes(cls, filename: str, content: bytes) -> Dict[str, Any]:
        if not content:
            raise ValueError("导入文件为空")
        if len(content) > cls.MAX_BYTES:
            raise ValueError("导入文件不能超过 5MB")
        file_format = Path(filename or "").suffix.lower().lstrip(".")
        if file_format not in {"csv", "json", "xlsx"}:
            raise ValueError("仅支持 CSV、JSON 和 XLSX")
        if file_format == "csv":
            reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
            columns = [str(item or "").strip() for item in (reader.fieldnames or [])]
            rows = [{key: cls._coerce(value) for key, value in row.items()} for row in reader]
        elif file_format == "json":
            parsed = json.loads(content.decode("utf-8-sig"))
            rows = parsed.get("records") if isinstance(parsed, dict) else parsed
            if not isinstance(rows, list) or any(not isinstance(item, dict) for item in rows):
                raise ValueError("JSON 必须是对象数组或包含 records 数组")
            columns = list(dict.fromkeys(str(key) for item in rows for key in item.keys()))
            rows = [{key: cls._jsonable(item.get(key)) for key in columns} for item in rows]
        else:
            book = load_workbook(io.BytesIO(content), read_only=True, data_only=False)
            sheet = book.active
            raw_rows = list(sheet.iter_rows(values_only=True))
            if not raw_rows:
                raise ValueError("XLSX 工作表为空")
            columns = [str(item or "").strip() for item in raw_rows[0]]
            rows = []
            for raw in raw_rows[1:]:
                if any(isinstance(value, str) and value.startswith("=") for value in raw):
                    raise ValueError("XLSX 公式不允许进入扩展数据暂存")
                if all(value in (None, "") for value in raw):
                    continue
                rows.append({columns[index]: cls._jsonable(raw[index] if index < len(raw) else None) for index in range(len(columns))})
        cls._validate_table(columns, rows)
        return {"format": file_format, "columns": columns, "rows": rows}

    @classmethod
    def export_rows(cls, file_format: str, columns: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> bytes:
        if file_format == "json":
            return json.dumps(list(rows), ensure_ascii=False, indent=2, default=str).encode("utf-8")
        if file_format == "csv":
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=list(columns))
            writer.writeheader()
            for row in rows:
                writer.writerow({key: cls._safe_export_value(row.get(key)) for key in columns})
            return ("\ufeff" + output.getvalue()).encode("utf-8")
        if file_format != "xlsx":
            raise ValueError("导出格式仅支持 CSV、JSON 和 XLSX")
        book = Workbook()
        sheet = book.active
        sheet.title = "扩展数据"
        sheet.append(list(columns))
        header_fill = PatternFill("solid", fgColor="1F4E78")
        for cell in sheet[1]:
            cell.font = Font(name="Arial", bold=True, color="FFFFFF")
            cell.fill = header_fill
        for row in rows:
            sheet.append([cls._safe_export_value(row.get(key)) for key in columns])
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                cell.font = Font(name="Arial")
        sheet.freeze_panes = "A2"
        for column_cells in sheet.columns:
            width = min(40, max(10, max(len(str(cell.value or "")) for cell in column_cells) + 2))
            sheet.column_dimensions[column_cells[0].column_letter].width = width
        output = io.BytesIO()
        book.save(output)
        return output.getvalue()

    def create_import(self, name: str, filename: str, content: bytes, source_type: str = "file", source_uri: str | None = None) -> Dict[str, Any]:
        parsed = self.parse_bytes(filename, content)
        clean_name = str(name or Path(filename).stem).strip()
        if not clean_name or len(clean_name) > 120:
            raise ValueError("数据集名称长度必须为 1-120 字")
        digest = hashlib.sha256(content).hexdigest()
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """INSERT INTO extension_data_imports(name,source_type,source_uri,file_format,original_filename,row_count,column_names,content_hash,size_bytes)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                    (clean_name, source_type, source_uri, parsed["format"], filename, len(parsed["rows"]), psycopg2.extras.Json(parsed["columns"]), digest, len(content)),
                )
                imported = dict(cursor.fetchone())
                values = [(imported["id"], index + 1, psycopg2.extras.Json(row), self._row_hash(row)) for index, row in enumerate(parsed["rows"])]
                psycopg2.extras.execute_values(cursor, "INSERT INTO extension_data_records(import_id,ordinal,payload,row_hash) VALUES %s", values)
                return imported

    def create_http_import(self, name: str, url: str, file_format: str, allowed_hosts: Sequence[str]) -> Dict[str, Any]:
        normalized_url = self.validate_http_url(url, allowed_hosts)
        normalized_format = str(file_format or "").lower()
        if normalized_format not in {"csv", "json", "xlsx"}:
            raise ValueError("HTTP 数据格式仅支持 CSV、JSON 和 XLSX")
        with httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as client:
            with client.stream("GET", normalized_url, headers={"Accept": "application/json,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}) as response:
                response.raise_for_status()
                if 300 <= response.status_code < 400:
                    raise ValueError("HTTP 扩展数据禁止重定向")
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > self.MAX_BYTES:
                        raise ValueError("HTTP 扩展数据不能超过 5MB")
        return self.create_import(name, f"remote.{normalized_format}", bytes(content), source_type="http", source_uri=normalized_url)

    @staticmethod
    def validate_http_url(url: str, allowed_hosts: Sequence[str]) -> str:
        parsed = urlparse(str(url or "").strip())
        host = str(parsed.hostname or "").lower()
        allowed = {str(item).strip().lower() for item in allowed_hosts if str(item).strip()}
        if parsed.scheme != "https" or not host:
            raise ValueError("HTTP 扩展数据仅允许 HTTPS")
        if host not in allowed:
            raise ValueError("HTTP 主机不在白名单")
        try:
            addresses = {item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
        except socket.gaierror as exc:
            raise ValueError("HTTP 主机 DNS 解析失败") from exc
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified:
                raise ValueError("HTTP 主机解析到非公网地址")
        return parsed.geturl()

    def list_imports(self) -> List[Dict[str, Any]]:
        return self._rows("SELECT * FROM extension_data_imports ORDER BY created_at DESC,id DESC LIMIT 200")

    def export_import(self, import_id: str, file_format: str) -> tuple[Dict[str, Any], bytes]:
        imported = self._row("SELECT * FROM extension_data_imports WHERE id=%s", (import_id,))
        if not imported:
            raise ValueError("扩展数据导入不存在")
        records = self._rows("SELECT payload FROM extension_data_records WHERE import_id=%s ORDER BY ordinal", (import_id,))
        return imported, self.export_rows(file_format, list(imported["column_names"]), [item["payload"] for item in records])

    def delete_import(self, import_id: str) -> Dict[str, Any]:
        row = self._row("DELETE FROM extension_data_imports WHERE id=%s RETURNING id,name", (import_id,))
        if not row:
            raise ValueError("扩展数据导入不存在")
        return {**row, "deleted": True}

    @classmethod
    def _validate_table(cls, columns: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> None:
        if not columns or any(not item for item in columns):
            raise ValueError("表头不能为空")
        if len(set(columns)) != len(columns):
            raise ValueError("表头不能重复")
        if len(columns) > cls.MAX_COLUMNS:
            raise ValueError("列数不能超过 200")
        if not rows:
            raise ValueError("导入文件没有数据行")
        if len(rows) > cls.MAX_ROWS:
            raise ValueError("数据行不能超过 10000")

    @staticmethod
    def _coerce(value: Any) -> Any:
        text = str(value or "").strip()
        if text == "": return None
        try:
            return float(text) if any(mark in text.lower() for mark in (".", "e")) else text
        except ValueError:
            return text

    @staticmethod
    def _jsonable(value: Any) -> Any:
        if isinstance(value, (date, datetime)): return value.isoformat()
        if value is None or isinstance(value, (str, int, float, bool)): return value
        return str(value)

    @classmethod
    def _safe_export_value(cls, value: Any) -> Any:
        if isinstance(value, str) and value.startswith(cls.FORMULA_PREFIXES): return "'" + value
        return value

    @staticmethod
    def _row_hash(row: Mapping[str, Any]) -> str:
        return hashlib.sha256(json.dumps(dict(row), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()

    def _rows(self, query: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, tuple(params)); return [dict(row) for row in cursor.fetchall()]

    def _row(self, query: str, params: Sequence[Any] = ()) -> Dict[str, Any] | None:
        rows = self._rows(query, params); return rows[0] if rows else None
