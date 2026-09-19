# Arabic Learning Hub (BeeHub)  — Build Spec

> **How to use this file:** save it in the repo root as `SPEC.md` and open Claude Code in that directory. First message: *"Read SPEC.md and build Phase 1. Ask me anything ambiguous before you start writing code."* Claude Code will keep referring back to it as the build progresses, which is why this is better than pasting it into chat once.

---

## 1. What this is

A single-user (initially) web app that acts as a hub for learning Modern Standard Arabic. The user uploads or registers their own learning materials — PDFs, books, poetry, videos, podcasts — and the app generates practice from *those specific materials*, grades the answers, and tracks progress against the CEFR scale (A1 → C2).

The core loop:

```
Resources  →  Learning (AI-generated practice)  →  Grading  →  Metrics + Review queue
     ↑                                                                    │
     └────────────────── informs difficulty of next practice ─────────────┘
```

**The thing that makes or breaks this product is the AI layer.** Question quality, grading accuracy and grammar feedback have to be genuinely good, or none of the metrics mean anything. Section 5 is the most important part of this spec — do not treat it as an afterthought or hand-wave the prompts.

---

## 2. Tabs

### 2.1 Home (dashboard)
Landing page after login.
- Today's suggested tasks (pulled from the review queue + current resource progress)
- Streak counter
- Current CEFR estimate with a small trend sparkline
- Top 3 current weak spots (from error tags)
- Quick-start buttons into the learning tab

### 2.2 Resources
The library. All practice is grounded in these.
- **Upload**: PDFs (stored, parsed, chunked, embedded)
- **Register without upload**: books, poetry collections, YouTube videos, podcasts — title, author, language level, optional URL
- **Optional position tracking**: current page number, or timestamp in minutes. This matters — practice should only be generated from material the user has actually reached. Never generate questions from page 200 if they're on page 40.
- Per-resource progress bar and per-resource stats (questions attempted, accuracy, vocab harvested)
- Tagging: topic, dialect/register (MSA, Classical, Levantine…), difficulty

### 2.3 Learning
The core tab. User picks a resource (or "all resources"), then picks a mode:

| Mode | Description |
|---|---|
| **Vocabulary** | Quizlet-style flashcards, plus a matching/pairs game. Vocab is harvested from the resources the user is actually reading, not a generic word list. |
| **Questions** | AI-generated from the selected resource: true/false, multiple choice, short written answer, comprehension questions ("who did X?"). Difficulty pinned to the user's current CEFR estimate. |
| **Essays** | Longer prompts tied to the resource's themes. User types in Arabic. Graded against a CEFR rubric. |
| **Speaking** | User speaks Arabic into the mic; audio is transcribed; the AI responds **in text** (no TTS — keeps cost down). Conversational prompts and follow-up questions tied to the resource. |
| **Upload an answer** | User writes on paper, photographs it, uploads. Vision model reads the Arabic handwriting and grades it the same way as typed input. |

Everything graded here writes to metrics and, on error, to the review queue.

### 2.4 Review
Spaced repetition. Not new material — only things previously got wrong.
- SM-2 or FSRS scheduling algorithm (FSRS is better; SM-2 is simpler — pick one and note the choice)
- Items are individual vocab words, grammar points, or error tags
- Resurfaces at expanding intervals until retired

### 2.5 Metrics
- **CEFR estimate** per skill: reading, writing, speaking, vocabulary. Not one blended number — the user will be uneven across skills and that's useful information.
- Confidence interval on the estimate. Early on it should say "A2, low confidence (12 graded items)" rather than pretending precision it doesn't have.
- **Error taxonomy breakdown**: which grammatical categories are failing (see §5.6)
- Vocabulary: total known, retention rate, words due for review
- Activity over time; per-resource completion

### 2.6 Settings
Target level, daily goal, active resources, dialect preference, model preferences (if exposed).

---

## 3. Tech stack

