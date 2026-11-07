# Audiobook — Plan

Turn a PDF (books, and also papers and reports) into an audiobook narrated in English in a voice
cloned from a short recording the user provides. Everything runs locally and free, on this CPU-only
machine.

`CLAUDE.md` holds the engineering rules; this file holds the decisions, the design and the order of
work. When they disagree, fix whichever is wrong — don't let them drift.

---

## 1. Locked decisions

| Decision | Choice | Why |
|---|---|---|
| Language | **Python** | The TTS model and the strongest PDF-understanding tools are Python-only. Time is spent in model inference, not in the host language. A TypeScript web UI can sit in front later. |
| Voice | **Pocket TTS** (Kyutai, MIT), **cloned voices** | Runs faster than real time on CPU; clones from a short clip. User's choice. |
| PDF understanding | **Docling** (IBM, MIT) | Layout model gives real reading order and labels every element (heading, paragraph, list item, table, formula, caption, page header/footer). Hand-written PyMuPDF heuristics could not do this reliably — see §2. |
| Runtime | Python 3.14 venv at `.venv/`, CPU-only PyTorch | No usable GPU (Intel UHD 620 + AMD WX 3200, unsupported by PyTorch). |
| Output | One MP3 per chapter + optional single `.m4b` with chapter markers | MP3 plays anywhere; M4B is the audiobook-app standard. |
| Interface | CLI and MCP door; **no UI of its own** | The standalone web app (M7) was removed on 2026-10-10 and its features live in Shelby's Audiobooks panel (M8). |

## 2. What we learned (evidence, 2026-09-29)

Measured on this machine:

- **Pocket TTS**: model load ~8 s (first run also downloads weights); cloning a voice ~2.5 s;
  synthesis **~1.4× real time**. A 10-hour book ≈ 7 hours of rendering. → Rendering must be
  resumable and must never redo finished work.
- Pocket TTS cloning weights are gated on Hugging Face (terms accepted; token in `.env`).
- Pocket TTS reads reference WAVs with Python's `wave` module: **16-bit PCM only**. Float WAVs fail
  with `wave.Error: unknown format: 3`. Always convert the reference with ffmpeg first.
- **Docling** on the test paper (`books/2609.09153v1.pdf`, 36 pages, two-column arXiv paper), OCR
  and table-structure models off: **125 s** (~3.5 s/page). A 300-page book ≈ 17 min — negligible
  next to rendering, but worth caching.

What the first prototype (PyMuPDF + heuristics) got wrong on the paper, and what Docling does:

| Problem | PyMuPDF prototype | Docling |
|---|---|---|
| Section starting mid-page ("4. Experimental Setup" on the same page as "5. Results") | Lost/merged — bookmarks only give a page | Correct: headings found in reading order |
| Running headers, page numbers, arXiv stamp, "Corresponding author" footnote | Partly removed by repetition heuristic | Moved to a separate *furniture* layer — excluded automatically |
| Tables | Read out as streams of numbers | Labelled `table` → skip |
| Equations | Garbled symbols | Labelled `formula` → skip |
| Figure/table captions | Read inline | Labelled `caption` → skip (configurable) |
| Reference list | Appended to "Conclusion" | Starts at a `References` heading → skip that section |

Still needed on top of Docling (observed in its output):

1. **Heading hierarchy**: Docling reports every heading as level 1 ("5." and "5.1." alike). Derive
   the level from the numbering (`5` → 1, `5.1` → 2, `A.1` → 2).
2. **Paragraphs split by a figure or page break**: "…responsive to its current progress," | figure |
   "and able to improve…". Join a paragraph that doesn't end a sentence with the next one when that
   one starts in lowercase.
3. **Inline citations**: "(Qin et al., 2024; Sumers et al., 2023)", "[12]", "Yao et al. (2023b)".
   Unreadable noise when spoken; strip them.
4. **Front matter**: author list with affiliation superscripts ("Yuxing Lu 1,2,3 , …"),
   affiliations. Read the title and abstract, not the affiliations.
