"""Two mounted projects: timeline, lock, files, keys, and write_lock stay isolated."""

from __future__ import annotations

from pathlib import Path

import pytest

from prd_ai_battle.config import (
    LOCAL_ENV_NAME,
    LOCAL_YAML_NAME,
    AppConfig,
    GatewayConfig,
    LOCAL_GATEWAY_URL,
    ModelConfig,
    default_offline_config,
    read_env_file,
)
from prd_ai_battle.llm import MockChatClient
from prd_ai_battle.models import ChatMessage, ComplianceMatrix, MatrixRow, Phase, SessionState
from prd_ai_battle.projects import (
    DEFAULT_PROJECT_NAME,
    NEW_PROJECT_PREFIX,
    ProjectHub,
    is_empty_d01_stub,
    is_leftover_tender_fixture,
    is_locked_or_later,
    peek_workspace_state,
)
from prd_ai_battle.session import Session
from prd_ai_battle.write_lock import WriteDenied


SHARED_KEY_ENV = "PRD_PROJECT_SHARED_KEY"


def _cfg(*, workspace: str, primary_id: str, advisor_id: str, key_env: str) -> AppConfig:
    cfg = AppConfig(
        workspace=workspace,
        offline=True,
        gateway=GatewayConfig(base_url=LOCAL_GATEWAY_URL, api_key=""),
        primary=ModelConfig(
            id=primary_id,
            model="mock-primary",
            api_key_env=key_env,
            temperature=0.2,
        ),
        advisors=[
            ModelConfig(id=advisor_id, model="mock-adv", api_key_env=key_env, temperature=0.4),
        ],
    )
    return cfg.resolve()


def _two_projects(tmp_path: Path) -> tuple[ProjectHub, str, str]:
    seed = _cfg(
        workspace=str(tmp_path / "seed-ws"),
        primary_id="lead-seed",
        advisor_id="adv-seed",
        key_env=SHARED_KEY_ENV,
    )
    hub = ProjectHub.open(tmp_path / "board", seed_config=seed, offline=True)
    a = hub.create_project(
        "项目甲",
        config=_cfg(
            workspace=str(tmp_path / "unused-a"),
            primary_id="lead-a",
            advisor_id="adv-a",
            key_env=SHARED_KEY_ENV,
        ),
        env={SHARED_KEY_ENV: "secret-a"},
        offline=True,
    )
    b = hub.create_project(
        "项目乙",
        config=_cfg(
            workspace=str(tmp_path / "unused-b"),
            primary_id="lead-b",
            advisor_id="adv-b",
            key_env=SHARED_KEY_ENV,
        ),
        env={SHARED_KEY_ENV: "secret-b"},
        offline=True,
    )
    hub.switch(a.id)
    return hub, a.id, b.id


def _prep(session, *, delay: float = 0.0) -> None:
    session.client = MockChatClient(delay_s=delay)
    session.load_sample()
    session.seed_matrix_offline()


