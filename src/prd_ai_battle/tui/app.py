"""Split-pane TUI: brief/matrix/state on the left, one shared labeled discuss chat on the right."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Button, DataTable, Footer, Header, Input, Markdown, Static, TabbedContent, TabPane

from prd_ai_battle.config import AppConfig
from prd_ai_battle.llm import StreamDelta
from prd_ai_battle.models import Phase, iso_now
from prd_ai_battle.projects import BOARD_DIR_NAME, ProjectHub
from prd_ai_battle.session import Session
from prd_ai_battle.state import IllegalTransition
from prd_ai_battle.tui.skin import (
    BTN_NEW_PROJECT,
    NEW_PROJECT_PLACEHOLDER,
    SIDEBAR_TITLE,
    TAB_BRIEF,
    TAB_MATRIX,
    TAB_REQUIREMENT,
    TAB_STATE,
    header_subtitle,
    speaker_color,
    speaker_css_class,
    speaker_display_name,
    status_line,
)
from prd_ai_battle.write_lock import WriteDenied

CSS_PATH = Path(__file__).with_name("app.tcss")


class StreamEvent(Message):
    def __init__(self, event: StreamDelta) -> None:
        super().__init__()
        self.event = event


class Bubble(Vertical):
    """One utterance on the shared discuss stream. Color follows yaml speaker id."""

    DEFAULT_CSS = """
    Bubble {
        height: auto;
    }
    """

    def __init__(
        self,
        model_id: str,
        ts: str | None = None,
        *,
        primary_id: str = "primary",
        advisor_ids: Sequence[str] = (),
    ) -> None:
        self.model_id = model_id
        self.ts = ts or iso_now()
        self.body = ""
        self.primary_id = primary_id
        self.advisor_ids = tuple(advisor_ids)
        self.display_name = speaker_display_name(model_id, primary_id=primary_id)
        self.speaker_class = speaker_css_class(
            model_id, primary_id=primary_id, advisor_ids=self.advisor_ids
        )
        self.accent = speaker_color(
            model_id, primary_id=primary_id, advisor_ids=self.advisor_ids
        )
        super().__init__()
        self.add_class("bubble", self.speaker_class)

    def _header_text(self) -> str:
        clock = self.ts[11:19] if len(self.ts) >= 19 else self.ts
        return f"{self.display_name} · {clock}"

    def compose(self) -> ComposeResult:
        yield Static(self._header_text(), classes="bubble-header", markup=False)
        yield Static(self.body, classes="bubble-body", markup=False)

    def append(self, text: str) -> None:
        self.body += text
        if self.is_mounted:
            self.query_one(".bubble-header", Static).update(self._header_text())
            self.query_one(".bubble-body", Static).update(self.body)


class BattleApp(App[None]):
    CSS_PATH = CSS_PATH
    TITLE = "prd-ai-battle"
    BINDINGS = [
        Binding("l", "load_sample", "载入样例", show=True),
        Binding("d", "discuss", "讨论", show=True),
        Binding("c", "lock_matrix", "锁定", show=True),
        Binding("e", "execute", "执行", show=True),
        Binding("r", "review", "审核", show=True),
        Binding("v", "revise", "修订", show=True),
        Binding("slash", "focus_composer", "输入", show=True),
        Binding("n", "new_project", "新建", show=True),
        Binding("x", "export_bundle", "导出", show=True),
        Binding("escape", "escape", "停止", show=True),
        Binding("q", "quit", "退出", show=True),
    ]

    STOP_COMMANDS = frozenset({"停止", "/停止", "stop", "/stop"})

    def __init__(
        self,
        config: AppConfig | None = None,
        *,
        hub: ProjectHub | None = None,
        board_home: Path | None = None,
        requirement: Path | None = None,
        screenshot_ready: bool = False,
    ) -> None:
        super().__init__()
        if hub is None:
            if config is None:
                raise ValueError("BattleApp requires config or hub")
            home = Path(board_home) if board_home is not None else Path(config.workspace).resolve() / BOARD_DIR_NAME
            hub = ProjectHub.open(home, seed_config=config)
        self.hub = hub
        self._screenshot_ready = screenshot_ready
        self._speed_client()
        self._requirement_arg = requirement
        self._live: dict[str, Bubble] = {}
        self._busy = False
        self.status_text = ""
        self._stream_kind = "chat"

    @property
    def session(self) -> Session:
        return self.hub.active_session()

    def _speed_client(self) -> None:
        if self._screenshot_ready and hasattr(self.session.client, "delay_s"):
            self.session.client.delay_s = 0.0  # type: ignore[attr-defined]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(id="status")
        with Horizontal(id="body"):
            with Vertical(id="projects"):
                yield Static(SIDEBAR_TITLE, id="projects-title")
                yield VerticalScroll(id="project-list")
                yield Button(BTN_NEW_PROJECT, id="new-project")
                yield Input(placeholder=NEW_PROJECT_PLACEHOLDER, id="new-project-name")
            with Vertical(id="left"):
                with TabbedContent():
                    with TabPane(TAB_REQUIREMENT, id="tab-req"):
                        yield VerticalScroll(Markdown("", id="requirement"))
                    with TabPane(TAB_BRIEF, id="tab-brief"):
                        yield VerticalScroll(Markdown("", id="brief"))
                    with TabPane(TAB_MATRIX, id="tab-matrix"):
                        yield DataTable(id="matrix", cursor_type="row")
                    with TabPane(TAB_STATE, id="tab-state"):
                        yield VerticalScroll(Markdown("", id="state"))
            with Vertical(id="right"):
                yield Static("共享讨论 — 一条时间线", id="chat-banner")
                yield VerticalScroll(id="chat")
        yield Input(placeholder="讨论提示（可选）— 回车发起一轮讨论", id="composer")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#matrix", DataTable)
        table.add_columns("条款", "是否响应", "证据页码", "意见", "状态")
        self._refresh_projects()
        self._refresh_status()
        if self._requirement_arg is not None:
            self._apply_requirement(self._requirement_arg)
        else:
            self.query_one("#requirement", Markdown).update(
                "按 **L** 载入内置招标文件，或传入 `--requirement PATH`。"
            )
        self.query_one("#composer", Input).can_focus = True
        self._replay_timeline()
        self.set_focus(table)

    def _speaker_kwargs(self) -> dict[str, object]:
        state = self.session.state
        return {"primary_id": state.primary, "advisor_ids": tuple(state.advisors)}

    def _make_bubble(self, model_id: str, ts: str | None = None) -> Bubble:
        return Bubble(model_id, ts=ts, **self._speaker_kwargs())  # type: ignore[arg-type]

    def _replay_timeline(self) -> None:
        chat = self.query_one("#chat", VerticalScroll)
        for msg in self.session.load_timeline():
            bubble = self._make_bubble(msg.model_id, ts=msg.ts)
            bubble.append(msg.content)
            chat.mount(bubble)

    def _refresh_status(self) -> None:
        state = self.session.state
        # Always surface phase, 对照表 lock, and who holds write_lock (primary.id).
        self.status_text = status_line(
            phase=state.phase,
            matrix_locked=state.matrix.locked,
            writer_id=state.primary,
        )
        extra = ""
        if self._busy and state.phase is Phase.DISCUSS:
            extra = "    [bold #f2cc60]讨论中 — Esc 停止[/]"
        self.query_one("#status", Static).update(self.status_text + extra)
        self.sub_title = header_subtitle(
            phase=state.phase,
            matrix_locked=state.matrix.locked,
            writer_id=state.primary,
            project_name=self.hub.active_record().name,
        )

    def _refresh_state_tab(self) -> None:
        state = self.session.state
        brief = state.brief.summary if state.brief else "—"
        cfg = self.session.config
        gw_url = cfg.primary.resolved_base_url(cfg.gateway)
        key_state = "set" if cfg.primary.resolved_key(cfg.gateway) else "missing"
        project = self.hub.active_record()
        md = (
            f"```\n"
            f"project: {project.name}\n"
            f"workspace: {project.workspace}\n"
            f"phase: {state.phase.value}\n"
            f"primary: {state.primary}\n"
            f"advisors: {state.advisors}\n"
            f"brief: {brief}\n"
            f"matrix.rows: {len(state.matrix.rows)}  locked={state.matrix.locked}\n"
            f"artifact_version: {state.artifact_version or '(none)'}\n"
            f"write_lock: {state.write_lock}  "
            f"allows_write(primary)={state.allows_write(state.primary)}\n"
            f"gateway.base_url: {gw_url}\n"
            f"gateway.api_key: {key_state}\n"
            f"```\n\n"
            "Advisors always receive `tools: []`.\n"
            "Review input is **brief + matrix + chapter_diff** only.\n"
            "Keys come from **this project's** gitignored env — never from git, never from other projects."
        )
        self.query_one("#state", Markdown).update(md)

    def _refresh_left(self) -> None:
        req = self.session.requirement or "_尚无需求。_"
        self.query_one("#requirement", Markdown).update(req)
        brief = self.session.brief.as_prompt_block() if self.session.brief else "_尚无摘要。_"
        self.query_one("#brief", Markdown).update(brief)
        table = self.query_one("#matrix", DataTable)
        table.clear()
        for row in self.session.matrix.rows:
            table.add_row(
                f"{row.clause_id} {row.clause}",
                row.responded.value,
                row.evidence_page,
                row.opinion,
                row.status.value,
                key=row.clause_id,
            )
        self._refresh_state_tab()
        self._refresh_status()

    def _apply_requirement(self, path: Path) -> None:
        self.session.load_requirement(path)
        if self.session.config.offline:
            self.session.seed_matrix_offline()
        self.session.enter_discuss()
        self._refresh_left()
        self._user_note(f"已载入 {path.name}。阶段=讨论。模型只看摘要，不看招标原文。")

    def _user_note(self, text: str) -> None:
        chat = self.query_one("#chat", VerticalScroll)
        bubble = self._make_bubble("user")
        bubble.append(text)
        chat.mount(bubble)
        chat.scroll_end(animate=False)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._refresh_status()

    def _refresh_projects(self) -> None:
        box = self.query_one("#project-list", VerticalScroll)
        by_id: dict[str, Button] = {}
        for btn in box.query(".project-item"):
            pid = (btn.id or "").removeprefix("proj-")
            if pid:
                by_id[pid] = btn
        seen: set[str] = set()
        active = self.hub.active_id
        for rec in self.hub.iter_projects():
            seen.add(rec.id)
            btn = by_id.get(rec.id)
            if btn is None:
                btn = Button(rec.name, id=f"proj-{rec.id}", classes="project-item")
                box.mount(btn)
            else:
                btn.label = rec.name
            btn.set_class(rec.id == active, "active")
        for pid, btn in by_id.items():
            if pid not in seen:
                btn.remove()

    def _show_session(self) -> None:
        """Rebuild left panes + timeline from the active project. Other mounts stay."""
        self._live.clear()
        chat = self.query_one("#chat", VerticalScroll)
        chat.remove_children()
        self._replay_timeline()
        self._refresh_left()
        self._refresh_projects()
        if not self.session.brief and not self.session.requirement:
            self.query_one("#requirement", Markdown).update(
                "按 **L** 载入内置招标文件，或传入 `--requirement PATH`。"
            )

    def switch_project(self, project_id: str) -> None:
        if project_id == self.hub.active_id:
            return
        if self._busy:
            self.notify("请先停止当前讨论（Esc）再切换项目", severity="warning")
            return
        self.hub.active_session().persist()
        self.hub.switch(project_id)
        self._speed_client()
        self._show_session()
        self.notify(f"已切换到「{self.hub.active_record().name}」")

    def create_project(self, name: str | None = None) -> None:
        if self._busy:
            self.notify("请先停止当前讨论（Esc）再新建项目", severity="warning")
            return
        rec = self.hub.create_project(name or "")
        try:
            self.query_one("#new-project-name", Input).value = ""
        except Exception:  # noqa: BLE001
            pass
        self._speed_client()
        self._show_session()
        self.notify(f"已新建「{rec.name}」")

    def action_new_project(self) -> None:
        raw = ""
        try:
            raw = self.query_one("#new-project-name", Input).value.strip()
        except Exception:  # noqa: BLE001
            raw = ""
        self.create_project(raw or None)

    @on(Button.Pressed, "#new-project")
    def _click_new_project(self) -> None:
        self.action_new_project()

    @on(Button.Pressed, ".project-item")
    def _click_project(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if not button_id.startswith("proj-"):
            return
        self.switch_project(button_id.removeprefix("proj-"))

    @on(Input.Submitted, "#new-project-name")
    def _submit_new_project(self, event: Input.Submitted) -> None:
        self.create_project(event.value.strip() or None)

    @on(DataTable.RowSelected, "#matrix")
    def _cycle_matrix(self, event: DataTable.RowSelected) -> None:
        if self.session.matrix.locked:
            self.notify("对照表已锁定（阶段=锁定及之后）", severity="warning")
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
        if prompt in self.STOP_COMMANDS:
            self.action_stop_discuss()
            return
        self.action_discuss(prompt or None)

    def action_focus_composer(self) -> None:
        self.query_one("#composer", Input).focus()

    def action_blur_composer(self) -> None:
        self.query_one("#matrix", DataTable).focus()

    def action_escape(self) -> None:
        if self._busy and self.session.state.phase is Phase.DISCUSS:
            self.action_stop_discuss()
            return
        self.action_blur_composer()

    def action_stop_discuss(self) -> None:
        if not self._busy:
            self.notify("当前没有进行中的讨论", severity="information")
            return
        self.session.request_stop()
        self._user_note("已停止讨论。部分发言保留在时间线。阶段仍为讨论，未写文件。")
        self.notify("已停止讨论。部分发言保留在时间线。")

    def action_export_bundle(self) -> None:
        from prd_ai_battle.export import export_deliverable

        payload = export_deliverable(self.session)
        path = payload["path"]
        if payload.get("draft_present"):
            self.notify(f"已导出到 {path}")
            self._user_note(f"已导出标书正文与对照表到 {path}")
        else:
            self.notify(f"已导出（尚无正文）到 {path}")
            self._user_note(f"已导出对照表与讨论记录到 {path}（尚无标书正文）。")

    def action_load_sample(self) -> None:
        from prd_ai_battle.ingest import bundled_sample_path

        self._apply_requirement(bundled_sample_path())
        self.notify("已载入样例 — 阶段=讨论")

    def action_discuss(self, prompt: str | None = None) -> None:
        if self._busy:
            self.notify("正在生成，请稍候", severity="warning")
            return
        if not self.session.brief:
            self.notify("请先载入需求（L）", severity="warning")
            return
        self._user_note(prompt or "交叉讨论 — 先并行开场，再读整条时间线互相回应。不写文件。")
        self._run_stream(self.session.discuss_group(prompt))

    def action_lock_matrix(self) -> None:
        try:
            self.session.lock_matrix()
        except IllegalTransition as exc:
            self.notify(str(exc), severity="error")
            return
        self._refresh_left()
        writer = self.session.state.primary
        self._user_note(f"阶段=锁定。写入仍由 {writer} 持有 — 按 E 进入执行。")
        self.notify("阶段=锁定")

    def action_execute(self) -> None:
        if self._busy:
            return
        if self.session.state.phase not in {Phase.LOCKED, Phase.EXECUTE}:
            self.notify("锁定（C）之后才能执行", severity="warning")
            return
        self._user_note("阶段=执行 — 主笔可写。顾问仍是 tools=[]。")
        self._run_stream(self.session.execute_primary_stream(note="tui execute"), kind="execute")

    def action_review(self) -> None:
        if self._busy:
            return
        if not self.session.state.artifact_version:
            self.notify("主笔须先写出稿（E）", severity="warning")
            return
        self._user_note("阶段=审核 — 顾问只看 摘要 + 对照表 + chapter_diff。")
        self._run_stream(self.session.review())

    def action_revise(self) -> None:
        if self._busy:
            return
        if self.session.state.phase not in {Phase.REVIEW, Phase.REVISE}:
            self.notify("审核之后才能修订", severity="warning")
            return
        self._user_note("阶段=修订 — 主笔写下一版 artifact_version。")
        self._run_stream(self.session.execute_primary_stream(note="tui revise"), kind="execute")

    def _run_stream(self, agen, *, kind: str = "chat") -> None:
        self._live.clear()
        self._stream_kind = kind
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
            self._refresh_left()

    def on_stream_event(self, message: StreamEvent) -> None:
        event = message.event
        chat = self.query_one("#chat", VerticalScroll)
        bubble = self._live.get(event.model_id)
        if bubble is None:
            bubble = self._make_bubble(event.model_id)
            self._live[event.model_id] = bubble
            chat.mount(bubble)
        if event.text:
            bubble.append(event.text)
        if event.done:
            self._live.pop(event.model_id, None)
        chat.scroll_end(animate=False)
