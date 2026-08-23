from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_docs_root_uses_english_index_and_categorized_general_docs():
    root_files = sorted(path.name for path in (ROOT / "docs").iterdir() if path.is_file())
    assert root_files == ["index.md"]

    categorized_files = [
        "docs/product/specification.md",
        "docs/product/disclaimer.md",
        "docs/project/progress.md",
        "docs/architecture/architecture.md",
        "docs/architecture/codebase-guide.md",
        "docs/architecture/technical-reference.md",
        "docs/strategy/development-guide.md",
        "docs/strategy/research-notes.md",
        "docs/strategy/quant-strategies-guide.md",
        "docs/integrations/okx-signal-bot-json-format.md",
        "docs/integrations/exchange-fees-api-analysis.md",
        "docs/guides/crypto-beginner-guide.md",
        "docs/guides/ai-agent-development-tools-guide.md",
        "docs/references/top50-crypto-assets.md",
        "docs/market/global-delivery-calendar-guide.md",
        "docs/market/global-options-market-guide.md",
        "docs/market/options-beginner-guide.md",
        "docs/results/backtest-results.json",
        "docs/results/okx-backtest-results.json",
    ]

    for relative_path in categorized_files:
        path = ROOT / relative_path
        assert path.exists(), relative_path
        assert path.name == path.name.lower()
        assert "_" not in path.name


def test_readme_links_project_disclaimer_and_highlights_core_risks():
    text = _read("README.md")

    assert "简体中文 | [中文兼容入口](README_EN.md)" in text
    assert "## 项目定位" in text
    assert "## 真实页面截图" in text
    assert "## 核心工作流" in text
    assert "## 内置策略类型" in text
    assert "docs/screenshots/截图采集记录.md" in text
    assert "docs/product/disclaimer.md" in text
    assert "主要用于策略研究" in text
    assert "OKX Signal Bot" in text
    assert "实盘预检和二次确认" in text
    assert "OKX Trade API 下单" in text
    assert "实盘执行订阅" in text
    assert "不构成投资建议" in text
    assert "模拟盘" in text
    assert "没有 mock API、没有请求拦截、没有临时注入数据" in text
    assert "/trading" not in text
    assert "[实盘试运行]" not in text


def test_readme_en_is_chinese_compatibility_entry_and_preserves_guarded_live_boundary():
    text = _read("README_EN.md")

    assert "[简体中文主文档](README.md) | 中文兼容入口" in text
    assert "# BitPro" in text
    assert "本文件曾作为英文 README" in text
    assert "除非用户明确要求英文镜像" in text
    assert "## 核心边界" in text
    assert "## 文档入口" in text
    assert "## 页面与截图索引" in text
    assert "docs/screenshots/截图采集记录.md" in text
    assert "主要用于策略研究" in text
    assert "OKX Signal Bot" in text
    assert "OKX Trade API" in text
    assert "不构成投资建议" in text
    assert "docs/product/disclaimer.md" in text
    assert "/trading" not in text
    assert "LiveBroker" not in text


def test_readme_screenshot_manifest_records_real_capture_boundary():
    text = _read("docs/screenshots/截图采集记录.md")

    assert "2026-05-13 21:43-21:45 Asia/Shanghai" in text
    assert "01-home.png` 于 2026-05-13 23:18 Asia/Shanghai 重新采集" in text
    assert "生产部署地址" in text
    assert "API mock | 无" in text
    assert "请求拦截 | 无" in text
    assert "DOM/数据注入 | 无" in text
    assert "`05-live.png` | `/live`" in text
    assert "`06-live-real.png` | `/live-real`" in text
    assert "按设计属于模拟研究值" in text


def test_spec_records_disclaimer_boundaries():
    text = _read("docs/product/specification.md")

    assert "## 免责声明" in text
    assert "`README.md` 是中文主入口" in text
    assert "`README_EN.md` 仅作为历史英文路径的中文兼容入口保留" in text
    assert "`docs/` 根目录只保留 `index.md`" in text
    assert "小写 kebab-case 英文文件名" in text
    assert "策略研究、工程验证" in text
    assert "OKX Trade API" in text
    assert "实盘预检" in text
    assert "操作者配置的 webhook 流程" in text
    assert "人工确认开关" in text
    assert "不构成投资、法律、税务、会计或合规建议" in text
    assert "不保证未来结果" in text
    assert "操作者负责遵守" in text
    assert "README_EN.md` (English)" not in text


def test_central_disclaimer_document_covers_required_topics():
    text = _read("docs/product/disclaimer.md")

    required = [
        "主要用于策略研究",
        "OKX Signal Bot",
        "实盘预检和二次确认",
        "OKX Trade API 下单",
        "账户级实盘执行订阅",
        "不允许信号绕过策略启用、通道启用、白名单、TTL、动作和保证金校验",
        "不构成投资建议",
        "不构成法律、税务、会计或合规建议",
        "模拟盘和回测结果不代表未来结果",
        "杠杆、衍生工具、做空、强制平仓和流动性不足可能导致快速亏损",
        "AI、模型预测、回测和历史表现不保证未来收益",
        "外部平台、API、网络、数据源、Webhook、OKX Signal Bot 和第三方服务可能中断、延迟、重复处理或返回错误数据",
        "使用者需自行确认当地法律法规、平台规则、税务申报、数据授权、凭证安全和资金来源合规",
    ]
    for phrase in required:
        assert phrase in text

    assert "加密货币" not in text
