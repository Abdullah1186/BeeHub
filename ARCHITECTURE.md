# BeeHub — how this repo works

A guide to the codebase as it stands: what each piece does, why it is shaped
that way, and which decisions departed from `BeehubSpec.md`.

For *what the product is*, read the spec. This document is about the build.

---

## 1. The one-paragraph version

You upload Arabic learning material. It is extracted, checked for extraction
damage, split into page-bounded chunks, and embedded. When you practise, the app
picks a passage **you have actually read**, asks Claude to write a question
grounded in that passage, and grades your answer against key points that were
extracted at generation time. Every mark is computed in Python from the model's
discrete verdicts, never taken as a number from the model.

---

## 2. The core loop

```
┌──────────┐   upload    ┌──────────────┐   queue    ┌──────────┐
│  You     │────────────▶│  FastAPI     │───────────▶│  worker  │
└──────────┘             │  /resources  │            └────┬─────┘
                         └──────────────┘                 │
                                                          ▼
                    ┌─────────────────────────────────────────────┐
                    │  extract → normalise → QUALITY GATE → chunk │
                    └──────────────────┬──────────────────────────┘
                                       │ passed?
                         ┌─────────────┴──────────────┐
                        no                           yes
                         │                            │
                         ▼                            ▼
                 ingest_status =              resource_chunks
                 'failed', 0 chunks           (+ embeddings)
                 NOTHING generated                    │
                                                      ▼
                                          ┌───────────────────────┐
                                          │  POSITION GATE (§5.2) │
                                          │  page_end <= position │
                                          └───────────┬───────────┘
                                                      ▼
                                       select_chunk_window (contiguous)
                                                      │
                                                      ▼
                                       ┌──────────────────────────┐
                                       │ Claude: generate question│
                                       │ + key_points + quotes    │
                                       └──────────┬───────────────┘
                                                  │
                                    grounding check: every quote
                                    must be verbatim in the passage
                                                  │
                                                  ▼
                                          generated_items (cached)
                                                  │
                          you answer ─────────────┤
                                                  ▼
                                       ┌──────────────────────────┐
                                       │ Claude: grade + tag      │
                                       │ verdicts, not a score    │
                                       └──────────┬───────────────┘
                                                  ▼
                                       compute_score()  ← Python
                                                  │
                                    ┌─────────────┼─────────────┐
                                    ▼             ▼             ▼
                               attempts      error_tags    model_calls
                             (content +      (taxonomy)     (cost log)
                              language)
```

Two properties this shape is built to guarantee:

1. **A question can only come from material you have reached.** Enforced in SQL,
   in one function, re-checked at serve time.
2. **A question can only come from text that actually exists.** Every key point
   carries a verbatim quote, checked as a substring before the item is stored.

---

## 3. Repo layout

```
BeeHub/
├── apps/web/               React + TS + Vite frontend (Vercel)
│   ├── src/lib/            supabase client, typed API client
│   ├── src/components/     Auth, Resources, Practice
│   └── public/fonts/       Noto Naskh Arabic, self-hosted
│
├── apps/api/               FastAPI backend — a self-contained deployable
│   ├── app/                Python package
│   │   ├── ingest/         PDF → text → quality gate → chunks
│   │   ├── retrieval/      gated chunk selection
│   │   ├── embeddings/     Voyage provider (+ deterministic fake)
│   │   ├── ai/             Claude client, routing, pricing
│   │   ├── schemas/        Pydantic models = the model's output contract
│   │   ├── grading/        score arithmetic (pure functions)
│   │   ├── skills/         the LOADER for skill files (not the files)
│   │   ├── api/            HTTP endpoints
│   │   └── worker.py       ingestion job runner
│   ├── skills/             ALL prompt text lives here (§5.1)
│   │   ├── _shared/        conventions, CEFR, taxonomy, output contract
│   │   ├── generate-comprehension-questions.md
│   │   └── grade-short-answer.md
│   ├── config/models.yaml  model routing, no prompt text
│   └── tests/              142 tests, no network, no API key
│
├── evals/                  measurement harness
│   ├── cases/              62 golden cases with known-correct outcomes
│   ├── cassettes/          recorded responses → replay is free
│   ├── baselines/          per-case pass record → regression detection
│   └── runner.py
│
├── supabase/
│   ├── migrations/         schema, RLS, gate functions
│   ├── tests/gate_test.sql the §5.2 guarantee, attacked
│   └── local/              auth stub for offline testing
│
└── .github/workflows/      free CI + gated paid CI

> **Why skills/ sits inside apps/api rather than at the repo root** (departing
> from the spec's layout): the backend is the only thing that needs them at
> runtime, so keeping them inside makes it a self-contained deployable. Path
> resolution is then a fixed `parents[1]`, with no discovery logic, no env vars,
> and no build-context requirements. An earlier root-level layout resolved
> paths by climbing `parents[3]`, which worked locally and would have broken on
> any deployment whose build context was `apps/api/` — booting green and failing
> on the first practice request.
```

