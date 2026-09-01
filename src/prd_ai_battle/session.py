"""Orchestrates ingest → discuss → lock → primary write → advisor review."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from prd_ai_battle.config import AppConfig
from prd_ai_battle.diffs import chapter_diffs
from prd_ai_battle.ingest import bundled_sample_path, extract_brief
from prd_ai_battle.llm import ChatClient, MockChatClient, StreamDelta, stream_parallel
from prd_ai_battle.matrix import apply_offline_seed, matrix_from_brief
from prd_ai_battle.models import (
    Brief,
    ChatMessage,
    ComplianceMatrix,
    DraftVersion,
    Phase,
    ReviewPacket,
    SessionMeta,
    iso_now,
)
from prd_ai_battle.state import IllegalTransition, StateMachine
from prd_ai_battle.store import WorkspaceStore
from prd_ai_battle.write_lock import ArtifactWriter, WriteDenied, WriteLock


class Session:
    def __init__(self, config: AppConfig, root: Path | None = None) -> None:
        self.config = config
        self.store = WorkspaceStore(Path(root) if root is not None else Path(config.workspace))
        self.store.init()
        self.machine = StateMachine()
        self.lock = WriteLock(config.primary.id)
        self.writer = ArtifactWriter(self.store.drafts_dir, self.lock, self.machine)
        self.client: ChatClient = MockChatClient() if config.offline else ChatClient()
        self.requirement: str = ""
        self.brief: Brief | None = None
        self.matrix = ComplianceMatrix()
        self.meta = SessionMeta()
        self._buffers: dict[str, str] = {}
        self.last_write_path: Path | None = None

    def load_requirement(self, path: Path) -> Brief:
        text = path.read_text(encoding="utf-8")
        return self.load_requirement_text(text, source=str(path))

    def load_requirement_text(self, text: str, *, source: str = "") -> Brief:
        self.requirement = text
        self.store.save_requirement(text, source)
        self.brief = extract_brief(text, source_path=source)
        self.store.save_brief(self.brief)
        self.matrix = matrix_from_brief(self.brief)
        self.store.save_matrix(self.matrix)
        self.machine.has_brief = True
        self.meta.requirement_path = source
        self.meta.phase = Phase.IDLE
        self.store.save_meta(self.meta)
        return self.brief

    def load_sample(self) -> Brief:
        return self.load_requirement(bundled_sample_path())

    def seed_matrix_offline(self) -> None:
        apply_offline_seed(self.matrix)
        self.store.save_matrix(self.matrix)

    def enter_discuss(self) -> None:
        if self.machine.phase is Phase.IDLE:
            self.machine.advance(Phase.DISCUSS)
            self.meta.phase = Phase.DISCUSS
            self.store.save_meta(self.meta)

    def lock_matrix(self) -> ComplianceMatrix:
        if not self.matrix.rows:
            raise IllegalTransition("Matrix is empty — ingest a requirement first")
        if self.machine.phase is Phase.IDLE and self.machine.has_brief:
            self.enter_discuss()
        self.matrix.lock()
        self.store.save_matrix(self.matrix)
        self.machine.lock_matrix()
        self.meta.phase = Phase.CONFIRM
        self.store.save_meta(self.meta)
        return self.matrix

    def cycle_row(self, clause_id: str) -> None:
        self.matrix.cycle_status(clause_id)
        self.store.save_matrix(self.matrix)

    def _client_messages(self, extra_user: str) -> list[dict[str, str]]:
        if self.brief is None:
            raise IllegalTransition("No brief loaded")
        system = (
            "You are one advisor in a shared multi-model discussion. "
            "You receive the extracted brief only — never a full repository dump. "
            f"Your id is shown to the user. Phase={self.machine.phase.value}."
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": self.brief.as_prompt_block()},
            {"role": "user", "content": extra_user},
        ]

    def _review_messages(self, packet: ReviewPacket) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": packet.as_prompt()},
            {
                "role": "user",
                "content": "Review the chapter diffs against the brief and locked matrix. "
                "List gaps only. Do not request the rest of the repo.",
            },
        ]

    def build_review_packet(self) -> ReviewPacket:
        if self.brief is None:
            raise IllegalTransition("No brief")
        version = self.store.latest_version()
        if version < 1:
            raise IllegalTransition("No draft to review")
        current = self.store.read_draft(version)
        previous = self.store.read_draft(version - 1) if version > 1 else ""
        return ReviewPacket(
            brief=self.brief,
            matrix=self.matrix,
            diffs=chapter_diffs(previous, current),
            version=version,
        )

    async def discuss(self, user_prompt: str | None = None) -> AsyncIterator[StreamDelta]:
        self.enter_discuss()
        if self.machine.phase is not Phase.DISCUSS:
            raise IllegalTransition(f"Discuss is only valid in discuss (in {self.machine.phase.value})")
        prompt = user_prompt or (
            "Discuss the brief in one shared thread. Identify must-win scoring points, "
            "废标风险, and what should go into the 响应对照表. Do not write files."
        )
        self._persist_user(prompt, Phase.DISCUSS)
        async for event in self._fanout(self._client_messages(prompt), Phase.DISCUSS):
            yield event

    async def execute_primary_stream(self, *, note: str = "v1 draft") -> AsyncIterator[StreamDelta]:
        """Primary writes a draft (streamed). Advisors never get this tool."""
        if not self.machine.writes_allowed():
            self.lock.assert_can_write(self.config.primary.id, self.machine)
        version = self.store.latest_version() + 1
        prompt = (
            "Write the first draft of the bid response as Markdown. "
            "Cover ★ clauses, scoring-point outlines, and 废标规避. "
            if version == 1
            else "Revise the draft using the latest review comments."
        )
        phase = self.machine.phase
        chunks: list[str] = []
        async for token in self.client.stream_chat(
            self.config.primary,
            self._client_messages(prompt),
            tools=self.lock.tools_for(self.config.primary.id, self.machine),
        ):
            chunks.append(token)
            yield StreamDelta(self.config.primary.id, token, False)
        content = "".join(chunks).strip() + "\n"
        path = self.writer.write(self.config.primary.id, "response.md", content, version=version)
        self.last_write_path = path
        self.store.register_draft(
            self.meta,
            DraftVersion(version=version, path=str(path), written_by=self.config.primary.id, note=note),
        )
        notice = f"\n\n[wrote {path}]"
        self._persist_assistant(self.config.primary.id, f"[wrote {path}]\n\n{content}", phase)
        yield StreamDelta(self.config.primary.id, notice, True)

    async def execute_primary(self, *, note: str = "v1 draft") -> Path:
        async for _event in self.execute_primary_stream(note=note):
            pass
        if self.last_write_path is None:
            raise RuntimeError("Primary write produced no artifact")
        return self.last_write_path

    async def review(self) -> AsyncIterator[StreamDelta]:
        if self.machine.phase is Phase.CONFIRM:
            self.machine.start_review()
        elif self.machine.phase is not Phase.REVIEW:
            raise IllegalTransition(f"Review is only valid after confirm (in {self.machine.phase.value})")
        self.meta.phase = Phase.REVIEW
        self.store.save_meta(self.meta)
        packet = self.build_review_packet()
        # Advisors only — and they get the packet, never the workspace tree.
        advisors = list(self.config.advisors)
        messages_for = {m.id: self._review_messages(packet) for m in advisors}
        tools_for = {m.id: self.lock.tools_for(m.id, self.machine) for m in advisors}
        assert all(tools_for[m.id] == [] for m in advisors)
        self._persist_user(
            f"Review v{packet.version} using brief + matrix + section diffs only.",
            Phase.REVIEW,
        )
        async for event in self._run_models(advisors, messages_for, tools_for, Phase.REVIEW):
            yield event

    async def revise(self) -> Path:
        if self.machine.phase is not Phase.REVIEW:
            raise IllegalTransition("Revise is only valid in review")
        return await self.execute_primary(note="revised after review")

    async def _fanout(self, messages: list[dict[str, str]], phase: Phase) -> AsyncIterator[StreamDelta]:
        models = self.config.all_models()
        messages_for = {m.id: messages for m in models}
        tools_for = {m.id: self.lock.tools_for(m.id, self.machine) for m in models}
        async for event in self._run_models(models, messages_for, tools_for, phase):
            yield event

    async def _run_models(
        self,
        models,
        messages_for: dict[str, list[dict[str, str]]],
        tools_for: dict[str, list[str]],
        phase: Phase,
    ) -> AsyncIterator[StreamDelta]:
        self._buffers = {m.id: "" for m in models}
        async for event in stream_parallel(self.client, models, messages_for, tools_for):
            if event.text:
                self._buffers[event.model_id] = self._buffers.get(event.model_id, "") + event.text
            if event.done:
                self._persist_assistant(event.model_id, self._buffers.get(event.model_id, ""), phase)
            yield event

    def _persist_user(self, content: str, phase: Phase) -> None:
        msg = ChatMessage(model_id="user", role="user", phase=phase, content=content)
        self.store.append_message(msg)

    def _persist_assistant(self, model_id: str, content: str, phase: Phase) -> None:
        if not content.strip():
            return
        self.store.append_message(
            ChatMessage(model_id=model_id, role="assistant", phase=phase, content=content, ts=iso_now())
        )

    def advisor_try_write(self, advisor_id: str, content: str) -> None:
        """Used by tests to prove advisors cannot write."""
        version = max(self.store.latest_version(), 0) + 1
        self.writer.write(advisor_id, "sneaky.md", content, version=version)


async def run_offline_pipeline(workspace: Path, *, seed_matrix: bool = True) -> dict:
    """Headless success path: sample → discuss → lock → write → review → revise."""
    from prd_ai_battle.config import default_offline_config

    session = Session(default_offline_config(str(workspace)), root=workspace)
    session.client = MockChatClient(delay_s=0.0)
    session.load_sample()
    if seed_matrix:
        session.seed_matrix_offline()
    discuss_ids: set[str] = set()
    async for event in session.discuss():
        if event.text:
            discuss_ids.add(event.model_id)
    session.lock_matrix()
    v1 = await session.execute_primary()
    review_ids: set[str] = set()
    async for event in session.review():
        if event.text:
            review_ids.add(event.model_id)
    v2 = await session.revise()
    return {
        "phase": session.machine.phase.value,
        "matrix_locked": session.matrix.locked,
        "discuss_models": sorted(discuss_ids),
        "review_models": sorted(review_ids),
        "v1": str(v1),
        "v2": str(v2),
        "workspace": str(workspace),
        "transcript": str(session.store.transcript_path),
    }


__all__ = ["Session", "WriteDenied", "run_offline_pipeline"]