| Layer | Choice | Notes |
|---|---|---|
| Frontend | React + TypeScript, Vite | Deploy to **Vercel** |
| Styling | Tailwind | Needs solid RTL support — see §7 |
| Backend | **Python + FastAPI** | Deploy to **Railway** |
| Database | **Supabase** (Postgres) | Also provides auth and object storage |
| Vector search | **pgvector** inside the same Supabase Postgres | Do not add a separate vector DB. Unnecessary at this scale. |
| File storage | Supabase Storage | PDFs, uploaded answer photos, audio blobs |
| Auth | Supabase Auth | Email + magic link is fine |
| LLM | Anthropic Claude API, called directly | **No LangChain.** See §5.1 |
| Speech-to-text | Whisper (OpenAI API or self-hosted `faster-whisper`) | Arabic support is decent; test both |
| Background jobs | Railway worker + Postgres-backed queue, or Supabase Edge Functions | For PDF parsing/embedding, which is too slow for a request cycle |

### Why not LangChain
The AI work here is: send a well-constructed prompt with retrieved context, get structured JSON back, validate it. LangChain adds abstraction layers that make prompt debugging harder and version churn that breaks builds. Use the `anthropic` Python SDK directly. If you later need agentic multi-step tool loops, revisit — but not on day one.

### On MCP
Not needed for v1. MCP is for exposing tools to an AI across process boundaries. Here the backend *is* the tool layer — plain Python functions passed as tool definitions in the API call. Revisit only if you later want the tutor reaching into external systems.

---

## 4. Data model

Sketch; refine as needed but keep the shape.

```
users              id, email, target_level, daily_goal, dialect_pref, created_at
resources          id, user_id, title, author, type (pdf|book|poetry|video|podcast),
                   storage_path, url, level_hint, tags[], position_value,
                   position_unit (page|minute|percent), total_length
resource_chunks    id, resource_id, chunk_index, text, page_or_timestamp,
                   embedding vector(1536)
vocab_items        id, user_id, resource_id, arabic, root, pos, translation,
                   context_sentence, first_seen_at
attempts           id, user_id, resource_id, mode, item_type, prompt_text,
                   user_answer, input_method (typed|photo|speech),
                   raw_transcript, score, max_score, model_used, created_at
error_tags         id, attempt_id, category, subcategory, span, explanation, severity
review_queue       id, user_id, item_ref (vocab|error_tag), due_at, interval,
                   ease_factor, repetitions, retired_at
level_estimates    id, user_id, skill (reading|writing|speaking|vocab),
                   cefr_level, confidence, n_observations, computed_at
generated_items    id, resource_id, item_type, payload jsonb, source_chunk_ids[],
                   difficulty_cefr, created_at, human_flagged
```

Note `generated_items` — cache generated questions rather than regenerating on every view. Cuts cost substantially and makes the app feel faster.

---

## 5. The AI layer (read this section twice)

### 5.1 Structure

Create a `skills/` directory at the repo root. One markdown file per AI task. Each file is the complete, versioned specification for that task — instructions, constraints, few-shot examples, and the exact output schema. The Python code loads these files at runtime; **no prompt text lives inline in Python.**

```
skills/
  _shared/
    arabic-conventions.md       # diacritics, transliteration, root notation, RTL
    cefr-descriptors.md         # canonical CEFR can-do statements per level
    error-taxonomy.md           # the controlled vocabulary for error tags
    output-contract.md          # JSON-only rules, refusal behaviour, no preamble
  generate-vocab-items.md
  generate-comprehension-questions.md
  generate-essay-prompt.md
  grade-short-answer.md
  grade-essay.md
  tag-grammar-errors.md
  speaking-partner.md
  transcribe-cleanup.md
  estimate-cefr-level.md
  extract-vocab-from-chunk.md
```

Each skill file must contain, in this order:

