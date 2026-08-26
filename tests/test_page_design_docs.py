from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


PAGES = [
    ("首页", "/", "docs/pages/首页.md", "docs/screenshots/01-home.png"),
    ("行情", "/market", "docs/pages/行情.md", "docs/screenshots/02-market.png"),
    ("策略", "/strategy", "docs/pages/策略中心.md", "docs/screenshots/03-strategy.png"),
    ("回测", "/backtest", "docs/pages/回测.md", "docs/screenshots/04-backtest.png"),
    ("链上", "/onchain", "docs/pages/链上研究.md", None),
    ("模拟盘", "/live", "docs/pages/模拟盘.md", "docs/screenshots/05-live.png"),
    ("实盘", "/live-real", "docs/pages/实盘工作台.md", "docs/screenshots/06-live-real.png"),
    ("盯盘", "/watch", "docs/pages/盯盘.md", "docs/screenshots/07-watch.png"),
    ("复盘", "/review", "docs/pages/复盘中心.md", None),
    ("信号中心", "/signals", "docs/pages/信号中心.md", "docs/screenshots/08-signals.png"),
    ("监控", "/monitor", "docs/pages/监控.md", "docs/screenshots/09-monitor.png"),
    ("数据中心", "/data", "docs/pages/数据中心.md", "docs/screenshots/10-data.png"),
    ("AI研发", "/ai-lab", "docs/pages/人工智能研发.md", "docs/screenshots/11-ai-lab.png"),
]


def test_every_first_level_page_has_design_doc_and_readme_screenshot():
    page_index = (ROOT / "docs/pages/页面文档索引.md").read_text()
    readme = (ROOT / "README.md").read_text()
    readme_en = (ROOT / "README_EN.md").read_text()
    capture = (ROOT / "docs/screenshots/截图采集记录.md").read_text()

    for label, route, doc_path, screenshot_path in PAGES:
        doc = ROOT / doc_path
        screenshot = ROOT / screenshot_path if screenshot_path else None

        assert doc.exists(), f"missing page design doc for {label}: {doc_path}"
        assert doc.name in page_index
        assert doc_path in readme
        assert doc_path in readme_en
        assert route in page_index
        if screenshot_path:
            assert screenshot is not None
            assert screenshot.exists(), f"missing README screenshot for {label}: {screenshot_path}"
            assert screenshot_path in readme
            assert screenshot_path in readme_en
            assert screenshot.name in capture
        else:
            assert f"[{doc.name}]" in page_index


def test_page_docs_define_required_contract_sections():
    required_sections = [
        "## 路由",
        "## 页面目的",
        "## 首屏布局",
        "## 数据来源",
        "## 交互规则",
        "## 空态和错误态",
        "## 截图合同",
    ]

    for _, _, doc_path, _ in PAGES:
        text = (ROOT / doc_path).read_text()
        for section in required_sections:
            assert section in text, f"{doc_path} missing {section}"


def test_provider_center_contract_documents_capabilities_and_task_selection():
    documents = {
        "specification": (ROOT / "docs/product/specification.md").read_text(),
        "ai_contract": (ROOT / "docs/contracts/人工智能实验室持久研发流程.md").read_text(),
        "ai_page": (ROOT / "docs/pages/人工智能研发.md").read_text(),
        "settings_page": (ROOT / "docs/pages/登录门禁.md").read_text(),
        "factor_page": (ROOT / "docs/pages/因子库.md").read_text(),
    }

    provider_docs = ("specification", "ai_contract", "ai_page", "settings_page")
    for name in provider_docs:
        text = documents[name]
        for fragment in ("Codex Provider", "Cursor Provider", "思考深度", "速度", "禁止静默切换"):
            assert fragment in text, f"{name} missing Provider capability fragment: {fragment}"
        for fragment in ("get_research_provider_client", "get_qwen_client", "任务级", "legacy/兼容"):
            assert fragment in text, f"{name} missing Provider routing fragment: {fragment}"
        for fragment in ("Codex 的 models", "Cursor 的实际模型列表", "已声明/当前配置模型", "probed_at"):
            assert fragment in text, f"{name} missing model-state fragment: {fragment}"

    assert "get_research_provider_client" in documents["factor_page"]
    assert "get_qwen_client" in documents["factor_page"]

    for name, text in documents.items():
        for fragment in ("十六个内置定义", "summary/catalog", "所有已注册定义", "自定义定义"):
            assert fragment in text, f"{name} missing FactorLab registry fragment: {fragment}"
        for fragment in ("不连接现有 BitPro MCP", "Paper/Live", "factorlab_research", "逐工具授权", "research-task/experiment"):
            assert fragment in text, f"{name} missing FactorLab boundary fragment: {fragment}"
        assert "阶段 2/3 MVP" in text, f"{name} missing implemented FactorLab MVP boundary"
        assert "gateway 未实现" in text, f"{name} must keep the research gateway unfinished"

    settings = documents["settings_page"]
    assert "设置中心不会自动执行 Cursor" in settings
    assert "probed_at" in settings
    assert "probe status" in settings
