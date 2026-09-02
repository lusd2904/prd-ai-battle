from pathlib import Path

from prd_ai_battle.config import AppConfig, GatewayConfig, LOCAL_GATEWAY_URL, ModelConfig, default_offline_config
from prd_ai_battle.models import Phase
from prd_ai_battle.tui.app import BattleApp, Bubble
from prd_ai_battle.tui.skin import (
    ADVISOR_PALETTE,
    TAB_BRIEF,
    TAB_MATRIX,
    TAB_REQUIREMENT,
    header_subtitle,
    speaker_color,
    speaker_css_class,
    speaker_display_name,
    status_line,
)


def test_speaker_palette_n_advisors_get_distinct_classes_and_colors():
    """N>2 yaml advisor ids must not collapse onto the old advisor-a purple."""
    advisors = ["advisor-sonnet", "advisor-grok", "advisor-kimi", "advisor-qwen"]
    classes = [
        speaker_css_class(aid, primary_id="primary", advisor_ids=advisors) for aid in advisors
    ]
    colors = [speaker_color(aid, primary_id="primary", advisor_ids=advisors) for aid in advisors]
    assert classes == ["speaker-0", "speaker-1", "speaker-2", "speaker-3"]
    assert len(set(classes)) == len(advisors)
    assert len(set(colors)) == len(advisors)
    assert colors == list(ADVISOR_PALETTE[:4])
    assert speaker_css_class("primary", primary_id="primary", advisor_ids=advisors) == "speaker-primary"
    assert speaker_css_class("user", primary_id="primary", advisor_ids=advisors) == "speaker-user"
    assert speaker_color("primary", primary_id="primary", advisor_ids=advisors) not in colors
    assert speaker_color("user", primary_id="primary", advisor_ids=advisors) not in colors
    # Seed yaml ids used to both fall through to model-advisor-a.
    assert speaker_css_class("advisor-sonnet", primary_id="primary", advisor_ids=advisors) != (
        speaker_css_class("advisor-grok", primary_id="primary", advisor_ids=advisors)
    )


def test_speaker_display_name_is_short_not_model_dump():
    assert speaker_display_name("user") == "用户"
    assert speaker_display_name("primary", primary_id="primary") == "主笔"
    assert speaker_display_name("lead", primary_id="lead") == "主笔"
    assert speaker_display_name("advisor-sonnet") == "sonnet"
    assert speaker_display_name("advisor-grok") == "grok"
    assert "x-ai/" not in speaker_display_name("advisor-grok")
    assert "claude" not in speaker_display_name("advisor-sonnet")


def test_status_line_always_shows_phase_matrix_lock_and_writer():
    discuss = status_line(phase=Phase.DISCUSS, matrix_locked=False, writer_id="lead")
    assert "讨论" in discuss
    assert "锁定" in discuss and "执行" in discuss and "审核" in discuss and "修订" in discuss
    assert "对照表" in discuss and "未锁定" in discuss
    assert "写入" in discuss and "lead" in discuss
    locked = status_line(phase=Phase.LOCKED, matrix_locked=True, writer_id="lead")
    assert "已锁定" in locked
    assert "写入" in locked and "lead" in locked
    sub = header_subtitle(phase=Phase.EXECUTE, matrix_locked=True, writer_id="lead")
    assert "执行" in sub
    assert "对照表已锁定" in sub
    assert "写入 lead" in sub
    assert "claude" not in sub
    assert "x-ai/" not in sub


def _n_advisor_config(workspace: str, n: int = 3) -> AppConfig:
    advisors = [
        ModelConfig(id=f"advisor-{name}", model=f"mock-{name}", temperature=0.4)
        for name in ("sonnet", "grok", "kimi", "qwen")[:n]
    ]
    cfg = AppConfig(
        workspace=workspace,
        offline=True,
        gateway=GatewayConfig(base_url=LOCAL_GATEWAY_URL, api_key=""),
        primary=ModelConfig(id="primary", model="mock-primary", temperature=0.2),
        advisors=advisors,
    )
    return cfg.resolve()


