# AI Teacher protocol

This is the contract for the student-portal whiteboard. The AI service plans a lesson, speaks in short sentences, and emits board actions the frontend draws. Students never see the model's private notes or the answer key.

Protocol version: `1.0`. `GET /api/v1/ai/teacher/protocol` returns the JSON Schema for one board action.

## Auth

Every route uses the same bearer token as the rest of the AI API (Cognito, or a School backend HS256 session token). The token's `school_id` is the tenant. Row level security also checks `app.user_id`:

| Role | Read a lesson | Send messages / resume |
| --- | --- | --- |
| Student | Their own lessons | Yes |
| Parent | Lessons whose guardian list contains them | No |
| Teacher | Lessons whose teacher list contains them | No |
| School or platform admin | No | No |

Guardian and teacher ids come from the Core learning context (`guardians`, `teachers`) when the student starts the lesson, and again on each student turn and on resume. The client cannot supply those ids. A parent or teacher linked after the last student turn cannot see that lesson until the student opens it again.

## Endpoints

Base path: `/api/v1/ai/teacher`

| Method | Path | Body | Result |
| --- | --- | --- | --- |
| `GET` | `/protocol` | | `{ "version": "1.0", "schema": { ... } }` |
| `POST` | `/sessions` | `StartSessionRequest` | `201` `TurnResponse`, or `201` SSE if `stream` is true |
| `GET` | `/sessions` | | Lesson list for the caller |
| `GET` | `/sessions/{id}` | | Session plus board replay |
| `POST` | `/sessions/{id}/messages` | `MessageRequest` | `TurnResponse`, or SSE if `stream` is true |
| `POST` | `/sessions/{id}/stream` | `MessageRequest` | SSE playback of that turn |
| `POST` | `/sessions/{id}/resume` | | Session detail. Students only. Reopens a paused or finished lesson. |
| `WS` | `/sessions/{id}/live` | First frame `{ "message": "...", "pace": false }` | Same events as SSE, one JSON object per frame |

`StartSessionRequest` and `MessageRequest`:

```json
{
  "message": "Please teach me fractions",
  "subject_id": null,
  "title": null,
  "stream": false,
  "pace": false
}
```

`subject_id` and `title` exist only on start. `message` is 1–4000 characters.

`pace: true` makes the server sleep between events (capped at 8 seconds per gap and 90 seconds total). Leave it false and play `at_ms` / `delay_ms` on the client. That is the timing the board should follow.

## One student turn

The graph is LangGraph, one invocation per message:

1. **understand** — school topic, off-topic chat, or a refusal.
2. **plan** — topic, goals, prerequisites, and steps. Only when the lesson has not been planned yet, or the previous lesson already finished.
3. **teach** — student-facing explanation plus board actions for the current step.
4. **check** — one question (`ask` or `quiz`). The turn ends here so the student can answer.
5. On the next message, **grade** the answer. A miss **adapts** and re-explains the same step. Two misses, or a correct answer, move on. After the last step, **summarise** and mark the session completed.

A correct short answer such as `2` is graded. It is not treated as a new topic. Off-topic chat such as a game request is redirected with no board. Harmful requests get a fixed refusal and no board actions. The reply does not repeat the request.

`phase` on the turn is `check`, `summarise`, `refuse`, or `redirect`.

## SSE and WebSocket events

SSE frames:

```
event: meta
data: {"type":"meta","at_ms":0,"delay_ms":0,"session_id":"...","phase":"check","step_index":0,"protocol":"1.0","refused":false,"redirected":false}

event: chat
data: {"type":"chat","at_ms":0,"delay_ms":0,"content":"A fraction names equal parts of a whole."}

event: narration
data: {"type":"narration","at_ms":0,"delay_ms":0,"text":"...","duration_ms":4200,"page_id":"...","action_id":"...","voice":null}

event: board
data: {"type":"board","at_ms":800,"delay_ms":800,"action":{"type":"write_text","id":"...","page_id":"...","at_ms":800,"text":"Fractions","x":0.08,"y":0.1,"size":"lg","color":"#111827"}}

event: check
data: {"type":"check","at_ms":4200,"delay_ms":0,"prompt":"What is the denominator in one half?","kind":"ask","choices":[]}

event: done
data: {"type":"done","at_ms":4200,"delay_ms":0,"session_id":"...","message_id":"...","phase":"check"}
```

