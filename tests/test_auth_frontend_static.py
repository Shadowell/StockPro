from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_frontend_uses_auth_gate_before_rendering_main_layout() -> None:
    app = read("frontend/src/App.tsx")
    auth_provider = ROOT / "frontend/src/auth/AuthProvider.tsx"
    login_page = ROOT / "frontend/src/pages/Login.tsx"

    assert auth_provider.exists()
    assert login_page.exists()
    assert "AuthProvider" in app
    assert "Login" in app
    assert "MainLayout" in app
    assert "authEnabled" in auth_provider.read_text(encoding="utf-8")
    assert "访客邀请码" in login_page.read_text(encoding="utf-8")
    assert "管理员登录" in login_page.read_text(encoding="utf-8")


def test_admin_login_prefills_default_username() -> None:
    login_page = read("frontend/src/pages/Login.tsx")

    assert "DEFAULT_ADMIN_USERNAME = 'Shadowell'" in login_page
    assert "useState(DEFAULT_ADMIN_USERNAME)" in login_page


def test_guest_invite_hash_link_auto_logs_in_and_cleans_url() -> None:
    login_page = read("frontend/src/pages/Login.tsx")

    assert "AUTO_GUEST_INVITE_PARAM_NAMES = ['invite', 'guest_code']" in login_page
    assert "window.location.hash" in login_page
    assert "new URLSearchParams(hash.slice(1))" in login_page
    assert "await loginGuest(inviteCode)" in login_page
    assert "window.history.replaceState" in login_page
    assert "window.location.search" not in login_page


def test_arc_console_approve_is_disabled_when_unknowns_are_present() -> None:
    page = read("frontend/src/pages/ArcConsole.tsx")
    assert "const approveBlocked = unknowns.length > 0" in page
    assert "disabled={approveBlocked || busy}" in page
    assert "path: '/arc'" in read("frontend/src/components/MainLayout.tsx")
    assert "allowedRoles: ['admin']" in read("frontend/src/components/MainLayout.tsx")


def test_guest_role_can_see_all_primary_navigation_and_settings_code_manager_exists() -> None:
    app = read("frontend/src/App.tsx")
    layout = read("frontend/src/components/MainLayout.tsx")
    client = read("frontend/src/api/client.ts")

    assert "useAuth" in layout
    assert "allowedRoles" in layout
    assert "RoleRoute" not in app
    assert "allowedRoles={['admin']}" not in app
    for path in ("/live-real", "/watch", "/monitor", "/data", "/ai-lab"):
        assert f"path: '{path}'," in layout
    assert layout.count("allowedRoles: ['admin', 'guest']") >= 10
    assert "访客邀请码管理" in layout
    assert "createGuestCode" in client
    assert "revokeGuestCode" in client
    assert "/auth/guest-codes" in client


def test_guest_mode_shows_limited_feature_notice() -> None:
    layout = read("frontend/src/components/MainLayout.tsx")

    assert "isGuest &&" in layout
    assert "访客模式：" in layout
    assert "部分页面功能不可用" in layout
    assert "仅支持查看和受限回测" in layout
    assert "实盘控制" in layout


def test_guest_live_real_page_is_read_only() -> None:
    live_center = read("frontend/src/pages/liveTrading/LiveExecutionCenter.tsx")

    assert "useAuth" in live_center
    assert "const readOnly = isGuest" in live_center
    assert "if (readOnly) return;" in live_center
    assert "!readOnly &&" in live_center
    assert "readOnly ? null : renderDeployPipeline()" in live_center


def test_guest_code_manager_does_not_render_revoked_rows_after_delete() -> None:
    layout = read("frontend/src/components/MainLayout.tsx")

    assert "setCodes((current) => current.filter((code) => code.id !== codeId));" in layout
    assert "已撤销" not in layout
    assert "disabled={revoked}" not in layout


def test_guest_code_form_labels_are_paired_with_inputs() -> None:
    layout = read("frontend/src/components/MainLayout.tsx")

    assert "grid grid-cols-1 items-start gap-3 lg:grid-cols-[minmax(180px,1.2fr)_repeat(4,minmax(90px,0.7fr))_auto]" in layout
    assert layout.count('className="flex min-w-0 flex-col gap-2"') >= 5
    assert layout.count('className="text-[10px] font-medium text-gray-600"') >= 5
    assert "mt-2 grid grid-cols-2 gap-2 text-[10px] text-gray-600 sm:grid-cols-5" not in layout


def test_settings_panel_exposes_mcp_token_generator() -> None:
    layout = read("frontend/src/components/MainLayout.tsx")
    client = read("frontend/src/api/client.ts")

    assert "设置中心" in layout
    assert "activeSettingsTab" in layout
    assert "settingsTabs" in layout
    assert "SettingsConfigBlock" in layout
    assert "MCP Agent Token" in layout
    assert "STOCKPRO_MCP_API_TOKEN" in layout
    assert "X-StockPro-MCP-Token" in layout
    assert "BITPRO_MCP_API_TOKEN" in layout
    assert "新 Token 仅显示一次" in layout
    assert "generateMcpToken" in layout
    assert "getMcpToken" in client
    assert "generateMcpToken" in client
    assert "/settings/mcp-token" in client
    assert "/settings/mcp-token/generate" in client


def test_settings_panel_uses_grouped_extensible_configuration_blocks() -> None:
    layout = read("frontend/src/components/MainLayout.tsx")

    for label in ("AI 与模型", "Agent 接入", "访问权限", "通知通道", "显示偏好"):
        assert label in layout
    assert "模型厂商" in layout
    assert "新增厂商" in layout
    assert "保存厂商" in layout
    assert "API Key 环境变量" in layout
    assert "llmConfig.providers" in layout
    assert "通知通道扩展槽" in layout
    assert "OPENAI_API_KEY" in layout
    assert "ANTHROPIC_API_KEY" in layout
    assert "GOOGLE_API_KEY" in layout
    assert "SettingsStatusBadge" in layout
    assert "max-w-6xl" in layout
