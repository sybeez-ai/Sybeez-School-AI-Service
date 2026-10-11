"""Whiteboard actions the student-portal frontend renders.

Coordinates are fractions of the board, from 0 at the top-left to 1 at the bottom-right.
The model must return these objects as JSON. `prepare_actions` fills plot samples and
rejects unsafe LaTeX and image URLs before anything is stored or streamed.
"""

import ast
import math
import re
import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator

PROTOCOL_VERSION = "1.0"

ACTION_TYPES = frozenset(
    {
        "write_text",
        "write_math",
        "draw_shape",
        "plot_function",
        "graph",
        "place_icon",
        "place_image",
        "highlight",
        "clear_region",
        "new_page",
        "narration",
    }
)

_LATEX_DENY = re.compile(
    r"\\(input|include|write18|write|openout|immediate|special|catcode|read|newread|verbatiminput)\b",
    re.IGNORECASE,
)
_EXPR_CHARS = re.compile(r"[0-9xX+\-*/^().,\sa-zA-Z]+")
_FUNCS = {"sin": math.sin, "cos": math.cos, "sqrt": math.sqrt, "abs": abs}


class ProtocolError(ValueError):
    """The model did not produce a valid board script after retries."""


class SamplePoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float
    y: float | None = None


class Point(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class _Action(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1, max_length=80)
    page_id: str = Field(default="current", min_length=1, max_length=80)
    at_ms: int = Field(default=0, ge=0)


class WriteText(_Action):
    type: Literal["write_text"] = "write_text"
    text: str = Field(min_length=1, max_length=2000)
    x: float = Field(default=0.08, ge=0, le=1)
    y: float = Field(default=0.12, ge=0, le=1)
    size: Literal["sm", "md", "lg"] = "md"
    color: str = Field(default="#111827", pattern=r"^#[0-9A-Fa-f]{6}$")


class WriteMath(_Action):
    type: Literal["write_math"] = "write_math"
    latex: str = Field(min_length=1, max_length=2000)
    x: float = Field(default=0.08, ge=0, le=1)
    y: float = Field(default=0.28, ge=0, le=1)
    display: bool = True


class DrawShape(_Action):
    type: Literal["draw_shape"] = "draw_shape"
    shape: Literal["line", "arrow", "rect", "circle", "path"]
    points: list[Point] = Field(default_factory=list)
    x: float | None = Field(default=None, ge=0, le=1)
    y: float | None = Field(default=None, ge=0, le=1)
    w: float | None = Field(default=None, ge=0, le=1)
    h: float | None = Field(default=None, ge=0, le=1)
    r: float | None = Field(default=None, ge=0, le=1)
    stroke: str = Field(default="#111827", pattern=r"^#[0-9A-Fa-f]{6}$")

    @model_validator(mode="after")
    def check_geometry(self):
        if self.shape in {"line", "arrow", "path"} and len(self.points) < 2:
            raise ValueError(f"{self.shape} needs at least 2 points")
        if self.shape == "rect" and None in (self.x, self.y, self.w, self.h):
            raise ValueError("rect needs x, y, w, h")
        if self.shape == "circle" and None in (self.x, self.y, self.r):
            raise ValueError("circle needs x, y, r")
        return self


class PlotFunction(_Action):
    type: Literal["plot_function"] = "plot_function"
    expression: str = Field(min_length=1, max_length=200)
    x_min: float = -5
    x_max: float = 5
    x_label: str = "x"
    y_label: str = "y"
    samples: list[SamplePoint] = Field(default_factory=list)
    x: float = Field(default=0.08, ge=0, le=1)
    y: float = Field(default=0.4, ge=0, le=1)
    w: float = Field(default=0.55, ge=0, le=1)
    h: float = Field(default=0.4, ge=0, le=1)


class GraphSeries(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    points: list[SamplePoint] = Field(min_length=1)


class GraphNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=80)
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class GraphEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=64)
    target: str = Field(min_length=1, max_length=64)
    label: str = ""