async def test_tui_load_sample_and_status(tmp_path: Path):
    app = BattleApp(default_offline_config(str(tmp_path)), screenshot_ready=True)
    async with app.run_test(size=(140, 40)) as pilot:
        app.action_load_sample()
        await pilot.pause()
        assert app.session.brief is not None
        assert app.session.machine.phase is Phase.DISCUSS
        assert app.query_one("#matrix").row_count > 0
        assert app.query_one("#chat")
        tab_titles = {str(getattr(p, "_title", "") or "") for p in app.query("TabPane")}
        assert TAB_REQUIREMENT in tab_titles
        assert TAB_BRIEF in tab_titles
        assert TAB_MATRIX in tab_titles
        assert "讨论" in app.status_text
        assert "对照表" in app.status_text
        assert "未锁定" in app.status_text
        assert "写入" in app.status_text
        assert app.session.state.primary in app.status_text
        assert "讨论" in app.sub_title
        assert "写入" in app.sub_title
        labels = [b.description for b in app.BINDINGS if getattr(b, "show", True)]
        assert "讨论" in labels
        assert "锁定" in labels
        assert "执行" in labels
        assert "审核" in labels
        assert "修订" in labels
        assert "退出" in labels


async def test_tui_full_offline_round(tmp_path: Path):
    app = BattleApp(default_offline_config(str(tmp_path)), screenshot_ready=True)
    async with app.run_test(size=(140, 40)) as pilot:
        app.action_load_sample()
        await pilot.pause()
        app.action_discuss()
        await _wait_idle(app, pilot)
        bubbles = list(app.query(Bubble))
        assert any(b.model_id == "primary" for b in bubbles)
        assert any(b.model_id == "advisor-a" for b in bubbles)
        assert app.query_one("#chat")
        assert app.query_one("#chat-banner")
        assert {b.model_id for b in bubbles} >= {"user", "primary", "advisor-a", "advisor-b"}
        assert all(b.ts for b in bubbles)
        assert all(b.display_name for b in bubbles)
        primary = next(b for b in bubbles if b.model_id == "primary")
        assert primary.display_name == "主笔"
        assert primary.speaker_class == "speaker-primary"
        adv_a = next(b for b in bubbles if b.model_id == "advisor-a")
        adv_b = next(b for b in bubbles if b.model_id == "advisor-b")
        assert adv_a.speaker_class != adv_b.speaker_class
        assert adv_a.accent != adv_b.accent
        app.action_lock_matrix()
        assert app.session.state.phase is Phase.LOCKED
        assert not app.session.state.allows_write(app.session.state.primary)
        assert "已锁定" in app.status_text
        assert app.session.state.primary in app.status_text
        assert "写入" in app.status_text
        app.action_execute()
        await _wait_idle(app, pilot)
        assert app.session.state.phase is Phase.EXECUTE
        assert app.session.state.artifact_version == "v1"
        assert "执行" in app.status_text
        assert "已锁定" in app.status_text
        assert "写入" in app.status_text
        app.action_review()
        await _wait_idle(app, pilot)
        assert app.session.state.phase is Phase.REVIEW
        assert "审核" in app.status_text
        app.action_revise()
        await _wait_idle(app, pilot)
        assert app.session.state.phase is Phase.REVISE
        assert app.session.state.artifact_version == "v2"
        assert "修订" in app.status_text
        assert app.session.store.latest_version() == 2
        assert app.session.store.read_draft(1)
        assert app.session.store.read_draft(2)


async def test_tui_n_advisors_mount_distinct_speaker_classes(tmp_path: Path):
    app = BattleApp(_n_advisor_config(str(tmp_path), n=3), screenshot_ready=True)
    async with app.run_test(size=(140, 40)) as pilot:
        chat = app.query_one("#chat")
        ids = ["user", "primary", "advisor-sonnet", "advisor-grok", "advisor-kimi"]
        for mid in ids:
            bubble = app._make_bubble(mid)
            bubble.append("ping")
            chat.mount(bubble)
        await pilot.pause()
        mounted = {b.model_id: b for b in app.query(Bubble) if b.model_id in ids}
        assert set(mounted) == set(ids)
        advisor_classes = {mounted[i].speaker_class for i in ids if i.startswith("advisor-")}
        advisor_colors = {mounted[i].accent for i in ids if i.startswith("advisor-")}
        assert len(advisor_classes) == 3
        assert len(advisor_colors) == 3
        assert mounted["primary"].speaker_class == "speaker-primary"
        assert mounted["user"].speaker_class == "speaker-user"
        assert mounted["advisor-sonnet"].display_name == "sonnet"
        assert mounted["advisor-grok"].display_name == "grok"
        assert mounted["advisor-kimi"].display_name == "kimi"
        # Has classes, not the old hardcoded advisor-a/b collapse.
        assert "model-advisor-a" not in mounted["advisor-kimi"].classes
        assert "speaker-2" in mounted["advisor-kimi"].classes


async def _wait_idle(app: BattleApp, pilot, ticks: int = 40) -> None:
    for _ in range(ticks):
        await pilot.pause(0.05)
        if not app._busy:
            return
    raise AssertionError("stream worker did not finish")