Play events in order. `at_ms` is the clock for that turn, starting at 0. `delay_ms` is the gap from the previous event. Chat sentences and board actions share that clock so speech and drawing stay together.

- Speak `narration` events. Do not also speak a board action.
- Draw every `board` event. Narration is not repeated as a `board` event.
- Show `check` as the question. Quiz `choices` are the options. The correct answer is not in the stream.
- `voice` is `null`, or `{ "provider", "mime_type", "audio_base64", "duration_ms", "sample_rate" }`.

WebSocket auth is `Authorization: Bearer ...` or `?token=`. The socket then waits for one client frame with `message`. Error frames are `{ "type": "error", "message": "..." }` and the socket closes with `1008`.

The JSON `TurnResponse` includes the same `events` array plus `chat_text`, `actions`, `phase`, `awaiting_check`, and `check_prompt`.

## Board actions

Coordinates are fractions of the board: `0` is the top-left, `1` is the bottom-right. `page_id` in a model draft may be `"current"`. Stored and streamed actions use real page ids. `id` identifies the mark so a later `highlight` or `clear_region` can point at it.

Colors are `#RRGGBB`.

### write_text

```json
{"type":"write_text","id":"...","page_id":"...","at_ms":400,"text":"The denominator is the bottom number.","x":0.08,"y":0.22,"size":"md","color":"#111827"}
```

`size` is `sm`, `md`, or `lg`.

### write_math

LaTeX. File and shell commands (`\input`, `\write`, `\include`, and similar) are rejected.

```json
{"type":"write_math","id":"...","page_id":"...","at_ms":800,"latex":"\\frac{1}{2}","x":0.08,"y":0.48,"display":true}
```

### draw_shape

`shape` is `line`, `arrow`, `rect`, `circle`, or `path` (freehand). Lines, arrows, and paths need at least two `points`. A rect needs `x`, `y`, `w`, `h`. A circle needs `x`, `y`, `r`.

```json
{"type":"draw_shape","id":"...","page_id":"...","at_ms":1200,"shape":"arrow","points":[{"x":0.12,"y":0.55},{"x":0.42,"y":0.55}],"stroke":"#111827"}
```

### plot_function

`expression` uses `x`, `+ - * / ^`, and `sin`, `cos`, `sqrt`, `abs`. The server fills `samples` (`x` / `y`, `y` null where the expression breaks). Do not evaluate the expression in the browser.

```json
{"type":"plot_function","id":"...","page_id":"...","at_ms":1600,"expression":"x^2","x_min":-4,"x_max":4,"x_label":"x","y_label":"y","samples":[{"x":-4,"y":16}],"x":0.08,"y":0.4,"w":0.55,"h":0.4}
```

### graph

A chart that is not a function plot. `kind` is `line`, `bar`, or `nodes`.

```json
{"type":"graph","id":"...","page_id":"...","at_ms":1600,"title":"Parts","kind":"bar","series":[{"name":"shaded","points":[{"x":1,"y":1},{"x":2,"y":1}]}],"nodes":[],"edges":[],"x":0.08,"y":0.4,"w":0.6,"h":0.4}
```

Node diagrams use `nodes` (`id`, `label`, `x`, `y`) and `edges` (`source`, `target`, `label`).

### place_icon

`library` is `lucide`, `phosphor`, or `emoji`. `name` is kebab-case (`lightbulb`, `book-open`). The frontend maps the name in that library. The API does not ship icon files.