5. **Paper-internal oddities**: code blocks, prompt templates and agent traces in appendices show up
   as `code` items or as headings ("Step 45 (Month 31):"). Code is skipped; the rest is handled by
   the appendix policy (§4.3).

## 3. Architecture

Stages with hard boundaries, following the pattern that worked in `docu-ai`: each stage has one job,
and the data between stages is plain, inspectable, and saved to disk.

```
PDF ─[1 extract]─► DoclingDocument (cached JSON)
    ─[2 plan]────► BookPlan  (chapters → spoken segments + skipped items with reasons)
    ─[3 voice]───► VoiceState (cached .safetensors)
    ─[4 speak]───► per-segment audio (cached .npy)
    ─[5 assemble]► chapter MP3s / M4B
```

Boundaries:

- **extract** is the only module that imports Docling. It returns a `DoclingDocument` and caches it
  as JSON keyed by the PDF's content hash, so re-planning never re-runs layout analysis.
- **plan** is pure: no I/O, no models, no Docling calls — it takes a `DoclingDocument` (or the
  cached JSON) and returns a `BookPlan`. All cleaning and chapter decisions live here, so they're
  unit-testable against saved JSON with no model loaded. Every dropped element is recorded with a
  reason ("table", "citation", "references section", …) — nothing disappears silently.
- **speak** is the only module that imports Pocket TTS. It knows nothing about PDFs.
- **assemble** is the only module that calls ffmpeg for output.
- **The CLI** is a thin front door over functions in `operations.py` that take data and return
  data. A web UI or MCP server later reuses the same operations — neither front door wraps the other.

### BookPlan (the central data structure)

```python
@dataclass
class Segment:            # one unit the narrator speaks
    kind: Literal["title", "heading", "paragraph", "list_item"]
    text: str             # final spoken text, after all cleaning
    source_pages: list[int]

@dataclass
class Skipped:
    kind: str             # "table", "formula", "caption", "code", "references", "citation", ...
    text: str             # original text (truncated), for the preview report
    page: int

@dataclass
class Chapter:
    title: str
    segments: list[Segment]
    skipped: list[Skipped]

@dataclass
class BookPlan:
    title: str
    chapters: list[Chapter]
```

Serialised to JSON next to the output so a run can be inspected, diffed and resumed.

## 4. Stage design

### 4.1 Extract (Docling)

- `PdfPipelineOptions(do_ocr=False, do_table_structure=False)` by default — we skip tables, so
  their structure isn't needed, and OCR is slow.
- **Scanned PDFs**: detect "no text layer" (Docling returns almost no text items) and re-run with
  `do_ocr=True`, warning that it's slow. Not in v1's acceptance criteria.
- Cache: `.cache/docling/<sha256-of-pdf>.json`.
- Memory: this machine has ~3–5 GB free. For long books, convert in page batches if memory becomes a
  problem (measure on a 300-page book in M2 before building this).

### 4.2 Plan — cleaning rules

Applied in this order; each is a small pure function with its own tests.

1. **Drop by label**: `table`, `formula`, `picture`, `caption`, `code`, `page_header`,
   `page_footer`, `footnote`, `document_index` (tables of contents). Recorded as `Skipped`.
2. **Heading levels from numbering**: `^(\d+|[A-Z])(\.\d+)*\.?\s` → level = number of parts.
   Unnumbered headings inherit "subsection" unless they match a known top-level name (Abstract,
   Introduction, Conclusion, References, Acknowledgements, Appendix, Preface, Prologue, Epilogue,
   "Chapter N", "Part N").
3. **Section filters**: drop everything under `References` / `Bibliography` / `Works Cited` until
   the next top-level heading. Also `Acknowledgements` (configurable).
4. **Join split paragraphs**: if a paragraph has no sentence-final punctuation and the next text item
   starts lowercase, merge them (skipping over any dropped items in between).
5. **Strip citations**: parenthetical author–year groups, numeric brackets `[3]`, `[3, 7–9]`, and the
   year part of narrative citations ("Yao et al. (2023b)" → "Yao et al."). Must not touch ordinary
   parentheses ("(Mode 3)", "(see below)") — the year pattern is the discriminator.
