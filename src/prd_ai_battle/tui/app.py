"""Split-pane TUI: brief/matrix on the left, parallel model streams on the right."""

from __future__ import annotations

from pathlib import Path

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import DataTable, Footer, Header, Input, Markdown, Static, TabbedContent, TabPane

from prd_ai_battle.config import AppConfig
from prd_ai_battle.llm import StreamDelta
from prd_ai_battle.models import Phase, iso_now
from prd_ai_battle.session import Session
from prd_ai_battle.state import IllegalTransition
from prd_ai_battle.write_lock import WriteDenied

CSS_PATH = Path(__file__).with_name("app.tcss")


class StreamEvent(Message):
    def __init__(self, event: StreamDelta) -> None:
        super().__init__()
        self.event = event


class Bubble(Static):
    def __init__(self, model_id: str, ts: str | None = None) -> None:
        self.model_id = model_id
        self.ts = ts or iso_now()
        self.body = ""
        super().__init__(id=None)
        klass = "model-primary" if model_id == "primary" else f"model-{model_id}"
        if klass not in {"model-primary", "model-advisor-a", "model-advisor-b", "model-user"}:
            klass = "model-advisor-a"
        self.add_class("bubble", klass)

    def append(self, text: str) -> None:
        self.body += text
        clock = self.ts[11:19] if len(self.ts) >= 19 else self.ts
        self.update(f"[b]{self.model_id} · {clock}[/b]\n{self.body}")


