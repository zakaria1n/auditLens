# Phase 2 — controlled real-provider evaluation

Date: 2026-11-21. Provider: `opencode-cli`, model `big-pickle`.
The isolated FastAPI instance used commit `75347fd044d4` plus uncommitted
phase 2 changes. Its health endpoint reported prompt version
`composition-v2-2026-11-21-2` and prompt SHA-256
`28a6fcf4a369ba4a24dc77eef297c5e4b7a6e1b6ea92c189353f34b97fa4a5d7`.
No browser was used. An optional Vitest/jsdom contract test validated the
actual returned JSON through `validateComposition` and rendered `VizBlock`.

| Prompt | Actual result | Validation and persistence |
| --- | --- | --- |
| Explain the architecture of an AI Agent Harness with an interactive diagram. | One v2 block: heading, paragraph, two visualizations, section, caption. | Valid and rendered in jsdom; SSE text matched retrieved stored assistant text. |
| Explain an ERP order-to-cash workflow, including alternative paths. | Two v2 blocks, each with heading and visualization. | Both valid and rendered in jsdom; stored text matched stream. |
| Explain the difference between tool calling and agent orchestration with a visual comparison. | First call returned one malformed JSON block with extra closing data; no usable visual. A second independent conversation with the same prompt returned one v2 block with heading, two visualizations and caption. | First call failed JSON parsing and used textual fallback. Second call validated and rendered in jsdom; both stored texts matched streams. This retry was a new conversation, not the repair feature. |
| What is an AI Agent? | Text only; no visualization. | Stored text matched stream. |

Each conversation made one provider call and no audit tool calls. No model-assisted
repair was requested for these runs. Provider output and any temporary test data
are not included here. OpenCode CLI produces a completed response rather than
true token streaming; its free model availability is controlled by OpenCode.
These results do not establish reliability for other providers or visual quality
in a browser. Evidence-backed compositions are not supported in this phase.