1. **Role** — one paragraph, what this skill does and nothing else
2. **Inputs** — named, typed, with an example of each
3. **Constraints** — hard rules, written as imperatives
4. **Output schema** — a JSON Schema, plus one fully worked example
5. **Few-shot examples** — minimum 3, covering an easy case, a hard case, and an edge case
6. **Failure mode** — what to emit when the input is unusable (never guess, never invent content not in the source)

Alongside, create `tools/` with JSON tool definitions (the `tools` array passed to the API):

```
tools/
  search_resource_chunks.json    # semantic + keyword search over one resource
  get_user_level.json            # current CEFR estimate per skill
  get_recent_errors.json         # last N error tags, for targeting practice
  record_attempt.json            # write score + tags back to the DB
  get_vocab_due.json             # what's due in the review queue
```

Give the model tools rather than stuffing everything into context. Retrieval should be a tool call the model makes when it needs more of the source text, not a blind top-k dump.

### 5.2 Grounding is mandatory

Every generated question must cite the chunk IDs it came from. Store them in `generated_items.source_chunk_ids`. If the model cannot ground a question in retrieved text, it must not produce the question. **Hallucinated comprehension questions about a book the user is reading are worse than no questions at all** — the user will answer correctly from the text and be marked wrong.

Enforce this in code: reject any generated item whose `source_chunk_ids` is empty or references chunks not in the retrieval set.

Respect `position_value`. Only retrieve chunks at or before the user's current page/timestamp.

### 5.3 Model routing

Current Claude models and list prices (verify at `claude.com/pricing` before committing to a budget — these change):

| Model | ID | Input / Output per MTok |
|---|---|---|
| Haiku 4.5 | `claude-haiku-4-5-20251001` | $1 / $5 |
| Sonnet 5 | `claude-sonnet-5` | $3 / $15 |
| Opus 5 | `claude-opus-5` | $5 / $25 |

Route by how much judgement the task needs:

| Task | Model | Why |
|---|---|---|
| Vocab flashcard generation | Haiku 4.5 | Mechanical extraction |
| Vocab definition / translation check | Haiku 4.5 | Near-deterministic |
| True/false + MCQ generation | Sonnet 5 | Needs plausible distractors |
| Short-answer grading | Sonnet 5 | Semantic equivalence judgement |
| Comprehension question generation | Sonnet 5 | Needs genuine text understanding |
| **Essay grading** | **Opus 5** | Nuanced, CEFR-calibrated, highest-stakes |
| **Grammar error tagging** | **Opus 5** | Arabic morphology is hard; errors here poison the metrics |
| Speaking partner turns | Sonnet 5 | Conversational, latency-sensitive |
| CEFR level re-estimation | Opus 5 | Runs rarely; accuracy matters most |

Make the model per task configurable in one config file, not hardcoded at call sites, so routing can be tuned without a code change.

### 5.4 Cost controls

- **Prompt caching** on every skill file and every resource chunk set. Cache reads are ~90% cheaper than standard input. Put the static content — skill instructions, few-shot examples, shared reference files — at the *start* of the prompt and the variable content at the end. This matters more than model choice for total spend.
- **Batch API** (50% discount, 24h turnaround) for anything not user-facing: pre-generating question banks overnight, bulk vocab extraction after a PDF upload, periodic CEFR re-estimation.
- **Cache generated items** in Postgres. Never regenerate a question the user hasn't seen yet.
- Cap output tokens per task type. Grading does not need 2,000 tokens.

### 5.5 Structured output, always

Every skill returns JSON and nothing else — no preamble, no markdown fences. Validate every response against a Pydantic model. On validation failure, retry once with the validation error appended; on second failure, log and surface a graceful error to the user. Never render unvalidated model output into the UI.

### 5.6 Error taxonomy

Define this as a fixed controlled vocabulary in `skills/_shared/error-taxonomy.md`. The tagger must only emit categories from this list — free-text categories make the metrics tab useless because nothing aggregates.

Starting set (extend as needed):