6. **Front matter**: keep the document title and the abstract; drop author and affiliation lines
   (text items before the first heading that are mostly names, digits and commas).
7. **Speech normalisation** (what the narrator can't say well): Unicode NFKC (math italics
   `𝑆` → `S`), ligatures, `e.g.` → "for example", `i.e.` → "that is", `et al.` → "and colleagues",
   `%` → "percent", `±`, `→`, `≥`, URLs → "link", en-dash ranges "1–6" → "1 to 6". Exact list driven
   by listening tests (M3), not guessed up front.
8. **Heading text**: drop the number for speech ("5.1. Main Results" → "Main Results"), keep it
   in chapter metadata.

### 4.3 Plan — chapters

- A chapter = a top-level (level 1) heading section. Everything before the first one becomes
  "Opening" (title + abstract for papers; front matter for books).
- Subsections are spoken as headings inside the chapter, followed by a pause.
- **Appendices** (headings `A.`, `B.`, or after an "Appendix" heading): included, but flagged in the
  plan and preview so the user can deselect them with `--chapters`. Default: include.
- **Fallback** when a book has no usable headings: use PDF bookmarks, then fixed-size parts of
  ~30 minutes each, split at paragraph boundaries.

### 4.4 Voice

- `voice add <name> <audio-file>`: convert with ffmpeg to 24 kHz mono 16-bit PCM with no filtering
  (measured: highpass/loudnorm slightly reduce likeness). If the recording is longer than 30 s, try
  several ~30 s windows cut at pauses and keep the one whose clone scores highest on speaker
  similarity against the rest of the recording (WavLM x-vector). **Never exceed 30 s** — longer
  prompts break generation. Warn under 15 s. Save `voices/<name>.safetensors` and the chosen
  `voices/<name>.wav`.
- `voice test <name> ["text"]`: speak a fixed sample paragraph so the user can judge the clone in
  ~15 s before committing hours of rendering.
- Voices are referred to by name after that. Built-in presets (`alba`, …) remain usable.
- Consent: the tool is for voices the user owns or has permission to use; say so in `voice add`.

### 4.5 Speak

- Chunk each segment at sentence boundaries, ≤ ~400 characters (keeps progress granular and
  re-renders cheap; never split a sentence).
- Cache per chunk: `.cache/audio/<voice-id>/<sha256(text + engine settings)>.npy`. Editing one
  paragraph or cleaning rule only re-renders the chunks whose text changed.
- Pauses: between chunks 0.40 s (user's choice), paragraph 0.6 s, heading 0.8 s before / 0.5 s after, chapter title 1.2 s.
- Progress: chunks done / total, elapsed, **estimated time remaining** (from measured speed).
- Ctrl-C is safe at any point; the next run resumes.

### 4.6 Assemble

- Per chapter: concatenate chunk audio + pauses → WAV → MP3 (`libmp3lame -q:a 4`) with title,
  album, track tags.
- Loudness-normalise (ffmpeg `loudnorm`, −18 LUFS) so chapters play back at the same volume.
- Optional `.m4b`: AAC 64 kbps, chapter markers from the plan, title/author metadata from the PDF.

## 5. CLI (v1)

```bash
audiobook preview BOOK.pdf                 # extract + plan; print chapters with durations; write
                                           # output/<book>/preview.md: exactly what will be spoken,
                                           # plus everything skipped and why. No TTS. (The approval step.)
audiobook voice add NAME CLIP              # clone and save a voice
audiobook voice test NAME                  # hear it on a sample paragraph
audiobook voice list
audiobook render BOOK.pdf --voice NAME [--chapters 1-3,5] [--m4b]
```

`preview` is the most important command: rendering takes hours, so the user reads what will be
said before committing. It needs no voice and loads no TTS model.

## 6. Testing

- **Plan rules**: unit tests per cleaning function with small literal inputs (citations, joins,
  heading levels, front matter).
- **Golden test**: save the Docling JSON for the test paper as a fixture; snapshot the resulting
  `preview.md`. Any rule change shows up as a readable diff. No Docling or TTS needed to run it.
- **A second fixture that's a real book** (a public-domain novel PDF with chapters, e.g. from
  Project Gutenberg) so rules aren't tuned only to arXiv papers.
