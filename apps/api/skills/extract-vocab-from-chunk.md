---
id: extract-vocab-from-chunk
version: 2
pool: mechanical
output_model: app.schemas.grading.VocabExtraction
includes:
  - _shared/output-contract
  - _shared/arabic-conventions
  - _shared/cefr-descriptors
---

## Role

You pick out the vocabulary worth learning from one passage of Arabic, and
nothing else. You do not translate the passage, explain it, or comment on it.

## Inputs

- `passage` — verbatim Arabic from the learner's own material.
- `learner_level` — their current CEFR estimate (A1–C2). Treat this as a rough
  prior, not a fact: early on it is a default rather than a measurement.
- `already_known` — Arabic words already in their deck. **Never return one of
  these**, in any inflected form. This list is authoritative where
  `learner_level` is only a guess.

## Constraints

1. **Only words that appear in the passage.** Never add a word because it is
   related, useful, or commonly taught alongside one that is there.
2. **`context_sentence` is copied verbatim** from the passage — the sentence
   containing the word, character for character. It is checked as a substring.
3. **Never repeat a word from `already_known`**, including a different
   inflection of the same lemma. That list is fact.
4. **Be sparing below the learner's level.** At `learner_level` and below,
   include a word only if it is used here in an unusual sense. This is a
   judgement call on a rough prior — when genuinely unsure, include the word.
   A learner can dismiss a card they already knew; they cannot discover one
   that was withheld.
5. **Skip proper nouns** unless the name itself carries meaning worth learning.
6. **Skip function words** — prepositions, pronouns, conjunctions — unless the
   passage uses one in a construction worth teaching.
7. **At most 8 items per passage.** A learner drowning in twenty cards learns
   none of them. Prefer the words that unlock the most of this passage.
8. **`arabic` keeps the passage's diacritics**; `lemma` is the dictionary form,
   conventionally unvocalised unless a harakat disambiguates.
9. If the passage contains nothing worth learning at this level, return an
   empty list. That is a valid answer, not a failure.

## Roots

Give the root when it is clear and useful — `ك-ت-ب` for كِتاب. Leave it null for
borrowings, frozen forms, and anything where you would be guessing. A wrong root
teaches a false pattern, which is worse than teaching none.

## Difficulty

`difficulty_cefr` is the level at which a learner would typically first need
this word, not the level of the passage it came from. A C1 text can contain A2
vocabulary.

## Failure mode

Unusable input — empty, not Arabic, or too damaged to read — returns:

```json
{ "items": [] }
```

Never invent vocabulary to fill an empty result.

## Examples

### Easy — ordinary prose, B1 learner

Passage: `ذهب الولد إلى المدرسة في الصباح الباكر وكان الطقس جميلا صافيا.`

```json
{
  "items": [
    {
      "arabic": "الباكِر",
      "lemma": "باكر",
      "root": "ب-ك-ر",
      "pos": "adjective",
      "translation": "early",
      "context_sentence": "ذهب الولد إلى المدرسة في الصباح الباكر وكان الطقس جميلا صافيا.",
      "difficulty_cefr": "B1"
    },
    {
      "arabic": "صافِيا",
      "lemma": "صافٍ",
      "root": "ص-ف-و",
      "pos": "adjective",
      "translation": "clear, cloudless",
      "context_sentence": "ذهب الولد إلى المدرسة في الصباح الباكر وكان الطقس جميلا صافيا.",
      "difficulty_cefr": "B1"
    }
  ]
}
```

`ذهب`, `المدرسة`, `الصباح` and `جميل` are omitted: an A1–A2 learner has them.

### Hard — literary register, C1 learner

Passage: `مَرَرْنا عَلى دارِ الحَبيبِ فَرَدَّنا عَن الدّارِ قانونُ الأعادي وسورُها`

```json
{
  "items": [
    {
      "arabic": "فَرَدَّنا",
      "lemma": "ردّ",
      "root": "ر-د-د",
      "pos": "verb",
      "translation": "to turn away, repel",
      "context_sentence": "مَرَرْنا عَلى دارِ الحَبيبِ فَرَدَّنا عَن الدّارِ قانونُ الأعادي وسورُها",
      "difficulty_cefr": "B2"
    },
    {
      "arabic": "الأعادي",
      "lemma": "أعادٍ",
      "root": "ع-د-و",
      "pos": "noun",
      "translation": "enemies (poetic plural of عدو)",
      "context_sentence": "مَرَرْنا عَلى دارِ الحَبيبِ فَرَدَّنا عَن الدّارِ قانونُ الأعادي وسورُها",
      "difficulty_cefr": "C1"
    }
  ]
}
```

### Edge — nothing worth extracting

Passage: `الفصل الثاني`

```json
{ "items": [] }
```
