from prd_ai_battle.config import default_offline_config
from prd_ai_battle.models import Phase
from prd_ai_battle.tui.app import BattleApp


async def test_tui_load_sample_and_status():
    app = BattleApp(default_offline_config(), screenshot_ready=True)
    async with app.run_test(size=(140, 40)) as pilot:
        await app.action_load_sample()
        await pilot.pause()
        assert app.session.brief is not None
        assert app.session.machine.phase is Phase.DISCUSS
        status = str(app.query_one("#status").render())
        assert "discuss" in status