@pytest.mark.asyncio
async def test_two_projects_timeline_lock_files_and_keys_isolated(tmp_path: Path, monkeypatch):
    hub, id_a, id_b = _two_projects(tmp_path)
    sess_a = hub.mount(id_a)
    sess_b = hub.mount(id_b)
    assert sess_a is not sess_b
    assert sess_a.store.root.resolve() != sess_b.store.root.resolve()

    monkeypatch.setenv(SHARED_KEY_ENV, "LEAKED-FROM-PROCESS")
    assert sess_a.config.primary.resolved_key(sess_a.config.gateway) == "secret-a"
    assert sess_b.config.primary.resolved_key(sess_b.config.gateway) == "secret-b"
    assert sess_a.config.primary.resolved_key() != sess_b.config.primary.resolved_key()
    yaml_a = (hub.record(id_a).root_path / LOCAL_YAML_NAME).read_text(encoding="utf-8")
    yaml_b = (hub.record(id_b).root_path / LOCAL_YAML_NAME).read_text(encoding="utf-8")
    assert "secret-a" not in yaml_a and "secret-b" not in yaml_a
    assert "secret-a" not in yaml_b and "secret-b" not in yaml_b
    env_a = read_env_file(hub.record(id_a).root_path / LOCAL_ENV_NAME)
    env_b = read_env_file(hub.record(id_b).root_path / LOCAL_ENV_NAME)
    assert env_a[SHARED_KEY_ENV] == "secret-a"
    assert env_b[SHARED_KEY_ENV] == "secret-b"

    _prep(sess_a)
    if sess_a.state.brief is not None:
        sess_a.state.brief.summary = "甲摘要-UNIQUE-A"
        sess_a.persist()
    tools_seen: list[tuple[str, list[str]]] = []
    original = sess_a.client.stream_chat

    async def wrap(model, messages, *, tools=None):
        tools_seen.append((model.id, list(tools or [])))
        async for token in original(model, messages, tools=tools):
            yield token

    sess_a.client.stream_chat = wrap  # type: ignore[method-assign]
    async for _ in sess_a.discuss_group("甲交叉讨论"):
        pass
    assert sess_a.state.phase is Phase.DISCUSS
    assert any(mid == "adv-a" and tools == [] for mid, tools in tools_seen)
    assert all(tools == [] or mid == "lead-a" for mid, tools in tools_seen)
    sess_a.lock_matrix()
    assert sess_a.state.phase is Phase.LOCKED
    assert sess_a.state.primary == "lead-a"
    assert not sess_a.state.allows_write("lead-b")
    assert sess_a.state.tools_for("adv-a") == []
    path_a = await sess_a.execute_primary(note="project-a")
    assert path_a.is_file()
    assert path_a.resolve().is_relative_to(sess_a.store.root.resolve())
    assert not path_a.resolve().is_relative_to(sess_b.store.root.resolve())
    assert (sess_a.store.drafts_dir / "v1" / "response.md").is_file()
    assert not (sess_b.store.drafts_dir / "v1" / "response.md").exists()
    assert list(sess_b.store.drafts_dir.rglob("*.md")) == []

    with pytest.raises(WriteDenied, match="not the primary"):
        sess_a.advisor_try_write("adv-a", "nope")
    with pytest.raises(WriteDenied, match="not the primary"):
        sess_a.writer.write("lead-b", "from-b.md", "cross")
    assert not list(sess_a.store.drafts_dir.rglob("from-b.md"))

    timeline_a = [(m.model_id, m.content) for m in sess_a.load_timeline()]
    assert timeline_a
    assert any("甲交叉讨论" in c or m == "lead-a" for m, c in timeline_a)
    assert sess_b.load_timeline() == []
    assert sess_b.state.phase is Phase.DISCUSS
    assert sess_b.state.matrix.locked is False
    assert sess_b.state.primary == "lead-b"

    _prep(sess_b)
    if sess_b.state.brief is not None:
        sess_b.state.brief.summary = "乙摘要-UNIQUE-B"
        sess_b.persist()
    async for _ in sess_b.discuss_group("乙交叉讨论"):
        pass
    assert any("乙交叉讨论" in m.content or m.model_id == "lead-b" for m in sess_b.load_timeline())
    assert all("乙交叉讨论" not in c and "乙摘要-UNIQUE-B" not in c for _, c in timeline_a)
    a_transcript = sess_a.store.transcript_path.read_text(encoding="utf-8")
    b_transcript = sess_b.store.transcript_path.read_text(encoding="utf-8")
    assert "甲交叉讨论" in a_transcript
    assert "乙交叉讨论" not in a_transcript
    assert "乙交叉讨论" in b_transcript
    assert "甲交叉讨论" not in b_transcript

    sess_b.lock_matrix()
    path_b = await sess_b.execute_primary(note="project-b")
    assert path_b.resolve().is_relative_to(sess_b.store.root.resolve())
    assert not path_b.resolve().is_relative_to(sess_a.store.root.resolve())
    assert (sess_a.store.drafts_dir / "v1" / "response.md").read_text(encoding="utf-8")
    assert (sess_b.store.drafts_dir / "v1" / "response.md").is_file()

    packet_a = sess_a.build_review_packet()
    packet_b = sess_b.build_review_packet()
    text_a = packet_a.as_prompt()
    text_b = packet_b.as_prompt()
    assert "甲摘要-UNIQUE-A" in text_a
    assert "乙摘要-UNIQUE-B" not in text_a
    assert "乙摘要-UNIQUE-B" in text_b
    assert "甲摘要-UNIQUE-A" not in text_b
    assert packet_a.allowed_keys() == ("brief", "matrix", "chapter_diff")
    assert "投标截止时间" not in text_a

    # A → B → A restores the same Session object and disk.
    assert hub.switch(id_b) is sess_b
    assert hub.is_mounted(id_a)
    restored = hub.switch(id_a)
    assert restored is sess_a
    assert hub.active_session() is sess_a
    assert [(m.model_id, m.content) for m in restored.load_timeline()] == timeline_a
    assert restored.state.phase is Phase.EXECUTE
    assert restored.state.matrix.locked is True
    assert restored.state.primary == "lead-a"
    assert restored.store.read_draft(1)
    assert restored.config.primary.resolved_key() == "secret-a"