class GraphDiagram(_Action):
    type: Literal["graph"] = "graph"
    title: str = ""
    kind: Literal["line", "bar", "nodes"] = "line"
    series: list[GraphSeries] = Field(default_factory=list)
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    x: float = Field(default=0.08, ge=0, le=1)
    y: float = Field(default=0.4, ge=0, le=1)
    w: float = Field(default=0.6, ge=0, le=1)
    h: float = Field(default=0.4, ge=0, le=1)

    @model_validator(mode="after")
    def check_graph(self):
        if self.kind in {"line", "bar"} and not self.series:
            raise ValueError("line and bar graphs need series")
        if self.kind == "nodes" and not self.nodes:
            raise ValueError("node graphs need nodes")
        return self


class PlaceIcon(_Action):
    type: Literal["place_icon"] = "place_icon"
    library: Literal["lucide", "phosphor", "emoji"] = "lucide"
    name: str = Field(pattern=r"^[a-z0-9-]+$")
    x: float = Field(default=0.78, ge=0, le=1)
    y: float = Field(default=0.1, ge=0, le=1)


class PlaceImage(_Action):
    type: Literal["place_image"] = "place_image"
    source: Literal["generated", "searched"]
    query: str = Field(min_length=1, max_length=200)
    alt: str = Field(min_length=1, max_length=300)
    url: str | None = None
    x: float = Field(default=0.58, ge=0, le=1)
    y: float = Field(default=0.18, ge=0, le=1)
    w: float = Field(default=0.34, ge=0, le=1)
    h: float = Field(default=0.34, ge=0, le=1)


class Highlight(_Action):
    type: Literal["highlight"] = "highlight"
    target_id: str | None = None
    x: float | None = Field(default=None, ge=0, le=1)
    y: float | None = Field(default=None, ge=0, le=1)
    w: float | None = Field(default=None, ge=0, le=1)
    h: float | None = Field(default=None, ge=0, le=1)
    color: str = Field(default="#fde68a", pattern=r"^#[0-9A-Fa-f]{6}$")

    @model_validator(mode="after")
    def check_target(self):
        has_box = None not in (self.x, self.y, self.w, self.h)
        if not self.target_id and not has_box:
            raise ValueError("highlight needs a target_id or a region")
        return self


class ClearRegion(_Action):
    type: Literal["clear_region"] = "clear_region"
    target_id: str | None = None
    x: float | None = Field(default=None, ge=0, le=1)
    y: float | None = Field(default=None, ge=0, le=1)
    w: float | None = Field(default=None, ge=0, le=1)
    h: float | None = Field(default=None, ge=0, le=1)


class NewPage(_Action):
    type: Literal["new_page"] = "new_page"
    title: str = Field(default="Board", max_length=120)


class Narration(_Action):
    type: Literal["narration"] = "narration"
    text: str = Field(min_length=1, max_length=4000)
    duration_ms: int = Field(default=0, ge=0)
    voice_provider: str | None = None


BoardAction = Annotated[
    WriteText
    | WriteMath
    | DrawShape
    | PlotFunction
    | GraphDiagram
    | PlaceIcon
    | PlaceImage
    | Highlight
    | ClearRegion
    | NewPage
    | Narration,
    Field(discriminator="type"),
]

_ACTION_ADAPTER = TypeAdapter(BoardAction)