class BattleApp(App[None]):
    CSS_PATH = CSS_PATH
    TITLE = "prd-ai-battle"
    BINDINGS = [
        Binding("l", "load_sample", "Load sample", show=True),
        Binding("d", "discuss", "Discuss", show=True),
        Binding("c", "lock_matrix", "Lock 对照表", show=True),
        Binding("e", "execute", "Primary write", show=True),
        Binding("r", "review", "Review", show=True),
        Binding("v", "revise", "Revise", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    def __init__(
        self,
        config: AppConfig,
        *,
        requirement: Path | None = None,
        screenshot_ready: bool = False,
    ) -> None:
        super().__init__()
        self.session = Session(config)
        if screenshot_ready and hasattr(self.session.client, "delay_s"):
            self.session.client.delay_s = 0.0  # type: ignore[attr-defined]
        self._requirement_arg = requirement
        self._live: dict[str, Bubble] = {}
        self._busy = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(id="status")
        with Horizontal(id="body"):
            with Vertical(id="left"):
                with TabbedContent():
                    with TabPane("Requirement", id="tab-req"):
                        yield VerticalScroll(Markdown("", id="requirement"))
                    with TabPane("Brief", id="tab-brief"):
                        yield VerticalScroll(Markdown("", id="brief"))
                    with TabPane("对照表", id="tab-matrix"):
                        yield DataTable(id="matrix", cursor_type="row")
            with Vertical(id="right"):
                yield VerticalScroll(id="chat")
        yield Input(placeholder="Optional discuss prompt — Enter to run a discuss round", id="composer")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#matrix", DataTable)
        table.add_columns("条款ID", "条款", "是否响应", "证据页码", "意见")
        self._refresh_status()
        if self._requirement_arg is not None:
            self._apply_requirement(self._requirement_arg)
        else:
            self.query_one("#requirement", Markdown).update(
                "Press **L** to load the bundled 招标文件 sample, or pass `--requirement PATH`."
            )

    def _refresh_status(self) -> None:
        m = self.session.machine
        lock = "LOCKED" if self.session.matrix.locked else "unlocked"
        drafts = self.session.store.latest_version()
        models = ", ".join(self.session.config.model_ids())
        mode = "offline" if self.session.config.offline else "live"
        self.query_one("#status", Static).update(
            f" phase [b]{m.phase.value}[/b]   对照表 {lock}   drafts v{drafts}   "
            f"{mode}   models {models}   (Enter on a matrix row cycles 是否响应)"
        )
        self.sub_title = f"{m.phase.value} · {lock}"

    def _refresh_left(self) -> None:
        req = self.session.requirement or "_No requirement loaded._"
        self.query_one("#requirement", Markdown).update(req)
        brief = self.session.brief.as_prompt_block() if self.session.brief else "_No brief._"
        self.query_one("#brief", Markdown).update(brief)
        table = self.query_one("#matrix", DataTable)
        table.clear()
        for row in self.session.matrix.rows:
            table.add_row(
                row.clause_id,
                row.clause,
                row.responded.value,
                row.evidence_page,
                row.comment,
                key=row.clause_id,
            )
        self._refresh_status()

    def _apply_requirement(self, path: Path) -> None:
        self.session.load_requirement(path)
        if self.session.config.offline:
            self.session.seed_matrix_offline()
        self.session.enter_discuss()
        self._refresh_left()
        self._user_note(f"Loaded {path.name}. Brief extracted — models will not see the raw tender.")

    def _user_note(self, text: str) -> None:
        chat = self.query_one("#chat", VerticalScroll)
        bubble = Bubble("user")
        bubble.append(text)
        chat.mount(bubble)
        chat.scroll_end(animate=False)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._refresh_status()

    @on(DataTable.RowSelected, "#matrix")
    def _cycle_matrix(self, event: DataTable.RowSelected) -> None:
        if self.session.matrix.locked:
            self.notify("对照表 is locked", severity="warning")
            return
        row_key = event.row_key.value if event.row_key else None
        if not row_key:
            return
        try:
            self.session.cycle_row(str(row_key))
        except Exception as exc:  # noqa: BLE001
            self.notify(str(exc), severity="error")
            return
        self._refresh_left()

    @on(Input.Submitted, "#composer")
    def _submit_prompt(self, event: Input.Submitted) -> None:
        prompt = event.value.strip()
        event.input.value = ""
        self.action_discuss(prompt or None)

    def action_load_sample(self) -> None:
        from prd_ai_battle.ingest import bundled_sample_path

        self._apply_requirement(bundled_sample_path())
        self.notify("Sample tender loaded")

    def action_discuss(self, prompt: str | None = None) -> None:
        if self._busy:
            self.notify("A stream is already running", severity="warning")
            return
        if not self.session.brief:
            self.notify("Load a requirement first (L)", severity="warning")
            return
        self._user_note(prompt or "Discuss round — all models, read-only, no filesystem writes.")
        self._run_stream(self.session.discuss(prompt))

    def action_lock_matrix(self) -> None:
        try:
            self.session.lock_matrix()
        except IllegalTransition as exc:
            self.notify(str(exc), severity="error")
            return
        self._refresh_left()
        self._user_note("对照表 locked. Primary may now write artifacts. Advisors still have no write tools.")
        self.notify("Matrix locked — confirm phase")

    def action_execute(self) -> None:
        if self._busy:
            return
        if not self.session.machine.writes_allowed():
            self.notify("Lock the 对照表 before the primary can write", severity="warning")
            return
        self._user_note("Primary execute — advisors are not given write tools.")
        self._run_stream(self.session.execute_primary_stream(note="tui execute"), kind="execute")

    def action_review(self) -> None:
        if self._busy:
            return
        if self.session.store.latest_version() < 1:
            self.notify("Primary must write a draft first (E)", severity="warning")
            return
        self._user_note("Review stub — advisors receive brief + matrix + chapter diffs only.")
        self._run_stream(self.session.review())

    def action_revise(self) -> None:
        if self._busy:
            return
        if self.session.machine.phase is not Phase.REVIEW:
            self.notify("Revise is available after a review round", severity="warning")
            return
        self._user_note("Primary revise → next draft version.")
        self._run_stream(self.session.execute_primary_stream(note="tui revise"), kind="execute")

    def _run_stream(self, agen, *, kind: str = "chat") -> None:
        self._live.clear()
        self._set_busy(True)
        self._pump_stream(agen, kind)

    @work(exclusive=True)
    async def _pump_stream(self, agen, kind: str) -> None:
        try:
            async for event in agen:
                self.post_message(StreamEvent(event))
        except (IllegalTransition, WriteDenied, Exception) as exc:
            self.notify(str(exc), severity="error")
        finally:
            self._set_busy(False)
            self._refresh_status()
            if kind == "execute":
                self._refresh_left()

    def on_stream_event(self, message: StreamEvent) -> None:
        event = message.event
        chat = self.query_one("#chat", VerticalScroll)
        bubble = self._live.get(event.model_id)
        if bubble is None:
            bubble = Bubble(event.model_id)
            self._live[event.model_id] = bubble
            chat.mount(bubble)
        if event.text:
            bubble.append(event.text)
        if event.done:
            self._live.pop(event.model_id, None)
        chat.scroll_end(animate=False)
