from pathlib import Path

from prd_ai_battle.config import default_offline_config
from prd_ai_battle.models import Phase
from prd_ai_battle.tui.app import BattleApp, Bubble


async def test_tui_load_sample_and_status(tmp_path: Path):
    app = BattleApp(default_offline_config(str(tmp_path)), screenshot_ready=True)
    async with app.run_test(size=(140, 40)) as pilot:
        app.action_load_sample()
        await pilot.pause()
        assert app.session.brief is not None
        assert app.session.machine.phase is Phase.DISCUSS
        assert app.query_one("#matrix").row_count > 0
        assert app.query_one("#chat")


async def test_tui_full_offline_round(tmp_path: Path):
    app = BattleApp(default_offline_config(str(tmp_path)), screenshot_ready=True)
    async with app.run_test(size=(140, 40)) as pilot:
        app.action_load_sample()
        await pilot.pause()
        app.action_discuss()
        await _wait_idle(app, pilot)
        assert any(b.model_id == "primary" for b in app.query(Bubble))
        app.action_lock_matrix()
        assert app.session.state.phase is Phase.LOCKED
        assert not app.session.state.allows_write(app.session.state.primary)
        app.action_execute()
        await _wait_idle(app, pilot)
        assert app.session.state.phase is Phase.EXECUTE
        assert app.session.state.artifact_version == "v1"
        app.action_review()
        await _wait_idle(app, pilot)
        assert app.session.state.phase is Phase.REVIEW
        app.action_revise()
        await _wait_idle(app, pilot)
        assert app.session.state.phase is Phase.REVISE
        assert app.session.state.artifact_version == "v2"
        assert app.session.store.latest_version() == 2
        assert app.session.store.read_draft(1)
        assert app.session.store.read_draft(2)


async def _wait_idle(app: BattleApp, pilot, ticks: int = 40) -> None:
    for _ in range(ticks):
        await pilot.pause(0.05)
        if not app._busy:
            return
    raise AssertionError("stream worker did not finish")