@pytest.mark.asyncio
async def test_switch_does_not_destroy_other_session(tmp_path: Path):
    hub, id_a, id_b = _two_projects(tmp_path)
    sess_a = hub.mount(id_a)
    _prep(sess_a)
    async for _ in sess_a.discuss("keep-me"):
        pass
    count_a = len(sess_a.load_timeline())
    hub.switch(id_b)
    assert hub.session(id_a) is sess_a
    assert len(sess_a.load_timeline()) == count_a
    hub.switch(id_a)
    assert hub.active_session() is sess_a
    assert len(sess_a.load_timeline()) == count_a


def test_new_project_has_own_yaml_env_workspace(tmp_path: Path):
    seed = _cfg(
        workspace=str(tmp_path / "seed"),
        primary_id="lead-seed",
        advisor_id="adv-seed",
        key_env=SHARED_KEY_ENV,
    )
    hub = ProjectHub.open(tmp_path / "board", seed_config=seed, offline=True)
    assert hub.active_record().name == DEFAULT_PROJECT_NAME
    rec = hub.create_project("项目丙", offline=True)
    root = rec.root_path
    assert (root / LOCAL_YAML_NAME).is_file()
    assert (root / LOCAL_ENV_NAME).is_file()
    assert (Path(rec.workspace) / "session.json").is_file()
    yaml_text = (root / LOCAL_YAML_NAME).read_text(encoding="utf-8")
    assert "claude-opus-5" not in yaml_text
    assert "x-ai/grok-4.6" not in yaml_text
    assert "advisor-sonnet" not in yaml_text
    assert hub.is_mounted(rec.id)
    assert hub.active_id == rec.id


def test_helpers_leftover_fixture_empty_d01_and_locked():
    leftover = SessionState(
        primary="primary",
        advisors=["a"],
        requirement_path="/app/src/prd_ai_battle/data/tender.md",
    )
    assert is_leftover_tender_fixture(leftover, Path("."))
    empty = SessionState(
        primary="primary",
        advisors=["a"],
        matrix=ComplianceMatrix(rows=[MatrixRow(clause_id="D01", clause="")]),
    )
    assert is_empty_d01_stub(empty)
    assert is_empty_d01_stub(SessionState(primary="p", advisors=[]), name="D01")
    assert not is_empty_d01_stub(SessionState(primary="p", advisors=[]))
    locked = SessionState(primary="p", advisors=[], phase=Phase.LOCKED)
    assert is_locked_or_later(locked)
    assert not is_locked_or_later(SessionState(primary="p", advisors=[]))