---

## 4. The parts that carry weight

### 4.1 The quality gate — `app/ingest/quality.py`

The highest-risk failure in the system is a PDF that extracts as garbage, gets
chunked, and produces confident questions about text that is not what the book
says. You answer correctly from the page and are marked wrong.

So extraction is **gated**, not trusted:

```
        extract
           │
           ▼
   NFKC normalise ──── repairs presentation forms (U+FExx → base letters)
           │
           ▼
   ┌───────────────────────────────────────────┐
   │ arabic ratio        < 0.15  → scan/empty  │
   │ presentation forms  > 0.02  → bad encoding│
   │ mean word length    > 25    → no spaces   │
   │ reversed order      > 0.40  → visual order│
   │ mirrored text       > 0.50  → char mirror │
   │ fragmentation       > 0.20  → split words │
   │ orphan diacritics   > 0.30  → detached    │
   └───────────────┬───────────────────────────┘
                   ▼
        ok  │  degraded  │  failed
             practice     NO chunks
             + warning    NO generation
```

Two of these detectors exist because real PDFs failed in ways the others missed:

- **Mirrored text.** A generated Arabic PDF extracted fully reversed — word order
  *and* letters within each word. The word-position heuristic could not see it,
  because reversing a line also reverses the particles it looks for (`في` → `يف`).
  Detected morphologically: Arabic words overwhelmingly start with `ال` and end
  with `ة`/`ى`, and reversal inverts that distribution. Scores 0.93 on mirrored
  text, 0.0 on correct Arabic.

- **Intra-word fragmentation.** A real poetry PDF passed every check while 11% of
  its tokens were single letters — `فَقُلْتُ` had become `فَق لْت`. The glyphs and
  their order were fine; only token counting reveals it.

> **Never "fix" apparently-backwards Arabic by reversing it.** Extractors return
> logical order; reversing again produces double-reversed text that looks
> plausible and is wrong. Detect and quarantine instead.

### 4.2 The position gate — `supabase/migrations/0003_functions.sql`

Spec §5.2: never generate from material past where the learner has reached.

```sql
resolve_max_page(resource, user)
  ├─ not your resource      → -1   (expose nothing)
  ├─ position_value IS NULL → MAX  (untracked, all fair game)
  └─ position_value = N     → N
```

Everything funnels through that one function. It is deliberately **not**
reimplemented in Python: two implementations drift, and one of them eventually
leaks.

It is re-applied at **serve** time as well as generation time, because you can
move your position *backwards* — an item generated when you were further ahead
must stop being served.

`supabase/tests/gate_test.sql` attacks it: 1000 random selections, cross-user
access, position rollback, window contiguity, and the grounding constraint.

> **A bug this caught:** `array_length('{}', 1)` returns NULL, not 0 — and a
> Postgres CHECK that evaluates to NULL **passes**. The grounding constraint was
> silently inert and accepted ungrounded items. `cardinality()` is the correct
> form.