- **Smoke tests** (slower, opt-in): Docling on a 2-page PDF; Pocket TTS on one sentence with a
  preset voice.
- `pytest`; the default test run needs no network, no Hugging Face token and no model downloads.

## 7. Milestones

Each ends with something the user can run and judge.

| # | Milestone | Done when |
|---|---|---|
| M0 | CLI prototype (PyMuPDF) | ✅ Done — renders a simple PDF to MP3/M4B with a cloned voice, resumable. |
| M1 | Docling extract + BookPlan + `preview` | ✅ Done (2026-09-30). On the test paper, `preview.md` has the correct 6 main sections + 6 appendices, no tables/formulas/captions/references/citations/page furniture, and no mid-sentence paragraph splits. Golden test in place. |
| M2 | Book fixture | ✅ Done (2026-09-30) with *The Final Quest* (163 pages): 6 chapters + 30 sections match its contents; Docling 6 min 8 s; memory not measured but no problems on this machine. Fixed: dialogue mislabelled as footnotes/list items, title from PDF metadata, "0f" typo. A public-domain novel previews with correct chapters and no page furniture; measured Docling time and memory for a 300+ page book recorded here. |
| M3 | Voice management + speech normalisation | ✅ Done (2026-09-30): `voice add` (window search), `voice test`, `voice list`; `speech.py` rules (roman numerals after Part/Chapter, Bible references, other n:n, all-caps runs, spaced ellipses, &, underscores, stray symbols), each verified by synthesis + Whisper; per-book corrections file. Extend as the user reports misreadings. |
| M4 | Render on top of BookPlan | ✅ Done (2026-09-30): renders from the plan, per-chunk cache, progress with time left, WAVs cleaned per chapter. Levelling was tried and rejected (see CLAUDE.md). |
| M5 | Full-length run | ✅ Done (2026-09-30): *The Final Quest*, 6 chapters, 4 h 07 min at 0.95×, one MP3 per part + M4B with chapter markers. Rendered across several runs (stopped and resumed; cached chunks reused). Parts II–V took ~2 h 10 min. |
| M6 | Scanned-PDF support (OCR) | ✅ Done (2026-09-30): no text layer → Docling re-run with RapidOCR (torch backend); 98% word accuracy on a test scan. |
| M7 | Web UI | ✅ Done (2026-09-30): `serve` — FastAPI + one-page UI: library/upload, chapter table, exact text, corrections editor, voice samples and cloning (with consent box), render with progress/time left, in-page players and downloads. One job at a time. **Superseded 2026-10-10 by M8: the app and `serve` were removed.** |
| M8 | Joined Shelby | ✅ Done (2026-10-10): merged with history into `shelby/audiobook/`; own `.venv`; MCP door (12 tools) over `operations.py`; analysis, render and voice work as detached background jobs that survive a backend restart; every M7 feature rebuilt as Shelby web app's Audiobooks panel (PDF and recording uploads, file playback and download through the assistant). See CLAUDE.md, "Shelby integration". |

## 8. Risks

| Risk | Mitigation |
|---|---|
| Pocket TTS mispronounces symbols, acronyms, numbers | Normalisation list built from listening tests (M3); `preview` shows the exact spoken text. |
| Clone quality depends on the reference clip | `voice add` cleans the clip and warns on length; `voice test` before long renders. |
| Docling memory on very long books (~3–5 GB free) | Measure in M2; batch by page range if needed. |
| Docling misses or mislabels a heading | Chapter fallback (§4.3); `preview` makes it visible before rendering. |
| Multi-hour renders get interrupted | Per-chunk cache; resume is a first-class tested path (M5). |
| Python 3.14 compatibility of future dependencies | Fall back to a 3.12 venv if a needed package lags. |

## 9. Open questions (defaults chosen; change any)

- **Figure/table captions**: skipped by default. Alternative: read captions as "Figure: …".
- **Appendices**: included by default, flagged in `preview`.
- **Authors**: dropped by default; the title and abstract are read.
- **Acknowledgements**: dropped by default.
