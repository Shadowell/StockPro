from __future__ import annotations

import hashlib
from pathlib import Path

from rebuild.audit_frontend_parity import audit_frontend_parity


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_frontend_parity_accepts_exact_adapted_and_quarantined_files(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "exact.ts").write_text("export const exact = 1\n")
    (target / "exact.ts").write_text("export const exact = 1\n")
    (source / "adapted.tsx").write_text("export const product = 'BitPro'\n")
    (target / "Ashare.tsx").write_text("export const product = 'StockPro'\n")
    (source / "crypto.tsx").write_text("export const exchange = 'okx'\n")
    quarantine = target / "_quarantine" / "crypto.tsx.disabled"
    quarantine.parent.mkdir()
    quarantine.write_text("export const exchange = 'okx'\n")

    result = audit_frontend_parity(source, target, {
        "adapted.tsx": {
            "classification": "adapted",
            "target": "Ashare.tsx",
            "source_sha256": digest(source / "adapted.tsx"),
            "contract": "A-share product mapping",
        },
        "crypto.tsx": {
            "classification": "quarantined",
            "target": "_quarantine/crypto.tsx.disabled",
            "source_sha256": digest(source / "crypto.tsx"),
            "contract": "No A-share execution equivalent",
        },
    })

    assert result["passed"] is True
    assert result["counts"] == {"source": 3, "exact": 1, "adapted": 1, "quarantined": 1}
    assert result["blockers"] == []


def test_frontend_parity_rejects_missing_and_stale_classifications(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "missing.ts").write_text("missing\n")
    (source / "stale.ts").write_text("current\n")
    (target / "stale.ts").write_text("adapted\n")

    result = audit_frontend_parity(source, target, {
        "stale.ts": {
            "classification": "adapted",
            "target": "stale.ts",
            "source_sha256": "0" * 64,
            "contract": "stale entry",
        },
    })

    assert result["passed"] is False
    assert {item["source"] for item in result["blockers"]} == {"missing.ts", "stale.ts"}