### 4.3 Retrieval is contiguous, not top-k — `app/retrieval/selector.py`

Question generation does **not** use vector search.

There is no query when the task is "ask me about what I just read". Top-k
similarity returns semantically related but narratively *disconnected* fragments
— exactly the input that produces incoherent comprehension questions.

Instead: a contiguous run of chunks, weighted toward recent pages.

> **A bug this caught:** the first recency weighting (`chunk_index * random()`)
> put 99.3% of draws in the last ten pages; pages 1–20 were never selected in
> 2000 draws. Review of earlier material was impossible. Now a mixture — 60%
> from the recent third, else uniform — giving ~20% early / ~80% recent.

Embeddings are used for vocab context and Phase 2 thematic search. They live in
exactly one table: `resource_chunks.embedding`, `vector(1024)`.

### 4.4 Grading: verdicts from the model, numbers from Python

```
generation time ──▶ key_points: [{id, text, source_quote}]
                         │        (each quote verbatim in the passage)
                         ▼
grading time  ──▶ per key point: conveyed │ partially │ absent │ contradicted
                  plus error tags from a CLOSED taxonomy
                         │
                         ▼
compute_score()  ──▶ content_score   (→ reading CEFR)
                     language_score  (→ writing CEFR)
                     final_score
```

Three decisions encoded here:

**Key points come from generation, not grading.** The grader only decides whether
each was conveyed — far more repeatable than "grade this answer", and it costs
nothing extra.

**`contradicted` ≠ `absent`.** Saying the opposite is a comprehension failure;
saying nothing is an omission. A four-value enum catches near-misses that a
boolean would miss entirely.

**Minor errors cost nothing.** A learner who conveys the meaning with a hamza slip
has comprehended. The error is still tagged and still feeds metrics and the
review queue — it just does not reduce the mark. This is the fair-to-paraphrase
guarantee, enforced in code rather than requested in a prompt.

The model's own holistic score is recorded but **never used**. When it disagrees
with the computed score by more than 0.3, the attempt is flagged — and those
flags become free eval cases.

### 4.5 Skills — `skills/*.md`, loaded by `app/skills/loader.py`

All prompt text lives in markdown. No prompt strings in Python (§5.1).

```
error-taxonomy.yaml ─┬─▶ taxonomy.py  → closed StrEnums (Pydantic)
                     └─▶ loader.py    → rendered into the prompt
```

One file feeds both, so the enum and the prompt cannot drift. A test asserts
every enum member appears in the rendered prompt — the model cannot emit what it
was never shown.

**`prompt_hash` is sha256 of the fully rendered prompt**, not of the single file.
Editing `error-taxonomy.yaml` changes the hash of every skill that includes it.
Without that, evals would attribute a result to the wrong prompt version and you
would tune against a lie.

### 4.6 Routing — `config/models.yaml` + `app/ai/router.py`

Routes to a **pool**, not a bare model. A pool is one prompt-cache namespace;
caches are model-scoped, so each extra model fragments the caching that §5.4
calls the biggest lever on spend.

| Pool | Model | Used for |
|---|---|---|
| `judgment` | `claude-sonnet-5` | generation, grading, tagging, CEFR |
| `mechanical` | `claude-haiku-4-5` | bulk vocab extraction (batched) |

**Opus is excluded for cost**, overriding §5.3. Sonnet is ~60% cheaper per graded
answer (~$10 vs $25 per 1000). `router.py` raises if any pool resolves to Opus,
so the decision cannot be undone by an unreviewed config edit.

The risk this accepts: §5.3 put Opus on error tagging because Arabic morphology
is hard and bad tags poison the metrics. The tagging eval's **false-positive rate
on correct sentences** is the tripwire.

**Measured, and the decision holds.** Tagging scores 34/40 (85%) with a
**0% false-positive rate** — Sonnet did not invent a single error across 8
correct sentences, including fully vocalised text, a three-term iḍāfa chain,
correct dual agreement, and the passive. That was the failure mode that would
have quietly corrupted the metrics tab, review queue, and writing CEFR.

