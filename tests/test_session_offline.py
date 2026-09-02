from pathlib import Path

import pytest

from prd_ai_battle.config import default_offline_config, expand_env, load_config
from prd_ai_battle.llm import ChatClient, MockChatClient, stream_parallel
from prd_ai_battle.models import Phase
from prd_ai_battle.session import Session, run_offline_pipeline
from prd_ai_battle.write_lock import WriteDenied
from pdf_fixture import MINI_TENDER, write_text_pdf


@pytest.mark.asyncio
async def test_offline_pipeline(tmp_path: Path):
    result = await run_offline_pipeline(tmp_path / "ws")
    assert result["phase"] == Phase.REVISE.value
    assert result["artifact_version"] == "v2"
    assert result["write_lock"] is True
    assert result["primary"] == "primary"
    assert "advisor-a" in result["advisors"]
    assert result["matrix_locked"] is True
    assert "primary" in result["discuss_models"]
    assert "advisor-a" in result["discuss_models"]
    assert "primary" not in result["review_models"]
    assert Path(result["v1"]).is_file()
    assert Path(result["v2"]).is_file()
    assert Path(result["v1"]).read_text(encoding="utf-8")
    transcript = Path(result["transcript"]).read_text(encoding="utf-8")
    assert "primary" in transcript
    assert "advisor-a" in transcript


@pytest.mark.asyncio
async def test_review_packet_has_no_repo_dump(tmp_path: Path):
    session = Session(default_offline_config(str(tmp_path)), root=tmp_path)
    session.client.delay_s = 0.0  # type: ignore[attr-defined]
    session.load_sample()
    session.seed_matrix_offline()
    async for _ in session.discuss():
        pass
    session.lock_matrix()
    await session.execute_primary()
    packet = session.build_review_packet()
    prompt = packet.as_prompt()
    assert packet.allowed_keys() == ("brief", "matrix", "chapter_diff")
    assert set(packet.model_dump()) == {"brief", "matrix", "chapter_diff"}
    assert "You do not have repository access" in prompt
    assert "chapter_diff" in prompt
    assert "drafts/" not in prompt
    assert "__pycache__" not in prompt
    assert "投标截止时间" not in prompt  # raw tender body stays out; only the brief is shared


@pytest.mark.asyncio
async def test_pdf_ingest_advisors_see_brief_not_raw_pdf(tmp_path: Path):
    pdf = write_text_pdf(tmp_path / "招标文件.pdf", MINI_TENDER)
    session = Session(default_offline_config(str(tmp_path / "ws")), root=tmp_path / "ws")
    session.client.delay_s = 0.0  # type: ignore[attr-defined]
    session.load_requirement(pdf)
    session.seed_matrix_offline()
    messages = session._client_messages("discuss the brief")
    blob = "\n".join(m["content"] for m in messages)
    assert "评分点" in blob
    assert "废标项" in blob
    assert "%PDF" not in blob
    assert pdf.read_bytes()[:5] == b"%PDF-"
    session.lock_matrix()
    await session.execute_primary()
    packet = session.build_review_packet()
    assert packet.allowed_keys() == ("brief", "matrix", "chapter_diff")
    review = packet.as_prompt()
    assert "%PDF" not in review
    assert "招标文件.pdf" not in review


@pytest.mark.asyncio
async def test_advisor_cannot_write_via_session(tmp_path: Path):
    session = Session(default_offline_config(str(tmp_path)), root=tmp_path)
    session.load_sample()
    session.seed_matrix_offline()
    session.enter_discuss()
    session.lock_matrix()
    with pytest.raises(WriteDenied):
        session.advisor_try_write("advisor-a", "pwned")


def test_expand_env(monkeypatch):
    monkeypatch.setenv("FOO_URL", "https://example.test/v1")
    assert expand_env("${FOO_URL}") == "https://example.test/v1"
    assert expand_env("${MISSING:-http://fallback}") == "http://fallback"


class _OneAdvisorTimeout(ChatClient):
    """Live-shaped client: one advisor raises; siblings must still stream."""

    def __init__(self) -> None:
        super().__init__()
        self._ok = MockChatClient(delay_s=0.0)

    async def stream_chat(self, model, messages, *, tools=None):
        if model.id == "advisor-b":
            raise TimeoutError("simulated advisor timeout")
        async for token in self._ok.stream_chat(model, messages, tools=tools):
            yield token


@pytest.mark.asyncio
async def test_discuss_continues_when_one_advisor_times_out(tmp_path: Path):
    session = Session(default_offline_config(str(tmp_path)), root=tmp_path)
    session.client = _OneAdvisorTimeout()
    session.load_sample()
    ids: set[str] = set()
    errored: set[str] = set()
    async for event in session.discuss():
        ids.add(event.model_id)
        if "[error]" in event.text:
            errored.add(event.model_id)
    assert {"primary", "advisor-a", "advisor-b"} <= ids
    assert "advisor-b" in errored
    assert "primary" not in errored
    assert "advisor-a" not in errored
    assert session.state.phase is Phase.DISCUSS


@pytest.mark.asyncio
async def test_stream_parallel_isolates_advisor_failure():
    cfg = default_offline_config()
    client = _OneAdvisorTimeout()
    messages = {m.id: [{"role": "user", "content": "hi"}] for m in cfg.all_models()}
    tools = {m.id: [] for m in cfg.all_models()}
    seen: dict[str, str] = {}
    async for event in stream_parallel(client, cfg.all_models(), messages, tools):
        seen[event.model_id] = seen.get(event.model_id, "") + event.text
    assert "[error]" in seen["advisor-b"]
    assert "timeout" in seen["advisor-b"].lower()
    assert "[error]" not in seen["primary"]
    assert seen["advisor-a"]


def test_load_example_config(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("PRD_AI_GATEWAY_URL", raising=False)
    src = Path("config.example.yaml")
    cfg = load_config(src, offline=True)
    assert cfg.primary.id == "primary"
    assert cfg.advisors
    assert cfg.primary.resolved_base_url(cfg.gateway) == "https://xixiapi.io/v1"