```json
{"type":"place_icon","id":"...","page_id":"...","at_ms":200,"library":"lucide","name":"lightbulb","x":0.8,"y":0.1}
```

### place_image

`source` is `searched` or `generated`. `url` may be null. When it is set, it is `https` on an allowed host (Wikimedia by default). `alt` is the description to show if the image is missing.

```json
{"type":"place_image","id":"...","page_id":"...","at_ms":1400,"source":"searched","query":"one half shaded circle","alt":"A circle split into two equal parts, one shaded.","url":"https://upload.wikimedia.org/wikipedia/commons/thumb/example.jpg","x":0.58,"y":0.4,"w":0.34,"h":0.34}
```

### highlight and clear_region

`target_id` points at an earlier action. A region uses `x`, `y`, `w`, `h`. A highlight needs one of those. A clear with neither target nor region clears the page.

```json
{"type":"highlight","id":"...","page_id":"...","at_ms":1800,"target_id":"<write_text id>","color":"#fde68a"}
```

```json
{"type":"clear_region","id":"...","page_id":"...","at_ms":100,"x":0.05,"y":0.05,"w":0.9,"h":0.9}
```

### new_page

Opens a page. Following actions in that step use its `page_id`.

```json
{"type":"new_page","id":"...","page_id":"<new page id>","at_ms":0,"title":"See one half"}
```

### narration

The spoken line for this step. `duration_ms` matches the speech clock (about 380 ms per word) or the audio clip when voice is attached. Replay stores this action. The live `narration` event is what the client should speak. Audio bytes are not stored.

```json
{"type":"narration","id":"...","page_id":"...","at_ms":0,"text":"A fraction names equal parts of a whole.","duration_ms":4200,"voice_provider":"gemini_live"}
```

## Replay

`GET /sessions/{id}` returns `pages`, `actions`, `messages`, `progress`, and `plan`.

Sort `actions` by `seq` (already sorted). Group by `turn_index`. Within a turn, play by `at_ms`. The Nth assistant message (`turn_index` starting at 1) matches that group. Replay has narration text and timing, not audio bytes. Speak the text again, or play a fresh clip if you call a turn with `stream`.

`plan.steps` include `expected_answer` for parents and teachers. Students do not receive it. `reasoning` is never returned.

`progress` entries are `{ "concept", "status", "score" }`. `status` is `mastered` or `needs_review`.

## Voice

`VOICE_PROVIDER=auto` uses Gemini Live when `GEMINI_API_KEY` is set, otherwise Qwen when `QWEN_VOICE_API_KEY` is set. Gemini Live audio is PCM 16-bit mono at 24000 Hz (`audio/pcm;rate=24000`). If neither provider returns audio, `voice` is null and `duration_ms` still times the text.

## Errors

| HTTP | code | When |
| --- | --- | --- |
| 401 | `unauthorized` | Missing or bad token |
| 403 | `forbidden` | A parent, teacher, or admin tries to start, send, or resume |
| 404 | `not_found` | The lesson is not visible to this user |
| 429 | `rate_limited` | Lesson turns exceed `TEACHER_RATE_LIMIT_PER_MINUTE` (default 20), on top of the API limit |
| 422 | `validation_error` | Bad JSON body |

## What this version does not do

- There was no LangGraph graph in the service before this. This module is the teacher graph. It does not use a LangGraph checkpoint table; the session row stores the phase, step, and pending answer.
- No image generator is configured. `place_image` with `source: "generated"` keeps `url` null unless a later provider fills an allowed https URL. Searched images use the Wikimedia Commons API when the network call succeeds.
- Replay does not include audio. Only the live turn attaches a voice clip.
- The WebSocket is one student message, then the teacher events. It is not a full-duplex microphone bridge to Gemini Live.
- Core must return `guardians` and `teachers` on the AI context payload. If those lists are empty, only the student can open the lesson.
- Admins do not get a school-wide view of student lessons.