Of the 6 failures, 3 are defensible alternative categorisations rather than
misses — `فاطمة ذهب` tagged `agreement/gender` instead of
`morphology/verb_conjugation` is an honest reading of the same error. Only 3 are
true misses (conditional mood, one register slip, one hamza seat).

### 4.7 The frontend and RTL

Spec §7 makes RTL a non-negotiable, and the easy mistake is to set
`dir="rtl"` on `<html>`. That flips the entire interface and makes mixed
Arabic/English strings *worse*: the bidi algorithm needs direction declared at
the boundary of each run, not globally.

So direction is per-element:

```html
<html lang="en" dir="ltr">          <!-- chrome is English -->
  …
  <p class="arabic" dir="rtl" lang="ar">عن ماذا تحدث الولد؟</p>
```

Three details that matter in practice:

- **`unicode-bidi: isolate`** on titles and error spans. Without it, an Arabic
  phrase adjacent to LTR text has its punctuation and digits reordered.
- **`line-height: 2.1`** for Arabic. Harakat sit above *and* below the baseline
  and clip at typical Latin leading.
- **Self-hosted font.** Noto Naskh Arabic (52 KB woff2, Arabic subset) rather
  than the Google CDN — the Arabic fallback stack is poor enough that a CDN
  round trip produces severe layout shift on exactly the text that matters.

The practice screen shows **understanding and accuracy as separate scores**, so a
correct answer in imperfect Arabic visibly scores well on one and less on the
other. That is the §2.5 distinction made visible rather than averaged away.

A `409` from `/learning/next` renders as information, not an error — it means the
position gate has nothing to offer, or no groundable question could be made.


---

## 5. API reference

All endpoints except `/health` require `Authorization: Bearer <supabase-jwt>`.
Every handler uses an RLS-scoped client built from that token, so the database
filters by user — the API never has to remember to.

### Resources

#### `POST /resources/upload`
Upload a PDF. `multipart/form-data`.

| Field | Type | Notes |
|---|---|---|
| `file` | file | must be a real PDF (`%PDF` magic bytes, ≤ 50 MB) |
| `title` | string | required |
| `author` | string | optional |
| `level_hint` | string | optional, `A1`–`C2` |
| `position_value` | int | **defaults to 1**, not the whole document |

Stores the file, creates the resource with `ingest_status: "pending"`, and
queues an ingestion job. Returns immediately — parsing happens in the worker.

> `position_value` defaults to page 1 rather than the full length on purpose. A
> whole-document default would make the §5.2 gate meaningless from the first
> question.

```
201 → { id, title, ingest_status: "pending", ... }
415 → not a PDF        413 → too large        502 → storage failed
```

#### `POST /resources`
Register material with no file — a paper book, a video, a podcast.

```json
{ "title": "ديوان المتنبي", "type": "poetry", "author": "المتنبي",
  "level_hint": "C1", "position_value": 12, "position_unit": "page" }
```

`type: "pdf"` is rejected here (400) — PDFs must go through `/upload` so they
get queued for extraction.

#### `GET /resources` · `GET /resources/{id}`
List or fetch. Both return `ingest_status` and `ingest_report`, which is how the
UI knows whether a resource is usable:

```json
{ "ingest_status": "degraded",
  "ingest_report": {
    "status": "degraded",
    "reasons": ["10% of Arabic words extracted as single letters — …"],
    "mean_fragmentation_ratio": 0.0975,
    "needs_ocr": false } }
```

`404` covers both "no such resource" and "not yours" — RLS hides other users'
rows, and the response leaks neither.

#### `PATCH /resources/{id}/position`
Move the learner's position. **This is the control that drives the §5.2 gate.**

```json
{ "position_value": 42, "position_unit": "page" }
```

