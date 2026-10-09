# ESL Feedback Design System — v1.5

Status: **v1.5**, updated 2026-10-09. Scope: student feedback documents (the
"ESL Analysis" family): homework analyses and IELTS band cards. Light theme
only. This system is a polish of a working style, not a redesign: every
decision below is checkable with numbers.

| File | What it is |
|---|---|
| `templates/homework-analysis-template.html` | Canonical template. A new document is a copy of this file |
| `templates/band-card-template.html` | Skeleton of the IELTS band card (band-card variant, v1.4) |
| `templates/REPLACE-ME.wav` | Audio placeholder: a one-second beep. A copy of a template that forgot to replace the `src` beeps instead of playing the recording |
| `tokens.json` | Machine-readable tokens for the linter (`version`, `colors.allowed`, `font_sizes`, `spacing`) |
| `docs/design-system.md` | This document |
| `tools/check_design.py` | Static conformance linter (stdlib only, no browser) |
| `tools/qa_run.py` | Headless Playwright runner: console errors, overflow, fonts, audio, screenshots |
| `tools/fixtures/`, `tools/selftest.sh` | Known-good / known-bad files and the tooling self-test |
| `examples/` | Two synthetic demo documents (no real student content) |

Rule: delivered documents are never edited afterwards. A typo or a new remark
means a new dated file; the old one stays as it is.

---

## 1. Colour

One hex per semantic role. Every role is a triplet: **base** (dot, left rule,
transcript underline, chip border), **tint** (card background and highlights),
**ink** (chip text, dark accent of the same role).

### Semantics (five roles; legend order and names are fixed)

| Role | Class | base | tint | ink | Chip text |
|---|---|---|---|---|---|
| Grammar | `red` | `#ef4444` | `#fef2f2` | `#b91c1c` | Grammar |
| Word choice | `orange` | `#d97706` | `#fffbeb` | `#92400e` | Word choice |
| Sentence flow | `yellow` | `#b8860b` | `#fefce8` | `#854d0e` | Sentence flow |
| Style & speech habits | `green` | `#17a34a` | `#f0fdf4` | `#065f46` | Style & speech |
| Punctuation (written only) | `purple` | `#a855f7` | `#faf5ff` | `#6d28d9` | Punctuation |

### Neutrals and UI

| Token | Hex | Role |
|---|---|---|
| `--white` | `#ffffff` | page background, chip background |
| `--ink-1` | `#0d0d0d` | primary text |
| `--ink-2` | `#615d59` | secondary text: why-notes, table heads |
| `--ink-3` | `#746f6b` | tertiary: subtitle, meta, section titles, originals |
| `--surface-1` | `#f6f5f4` | gadget cards: tips, pills, badges |
| `--surface-2` | `#fafaf9` | reading cards: transcript, fix notes, prompt summary |
| `--line` | `#ebebeb` | standard border |
| `--line-soft` | `#f0f0ef` | soft border (tips, prompt summary) |
| `--accent` | `#0075de` | blue rule, dot, tip number |
| `--accent-ink` | `#0070d5` | blue text: links, strong inside blue boxes |
| `--accent-deep` | `#1e3a5f` | text on the blue tint |
| `--accent-tint` | `#f2f9ff` | callout / strengths background |
| `--praise-line` | `#c3efdd` | border of the green praise box |

### Contrast (WCAG 2.x)

Minimums: normal text 4.5:1, non-text indicators 3:1.

| Check | System minimum | Requirement | Result |
|---|---|---|---|
| `--ink-2` on nine backgrounds | 5.97 | 4.5 | PASS |
| `--ink-3` on the same nine | 4.54 | 4.5 | PASS |
| base indicators vs white | 3.19 (orange) | 3.0 | PASS |
| base indicators vs their own tint | 3.07 (orange) | 3.0 | PASS |
| ink roles (chip text) | 5.91 (grammar) | 4.5 | PASS |
| `--accent-ink` on `--surface-1` | 4.58 | 4.5 | PASS |
| white text on `--style-ink` (until v1.5, the revised label) | 7.68 | 4.5 | PASS |