class LessonStep(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str = Field(min_length=1, max_length=120)
    goal: str = Field(min_length=1, max_length=400)
    explanation: str = Field(min_length=1, max_length=2000)
    example: str = ""
    check_prompt: str = Field(min_length=1, max_length=400)
    check_kind: Literal["ask", "quiz"] = "ask"
    choices: list[str] = Field(default_factory=list)
    expected_answer: str = Field(min_length=1, max_length=200)
    board: Literal["intro", "example", "practice", "summary"] = "intro"


class LessonPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reasoning: str = ""
    topic: str = Field(min_length=1, max_length=160)
    goals: list[str] = Field(min_length=1, max_length=6)
    prerequisites: list[str] = Field(min_length=1, max_length=6)
    steps: list[LessonStep] = Field(min_length=1, max_length=6)


class StepScript(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reasoning: str = ""
    chat: str = Field(min_length=1, max_length=4000)
    actions: list[BoardAction] = Field(min_length=1, max_length=12)
    check_prompt: str = ""
    check_kind: Literal["ask", "quiz"] = "ask"
    choices: list[str] = Field(default_factory=list)
    expected_answer: str = ""

    @model_validator(mode="after")
    def needs_narration(self):
        if not any(getattr(action, "type", None) == "narration" for action in self.actions):
            raise ValueError("actions must include narration")
        return self


def board_action_schema() -> dict:
    return _ACTION_ADAPTER.json_schema()


def validate_action(payload: dict) -> BoardAction:
    try:
        return _ACTION_ADAPTER.validate_python(payload)
    except ValidationError as exc:
        raise ProtocolError(str(exc)) from exc


def clean_latex(value: str) -> str:
    if _LATEX_DENY.search(value):
        raise ValueError("latex command not allowed")
    return value


def image_url_allowed(url: str, hosts: set[str]) -> bool:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host:
        return False
    if host in hosts:
        return True
    return host.endswith(".wikimedia.org")


def ensure_image_url(url: str, hosts: set[str] | None = None) -> str:
    from src.core.config import get_settings

    allowed = hosts if hosts is not None else get_settings().image_hosts
    if not image_url_allowed(url, allowed):
        raise ValueError("image url must be https on an allowed educational host")
    return url


class _MathEval(ast.NodeVisitor):
    def __init__(self, x: float):
        self.x = x

    def visit_Expression(self, node):
        return self.visit(node.body)

    def visit_Constant(self, node):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("only numbers")
        return float(node.value)

    def visit_Name(self, node):
        if node.id == "x":
            return self.x
        raise ValueError("only x is allowed")

    def visit_UnaryOp(self, node):
        value = self.visit(node.operand)
        if isinstance(node.op, ast.UAdd):
            return value
        if isinstance(node.op, ast.USub):
            return -value
        raise ValueError("operator")

    def visit_BinOp(self, node):
        left = self.visit(node.left)
        right = self.visit(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            if right == 0:
                raise ZeroDivisionError
            return left / right
        if isinstance(node.op, ast.Pow):
            if abs(right) > 8:
                raise ValueError("exponent")
            return left**right
        raise ValueError("operator")

    def visit_Call(self, node):
        if not isinstance(node.func, ast.Name) or node.keywords or len(node.args) != 1:
            raise ValueError("function")
        func = _FUNCS.get(node.func.id)
        if func is None:
            raise ValueError("function")
        return func(self.visit(node.args[0]))

    def generic_visit(self, node):
        raise ValueError("expression")


def safe_math(expr: str, x: float) -> float:
    if len(expr) > 200 or not _EXPR_CHARS.fullmatch(expr.strip()):
        raise ValueError("expression")
    tree = ast.parse(expr.replace("^", "**"), mode="eval")
    return float(_MathEval(x).visit(tree))


def sample_expression(expr: str, x_min: float, x_max: float, count: int = 21) -> list[dict]:
    if not math.isfinite(x_min) or not math.isfinite(x_max) or x_max <= x_min:
        raise ValueError("x_max must be greater than x_min")
    count = min(max(int(count), 2), 64)
    points: list[dict] = []
    for index in range(count):
        x = x_min + (x_max - x_min) * index / (count - 1)
        try:
            y = safe_math(expr, x)
        except (ValueError, ZeroDivisionError, OverflowError):
            y = None
        if y is None or not math.isfinite(y) or abs(y) > 1_000_000:
            points.append({"x": round(x, 4), "y": None})
        else:
            points.append({"x": round(x, 4), "y": round(y, 4)})
    if not any(point["y"] is not None for point in points):
        raise ValueError("expression could not be plotted")
    return points


def prepare_actions(actions: list[BoardAction]) -> list[BoardAction]:
    prepared: list[BoardAction] = []
    for action in actions:
        if isinstance(action, WriteMath):
            action = action.model_copy(update={"latex": clean_latex(action.latex)})
        elif isinstance(action, PlotFunction):
            samples = action.samples or [SamplePoint.model_validate(point) for point in sample_expression(action.expression, action.x_min, action.x_max)]
            action = action.model_copy(update={"samples": samples})
        elif isinstance(action, PlaceImage) and action.url:
            ensure_image_url(action.url)
        prepared.append(action)
    return prepared


def dump_action(action: BoardAction) -> dict:
    return action.model_dump(mode="json")