Lowering it is legitimate (re-reading, or fixing a mistake). The gate re-applies
at serve time, so questions already generated from beyond the new position stop
being served.

### Learning

#### `GET /learning/next?resource_id=<uuid>`
Serve a question.

```
        ┌─ cached unseen item in range? ──▶ return it            (no model call)
        │
        └─ none ──▶ select_chunk_window (gated, contiguous)
                       │
                       ├─ nothing visible ──────────▶ 409
                       │
                       └─▶ Claude generates
                              │
                              ├─ quote not verbatim ─▶ 409  (rejected, not stored)
                              ├─ unanswerable ───────▶ 409
                              └─ valid ──────────────▶ store + return
```

```json
{ "item_id": "…", "resource_id": "…",
  "question_arabic": "عن ماذا تحدث الولد وصديقه؟",
  "question_english": "What did the boy and his friend talk about?",
  "difficulty_cefr": "B1",
  "key_points": [ { "id": "kp1", "text": "They talked about a book…" } ] }
```

`key_points` carries the **text only**. The `source_quote` is withheld — it
would hand over the answer.

A `409` is not a bug. It means the position gate has nothing to offer, or the
passage genuinely could not support a grounded question. Both are §5.2 working.

#### `POST /learning/answer`
Grade an answer. One model call does grading *and* error tagging.

```json
{ "item_id": "…", "answer": "تحدثا عن كتاب عن تاريخ الأندلس…" }
```

```json
{ "gradable": true,
  "content_score": 1.0,       // → reading CEFR
  "language_score": 0.85,     // → writing CEFR
  "final_score": 0.8,
  "key_point_verdicts": [
    { "id": "kp1", "status": "conveyed",     "why": "…" },
    { "id": "kp2", "status": "contradicted", "why": "Says home; source says library." } ],
  "errors": [
    { "category": "syntax", "subcategory": "adjective_agreement",
      "span": "الكتاب الجديدة", "correction": "الكتاب الجديد",
      "explanation": "Masculine noun with a feminine adjective.",
      "severity": "moderate" } ],
  "feedback": "You understood the topic…" }
```

Writes an `attempts` row, one `error_tags` row per tag, and marks the item
consumed so it is not served again.

**The three scores are separate on purpose.** `content_score` measures
comprehension, `language_score` measures accuracy, and they move independently —
which is what lets reading and writing CEFR diverge, as §2.5 requires.

### Errors

| Code | Meaning |
|---|---|
| 401 | missing, malformed, or expired token |
| 404 | not found, or not yours (indistinguishable by design) |
| 409 | nothing to practise, or no groundable question |
| 413 / 415 | file too large / not a PDF |
| 502 | upstream failure (storage, or the model) |
| 422 | request body failed validation |


---

## 6. The evals harness

The problem: you have a grader that assigns marks. How do you know it is good?

If you make it stricter, you might fix near-misses and simultaneously start
punishing correct paraphrases — and never notice, because you would only see it
as unexplained CEFR drift months later.

### Four tiers

| Tier | When | Cost | What it proves |
|---|---|---|---|
| 0 | every commit | $0 | logic, schemas, arithmetic, the SQL gate |
| 1 | every PR | $0 | replays cassettes; nothing regressed |
| 2 | `skills/` changed | ~$0.60 | the model, today, behaves this way |
| 3 | manual/scheduled | ~$0.60 | model drift, with repetitions |

### The cassette mechanism

```
cassette key = sha256(prompt_hash + case_id)

prompt unchanged ──▶ replay from disk ──▶ $0
prompt  changed  ──▶ key misses       ──▶ CANNOT REPLAY, CI fails
```

You **cannot** change a prompt and quietly pass on stale recordings. Either you
re-measure, or the build stays red.

### The cases

- `short_answer.yaml` — 22 cases. `paraphrase/*` must score **high**;
  `near_miss/*` must score **low**. Engineered to be unambiguous, so no LLM judge
  is needed (a judge would put a second unversioned prompt in the measurement
  loop).