### What changed and why (movement kept to a minimum, all by the numbers)

| Was | Now | Reason |
|---|---|---|
| `#f59e0b` (orange) | `#d97706` | 2.15:1 vs white, below the 3:1 indicator threshold |
| `#eab308` (yellow) | `#b8860b` | 1.92:1 |
| `#22c55e` (green) | `#17a34a` | 2.28:1 |
| `#a39e98` (tertiary text) | `#746f6b` (`--ink-3`) | 2.66:1 vs white; the new value interpolates old-to-`#615d59` and passes 4.5:1 on every background |
| `#10b981` (revised label) | `#065f46` | white on `#10b981` is 2.54:1, a hard fail |
| `#0075de` for text | `#0070d5` (`--accent-ink`) | 4.19:1 on `--surface-1`; rules and dots keep `#0075de` (non-text, 3:1, they pass) |
| `rgba(0,0,0,…)` shadows and borders | hex tokens | the palette is fully hexadecimal, nothing for the linter to guess |

Drift closed by the initial audit (six documents, 2026-06…09): three reds
(`#e5484d`, `#ff6b6b`) collapsed into `#ef4444`; greens `#30a46c`/`#51cf66`
into `#17a34a`; oranges `#f76808`/`#f97316`/`#ffa94d` into `#d97706`; yellows
`#dda310`/`#fcc419` into `#b8860b`; purples `#8e4ec6`/`#cc5de8`/`#8b5cf6` into
`#a855f7`. The full legacy list for migration lives in `tokens.json` → `legacy`.

---

## 2. Typography

Six sizes, no others (the linter counts `font-size` values in CSS and compares
them with `tokens.json`).

| Token | Size | Role | Components |
|---|---|---|---|
| `--fs-1` | 1.75rem | document title | `h1` |
| `--fs-2` | 1.25rem | section heading | `h2` |
| `--fs-3` | 1rem | card title | `h3` |
| `--fs-4` | 0.95rem | body | body, transcript, callout, strengths, praise |
| `--fs-5` | 0.875rem | secondary | subtitle, meta, why, tables, tips, links |
| `--fs-6` | 0.75rem | label | badge, chip, legend item, section title, tip number (uppercase, letter-spaced) |

The audit's 26 distinct sizes were folded by component role into these six
(for example 14.5px went to 1rem as a card title and to 0.875rem as body text).
That is the point of the scale: six roles instead of twenty-six values.

Line heights: two values, 1.6 (default) and 1.8 (long-form reading: transcript).
Weights 400/500/600/700 (Inter, Google Fonts). Tracking:
-0.02em on h1, 0.06em on section titles, 0.04em on badges and chips.

---

## 3. Spacing, radii, shadows

4px grid, six steps: `--sp-1: 4px`, `--sp-2: 8px`, `--sp-3: 12px`,
`--sp-4: 16px`, `--sp-5: 24px`, `--sp-6: 32px`. The rule covers `margin`,
`padding` and `gap`; `0` is always allowed.

Exclusions (not spacing): border widths 1px / 1.5px (highlight underline) /
3px (left rule), focus outline 2px, component dimensions (legend dot 10px,
tip number 24px, page max-width 760px), radii.

Radii: `--r-1: 6px` (tip number, audio), `--r-2: 10px` (cards), `--r-3: 999px`
(badges, chips, legend pills); the callout uses
`0 10px 10px 0`. Shadows: none. Borders and tints carry every separation.

---

## 4. Components

Document skeleton: `h1` + `.subtitle` + `.meta` → `.legend` → task blocks →
Comprehension Overview → Actionable Tips → Strengths.