def test_open_prefers_last_locked_round_matrix_over_leftover_and_empty_d01(tmp_path: Path):
    leftover = tmp_path / "ws-leftover"
    sess_l = Session(default_offline_config(str(leftover)), root=leftover)
    sess_l.load_sample()
    sess_l.persist()
    assert is_leftover_tender_fixture(sess_l.state, leftover)

    d01 = tmp_path / "D01" / ".prd-ai-battle"
    sess_d = Session(default_offline_config(str(d01)), root=d01)
    sess_d.state.matrix = ComplianceMatrix(rows=[MatrixRow(clause_id="D01", clause="")])
    sess_d.persist()

    locked = tmp_path / "round-matrix" / ".prd-ai-battle"
    sess_r = Session(default_offline_config(str(locked)), root=locked)
    sess_r.load_sample()
    sess_r.seed_matrix_offline()
    sess_r.lock_matrix()
    assert sess_r.state.phase is Phase.LOCKED

    seed = default_offline_config(str(leftover))
    hub = ProjectHub.open(
        tmp_path / "board",
        seed_config=seed,
        offline=True,
        search_root=tmp_path,
    )
    names = {p.name for p in hub.iter_projects()}
    assert "round-matrix" in names
    assert hub.active_record().name == "round-matrix"
    assert hub.active_session().state.phase is Phase.LOCKED
    assert hub.active_session().state.matrix.locked is True


def test_open_creates_clean_project_when_only_leftover_fixture(tmp_path: Path):
    leftover = tmp_path / "ws-leftover"
    sess_l = Session(default_offline_config(str(leftover)), root=leftover)
    sess_l.load_sample()
    sess_l.persist()
    seed = default_offline_config(str(leftover))
    hub = ProjectHub.open(tmp_path / "board", seed_config=seed, offline=True)
    active = hub.active_session()
    assert not is_leftover_tender_fixture(active.state, hub.active_record().workspace_path)
    assert active.state.brief is None
    assert active.state.phase is Phase.DISCUSS
    leftovers = [
        p
        for p in hub.iter_projects()
        if is_leftover_tender_fixture(peek_workspace_state(p.workspace_path), p.workspace_path)
    ]
    assert leftovers


def test_explicit_workspace_opens_chosen_not_new_project(tmp_path: Path):
    leftover = tmp_path / "ws-leftover"
    sess_l = Session(default_offline_config(str(leftover)), root=leftover)
    sess_l.load_sample()
    sess_l.persist()
    assert is_leftover_tender_fixture(sess_l.state, leftover)

    chosen = tmp_path / "round-matrix" / ".prd-ai-battle"
    sess_r = Session(default_offline_config(str(chosen)), root=chosen)
    sess_r.load_sample()
    sess_r.seed_matrix_offline()
    sess_r.lock_matrix()
    hub = ProjectHub.open(
        tmp_path / "board",
        seed_config=default_offline_config(str(chosen)),
        offline=True,
        search_root=None,
        explicit_workspace=True,
    )
    assert Path(hub.active_record().workspace).resolve() == chosen.resolve()
    assert hub.active_record().name == "round-matrix"
    assert hub.active_session().state.phase is Phase.LOCKED
    assert not any(p.name.startswith(NEW_PROJECT_PREFIX) for p in hub.iter_projects())


def test_explicit_leftover_does_not_spawn_new_project(tmp_path: Path):
    leftover = tmp_path / "ws-leftover"
    sess_l = Session(default_offline_config(str(leftover)), root=leftover)
    sess_l.load_sample()
    sess_l.persist()
    hub = ProjectHub.open(
        tmp_path / "board-explicit",
        seed_config=default_offline_config(str(leftover)),
        offline=True,
        explicit_workspace=True,
    )
    assert len(hub.iter_projects()) == 1
    assert Path(hub.active_record().workspace).resolve() == leftover.resolve()
    assert not any(p.name.startswith(NEW_PROJECT_PREFIX) for p in hub.iter_projects())


def test_fresh_hub_reloads_catalog_from_disk(tmp_path: Path):
    hub, id_a, id_b = _two_projects(tmp_path)
    sess_a = hub.mount(id_a)
    _prep(sess_a)
    sess_a.store.append_message(
        ChatMessage(model_id="user", role="user", phase=Phase.DISCUSS, content="disk-keep"),
        sess_a.state,
    )
    sess_a.persist()
    again = ProjectHub.open(tmp_path / "board", seed_config=sess_a.config, offline=True)
    assert {p.id for p in again.iter_projects()} >= {id_a, id_b}
    again.switch(id_a)
    texts = [m.content for m in again.active_session().load_timeline()]
    assert "disk-keep" in texts