- `error_tagging.yaml` — 40 cases, 32 with known errors plus **8 clean sentences**
  that measure false positives. The clean ones matter more: a tagger that invents
  errors in correct Arabic makes the metrics tab lie, and recall alone will never
  reveal it.

### Per-case regression detection

Aggregate scores hide drift. A real example from this repo:

| | before | after |
|---|---|---|
| `near_miss/wrong_place` | fail | **pass** |
| `paraphrase/concise` | pass | **fail** |
| pass rate | 95% | **95%** |

The average is identical; a fix and a break cancelled out. The runner compares
**every case individually** and fails on any pass → fail flip, naming it.

> On investigation the grader was right and the *test* was wrong — the answer
> genuinely omitted detail. The expectation was corrected, not the prompt. That
> is a legitimate resolution, but only when it follows from reading the
> reasoning, not as a reflex.

### What replay does and does not prove

| Run | Proves |
|---|---|
| live | the grader, today, behaves this way |
| replay | your code turns those verdicts into these scores; nothing regressed |

A green replay means *"nothing changed since the last real measurement."* It does
not mean the grader works. If Claude's behaviour shifts underneath us, cassettes
still replay green — which is what Tier 3 is for.

---

## 7. Where the spec was wrong

Verified against current docs and live APIs.

| Spec | Reality | Why it matters |
|---|---|---|
| Sonnet 5 = $3/$15 | **$2/$10** | cost model was wrong |
| `claude-haiku-4-5-20251001` | `claude-haiku-4-5` | dated IDs are wrong for current models |
| `vector(1536)` | **1024** (Voyage) | Anthropic has no embeddings API; 1536 presumed OpenAI |
| "JSON only, validate, retry" | `messages.parse(output_format=…)` | constrained decoding makes parse failure near-impossible |
| "cache every skill file" | min prefix is **model-dependent** | below it, caching silently does nothing while still charging the write premium |
| `budget_tokens` | removed on Sonnet 5 (400) | use `output_config.effort` |
| retrieval as a model-called tool | retrieve-then-generate | the gate must be deterministic; a tool loop also forfeits the Batch API |
| Opus for tagging/essays/CEFR | Sonnet everywhere | cost; risk tracked by the tagging eval |

---

## 8. Running it

### Day to day

```bash
make install     # venv, backend deps, and npm install
make dev         # api + worker + web together, ctrl-C stops all three
```

`make dev` prefixes each stream so one terminal shows everything:

```
[api]    INFO:     Uvicorn running on http://127.0.0.1:8000
[worker] worker_started  mode=poll
[web]    ➜  Local:   http://localhost:5173/
```

Or run them separately, in three terminals:

```bash
make api         # :8000  FastAPI
make worker      # polls for uploaded PDFs and processes them
make web         # :5173  Vite
```

**The worker is not optional.** Without it an upload sits at
`ingest_status: pending` forever — the API only queues the job.

### Checks

```bash
make test        # 155 tests, no network, no API key
make db-test     # position gate against real Postgres (needs Docker)
make eval        # replay evals from cassettes — free
make check       # all three

make eval-live   # real API, re-records cassettes (~$0.60)
```

CI runs `test`, `db-test` and `eval` on every push — **with no API key in the
environment**, so it cannot spend money even through a bug. The live workflow
fires only when `skills/` or `config/models.yaml` changes, behind a GitHub
environment that can require approval.

---

## 9. A worked example

What actually happens when you upload a book and answer one question.

**1. Upload.** `POST /resources/upload` with `position_value: 40`. The PDF goes
to Supabase Storage, a `resources` row is created with `ingest_status: pending`,
and an `ingest_jobs` row is queued. The request returns in under a second.

**2. The worker picks it up.** Downloads the PDF, extracts page by page (page
numbers captured at extraction, never reconstructed), NFKC-normalises each page,
and runs the quality gate.

