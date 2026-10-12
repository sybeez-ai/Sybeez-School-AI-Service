from types import SimpleNamespace
from uuid import uuid4

from src.modules.conversations.schemas import ConversationCreate
from src.modules.conversations.service import ConversationService


async def test_placeholder_student_id_is_not_written():
    user, school = uuid4(), uuid4()
    saved = {}

    class Repo:
        async def create(self, conv):
            saved["conv"] = conv
            return conv

    svc = ConversationService.__new__(ConversationService)
    svc.repo = Repo()
    auth = SimpleNamespace(user_id=user, school_id=school, role="TEACHER")
    await svc.create(auth, ConversationCreate(title="AI Teacher", mode="board"), student_id=user)
    assert saved["conv"].student_id is None
    real = uuid4()
    await svc.create(auth, ConversationCreate(title="AI Teacher", mode="board"), student_id=real)
    assert saved["conv"].student_id == real
