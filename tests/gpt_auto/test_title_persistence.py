from types import SimpleNamespace
import pytest
from audiagentic.components.providers.adapters.gpt_auto.chat import PersistentChat
from audiagentic.components.providers.adapters.gpt_auto.config import GptAutoConfig
from audiagentic.components.providers.adapters.gpt_auto.prompt_fingerprint import PromptFingerprint
from .test_greenfield_config_urls import valid_config


def chat(sink, provider_id="conversation"):
    return PersistentChat(ag_session_id="session", project_name="project", project_url=None,
        runtime=SimpleNamespace(), config=GptAutoConfig.from_dict(valid_config()),
        binding_sink=sink, provider_session_id=provider_id)


@pytest.mark.asyncio
async def test_failed_persistence_does_not_suppress_retry():
    updates = []
    async def sink(update):
        updates.append(update)
        if len(updates) == 1:
            raise RuntimeError("temporary persistence failure")
    instance = chat(sink)
    with pytest.raises(RuntimeError):
        await instance.publish_conversation_title("Review")
    assert instance.conversation_title is None
    await instance.publish_conversation_title("Review")
    await instance.publish_conversation_title("Review")
    assert len(updates) == 2
    assert instance.conversation_title == "Review"


@pytest.mark.asyncio
async def test_pre_identity_title_remains_pending_not_persisted():
    updates = []
    instance = chat(updates.append, None)
    await instance.publish_conversation_title("Review")
    assert not updates
    assert instance.conversation_title is None
    assert instance._pending_conversation_title == "Review"
    instance.provider_session_id = "conversation"
    await instance.publish_conversation_title(instance._pending_conversation_title)
    assert updates[0].metadata == {"chat-title": "Review"}


@pytest.mark.asyncio
async def test_navigation_labels_never_replace_real_title():
    updates = []
    instance = chat(updates.append)
    await instance.publish_conversation_title("Review")
    await instance.publish_conversation_title("Skip to content")
    assert len(updates) == 1
    assert instance.conversation_title == "Review"


@pytest.mark.parametrize("suffix", ["\n", "\n\n", "\n \n\t\n", "\r\n\r\n"])
def test_trailing_blank_lines_do_not_block_prompt_proof(suffix):
    assert PromptFingerprint.from_text("Review the repo" + suffix).matches_text("Review the repo")


def test_meaningful_line_boundaries_still_differ():
    assert not PromptFingerprint.from_text("a\nb").matches_text("ab")


@pytest.mark.asyncio
@pytest.mark.parametrize("conversation,expected", [("conversation", 1), ("different", 0)])
async def test_snapshot_relays_only_its_own_conversation_title(conversation, expected):
    updates = []
    instance = chat(updates.append)
    class Browser:
        async def page_by_handle(self, handle):
            return SimpleNamespace(target_id="target")
        async def snapshot(self, page, **kwargs):
            return {"url": f"https://chatgpt.com/g/g-p-project/c/{conversation}", "conversationTitle": "Review"}
    instance.runtime.gpt_browser = Browser()
    instance.page_handle = "page"
    await instance.snapshot(allow_recovering=True)
    assert len(updates) == expected