Say the gate returns `degraded` — 10% of tokens are single letters. The resource
is still usable, chunks are stored, and the UI shows a warning. Had it returned
`failed`, **zero chunks** would be written and no question could ever be
generated from it.

**3. Chunks and embeddings.** ~700-character chunks, never crossing a page
boundary, stored with `page_start`/`page_end`. Then embedded via Voyage into
`vector(1024)`.

**4. You ask for a question.** `GET /learning/next?resource_id=…`

`next_practice_item` finds nothing cached, so generation runs.
`select_chunk_window` resolves your position (40), picks a random *contiguous*
run of 2–3 chunks from pages ≤ 40 — weighted toward recent pages but not
exclusively — and returns them.

**5. Claude writes a question.** It receives the passage, the chunk IDs, and your
current CEFR level. It returns a question plus 1–3 key points, each with a
verbatim quote.

**6. Grounding is checked in code.** Every `source_quote` must appear verbatim in
the passage. A quote that is paraphrased, "corrected", or invented fails, and the
item is rejected rather than stored. Only then does it reach `generated_items`.

**7. You answer.** `POST /learning/answer`. The grader sees the question, the key
points *with* their quotes, your answer, and the passage. It returns a verdict
per key point plus error tags — **not a score**.

**8. Python computes the mark.**

```
kp1 conveyed (1.0) + kp2 contradicted (0.0)  →  content_score 0.50
1 moderate error (0.05) + 2 minor (0.00)     →  language_penalty 0.05
                                                language_score   0.95
final = round((0.50 - 0.05) × 5) / 5         =  0.40
```

Minor errors cost nothing. A right answer in imperfect Arabic keeps its content
score; the errors are still tagged and still feed the metrics.

**9. Everything is recorded.** An `attempts` row with both scores, one
`error_tags` row per tag, and a `model_calls` row with tokens, latency and cost.
The item is marked consumed.

If the model's own holistic score disagreed with the computed one by more than
0.3, the attempt is flagged — and those flags become future eval cases.


---

## 10. Current state

### Working, end to end

| | |
|---|---|
| Ingestion | upload → storage → worker → extract → gate → chunk → embed |
| Position gate | §5.2, enforced in SQL, attacked by 7 tests |
| Generation | grounded questions, verbatim-quote enforced |
| Grading | verdicts + error tags in one call, score computed in Python |
| Telemetry | every call logged with tokens, latency, cost |
| Evals | 62 cases, cassette replay, per-case regression detection |
| Frontend | auth, upload, position tracking, the practice loop, RTL |

### Measured

- **Short answer: 22/22.** Valid paraphrase scores 1.00; a fluent near-miss
  scores 0.00 as `contradicted` rather than merely absent.
- **Error tagging: 34/40 (85%)**, with **0/8 false positives** on correct
  Arabic. That was the tripwire for dropping Opus, and it held.
- **Prompt caching live:** 7799 tokens written once, read thereafter — per-grade
  cost fell from $0.035 to ~$0.006.
- **155 tests**, no network or API key required. Both eval suites replay at $0.

### Not built yet

From the spec's phases: vocab flashcards, the review queue with spaced
repetition, the metrics tab, the home dashboard (Phase 2), speaking and photo
upload (Phase 3).

### Known limitations

**Heavily formatted bilingual PDFs may not be usable.** `في القدس` extracts with
11% of its Arabic tokens split mid-word. The gate correctly marks it `degraded`,
and the model correctly refuses to ground a question in it
(`answerable_from_source: false`). That is the system behaving as designed, but
it means that particular file cannot produce practice. Plain Arabic prose
extracts far better.

**Eval coverage is 62 cases on synthetic Arabic.** They are unambiguous by
construction, which makes them reliable — but they do not cover damaged
extraction, poetry, or classical registers. Real flagged attempts should feed
back as cases over time.

**One worker, no locking.** `claim_job` is safe for a single worker. Running two
would need `SELECT … FOR UPDATE SKIP LOCKED` over a direct connection.
