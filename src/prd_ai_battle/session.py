"""Orchestrates discuss → locked → execute → review → revise."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from prd_ai_battle.config import AppConfig
from prd_ai_battle.diffs import chapter_diffs
from prd_ai_battle.ingest import bundled_sample_path, extract_brief, read_requirement_text
from prd_ai_battle.llm import ChatClient, MockChatClient, StreamDelta, stream_parallel
from prd_ai_battle.matrix import apply_offline_seed, matrix_from_brief
from prd_ai_battle.models import (
    Brief,
    ChatMessage,
    ComplianceMatrix,
    DraftVersion,
    Phase,
    ReviewPacket,
    SessionState,
    iso_now,
    render_timeline,
    timeline_prompt_block,
)
from prd_ai_battle.state import IllegalTransition, StateMachine
from prd_ai_battle.store import WorkspaceStore
from prd_ai_battle.write_lock import ArtifactWriter, WriteDenied, WriteLock

OPENING_PROMPT = (
    "Discuss the brief in one shared thread. Identify must-win scoring points, "
    "废标风险, and what should go into the 响应对照表. Do not write files."
)

CROSSING_PROMPT = (
    "交叉讨论：阅读整条时间线上每个人的发言，然后回应他们——"
    "可以同意、反驳、或向某一发言人提问。不要写文件。"
)


class Session:
    def __init__(self, config: AppConfig, root: Path | None = None) -> None:
        self.config = config
        self.store = WorkspaceStore(Path(root) if root is not None else Path(config.workspace))
        fallback = SessionState(
            primary=config.primary.id,
            advisors=[a.id for a in config.advisors],
            phase=Phase.DISCUSS,
            write_lock=True,
        )
        self.store.init(fallback)
        self.state = self.store.load_state(fallback) if self.store.meta_path.exists() else fallback
        # write_lock always follows the current config primary id, not a stale session or opus name.
        self.state.primary = config.primary.id
        self.state.advisors = [a.id for a in config.advisors]
        if not self.store.meta_path.exists():
            self.store.save_state(self.state)
        self.store.sync_timeline(self.state)
        self._bind()
        self.client: ChatClient = MockChatClient() if config.offline else ChatClient()
        self.requirement: str = ""
        self._buffers: dict[str, str] = {}
        self._finalized: set[str] = set()
        self._stop_requested = False
        self._discuss_cancel: asyncio.Event | None = None
        self.last_write_path: Path | None = None
        if self.store.requirement_path.exists() and not self.requirement:
            self.requirement = self.store.requirement_path.read_text(encoding="utf-8")

    def _bind(self) -> None:
        self.machine = StateMachine(self.state)
        self.lock = WriteLock(self.state)
        self.writer = ArtifactWriter(self.store.drafts_dir, self.lock, self.machine)

    @property
    def brief(self) -> Brief | None:
        return self.state.brief

    @property
    def matrix(self) -> ComplianceMatrix:
        return self.state.matrix

    def persist(self) -> None:
        self.store.save_state(self.state)
        if self.state.brief is not None:
            self.store.save_brief(self.state.brief)
        self.store.save_matrix(self.state.matrix)

    def load_requirement(self, path: Path) -> Brief:
        text = read_requirement_text(path)
        return self.load_requirement_text(text, source=str(path))

    def same_requirement(self, path: Path) -> bool:
        """True when `path` is the brief already loaded in this workspace."""
        if self.state.brief is None:
            return False
        try:
            incoming = read_requirement_text(path)
        except OSError:
            return False
        stored = (self.requirement or "").strip()
        if stored and stored == incoming.strip():
            return True
        stored_path = (self.state.requirement_path or "").strip()
        if not stored_path:
            return False
        try:
            return Path(stored_path).resolve() == Path(path).resolve()
        except OSError:
            return stored_path == str(path)

    def reset_timeline(self) -> None:
        """Forget leftover utterances. Does not loosen write_lock or change review feed."""
        self.state.timeline = []
        self.store.clear_timeline(self.state)

    def load_requirement_text(self, text: str, *, source: str = "") -> Brief:
        self.reset_timeline()
        self.requirement = text
        self.store.save_requirement(text, source)
        self.state.brief = extract_brief(text, source_path=source)
        self.state.matrix = matrix_from_brief(self.state.brief)
        self.state.phase = Phase.DISCUSS
        self.state.requirement_path = source
        self.state.artifact_version = ""
        self.persist()
        return self.state.brief

    def load_sample(self) -> Brief:
        return self.load_requirement(bundled_sample_path())

    def seed_matrix_offline(self) -> None:
        apply_offline_seed(self.state.matrix)
        self.persist()

    def enter_discuss(self) -> None:
        self.machine.enter_discuss()
        self.persist()

    def lock_matrix(self) -> ComplianceMatrix:
        self.machine.lock_matrix()
        self.persist()
        return self.state.matrix

    def cycle_row(self, clause_id: str) -> None:
        self.state.matrix.cycle_status(clause_id)
        self.persist()

    def speakers(self) -> list[str]:
        """Current yaml primary + advisors[] — never a hardcoded seed pair."""
        return self.config.model_ids()

    def request_stop(self) -> None:
        """Cancel an in-flight parallel discuss. Phase stays discuss; no artifact writes."""
        self._stop_requested = True
        ev = self._discuss_cancel
        if ev is not None:
            ev.set()

    def stop_requested(self) -> bool:
        return self._stop_requested

    def _reset_stop(self) -> None:
        self._stop_requested = False
        self._discuss_cancel = None

    def discuss_assistant_count(self) -> int:
        return sum(
            1
            for m in self.load_timeline()
            if m.role == "assistant" and m.phase is Phase.DISCUSS
        )

    def _client_messages(self, extra_user: str) -> list[dict[str, str]]:
        if self.state.brief is None:
            raise IllegalTransition("No brief loaded")
        system = (
            "You are the primary drafter. "
            "You receive the extracted brief only — never a full repository dump. "
            f"Your id is {self.config.primary.id}. Phase={self.state.phase.value}."
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": self.state.brief.as_prompt_block()},
            {"role": "user", "content": extra_user},
        ]

    def _discuss_messages(self, model_id: str, extra_user: str) -> list[dict[str, str]]:
        if self.state.brief is None:
            raise IllegalTransition("No brief loaded")
        speakers = ", ".join(self.speakers())
        system = (
            "You are one speaker in a SINGLE shared discuss chat "
            "(one timeline, not a sidecar teammate pane). "
            f"Your speaker id is {model_id}. Other speakers: {speakers}. "
            "You receive the extracted brief only — never a full repository dump. "
            "Prior utterances from every mouth appear below, labeled [agent-id · timestamp]. "
            f"Phase={self.state.phase.value}."
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": self.state.brief.as_prompt_block()},
            {"role": "user", "content": self.state.matrix.as_prompt_table()},
        ]
        prior = [m for m in self.store.load_transcript() if m.phase is Phase.DISCUSS]
        block = timeline_prompt_block(prior)
        if block:
            messages.append({"role": "user", "content": block})
        messages.append({"role": "user", "content": extra_user})
        return messages

    def _review_messages(self, packet: ReviewPacket) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": packet.as_prompt()},
            {
                "role": "user",
                "content": "Review brief + matrix + chapter_diff only. List gaps. Do not request the repo.",
            },
        ]

    def build_review_packet(self) -> ReviewPacket:
        if self.state.brief is None:
            raise IllegalTransition("No brief")
        version = self.store.latest_version()
        if version < 1:
            raise IllegalTransition("No draft to review")
        current = self.store.read_draft(version)
        previous = self.store.read_draft(version - 1) if version > 1 else ""
        return ReviewPacket(
            brief=self.state.brief,
            matrix=self.state.matrix,
            chapter_diff=chapter_diffs(previous, current),
        )

    def write_review_packet(self) -> Path:
        """Persist the only review-phase advisor input (brief + matrix + chapter_diff)."""
        from prd_ai_battle.bridge import review_packet_path

        packet = self.build_review_packet()
        dest = review_packet_path(self.store.root)
        dest.write_text(packet.as_prompt(), encoding="utf-8")
        return dest

    def notice_external_write(self, relative_or_absolute: str | Path, *, actor_id: str | None = None) -> Path:
        """Record a draft written by OpenCode's write tool after write-check passed."""
        actor = actor_id or self.state.primary
        self.lock.assert_can_write(actor, self.machine)
        path = Path(relative_or_absolute)
        if not path.is_absolute():
            path = self.store.root / path
        version = self.store.latest_version() + 1
        label = f"v{version}"
        self.machine.record_draft(label)
        self.store.register_draft(
            self.state,
            DraftVersion(version=version, path=str(path), written_by=actor, note="opencode"),
        )
        self.persist()
        return path

    def _tools_map(self, model_ids: list[str]) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for model_id in model_ids:
            # Hard rule: advisors always get tools: []
            out[model_id] = [] if model_id != self.state.primary else self.state.tools_for(model_id)
        return out

    async def discuss(
        self,
        user_prompt: str | None = None,
        *,
        crossing: bool | None = None,
        reset_stop: bool = True,
    ) -> AsyncIterator[StreamDelta]:
        """One discuss round. Opening (round 0) or crossing (later rounds).

        Opening: yaml primary + advisors[] speak in parallel on the brief.
        Crossing: every speaker receives the FULL current timeline[] + brief,
        then replies (agree / disagree / ask). No artifact writes. write_lock
        stays closed. Speakers come from the current yaml, never seed ids.
        """
        self.enter_discuss()
        if self.state.phase is not Phase.DISCUSS:
            raise IllegalTransition(f"Discuss is only valid in discuss (in {self.state.phase.value})")
        if reset_stop:
            self._reset_stop()
        if crossing is None:
            crossing = self.discuss_assistant_count() > 0
        prompt = user_prompt or (CROSSING_PROMPT if crossing else OPENING_PROMPT)
        self._persist_user(prompt, Phase.DISCUSS)
        models = self.config.all_models()
        messages_for = {m.id: self._discuss_messages(m.id, prompt) for m in models}
        tools_for = self._tools_map([m.id for m in models])
        async for event in self._run_models(
            models, messages_for, tools_for, Phase.DISCUSS, cancellable=True
        ):
            yield event

    async def discuss_group(self, user_prompt: str | None = None) -> AsyncIterator[StreamDelta]:
        """Product discuss: opening (if needed) then one crossing round.

        Later calls are crossing-only — repeat until the user locks the 对照表.
        Interrupt stops further rounds; partial utterances stay on the timeline.
        """
        self._reset_stop()
        had_assistants = self.discuss_assistant_count() > 0
        if not had_assistants:
            async for event in self.discuss(user_prompt, crossing=False, reset_stop=False):
                yield event
            if self._stop_requested:
                return
            async for event in self.discuss(None, crossing=True, reset_stop=False):
                yield event
            return
        async for event in self.discuss(user_prompt, crossing=True, reset_stop=False):
            yield event

    async def print_unified_stream(self, user_prompt: str | None = None, *, sink=None) -> None:
        """Fan out discuss and print one labeled timeline as each speaker finishes."""
        import sys

        out = sink if sink is not None else sys.stdout
        speakers = ", ".join(self.speakers())
        out.write(f"# Shared discuss  (speakers: {speakers})\n")
        out.write("# One timeline — not OpenCode teammate panes\n")
        out.flush()
        async for event in self.discuss_group(user_prompt):
            if not event.done:
                continue
            for msg in reversed(self.load_timeline()):
                if msg.model_id == event.model_id and msg.role == "assistant":
                    out.write("\n" + msg.as_bubble() + "\n")
                    out.flush()
                    break

    def begin_execute(self) -> None:
        self.machine.enter_execute()
        self.persist()

    def begin_review(self) -> None:
        self.machine.enter_review()
        self.persist()

    def begin_revise(self) -> None:
        self.machine.enter_revise()
        self.persist()

    async def execute_primary_stream(self, *, note: str = "draft") -> AsyncIterator[StreamDelta]:
        """Primary writes a draft (streamed). Only valid in execute (or after begin_execute)."""
        if self.state.phase is Phase.LOCKED:
            self.begin_execute()
        elif self.state.phase is Phase.REVIEW:
            self.begin_revise()
        if not self.state.allows_write(self.state.primary):
            self.lock.assert_can_write(self.state.primary, self.machine)
        version = self.store.latest_version() + 1
        prompt = (
            "Write the first draft of the bid response as Markdown. "
            "Cover ★ clauses, scoring-point outlines, and 废标规避. "
            if version == 1
            else "Revise the draft using the latest review comments."
        )
        phase = self.state.phase
        chunks: list[str] = []
        async for token in self.client.stream_chat(
            self.config.primary,
            self._client_messages(prompt),
            tools=self.state.tools_for(self.state.primary),
        ):
            chunks.append(token)
            yield StreamDelta(self.config.primary.id, token, False)
        content = "".join(chunks).strip() + "\n"
        path = self.writer.write(self.config.primary.id, "response.md", content, version=version)
        self.last_write_path = path
        self.store.register_draft(
            self.state,
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
        if self.state.phase in {Phase.EXECUTE, Phase.REVISE}:
            self.begin_review()
        elif self.state.phase is not Phase.REVIEW:
            raise IllegalTransition(f"Review is only valid after execute (in {self.state.phase.value})")
        packet = self.build_review_packet()
        advisors = list(self.config.advisors)
        messages_for = {m.id: self._review_messages(packet) for m in advisors}
        tools_for = self._tools_map([m.id for m in advisors])
        if any(tools_for[m.id] for m in advisors):
            raise WriteDenied("Advisors must always receive tools: []")
        self._persist_user(
            f"Review {self.state.artifact_version} using brief + matrix + chapter_diff only.",
            Phase.REVIEW,
        )
        async for event in self._run_models(advisors, messages_for, tools_for, Phase.REVIEW):
            yield event

    async def revise(self) -> Path:
        if self.state.phase is Phase.REVIEW:
            self.begin_revise()
        if self.state.phase is not Phase.REVISE:
            raise IllegalTransition("Revise is only valid after review")
        return await self.execute_primary(note="revised after review")

    async def _fanout(self, messages: list[dict[str, str]], phase: Phase) -> AsyncIterator[StreamDelta]:
        models = self.config.all_models()
        messages_for = {m.id: messages for m in models}
        tools_for = self._tools_map([m.id for m in models])
        async for event in self._run_models(models, messages_for, tools_for, phase):
            yield event

    def load_timeline(self) -> list[ChatMessage]:
        return self.store.sync_timeline(self.state)

    def render_timeline(self) -> str:
        return render_timeline(self.load_timeline())

    async def _run_models(
        self,
        models,
        messages_for: dict[str, list[dict[str, str]]],
        tools_for: dict[str, list[str]],
        phase: Phase,
        *,
        cancellable: bool = False,
    ) -> AsyncIterator[StreamDelta]:
        for mid, tools in list(tools_for.items()):
            if mid != self.state.primary and tools:
                raise WriteDenied(f"Advisor {mid} must receive tools: []")
        self._buffers = {m.id: "" for m in models}
        self._finalized = set()
        cancel: asyncio.Event | None = None
        if cancellable:
            cancel = asyncio.Event()
            self._discuss_cancel = cancel
            if self._stop_requested:
                cancel.set()
        try:
            async for event in stream_parallel(
                self.client, models, messages_for, tools_for, cancel=cancel
            ):
                if event.text:
                    self._buffers[event.model_id] = self._buffers.get(event.model_id, "") + event.text
                if event.done:
                    self._persist_assistant(event.model_id, self._buffers.get(event.model_id, ""), phase)
                    self._finalized.add(event.model_id)
                yield event
        finally:
            self._flush_partials(phase)
            if cancellable:
                self._discuss_cancel = None

    def _flush_partials(self, phase: Phase) -> None:
        """Keep interrupted tokens on the shared timeline. No draft files."""
        for mid, text in list(self._buffers.items()):
            if mid in self._finalized:
                continue
            if text.strip():
                self._persist_assistant(mid, text, phase)
                self._finalized.add(mid)

    def _persist_user(self, content: str, phase: Phase) -> None:
        msg = ChatMessage(model_id="user", role="user", phase=phase, content=content)
        self._commit_message(msg)

    def _persist_assistant(self, model_id: str, content: str, phase: Phase) -> None:
        if not content.strip():
            return
        self._commit_message(
            ChatMessage(model_id=model_id, role="assistant", phase=phase, content=content, ts=iso_now())
        )

    def _commit_message(self, msg: ChatMessage) -> None:
        self.store.append_message(msg, self.state)

    def advisor_try_write(self, advisor_id: str, content: str) -> None:
        """Used by tests to prove advisors cannot write."""
        self.writer.write(advisor_id, "sneaky.md", content)


async def run_offline_pipeline(workspace: Path, *, seed_matrix: bool = True) -> dict:
    """Headless success path: sample → discuss → lock → execute → review → revise."""
    from prd_ai_battle.config import default_offline_config

    session = Session(default_offline_config(str(workspace)), root=workspace)
    session.client = MockChatClient(delay_s=0.0)
    session.load_sample()
    if seed_matrix:
        session.seed_matrix_offline()
    discuss_ids: set[str] = set()
    async for event in session.discuss_group():
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
        "phase": session.state.phase.value,
        "primary": session.state.primary,
        "advisors": session.state.advisors,
        "artifact_version": session.state.artifact_version,
        "write_lock": session.state.write_lock,
        "matrix_locked": session.matrix.locked,
        "discuss_models": sorted(discuss_ids),
        "review_models": sorted(review_ids),
        "v1": str(v1),
        "v2": str(v2),
        "workspace": str(workspace),
        "transcript": str(session.store.transcript_path),
        "contract": session.state.contract_view(),
    }


__all__ = ["Session", "WriteDenied", "run_offline_pipeline"]
