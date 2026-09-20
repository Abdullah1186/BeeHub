## Arabic conventions

### Variety
All generated Arabic is **Modern Standard Arabic (MSA / فصحى)** unless the
source material is explicitly Classical or dialectal, in which case match the
source. Never mix dialect into MSA output.

### Diacritics (harakat)
- **Preserve what the source has.** If the source is vocalised, quote it
  vocalised; if it is bare, quote it bare. Never add harakat to an unvocalised
  quotation, and never strip them from a vocalised one.
- When writing a *new* sentence (a question, an example), leave it unvocalised
  unless a harakat disambiguates the meaning.

### Quoting the source
Quotations must be **verbatim**, copied character for character including
diacritics and punctuation. They are checked programmatically as substrings of
the source text; a paraphrase, a normalised form, or a silently corrected typo
will fail that check and the whole item will be discarded.

If the source text itself contains an extraction artefact — a word split by a
stray space, a detached diacritic — quote it **as it appears**. Do not repair it.

### Roots and morphology
Cite roots as separated letters: `ك-ت-ب`. Refer to verb forms by Roman numeral
(I–X). Name patterns in transliteration when it aids clarity (`fa'ala`,
`maf'ul`).

### Mixed script
Arabic renders right-to-left and English left-to-right. When a sentence mixes
them, write each run naturally and do not insert direction-control characters —
the interface handles bidirectional rendering.

### Transliteration
Only when explaining a form to an English-speaking learner, and always
alongside the Arabic, never replacing it.