| Component | Class | Rules |
|---|---|---|
| Legend | `.legend` + `.legend-item` + `.legend-dot.{role}` | Five categories, fixed order, legend text is never reworded |
| Section title | `.section-title` | Uppercase label at 0.75rem with a bottom hairline; task number and badge go inside |
| Task badge | `.badge.audio` / `.badge.written` | Exactly one per task; audio is blue, written is neutral |
| Prompt summary | `.prompt-summary` | What the exercise asked, one or two lines; droppable for written gap tasks |
| Audio | `.audio-block > audio[controls]` | Full URL of the recording in `src`; the block is removed from written tasks; hidden in print |
| Transcript | `.transcript-box` + `.hl-{role}` | The student's errors are underlined in the role's base colour on its own tint. The class is the category; no other highlight classes allowed |
| Fix card | `.fix-item.{role}` | 3px left rule, tint background. Inside: `.chip` → `.fix-line` (`.orig` → `.sugg`) → `.why` |
| Category chip | `.chip` of the same role | **Mandatory in every fix**: the category as text on top of the colour (colour-blindness protection). Fixed forms: Grammar, Word choice, Sentence flow, Style & speech, Punctuation |
| Revised version (removed in v1.5) | ~~`.revised-box` + `.label`~~ | No longer part of the structure: "How It Could Sound/Read" blocks are not generated; they remain only in documents shipped before 2026-10-01 |
| Praise | `.praise-box` | One concrete win per task, with a number or a quote; always present |
| Blue boxes | `.strengths-box` (and optional `.callout`) | 3px blue left rule, `--accent-tint` background |
| Tables | `.table-scroll > table.comp` | The wrapper is mandatory (mobile scroll). Verdict cells: `td.good`, `td.miss` |
| Tips | `.tips-grid` + `.tip-card` + `.tip-num` | 2–4 cards, each drawn from this document's fixes; at most one link, and it points at a specific exercise |
| Strengths | `.strengths-box` + `.item` | 3–6 items, each starting with a star, each carrying a quote or a number |

Slot instructions for authors inside the template are marked
`<!-- SLOT: … -->` (11 markers) — each one says what to fill in and which
classes are allowed.

---

## 5. Accessibility, mobile, print

**Colour and colour blindness.** Red and green are not distinguishable under
deuteranopia, and no palette fixes that, so a redundant signal was added:
every fix card carries a text chip with its category, the legend is a fixed
list of labelled items, and the colour order never changes. Machado matrix
simulation (severity 1.0) shows grammar and style converging to a distance of
23 out of 441 and word choice and flow to 19; the conclusion is recorded here
as a rule: **colour is never the only carrier of meaning.**

**Minimums.** Text on tints ≥ 4.5:1 (both text tokens pass on all nine
backgrounds), non-text indicators ≥ 3:1 against white. Transcript highlights
differ by colour only, but their category is always repeated below in the fix
cards; this is a conscious limit of v1.

**Focus and theme.** `:focus-visible` for links and audio (2px `--accent`
outline, 2px offset), `<meta name="color-scheme" content="light">`. Dark theme
is not part of v1.

**Mobile.** The primary scenario is a phone at 390px. `body` max-width 760px,
padding 32/24px, at ≤480px 24/16px with smaller card paddings;
`@media (max-width: 600px)` collapses tips into one column; tables live in
`.table-scroll` (`overflow-x: auto`, table `min-width: 480px`) and scroll
horizontally; native audio controls span the full width.

**Print.** `@media print` hides the players, unrolls the table wrappers, keeps
cards and table rows from breaking across pages (`break-inside: avoid`),
`print-color-adjust: exact` preserves the tints, links get underlines, page
padding drops to zero.

---

## 6. Generation policy

1. **A new document is a copy of the template.** Fill the `<!-- SLOT -->`
   blocks. Classes, colours, sizes and spacings are never invented: the system
   already contains everything a document needs.
