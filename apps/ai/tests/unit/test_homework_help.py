import pytest

from src.modules.homework_help import service as S

pytestmark = pytest.mark.asyncio


class Script:
    """Replies come from a list; the checker verdicts from another."""

    def __init__(self, replies, verdicts):
        self.replies, self.verdicts, self.calls = list(replies), list(verdicts), 0


@pytest.fixture
def fake(monkeypatch):
    def make(replies, verdicts):
        s = Script(replies, verdicts)

        async def complete(llm, *, system, user, **kw):
            s.calls += 1
            if system == S.CHECK_SYSTEM:
                return '{"gives_final_answer": %s}' % str(s.verdicts.pop(0)).lower()
            return s.replies.pop(0)

        monkeypatch.setattr(S, "guarded_complete", complete)
        monkeypatch.setattr(S, "_llm", lambda: object())
        return s

    return make


async def test_good_hint_passes(fake):
    fake(["What is 3 x 4? Try that first."], [False])
    r = await S.help_student(S.HelpRequest(question="12 + 3 x 4"))
    assert not r.held_back_answer and "3 x 4" in r.reply


async def test_answer_is_regenerated(fake):
    s = fake(["The answer is 24.", "Which operation comes first? Think BODMAS."], [True, False])
    r = await S.help_student(S.HelpRequest(question="12 + 3 x 4"))
    assert r.held_back_answer and "24" not in r.reply and s.calls == 4


async def test_persistent_leak_gets_safe_fallback(fake):
    fake(["It is 24.", "Answer: 24"], [True, True])
    r = await S.help_student(S.HelpRequest(question="12 + 3 x 4"))
    assert r.held_back_answer and "24" not in r.reply


async def test_unparseable_check_is_treated_as_unsafe(fake):
    fake(["It is 24.", "Hmm."], [True, True])
    assert (await S.help_student(S.HelpRequest(question="xx"))).held_back_answer
