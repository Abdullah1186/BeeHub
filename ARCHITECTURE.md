# BeeHub — how this repo works

A complete guide to the codebase: what every piece does, why it is shaped that
way, and where the spec turned out to be wrong.

`BeehubSpec.md` describes *what the product is*. This describes *what was built*.

**Contents**

1. [What it does](#1-what-it-does)
2. [Repo layout](#2-repo-layout)
3. [Database schema](#3-database-schema)
4. [Auth and security](#4-auth-and-security)
5. [Ingestion: PDF → chunks](#5-ingestion-pdf--chunks)
6. [Embeddings and retrieval (the RAG part)](#6-embeddings-and-retrieval-the-rag-part)
7. [The AI layer](#7-the-ai-layer)
8. [Grading and scoring](#8-grading-and-scoring)
9. [The API](#9-the-api)
10. [The frontend](#10-the-frontend)
11. [Tests](#11-tests)
12. [Evals](#12-evals)
13. [Where the spec was wrong](#13-where-the-spec-was-wrong)
14. [Running it](#14-running-it)
15. [Current state](#15-current-state)

---

## 1. What it does

You upload Arabic learning material. It is extracted, checked for extraction
damage, split into page-bounded chunks, and embedded. When you practise, the app
picks a passage **you have actually read**, asks Claude to write a question
grounded in that passage, and grades your answer against key points that were
extracted at generation time.

Two guarantees shape everything else:

**Only material you have reached.** A question about page 200 when you are on
page 40 spoils the book. Enforced in SQL, in one function, re-checked when the
question is served.

**Only text that actually exists.** A hallucinated question gets answered
correctly from the page and marked wrong, which poisons every metric downstream.
Every key point carries a verbatim quote, checked as a substring before the item
is stored.

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

---

## 2. Repo layout

```
BeeHub/
├── apps/
│   ├── api/                    FastAPI backend — self-contained deployable
│   │   ├── app/
│   │   │   ├── main.py         app entry, router wiring, startup checks
│   │   │   ├── config.py       settings + path resolution
│   │   │   ├── db.py           two Supabase clients (user vs service)
│   │   │   ├── auth.py         JWT verification (ES256 via JWKS)
│   │   │   ├── worker.py       ingestion job runner
│   │   │   ├── api/            HTTP endpoints: resources, learning
│   │   │   ├── ingest/         extract → normalise → gate → chunk
│   │   │   ├── retrieval/      gated chunk selection
│   │   │   ├── embeddings/     Voyage provider + deterministic fake
│   │   │   ├── ai/             Claude client, routing, pricing
│   │   │   ├── schemas/        Pydantic models = the model's contract
│   │   │   ├── grading/        score arithmetic (pure functions)
│   │   │   ├── generation/     grounding validation
│   │   │   └── skills/         the LOADER for skill files
│   │   ├── skills/             ALL prompt text (§5.1)
│   │   │   ├── _shared/        conventions, CEFR, taxonomy, contract
│   │   │   ├── generate-comprehension-questions.md
│   │   │   └── grade-short-answer.md
│   │   ├── config/models.yaml  model routing
│   │   └── tests/              155 tests, no network, no API key
│   │
│   └── web/                    React + TS + Vite (Vercel)
│       ├── src/lib/            supabase client, typed API client
│       ├── src/components/     Auth, Resources, Practice
│       └── public/fonts/       Noto Naskh Arabic, self-hosted
│
├── evals/                      measurement harness
│   ├── cases/                  62 golden cases with known outcomes
│   ├── cassettes/              recorded responses → replay is free
│   ├── baselines/              per-case pass record
│   └── runner.py
│
├── supabase/
│   ├── migrations/             schema, RLS, functions, storage
│   ├── tests/gate_test.sql     the position gate, attacked
│   └── local/auth_stub.sql     offline stand-in for Supabase auth
│
└── .github/workflows/          free CI + gated paid CI
```

**`app/skills/` vs `apps/api/skills/`** — easy to confuse. The first is Python
code that *loads* prompt files; the second is the prompt markdown itself.

**Why prompts live inside `apps/api`** (departing from the spec's root-level
layout): the backend is the only thing that needs them at runtime, so keeping
them inside makes it self-contained. Path resolution is then a fixed
`parents[1]`, with no discovery logic and no build-context requirements. An
earlier root-level layout climbed `parents[3]`, which worked locally and would
have broken on any deployment whose build context was `apps/api/` — booting
green and failing on the first practice request.

---

## 3. Database schema

Ten tables. The full DDL is in `supabase/migrations/0001_init.sql`.

```
auth.users (Supabase)
    │ 1:1 via trigger
    ▼
profiles ──────┬──────────┬───────────┬──────────────┬─────────────┐
               │          │           │              │             │
               ▼          ▼           ▼              ▼             ▼
          resources   attempts   vocab_items  level_estimates  model_calls
               │          │
      ┌────────┼──────┐   └──▶ error_tags
      ▼        ▼      ▼
resource_  generated_  ingest_
 chunks      items      jobs
```

### The tables

| Table | Holds | Notes |
|---|---|---|
| `profiles` | one row per user | mirrors `auth.users`; created by trigger |
| `resources` | uploaded/registered material | carries `position_value` and `ingest_status` |
| `resource_chunks` | the text itself | page-bounded, embedded |
| `ingest_jobs` | the worker's queue | Postgres-backed, polled |
| `generated_items` | cached questions | grounded, gated by `max_page` |
| `attempts` | one per answer | **two** scores, not one |
| `error_tags` | grammar errors | closed vocabulary |
| `vocab_items` | harvested words | Phase 2 |
| `level_estimates` | CEFR per skill | stores `numeric_ability` too |
| `model_calls` | every API call | tokens, latency, cost (§7) |

### Columns that carry design decisions

**`resources.position_value`** — how far you have read. `NULL` means untracked
(a poetry collection read out of order), and the gate then allows everything.
Uploads default it to **1**, not the document length: a whole-document default
would make the gate meaningless from the first question.

**`resources.ingest_status`** ∈ `pending | extracting | ok | degraded | failed`
plus `ingest_report` JSONB. `failed` means zero chunks exist, so no question can
ever be generated. This is what stops unreadable text becoming practice.

**`resource_chunks.text` and `text_normalized`** — two copies. `text` keeps
diacritics for display and embedding; `text_normalized` folds them for keyword
search. Spec §7: *normalise for search, never for display.*

**`resource_chunks.page_start` / `page_end`** — equal in Phase 1, because the
chunker never crosses a page. Both columns exist so Phase 2 can relax that. A
chunk spanning pages 40–41 would be un-gateable when you are on page 40.

**`generated_items.max_page`** — denormalised `max(page_end)` of the sources, so
the serve-time gate is one integer comparison instead of a join.

**`generated_items.source_chunk_ids`** with `check (cardinality(...) >= 1)` —
the grounding guarantee, in the database.

> **A bug this caught.** The constraint was first written as
> `array_length(source_chunk_ids, 1) >= 1`. `array_length` returns **NULL** for
> an empty array, and a Postgres CHECK that evaluates to NULL **passes** — so
> the constraint was silently inert and accepted ungrounded items.
> `cardinality()` returns 0 and is the correct form.

**`attempts.content_score` and `language_score`** — separate on purpose. A right
answer in broken Arabic should score high on one and low on the other, which is
what lets reading and writing CEFR diverge as §2.5 requires.

**`level_estimates.numeric_ability`** — the Elo/theta value CEFR is *derived*
from, stored as the source of truth so the update rule can change without
rewriting history.

### Functions

`supabase/migrations/0003_functions.sql`. All `security definer` with a pinned
`search_path`, so the gate cannot be bypassed by a caller's schema.

```
resolve_max_page(resource, user) → int
  ├─ not yours / missing  → -1          (expose nothing, leak nothing)
  ├─ position_value NULL  → 2147483647  (untracked)
  └─ position_value = N   → N
```

Every other function calls it. It is deliberately **not** reimplemented in
Python: two implementations drift, and one of them eventually leaks.

| Function | Used by | Purpose |
|---|---|---|
| `resolve_max_page` | all of the below | the gate itself |
| `select_chunk_window` | generation | contiguous passage, recency-weighted |
| `match_chunks` | vocab, Phase 2 | semantic search, gated |
| `next_practice_item` | serving | next unseen in-range question |

---

## 4. Auth and security

### Sign-in

Supabase Auth. Magic link is the spec's choice; password sign-in exists too
because Supabase's built-in SMTP allows only a few emails per hour, which makes
link-only auth unusable in development.

### Token verification — `app/auth.py`

Supabase now signs with **ES256**, verified against the project's JWKS endpoint.
The legacy shared HS256 secret is still accepted for tokens issued before a
project migrates, so the token header's `alg` picks the path:

```
alg = ES256 / RS256 / EdDSA  → verify against JWKS public key   (preferred)
alg = HS256                  → verify against SUPABASE_JWT_SECRET (legacy)
anything else                → 401
```

JWKS is cached for 10 minutes and force-refreshed once on an unknown `kid`, so
key rotation needs no redeploy. Tests cover the rejection paths, including
`alg: none` forgery and an HS256 token when no secret is configured.

### Row Level Security

RLS is on for every user-owned table, from day one, even though this is
currently single-user. Retrofitting it later means rewriting every query, and it
keeps the position gate a **database guarantee** rather than an application
promise.

```sql
create policy resources_all on resources
  for all using (user_id = auth.uid());
```

`resource_chunks` has no `user_id`, so its policy joins through the parent:

```sql
create policy resource_chunks_select on resource_chunks
  for select using (
    exists (select 1 from resources r
            where r.id = resource_chunks.resource_id
              and r.user_id = auth.uid())
  );
```

### Two database clients — `app/db.py`

| Client | Behaviour | Used by |
|---|---|---|
| `user_client(jwt)` | RLS applies | every request handler |
| `service_client()` | **bypasses RLS** | the worker only |

The worker needs the bypass because it writes chunks for a user whose token it
does not hold. **Using it in a request handler would undo every guarantee
above.**

> **A bug this caught.** `user_client` originally called
> `client.postgrest.auth(token)`, which authenticates the *database* client and
> leaves storage on the anon key. Table queries succeeded while uploads were
> rejected as anonymous — a confusing split that no test caught, because tests
> never touch storage. The token now goes through `SyncClientOptions` at
> construction, covering every sub-client.

### File storage

Files live in a **private** Supabase bucket at `<user_id>/<resource_id>.pdf`.
The path shape is what makes the policy work:

```sql
(storage.foldername(name))[1] = auth.uid()::text
```

*"The first folder must be your own user ID."* Same idea as table RLS, applied
to files. Without it, a public bucket would let anyone read any book by guessing
a URL.

---

## 5. Ingestion: PDF → chunks

The highest-risk part of the system. A PDF that extracts as garbage, gets
chunked, and produces confident questions about text that is not what the book
says is worse than no questions at all.

```
upload
  │
  ▼
extract (PyMuPDF)          page numbers captured HERE, never reconstructed
  │
  ▼
NFKC normalise             folds presentation forms U+FExx → base letters
  │
  ▼
QUALITY GATE ──────────────────────────────────────┐
  │                                                 │
  ├─ ok        → chunk → embed → practice           │
  ├─ degraded  → chunk → embed → practice + warning │
  └─ failed    → ZERO chunks, generation impossible ┘
```

### Extraction — `app/ingest/extract.py`

PyMuPDF, not pdfplumber or pypdf. Page numbers are captured at extraction time;
concatenating a document and mapping offsets back to pages breaks on every
hyphenation and header strip, and the position gate depends on the page being
exactly right.

> **Never "fix" apparently-backwards Arabic by reversing it.** Extractors
> generally return logical order, and reversing again produces double-reversed
> text that looks plausible and is wrong. Detect and quarantine instead.

### Normalisation — `app/ingest/arabic_text.py`

Two outputs from every page:

| Function | Keeps | Used for |
|---|---|---|
| `normalize_for_display` | diacritics, letter forms | storage, display, embedding |
| `normalize_for_search` | neither | keyword matching only |

NFKC is the load-bearing step — it folds Arabic presentation forms (U+FBxx,
U+FExx) back to base letters. Many extractors emit those isolated-glyph
codepoints instead of real letters, which would otherwise make the text
unsearchable and wrong when copied.

The search form additionally strips harakat and folds `أإآ→ا`, `ى→ي`, `ة→ه`, so
`كتب` matches `كَتَبَ`.

### The quality gate — `app/ingest/quality.py`

Seven checks, each corresponding to a real extraction failure:

| Check | Threshold | Catches |
|---|---|---|
| Arabic ratio | < 0.15 | scan, empty page, Latin junk |
| Presentation forms | > 0.02 *after NFKC* | unrepairable encoding |
| Mean word length | > 25 chars | spaces not recovered |
| Reversed word order | > 0.40 | visual-order extraction |
| **Mirrored text** | > 0.50 | character-level reversal |
| **Fragmentation** | > 0.20 | words split mid-word |
| **Orphan diacritics** | > 0.30 | harakat detached from letters |

The last three exist because real PDFs failed in ways the first four missed:

> **Mirrored text.** A generated Arabic PDF extracted fully reversed — word order
> *and* letters within each word. The word-position heuristic could not see it,
> because reversing a line also reverses the particles it looks for (`في` → `يف`).
> Detected morphologically instead: Arabic words overwhelmingly start with `ال`
> and end with `ة`/`ى`, and reversal inverts that distribution. Scores 0.93 on
> mirrored text, 0.0 on correct Arabic.

> **Intra-word fragmentation.** A real poetry PDF (`في القدس`) passed every
> check while 11% of its tokens were single letters — `فَقُلْتُ` had become
> `فَق لْت`. The glyphs and their order were fine; only counting tokens reveals
> it. Two independent signals are required, because Arabic has genuine one-letter
> proclitics (`و`, `ل`, `ب`) and a leading harakat can legitimately follow a line
> break in poetry.

Verdicts: `degraded` still generates practice with a warning; `failed` produces
**zero chunks**, so generation is structurally impossible rather than merely
discouraged.

### Chunking — `app/ingest/chunker.py`

700 characters target, 1000 max, 120 overlap. **Never crosses a page boundary.**

Character-based rather than token-based: at this size the variance does not
justify an API round trip per chunk, and Arabic runs roughly 0.45–0.6 tokens per
character, so 700 chars ≈ 350–420 tokens — one or two paragraphs.

Split order: paragraph → sentence → clause → whitespace. **The sentence regex
must include Arabic punctuation** — `؟` (U+061F) and `،` (U+060C). A naive
`[.!?]` splitter finds almost no boundaries in Arabic prose and silently
degrades to mid-sentence whitespace splits.

### The worker — `app/worker.py`

A Postgres-backed queue polled by a separate process, not Supabase Edge
Functions — so the worker runs the same Python and the same PyMuPDF as the
tests, and what CI verifies is what production executes.

**The worker is not optional.** The API only queues the job; without the worker
an upload sits at `pending` forever.

---

## 6. Embeddings and retrieval (the RAG part)

This section is worth reading carefully, because **BeeHub's retrieval is
deliberately not standard RAG** and the difference matters.

### Standard RAG, and why it is wrong here

The usual shape is: embed a user's question, find the top-k most similar chunks,
stuff them into the prompt, answer.

That works when there *is* a question. Here there isn't. The task is *"ask me
about what I just read"*, and there is no query to embed.

Worse, top-k similarity actively hurts. It returns chunks that are semantically
related but **narratively disconnected** — a paragraph from page 12 and another
from page 78 that happen to use similar vocabulary. A comprehension question
built on that reads as incoherent, because the passage it describes never
existed as a passage.

### What BeeHub does instead

**Generation uses a contiguous window, selected by position — no vectors at all.**

```
select_chunk_window(resource, user, window=3)
  │
  ├─ resolve_max_page  → 40          (the gate)
  │
  ├─ 60% of the time: pick a start uniformly from the RECENT THIRD
  │  40% of the time: pick uniformly from EVERYTHING visible
  │
  └─ return chunks [start, start+3) where page_end <= 40
                    ▲
                    └─ contiguous: a real passage, in reading order
```

Two properties this buys:

- **Coherence.** Adjacent chunks are a passage someone actually read.
- **Gateability.** A contiguous run bounded by `page_end <= position` is trivially
  checkable; a scattered top-k set is not.

> **A bug this caught.** The first recency weighting was multiplicative —
> `chunk_index * random()`. It put **99.3%** of draws in the last ten pages;
> pages 1–20 were selected zero times in 2000 draws, making review of earlier
> material impossible. The mixture above gives roughly 20% early / 80% recent
> with nothing unreachable.

### So where are embeddings used?

`resource_chunks.embedding vector(1024)`, populated by the worker after the gate
passes. Currently they serve:

- **Vocab context** — finding the sentence a word appeared in (Phase 2)
- **Thematic search** — "questions about this topic" (Phase 2)

They are **not** used for question generation. This is a real departure from the
spec's emphasis on pgvector, and the reason is the coherence problem above.

### The provider — `app/embeddings/provider.py`

Voyage `voyage-4-lite`, 1024 dimensions.

**Why not 1536?** The spec said `vector(1536)`, which presumed OpenAI —
Anthropic has no embeddings API. 1024 is a native Voyage output size, ~3×
cheaper than OpenAI's small model, and sits safely under pgvector's **2000-dim
HNSW ceiling** (2048 would exceed it and force `halfvec`).

**The asymmetry matters.** Voyage embeds documents and queries differently,
prepending a different instruction to each. A query embedded as a document
retrieves measurably worse. That is baked into the interface as two methods
rather than a keyword argument someone will forget:

```python
provider.embed_documents(texts)   # input_type="document"  — indexing
provider.embed_query(text)        # input_type="query"     — searching
```

`FakeEmbeddings` mirrors the asymmetry deterministically, so tests catch a
swapped call without spending anything or needing a key.

### The index

```sql
create index chunks_vec_idx on resource_chunks
  using hnsw (embedding vector_cosine_ops) with (m = 16, ef_construction = 64);
```

At 20 chunks this is irrelevant — HNSW earns its keep at thousands. It is there
so the query shape does not have to change later.

`embedding` is **nullable** on purpose: a chunk is stored first and embedded
second, so a Voyage outage leaves usable text rather than failing the ingest.
`match_chunks` skips unembedded rows rather than erroring.

---

## 7. The AI layer

### Where prompts live

**No prompt text in Python** (§5.1). Every instruction lives in
`apps/api/skills/*.md` with YAML frontmatter:

```yaml
---
id: grade-short-answer
version: 2
pool: judgment
output_model: app.schemas.grading.ShortAnswerGrade
includes: [_shared/output-contract, _shared/arabic-conventions, _shared/cefr-descriptors]
---
```

`app/skills/loader.py` renders includes + body into one system prompt.

### prompt_hash — the mechanism everything else depends on

```
prompt_hash = sha256(FULLY RENDERED prompt)
```

Not a hash of the single file. Editing `_shared/error-taxonomy.yaml` changes the
hash of **every skill that includes it** — verified by test. Without that, evals
would attribute a result to the wrong prompt version and you would tune against
a lie.

Rendering is byte-deterministic: includes in declared order, sorted YAML, no
timestamps, no user IDs. Skills are loaded once at startup and **not
hot-reloaded in production** — a mid-request change would break the cached
prefix and produce two different results under one recorded hash.

### The taxonomy: one file, two consumers

```
skills/_shared/error-taxonomy.yaml
      │
      ├──▶ app/schemas/taxonomy.py   → closed StrEnums (Pydantic)
      └──▶ app/skills/loader.py      → rendered into the prompt
```

A prompt instruction saying "only use these categories" is necessary but not
sufficient. The closed enum, passed through `messages.parse`, makes an
out-of-vocabulary value **structurally impossible**. A CI test asserts every
enum member appears in the rendered prompt — the model cannot emit what it was
never shown. A pairing validator rejects crossed pairs like
`orthography/broken_plural` that a flat subcategory enum would accept.

### Routing — `apps/api/config/models.yaml`

Routes to a **pool**, not a bare model. A pool is one prompt-cache namespace;
caches are model-scoped, so each extra model fragments the caching that §5.4
calls the biggest lever on spend.

| Pool | Model | Tasks |
|---|---|---|
| `judgment` | `claude-sonnet-5` | generation, grading, tagging, CEFR |
| `mechanical` | `claude-haiku-4-5` | bulk vocab extraction (batched) |

**Opus is excluded for cost**, overriding §5.3. Sonnet is ~60% cheaper per
graded answer (~$10 vs $25 per 1000). `router.py` raises if any pool resolves to
Opus, so the decision cannot be undone by an unreviewed config edit.

> **The risk this accepted, and how it was settled.** §5.3 put Opus on error
> tagging because Arabic morphology is hard and bad tags poison the metrics.
> Measured: tagging scores 34/40 (85%) with a **0% false-positive rate** — Sonnet
> did not invent a single error across 8 correct sentences, including fully
> vocalised text, a three-term iḍāfa chain, correct dual agreement and the
> passive. That was the failure mode that would have quietly corrupted the
> metrics tab, review queue and writing CEFR. Of the 6 failures, 3 are defensible
> alternative categorisations rather than misses.

### The client — `app/ai/client.py`

Every model call goes through `call_skill()`, so three things always happen:

**1. Structured output.** `client.messages.parse(output_format=Model)` uses
constrained decoding, so the response validates against the Pydantic model by
construction. This replaces §5.5's parse-and-retry loop, written before
structured outputs existed.

**2. Prompt caching.** The skill prompt is the cached prefix (`cache_control` on
the system block); the variable content goes after it. Verified, not assumed:
`CallResult.cache_hit` reads `cache_read_input_tokens`.

Measured: 7799 tokens written once, read on every subsequent call — per-grade
cost fell from **$0.035 to ~$0.006**.

**3. Cost telemetry.** §7: *every model call is logged with model, token counts,
latency and cost.* Failures are logged too — spend you cannot see is spend you
cannot control.

> **A bug this caught.** The first real generation call failed with an opaque
> `Invalid JSON: EOF while parsing`. The cause was `max_tokens`: thinking at
> `effort=medium` consumed the 4000-token budget before the JSON closed.
> Truncation now reports itself by name, because its fix (raise `max_tokens`) is
> completely different from the fix for a genuine schema violation.

### Grounding enforcement — `app/generation/validate.py`

Before a generated question is stored:

| Check | Why |
|---|---|
| `source_chunk_ids` non-empty | must cite something |
| all IDs within the retrieval set | cannot invent a source |
| **every `source_quote` verbatim in the passage** | the real hallucination check |
| refusal must be empty-handed | cannot claim unanswerable *and* return a question |

The quote check is the one that works. Chunk IDs are trivial for a model to echo
back; reproducing exact Arabic from text that was never there is not. Whitespace
and Unicode form are normalised; **diacritics and letter forms are not**, so a
quote that silently "corrects" the source still fails.

> **A bug this caught.** `ComprehensionQuestion` had `min_length=1` on
> `key_points`, which made the §5.2 refusal path *unrepresentable* — a passage
> that cannot support a question must return `answerable_from_source: false` with
> no key points, and the schema forbade exactly that, pushing the model to invent
> a question rather than decline. Replaced with a validator carrying the real
> rule: non-empty when answerable, empty when not.

---

## 8. Grading and scoring

### Key points come from generation, not grading

When a question is generated, the generator also emits the 1–3 facts a correct
answer must contain, each with its verbatim supporting quote. Stored on
`generated_items.payload`.

The grader then decides only, **per key point**, whether the learner conveyed
it. That is a far more repeatable judgement than "grade this answer", and it
rides along on the generation call at no extra cost.

### Four verdicts, not two

| Verdict | Meaning |
|---|---|
| `conveyed` | expressed the fact; different wording is fine |
| `partially_conveyed` | incomplete, but nothing false asserted |
| `absent` | did not address it |
| `contradicted` | **asserted something the source denies** |

`contradicted` ≠ `absent` is what catches near-misses. A fluent, confident,
wrong answer is a comprehension failure; saying nothing is an omission. A boolean
would miss the distinction entirely.

> **This distinction was tightened after an eval failure.** A learner said they
> would read the book *at home* when the source said *the library*. The grader
> marked it `partially_conveyed`, reasoning they got the book, the joint reading
> and the timing right. The prompt now states that a **wrong detail is
> `contradicted`, however much else is correct**, with worked examples showing
> the boundary against genuine incompleteness.

### The score is arithmetic, in Python

`app/grading/score.py`. The model returns discrete verdicts; the number comes
from here.

```
credit:   conveyed 1.0 | partially 0.5 | absent 0.0 | contradicted 0.0
content_score    = mean(credits)                        → reading CEFR
language_penalty = min(0.25, 0.05·moderate + 0.12·blocking)
language_score   = 1.0 - language_penalty               → writing CEFR
final            = round((content - penalty) × 5) / 5
```

Three decisions encoded:

**Minor errors cost nothing.** A learner who conveys the meaning with a hamza
slip has comprehended. The error is still tagged and still feeds metrics and the
review queue — it just does not reduce the mark. This is the fair-to-paraphrase
guarantee, enforced in code rather than requested in a prompt.

**The penalty is capped at 0.25.** Without it, a long answer with many small
errors could score zero despite perfect comprehension.

**The model's own holistic score is never used.** It is recorded as a
*disagreement signal*: when it differs from the computed score by more than 0.3,
the attempt is flagged — and those flags become future eval cases.

Why arithmetic rather than asking the model for a number: a learner disputing a
mark can be shown exactly which key point was missed and what each error cost.
Weights change here, in code, covered by free tests, without touching a prompt.

---

## 9. The API

Every endpoint except `/health` requires `Authorization: Bearer <supabase-jwt>`.
Handlers use an RLS-scoped client, so the database filters by user — the API
never has to remember to.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | liveness; touches nothing external |
| `GET` | `/me` | round-trips the JWT |
| `POST` | `/resources/upload` | upload a PDF, queue ingestion |
| `POST` | `/resources` | register material with no file |
| `GET` | `/resources` | list |
| `GET` | `/resources/{id}` | fetch one, with ingest report |
| `PATCH` | `/resources/{id}/position` | move the reading position |
| `GET` | `/learning/next` | serve a question |
| `POST` | `/learning/answer` | grade an answer |

### `POST /resources/upload`

`multipart/form-data`: `file`, `title`, optional `author`, `level_hint`, and
`position_value` (**defaults to 1**).

Validates magic bytes and size *before* touching storage, writes the file to
`<user_id>/<resource_id>.pdf`, creates the row as `pending`, and queues a job.
Returns immediately — parsing happens in the worker.

```
201 → { id, title, ingest_status: "pending", ... }
415 → not a PDF     413 → too large     502 → storage failed
```

### `GET /learning/next?resource_id=<uuid>`

```
┌─ cached unseen item in range? ──▶ return it            (no model call)
│
└─ none ──▶ select_chunk_window (gated, contiguous)
               ├─ nothing visible ──────────▶ 409
               └─▶ Claude generates
                      ├─ quote not verbatim ─▶ 409  (rejected, not stored)
                      ├─ unanswerable ───────▶ 409
                      └─ valid ──────────────▶ store + return
```

`key_points` returns **text only** — the `source_quote` is withheld, since it
would hand over the answer.

**A 409 is not a bug.** It means the position gate has nothing to offer, or the
passage genuinely could not support a grounded question. Both are §5.2 working.

### `POST /learning/answer`

One model call does grading *and* error tagging. Writes an `attempts` row, one
`error_tags` row per tag, and marks the item consumed.

```json
{ "gradable": true,
  "content_score": 1.0, "language_score": 0.85, "final_score": 0.8,
  "key_point_verdicts": [
    { "id": "kp2", "status": "contradicted", "why": "Says home; source says library." } ],
  "errors": [
    { "category": "syntax", "subcategory": "adjective_agreement",
      "span": "الكتاب الجديدة", "correction": "الكتاب الجديد",
      "explanation": "Masculine noun with a feminine adjective.",
      "severity": "moderate" } ],
  "feedback": "…" }
```

### Status codes

| Code | Meaning |
|---|---|
| 401 | missing, malformed, or expired token |
| 404 | not found, **or not yours** (indistinguishable by design) |
| 409 | nothing to practise, or no groundable question |
| 413 / 415 | too large / not a PDF |
| 502 | upstream failure (storage or model) |
| 422 | request body failed validation |

---

## 10. The frontend

React + TypeScript + Vite + Tailwind v4. Three screens: `Auth`, `Resources`,
`Practice`. ~830 lines total.

### RTL, done properly

Spec §7 makes RTL non-negotiable, and the easy mistake is `dir="rtl"` on
`<html>`. That flips the entire interface and makes mixed Arabic/English
*worse*: the bidi algorithm needs direction declared at the boundary of each
run, not globally.

```html
<html lang="en" dir="ltr">                      <!-- chrome is English -->
  <p class="arabic" dir="rtl" lang="ar">…</p>   <!-- content declares itself -->
```

Three details that matter in practice:

- **`unicode-bidi: isolate`** on titles and error spans. Without it, an Arabic
  phrase adjacent to LTR text has its punctuation and digits reordered.
- **`line-height: 2.1`** for Arabic. Harakat sit above *and* below the baseline
  and clip at typical Latin leading.
- **Self-hosted font.** Noto Naskh Arabic (51 KB woff2, Arabic subset) rather
  than the Google CDN — the Arabic fallback stack is poor enough that a CDN
  round trip causes severe layout shift on exactly the text that matters.

### What the screens do

**Resources** polls every 3 seconds while anything is `pending` or `extracting`,
so the worker's progress appears without a refresh. Each row shows its ingest
status with the `ingest_report` reasons underneath, so a `degraded` resource
explains itself.

**Practice** shows **understanding and accuracy as separate scores**, making the
§2.5 distinction visible rather than averaging it away. Error tags render the
offending span struck through beside its correction. A 409 renders as
information, not an error.

---

## 11. Tests

**155 tests. No network, no API key, no cost.** `make test`

| File | Tests | Covers |
|---|---|---|
| `test_quality.py` | 24 | the seven gate checks, both directions |
| `test_embeddings.py` | 18 | dimensions, asymmetry, gate delegation |
| `test_score.py` | 17 | score arithmetic, table-driven |
| `test_api.py` | 15 | auth rejection, upload validation |
| `test_taxonomy.py` | 14 | closed enums, pair validation, prompt sync |
| `test_validate.py` | 13 | grounding enforcement |
| `test_arabic_text.py` | 12 | normalisation, NFKC repair |
| `test_chunker.py` | 12 | page boundaries, Arabic punctuation |
| `test_worker.py` | 10 | job lifecycle, retry, idempotent re-ingest |
| `test_pipeline.py` | 6 | end to end against generated PDFs |

### Three things worth knowing

**Real PDFs, not mocks.** `test_pipeline.py` and `test_worker.py` build actual
PDF files with PyMuPDF. The bugs that matter live in the extractor's interaction
with Arabic fonts, not in our code — a mocked extractor would have passed the
mirrored-text bug.

**A fake Supabase client.** `test_worker.py` implements enough of the client
surface to run the worker offline: job claiming, retry-to-max-attempts,
idempotent re-ingestion, and the load-bearing assertion that **a failed quality
gate stores zero chunks**.

**The tests are deliberately paranoid about direction.** For every "detects the
bad thing" test there is a "does not flag the good thing" test — mirrored *and*
correct Arabic, fragmented *and* heavily vocalised, because a false positive
that blocks a legitimate book is as bad as a miss.

### SQL tests — `make db-test`

Seven tests against a real Postgres in Docker (`supabase/tests/gate_test.sql`):

```
PASS resolve_max_page
PASS grounding constraint rejects ungrounded items
PASS window gate (1000 draws, max page 40)
PASS position rollback respected
PASS window contiguity
PASS recency mixture (early=387, late=1613)
PASS serve-time gate withholds out-of-range items
```

The 1000-draw test is the safety property: with position 40, nothing past page 40
is ever returned. Cross-user access returns zero rows. A rollback from 40 to 10
takes effect immediately.

---

## 12. Evals

Unit tests check *your code*. Evals check *the model's judgement* — a different
problem, because there is no assertion that "the grader is good".

The concrete risk: you make the grader stricter, it starts catching near-misses
**and** starts punishing correct paraphrases, and you never notice because the
aggregate score holds steady.

### The cases — 62 total

**`short_answer.yaml`** (22) — two halves testing opposite failure modes:

- `paraphrase/*` (10) must score **high**. A grader that punishes valid
  paraphrase teaches parroting instead of understanding.
- `near_miss/*` (10) must score **low**. Fluent, plausible, and wrong.
- `ungradable/*` (2) must refuse rather than invent a mark.

**`error_tagging.yaml`** (40) — 32 sentences with known errors, plus **8 clean
sentences** that measure false positives. The clean ones matter more: a tagger
that invents errors in correct Arabic makes the metrics tab lie, and recall alone
will never reveal it.

Cases are engineered to be unambiguous, so **no LLM judge is used** — a judge
would introduce a second unversioned prompt into the measurement loop.

### Four tiers

| Tier | When | Cost | Proves |
|---|---|---|---|
| 0 | every commit | $0 | logic, schemas, arithmetic, SQL gate |
| 1 | every PR | $0 | replays cassettes; nothing regressed |
| 2 | `skills/` changed | ~$0.50 | the model, today, behaves this way |
| 3 | manual | ~$0.50 | drift, with repetitions |

### The cassette mechanism

```
cassette filename = sha256(prompt_hash + case_id)[:24]

prompt unchanged ──▶ replay from disk ──▶ $0
prompt  changed  ──▶ filename misses  ──▶ CANNOT REPLAY, exit 2, CI fails
```

You **cannot** change a prompt and pass on stale recordings. Either you
re-measure, or the build stays red. Cassettes are committed on purpose — that is
what makes a fresh CI checkout free.

### Per-case regression detection

Aggregate scores hide drift. A real example from this repo:

| | before | after |
|---|---|---|
| `near_miss/wrong_place` | fail | **pass** |
| `paraphrase/concise` | pass | **fail** |
| pass rate | 95% | **95%** |

Identical average; a fix and a break cancelled out. The runner compares **every
case individually** and fails on any pass → fail flip, naming it.

> On investigation the grader was right and the *test* was wrong — that answer
> genuinely omits detail from both key points. The expectation was corrected, not
> the prompt. That is a legitimate resolution, but only when it follows from
> reading the reasoning, not as a reflex.

### What replay does and does not prove

| Run | Proves |
|---|---|
| live | the grader, today, behaves this way |
| replay | your code turns those verdicts into these scores; nothing regressed |

A green replay means *"nothing changed since the last real measurement."* If
Claude's behaviour shifts underneath us, cassettes still replay green. That is
the honest limit of Tier 1, and the reason Tier 3 exists.

### Current results

```
short_answer   22/22 (100%)
error_tagging  34/40  (85%)   false positives: 0/8
```

---

## 13. Where the spec was wrong

Verified against current docs and live APIs.

| Spec | Reality | Consequence |
|---|---|---|
| Sonnet 5 = $3/$15 | **$2/$10** | cost model was wrong |
| `claude-haiku-4-5-20251001` | `claude-haiku-4-5` | dated IDs are wrong for current models |
| `vector(1536)` | **1024** (Voyage) | Anthropic has no embeddings API; 1536 presumed OpenAI |
| "JSON only, validate, retry" | `messages.parse(output_format=…)` | constrained decoding makes parse failure near-impossible |
| "cache every skill file" | min prefix is **model-dependent** | below it, caching silently does nothing while charging the write premium |
| `budget_tokens` | removed on Sonnet 5 (400) | use `output_config.effort` |
| retrieval as a model-called tool | retrieve-then-generate | the gate must be deterministic; a tool loop also forfeits the Batch API |
| Opus for tagging / essays / CEFR | Sonnet everywhere | cost; validated by the 0% false-positive rate |
| `skills/` at repo root | inside `apps/api/` | makes the backend a self-contained deployable |
| similarity search for practice | contiguous windows | top-k returns narratively disconnected fragments |

---

## 14. Running it

### Day to day

```bash
make install     # venv, backend deps, npm install
make dev         # api + worker + web together, ctrl-C stops all three
```

`make dev` prefixes each stream so one terminal shows everything:

```
[api]    INFO:     Uvicorn running on http://127.0.0.1:8000
[worker] worker_started  mode=poll
[web]    ➜  Local:   http://localhost:5173/
```

Or separately, in three terminals:

```bash
make api         # :8000  FastAPI
make worker      # polls for uploaded PDFs
make web         # :5173  Vite
```

**The worker is not optional.** Without it an upload sits at `pending` forever —
the API only queues the job. `make worker-once` catches up on a backlog.

### Checks

```bash
make test        # 155 tests, free
make db-test     # position gate against real Postgres (needs Docker)
make eval        # replay evals from cassettes, free
make check       # all three

make eval-live   # real API, re-records cassettes (~$0.50)
```

### Configuration

`.env` at the repo root (gitignored; `.env.example` is the template):

| Variable | Used by |
|---|---|
| `ANTHROPIC_API_KEY` | generation, grading |
| `VOYAGE_API_KEY` | embeddings |
| `SUPABASE_URL`, `SUPABASE_ANON_KEY` | API and frontend |
| `SUPABASE_SERVICE_ROLE_KEY` | **worker only** — bypasses RLS |

`apps/web/.env.local` mirrors the public values as `VITE_*`. Only `VITE_*`
reaches the browser; never put a service role key there.

---

## 15. Current state

### Working, verified against the real project

| | |
|---|---|
| Ingestion | upload → storage → worker → extract → gate → chunk → embed |
| Position gate | §5.2 in SQL, attacked by 7 tests |
| Generation | grounded questions, verbatim-quote enforced |
| Grading | verdicts + tags in one call, score computed in Python |
| Telemetry | every call logged with tokens, latency, cost |
| Frontend | auth, upload, position tracking, practice loop, RTL |
| Evals | 62 cases, cassette replay, per-case regression detection |

End-to-end on `في القدس`: 18 pages extracted → gate `degraded` (correct) →
20 chunks → 20 embedded → a grounded A2 question from the opening couplet
(*ما الذي منع الشاعر من الوصول إلى دار الحبيب؟*) → answer graded 100/100 with no
false-positive tags.

### Not built yet

Vocab flashcards, the review queue with spaced repetition, the metrics tab, the
home dashboard (Phase 2); speaking and photo upload (Phase 3).

### Known limitations

**Heavily formatted bilingual PDFs extract poorly.** `في القدس` has 11% of its
Arabic tokens split mid-word. The gate marks it `degraded` and the model refuses
to ground questions in the worst passages — correct behaviour, but it means such
files yield less practice than their length suggests. Plain Arabic prose is far
better material.

**Eval coverage is 62 synthetic cases.** Unambiguous by construction, which makes
them reliable, but they do not cover damaged extraction, poetry, or classical
registers. Flagged attempts should feed back as cases over time.

**One worker, no locking.** `claim_job` is safe for a single worker. Two would
need `SELECT … FOR UPDATE SKIP LOCKED` over a direct connection.

**Cassettes cannot detect model drift.** A green replay means nothing changed
locally, not that the grader still behaves the same. Only a periodic live run
tells you that.