- **Morphology**: verb conjugation (person/number/gender), verb form (I–X), derived nouns, broken plurals, dual forms
- **Syntax**: iḍāfa construction, adjective agreement, word order (VSO/SVO), particle usage, negation, conditional structures
- **Case marking (iʿrāb)**: nominative/accusative/genitive errors
- **Agreement**: gender, number, definiteness
- **Lexis**: wrong word choice, register mismatch, calque from English
- **Orthography**: hamza placement, tāʾ marbūṭa vs hāʾ, alif maqṣūra, diacritics
- **Discourse**: cohesion, connectives, paragraph structure

Each tag carries: category, subcategory, the offending text span, a one-sentence explanation *in English*, the correction, and a severity (minor / moderate / blocking).

### 5.7 CEFR estimation

Do not ask the model "what level is this user?" on each attempt — the estimate will jitter wildly.

Instead:
- Each graded attempt records a difficulty (the CEFR level the item was generated at) and a score
- Run a periodic (nightly, batched) estimation job that reads the last N attempts per skill and produces a level + confidence
- Use a simple IRT-style or Elo-style update rather than pure model judgement — the model's role is grading individual items well, not doing the statistics
- Surface confidence honestly in the UI; do not show "B1" off the back of four answers

`skills/estimate-cefr-level.md` handles the qualitative side: given a sample of recent work, which CEFR descriptors does this learner meet? Feed that alongside the numeric estimate.

### 5.8 Evals — build these before you build features

Create `evals/` with a golden set:
- 30+ Arabic sentences with known, human-verified errors → assert the tagger finds them and assigns the right category
- 15+ essays at known CEFR levels → assert the grader lands within one band
- 20+ short-answer pairs (correct-but-differently-worded, and subtly wrong) → assert the grader doesn't punish valid paraphrase or accept near-misses

Run them in CI on every change to a skill file. Without this, prompt tuning is guesswork and you will silently regress grading quality while thinking you improved it.

---

## 6. Build phases

**Phase 1 — foundation**
Auth, resources tab with PDF upload + parsing + chunking + embedding, position tracking, basic vocab flashcards, one question type (comprehension short-answer), grading with error tagging, minimal metrics. The full grounded generate→grade→tag loop working end to end for one mode. Evals in place.

**Phase 2 — breadth**
Remaining question types, matching game, essays with full CEFR grading, review queue with spaced repetition, full metrics tab, home dashboard.

**Phase 3 — speaking + capture**
Mic capture, Whisper transcription, conversational speaking partner, photo upload of handwritten answers with vision grading.

**Phase 4 — polish**
Multi-user hardening, cost telemetry dashboard, question quality flagging (let the user flag a bad generated question; those flags become eval cases).

---

## 7. Non-negotiables

- **RTL throughout.** Arabic text renders right-to-left with correct bidirectional handling where Arabic and English mix. Use `dir="rtl"` properly, not CSS hacks. Test with mixed-script strings early — this is painful to retrofit.
- **Arabic typography.** Use a proper Arabic webfont (Noto Naskh Arabic or similar). System defaults look wrong and hurt readability.
- **Diacritics are optional but preserved.** Store source text with whatever diacritics it has; normalise for search/matching, never for display.
- **Grading must never invent.** If the model can't ground a mark in the source text or an explicit rubric, it returns "unable to grade" rather than guessing.
- **Every model call is logged** with model, token counts, latency and cost, into a table. You cannot optimise spend you can't see.
- **Secrets in environment variables**, never committed. `.env.example` checked in, `.env` gitignored.

---

## 8. First message to Claude Code

> Read `SPEC.md`. Set up the repo skeleton: FastAPI backend, React+TS frontend, Supabase schema migrations, the `skills/` and `tools/` directories with stub files, and the evals harness. Then build Phase 1. Ask me about anything ambiguous before writing code — particularly around the chunking strategy and the grading rubric, where I'd rather decide than have you assume.