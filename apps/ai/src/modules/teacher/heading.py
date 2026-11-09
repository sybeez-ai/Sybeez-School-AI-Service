"""Keep the board heading on the lesson the student is in right now."""

from uuid import uuid4


def _same(left: str, right: str) -> bool:
    return left.strip().lower() == right.strip().lower()


def align_board_heading(actions: list[dict], topic: str, *, previous_title: str = "") -> list[dict]:
    """Put this turn on a page titled with the current topic.

    A new topic must not keep the previous lesson's title. Actions stay on the
    new page so the heading and the drawing match.
    """
    title = (topic or "").strip()[:120]
    if not title:
        return actions
    if previous_title and _same(previous_title, title):
        return [dict(action) for action in actions]
    new_id = str(uuid4())
    heading = {
        "type": "new_page",
        "id": str(uuid4()),
        "page_id": new_id,
        "title": title,
        "at_ms": 0,
    }
    moved: list[dict] = [heading]
    for action in actions:
        item = dict(action)
        if item.get("type") == "new_page":
            # One heading for this turn. Drop the model's extra page breaks
            # so the title cannot stay on the previous lesson.
            continue
        item["page_id"] = new_id
        moved.append(item)
    return moved