2. **Both tools must be green before delivery:**
   `python3 tools/check_design.py <file>` (static conformance, reads
   `tokens.json`), then `python3 tools/qa_run.py <file>` (Playwright: overflow,
   fonts, audio, screenshots).
3. **Version stamp.** Line 2 of every document carries
   `<!-- design-system: vX.Y -->`. It is mandatory and never removed.
4. **A system change is a new version.** Edit the tokens, the template and
   this file, bump the version (v1.1, v1.2, …) in all three places: the HTML
   stamp, `tokens.json` → `version`, and this document's title.
5. **Delivered documents are never rewritten.** A typo fix is a new dated file;
   the old one stays as delivered.
6. **Prose rules for teacher text** (fix notes, praise, tips): short, 2–3
   sentences per why-note; second person ("you"), never third; no long
   dashes; no machine speech metrics (no wpm, no pause counts, no "thinking
   sound" counters); varied sentence lengths. The student's own
   words (transcripts, quotes, written answers) are never edited.

---

## 7. Acceptance history

- **v1.0** was accepted by a 42-check verifier: tag balance, all `hl-*` classes
  declared, print and focus rules present, exactly six distinct font sizes all
  resolving into `tokens.json`, zero inline styles, all 28 hex values on the
  whitelist, every margin/padding/gap on the 4px grid, a chip in each of the 13
  fixes with the chip class matching the fix class, version stamp after the
  DOCTYPE.
- Render checks across Chromium at 390×844 and 1280×900: four configurations,
  zero page overflow; on the phone the tables scroll inside their wrapper
  (483px inside 358px) while the desktop fits them whole; an old baseline had
  117px of horizontal overflow on mobile, which v1 removed.
- Linter: 9/9 on the templates and the demos at every version, including
  v1.1–v1.5. The tooling self-test (`tools/selftest.sh`) asserts both tools'
  exit codes against the fixtures.
- **v1.1** (2026-09-24): the closing block, the line after the legend and the
  "At a Glance" section were removed from the structure.
- **v1.2** (2026-09-24): all machine speech statistics were removed (pace,
  pauses, thinking-sound counters); the document now ends with Strengths.
- **v1.3** (2026-10-02): the band-card variant was added — band hero, dot
  scale (nine dots, role and aria-label mandatory), skill cards, findings,
  criteria tables, quick fixes, next moves. One scale value was added for the
  display band number (3.25rem), so band cards may use up to 7 distinct sizes.
- **v1.4** (2026-10-05): skill colour coding in band cards. Each block that
  belongs to a skill gets that skill's pastel tint through an `sk-*` class,
  which sets `--sk` / `--sk-tint` / `--sk-ink` and cascades to children
  (dots, stars, badges). No new colours; existing semantic tints are reused.
  Mapping: Listening → `--accent`, Reading → `--style`, Writing →
  `--word-choice`, Speaking → `--punct`. The text label of the skill is always
  kept: the colour duplicates, it does not replace.
- **v1.5** (2026-10-09): the revised-version block left the canon. The "How It
  Could Sound (Spoken)" / "How It Could Read" blocks and the green "More
  Polished …" label are no longer generated: after the fixes a task goes
  straight to its praise box (praise stays mandatory). Both templates lost
  the slot — 11 `SLOT` markers now — and the `.revised-box` / `.revised-box
  .label` CSS rules were removed from the canonical stylesheet (the component
  is retired the way `.closing` was in v1.1). The linter is unchanged: the
  block never was a required component. Applied to documents shipped from
  2026-10-01; earlier files and showcases keep the block historically and are
  not rebuilt. Version bumped in the three places: template stamps (v1.5),
  `tokens.json` (1.5), this document's title. The band-card skeleton is
  unchanged.

---

## 8. Out of scope for v1

Dark theme; an editor or document generator; editing old files; other document
types (lesson plans, worksheets). Each of these is its own decision after v1.
