# CLAUDE.md

Guidance for Claude Code when working in this folder. It is one tool of the suite (`../CLAUDE.md`
holds the rules that cover all of them) and also runs alone from here.

## Project

An audiobook generator: a PDF is extracted and cleaned, and narrated in English by a local TTS
engine using a voice the user chooses — either a built-in preset voice or a voice cloned from a
short reference clip.

**`plan.md` holds the locked decisions, the design and the milestone order. This file holds the
engineering rules and the facts learned the hard way.** When the two disagree, fix whichever is
wrong. Status: M0–M8 done. M3's speech rules are a first pass driven by one book; extend them as the user
reports misreadings. `preview` and `render` both run on Docling + BookPlan (the PyMuPDF reader
is gone).

**Two front doors, no interface of its own.** The CLI (`python -m audiobook`) and the MCP door
(`./mcp`, which the suite's assistant launches) both sit on `operations.py`; neither wraps the
other. The standalone web app this tool once had was removed on 2026-10-10: its features (read a
book, check what will be spoken, corrections, voices, render with progress, play and download) are
the **Audiobooks** panel of the suite's web app (`../web`), which reaches them through the
assistant. Don't add a UI here.

Language is Python, decided deliberately: Pocket TTS and the strong PDF-layout tools (Docling) are
Python-only, and time is spent in model inference, not the host language. Don't propose a
TypeScript rewrite; the interface is TypeScript already, in the suite's `../web`.

## Target hardware (matters for engine choice)

- CPU-only in practice: Intel i5/i7 Whiskey Lake-U (8 threads), ~14 GB RAM.
- GPUs present are an Intel UHD 620 and an AMD Radeon PRO WX 3200 (Polaris, 4 GB) — neither is
  usable for PyTorch acceleration (no CUDA, Polaris is not supported by ROCm; checked again 2026-10-31: the
  driver does not even list the AMD card for compute, only the processor). This machine runs on the CPU.
- **On a computer with an NVIDIA card (2026-10-31)** the same code speaks on it: `tts.place` moves the model
  to `cuda` when `torch.cuda.is_available()`, says which in the log ("Speaking on the GPU: …" / "Speaking on
  the processor."), and falls back to the processor if the card refuses the model. Audio comes back on the
  model's device, so it is read through `tts.to_array` (`.cpu()` first), never `.numpy()` directly. Voices
  loaded from `.safetensors` land on the model's device by themselves (Pocket TTS's `_import_model_state`),
  and saving one from a GPU works (safetensors copies to the processor first). Docling picks the card by
  itself (`AcceleratorOptions.device = "auto"`). The CPU-only PyTorch never sees a card, so the install
  decides: `./install-deps <python> nvidia` installs `requirements.txt` with its two CPU pins left out and
  `requirements-nvidia.txt` (PyTorch 2.14.0 for CUDA 12.6: any driver that runs CUDA 12, and the older cards
  CUDA 13 dropped) in their place; `./setup` and the backend image call it when they find an NVIDIA card.
  3.65 GB to download against the CPU build's 0.2 GB. **Not run on a GPU** (there is none here): the
  resolve of that set was checked (`pip install --dry-run`, 141 packages, `pip check` clean), and the CPU
  path was run for real after the change (a sentence in `abigail`, 1.09× real time, Whisper read it back
  word for word).
- A full book is hours of audio, so the engine must run at or above real-time on CPU.
- Python 3.14 in **this tool's own venv**, `.venv/` — never the suite's shared one. `./setup` at the
  suite's top builds it from `requirements.txt` (every version pinned, with PyTorch's CPU index
  declared in the file) and `requirements-dev.txt` (pytest); alone: `python3 -m venv .venv &&
  .venv/bin/pip install -r requirements.txt -r requirements-dev.txt`. Why separate (measured
  2026-10-10): it is 1.9 GB against the shared 696 MB, nothing else in the suite uses torch, Docling
  or Pocket TTS, and torch has to come from PyTorch's CPU index (PyPI's default is a multi-GB CUDA
  build). Packages in common are only fastapi, uvicorn, starlette, numpy, pydantic and
  huggingface_hub, at patch-level differences — it is the weight and the index, not a conflict,
  that decided it. `./mcp` and the job launcher both use this venv.
- `ffmpeg` is installed and is used for audio concatenation and encoding.

## Chosen engine: Pocket TTS, with voice cloning

The user chose **Pocket TTS** and wants voices **cloned** from a reference clip (not presets).

- API: `TTSModel.load_model()` → `model.get_state_for_audio_prompt(wav_or_preset_or_safetensors)`
  → `model.generate_audio(state, text)` returns a 1-D torch tensor at `model.sample_rate` (24 kHz).
- Cache cloned voices with `pocket_tts.export_model_state(state, "voice.safetensors")`; loading
  the `.safetensors` is much faster than re-encoding the WAV.
- Cloning weights are gated on Hugging Face (terms already accepted on the user's account). The
  token lives in `.env` as `HF_TOKEN` (git-ignored, mode 600) and the CLI loads it. Without it,
  only the built-in preset voices work and cloning raises `ValueError`.
- Pocket TTS reads reference WAVs with Python's `wave` module, so they must be 16-bit PCM —
  float WAVs fail with `wave.Error: unknown format: 3`. `tts.prepare_reference` converts any input
  with ffmpeg.
- The clone reproduces the reference audio's quality (noise, room echo), so clean the clip first.
- The user's voice is **`abigail`**: `voices/abigail.safetensors`, cloned from
  `voices/abigail.wav` = 0.3–29.0 s of `voice/abigail.mp3`, unprocessed (24 kHz mono s16). The
  source is low-bitrate (32 kbps, 22 kHz) mono. The user says the speaker consented; personal use only.
- Clone-likeness findings (WavLM speaker similarity vs held-out real speech; real-vs-real = 0.99):
  ~30 s prompts beat shorter ones (11 s 0.94, 19 s 0.95, 30 s 0.96); highpass+loudnorm slightly
  hurts; `temp` and decode steps don't help (defaults best). **Prompts over ~30 s break generation**
  (no EOS, similarity 0.71) — `voice add` must cap at 30 s. User rated v1 (0.95) "80% like her".
- Measured on this machine: model load ~8 s (first run also downloads weights), voice cloning
  ~2.5 s, generation ~1.4× real-time with the full model, so a 10-hour book took roughly 7 hours to render, hence the
  chunk cache. Renders are 8-bit and two pieces at a time since 2026-11-06: see "Faster renders".

## Other TTS engines considered

Keep the engine behind a common interface (see Architecture) so these can be added later.

| Engine | Role | Voice selection | License | Notes |
|---|---|---|---|---|
| **Pocket TTS** (kyutai-labs) | Default | ~26 presets + cloning from a `.wav` | MIT | 100M params, faster than real-time on CPU, supports Py 3.10–3.14. `pip install pocket-tts` |
| **Kokoro-82M** (hexgrad) | Fast preset voices | ~54 preset voices, no cloning | Apache 2.0 | Needs `espeak-ng`. `pip install kokoro` |
| **Chatterbox** (Resemble AI) | Highest-quality cloning | Cloning from ~10 s clip | MIT | Turbo (350M) wants a GPU; Nano (110M) is the CPU option. Tested on Py 3.11. Output is watermarked |
| **NeuTTS Air** (Neuphonic) | Alternative CPU cloning | Cloning from 3–15 s clip **plus its transcript** | Apache 2.0 | GGUF/llama.cpp builds for CPU. Output is watermarked |

Avoid for this project: XTTS-v2 and F5-TTS (non-commercial weight licenses, slow on CPU), and
`edge-tts` as a core dependency (free but an unofficial cloud endpoint with no cloning).

Voice cloning: only clone voices the user owns or has permission to use. Reference clips should
be clean, mono, single-speaker WAV with no music or background noise.

## Usage

```bash
.venv/bin/python -m audiobook preview book.pdf        # exact spoken text → output/<book>/preview.md
.venv/bin/python -m audiobook render book.pdf --voice abigail --chapters 1
.venv/bin/python -m audiobook render book.pdf --voice abigail --m4b
.venv/bin/python -m audiobook render book.pdf --voice abigail --speed 1.0   # default is 0.95 → *-0.95x.mp3
.venv/bin/python -m audiobook voice add NAME CLIP [--start S --end E]      # clone; long clips are searched
.venv/bin/python -m audiobook voice test NAME        # → output/voices/NAME-test.mp3
.venv/bin/python -m audiobook voice list
.venv/bin/python -m pytest -q                         # no models, network or token needed
```

Run everything from this folder: `output/`, `voices/`, `.cache/` and `.env` are relative to it (`./mcp`
and the background jobs do this themselves).

`--voice` takes a saved voice's name (`abigail`, `tina`), a `.safetensors` path, an audio file to
clone, or a preset like `alba`. Output goes to `output/<pdf name>/`. `--chapters` uses the numbers shown by `preview`.
`--speed` (0.5–2.0, **default 0.95** — the user's choice) is ffmpeg `atempo` applied at encode time — pitch
unchanged, and speech comes from the chunk cache, so a new speed costs seconds, not a re-render.

**Tried and rejected (2026-09-30) — don't re-propose without a new reason.** Output is the voice's
raw chunks + fixed silences + `atempo`, nothing else; the user compared by ear and chose this ("A")
as clearest.
- *Levelling*: the voice starts each sentence ~4.6 dB louder than the rest (inherited from the real
  reader, +4.2 dB; not caused by chunking). A heavy compressor + make-up gain closed the gap to
  0.6 dB but audibly reduced clarity (flattened within-word dynamics 14.6 → 12.2 dB). A slow gain
  curve kept dynamics (14.1 dB, gap 1.6 dB) but the user reverted everything before judging it.
- *Pause control*: replacing the voice's own pauses with fixed true silence. One sentence per
  generation gave exact pauses but duller consonants; shaping pauses inside multi-sentence chunks
  kept clarity but was reverted along with levelling.

## How a chapter opens (2026-10-31)

"Chapter 6 Knowing the Source of Your Dreams" was said as one phrase, so "six" ran straight into "knowing" (the user heard it in a
finished book, and Whisper's word times on chapter 6 agreed: `6` ended at 1.10 s, `Knowing` began at 1.10). `announcement` in
`render.py` now splits a label off the front of the spoken title (`plan.CHAPTER_PREFIX`: Chapter, Part or Book with a number, a
roman numeral or a number word) and says them apart: the label as a sentence of its own ("Chapter 6."), `LABEL_PAUSE` (0.7 s) of
silence, then the title, then the usual `TITLE_PAUSE`. A chapter with no label ("Opening", "Foreword") is one piece, as before.

- **Checked the way speech.py asks (the real abigail voice, then Whisper and silence detection):** the old way had no silence
  between the two (Whisper: gap 0.00 s); the new way has about one second of silence between "Chapter 6." and the title (0.7 s
  of ours at 0.95x, plus the voice's own tail), then the same pause after the title. **Not listened to by ear** by whoever wrote
  this: the user's ear is the last check.
- **A finished book keeps its old openings until it is rendered again.** The chunk cache is keyed on text, so the body of every
  chapter is already cached and a re-render costs only the new short title chunks and the encode.
- `chapter_texts` (what the progress count and the estimate are built from) uses the same pieces, so the count is exactly what the
  voice is asked for; a test says so.

## Speaking a chat reply (`speaking.py`, the `speak` tool, 2026-11-06)

The suite's chat reads replies aloud through `speak(text, voice)`: up to 600 characters in (the page sends a sentence
at a time), an MP3 back as base64, nothing written. It is marked `interface_only` in its `_meta`, so the assistant
never shows it to the model, and it is read-only.

- **Its own model, kept loaded, 8-bit on the processor** (`tts.load_speaking_model`, so Pocket TTS is still imported
  only by the speak stage). Measured on this laptop with abigail: 2.0x real time against the full model's 1.38x, a
  short opening phrase ready in 0.8 s against 1.35 s, every word right in Whisper's read-back (7 of 7 runs), and
  likeness 0.953 against 0.957 (two recordings of a real person score 0.99). More threads gave nothing (Pocket TTS
  pins itself to one, and 2 or 4 measured the same); Kyutai's optional torchao made it six times slower here. On an
  NVIDIA card it is the full model. Let go after ten idle minutes; about 0.85-1 GB while loaded.
- **Through the real backend:** the first call took 9.8 s (the libraries and the model loading), then 1.3-2.0 s per
  sentence for 2.4-4.8 s of audio, so each sentence is ready before the one before it has finished playing. Whisper
  read all five back word for word.
- **The same text rules as a book** (`speech.for_speech`), so a number or a run of capitals reads as it does in a
  render. A text with nothing to say, over the limit, or naming a voice that does not exist is refused before any
  model loads. The default voice is abigail where it exists, else the preset alba.
- **Not for books**: a render loads its own models in its own process (see "Faster renders"). It reads the mark
  `speak` touches on every call (`.cache/speaking`), and makes one piece at a time while a reply is being read.
- **Not listened to by ear** by whoever built it; the user's ear is the last check.

## Faster renders (2026-11-06)

A render speaks with the 8-bit model and, on the processor, makes two pieces at a time. The user chose 8-bit after
listening to the same passage from both models ("i think they are the same").

- **Measured on a whole chapter**: chapter 4 of `2609.09153v1.pdf` (8 min 20 s of audio, 32 pieces, abigail), with
  this laptop busy (load 3-7). One piece at a time took 231 s, 2.18x real time; two at a time 212 s, 2.36x. The full
  model is 1.38x, so a 10-hour book goes from about 7.2 hours to about 4.2. `preview`'s estimate is 2.0x
  (`RENDER_SPEED`, was 1.4).
- **The second worker is worth less than the bench said.** Idle, two copies made 2.84x between them against one's
  2.0x (+42%); on the real chapter with the laptop busy it was +8%. A third copy added nothing even idle (the memory
  bus is the limit by then). Each copy holds about 0.85 GB. Two is the default; one on an NVIDIA card or with under
  2.4 GB free; `AUDIOBOOK_RENDER_WORKERS` sets another number. The job's log says which ("Rendering 2 pieces at a time.").
- **How** (`workers.py`): Pocket TTS keeps itself to one processor thread, so one render left most of the laptop idle.
  Each worker is its own process with its own model (Pocket TTS is not thread-safe), started with `spawn`, never
  `fork` (a forked copy of a process that has loaded torch can hang). The render's own process loads no model at all
  (`Narrator` loads only when it first speaks). A chapter's missing pieces are made first, each returned with its own
  text and kept in the chunk cache; then the chapter is put together from the cache in its own order, exactly as a
  one-at-a-time render does, so the order never depends on which piece finished first.
- **While a reply is read aloud in Chat, a render makes one piece at a time**: `speak` touches `.cache/speaking`, and
  the render checks it before each piece, for 30 s after. Three copies at once slowed each to 0.96x real time, the
  edge of a reply stuttering.
- **The chunk cache keeps the two models apart**: 8-bit pieces in `.cache/audio/<voice id>-int8/`, the full model's
  where they always were. A chapter is spoken from the full model's pieces when every one is there (so a book rendered
  before re-encodes at a new speed for nothing and sounds as it did); otherwise the whole chapter is made in 8-bit, and
  one chapter never mixes the two. The cost: a chapter the full model had half made is made again, all of it.
- **Progress counts each piece once**, as it is made. Time left comes from the wall time between finished pieces, so
  it reflects two at a time; it counts only what the chapters' chosen models still lack.
- **A worker's output is flushed after it loads.** Otherwise "Loading Pocket TTS..." reached the job's log only when
  the render ended, and the job said "starting" instead of "loading the voice model" (`background.read_progress`).
- **Each model load prints PyTorch's warning** that quantized tensors (`torch.quantize_per_tensor`) are deprecated,
  once per worker. Harmless today. It means a later PyTorch may drop what 8-bit Pocket TTS uses: torch is pinned, and
  an upgrade must be checked with an 8-bit render.
- **Pocket TTS warns of its own limit**: "Chunk has 58 tokens (max 50), generation may skip words", for one long
  sentence of that chapter, in both renders. Not new and not changed here: by Pocket TTS's own account, a sentence
  that long may lose words with either model.
- **Whisper read each render of that chapter back** against its text (1131 words). Matching in order: two at a time
  1037 (91.7%), one at a time 1035 (91.5%), and the full model, rendered for this comparison, 1018 (90.0%). So 8-bit
  loses no words the full model keeps. In the two-at-a-time render, where every difference was listed, most were maths
  read aloud. Paragraphs' first words were found in order about equally (19, 18 and 18 of 22). One sentence's end
  ("compares these construction strategies") was missing from the two-at-a-time render only. Each piece is made
  afresh, and Pocket TTS samples, so one render can differ from the next; a worker hands back the whole piece it made.
- **Run:** 19 deliberate breaks of the new code, each caught by a test (two only after a test was added: progress
  counting a chapter the full model had already made, and the worker's buffered log line).
- **Not listened to by ear** as a whole chapter: the user compared one short passage. The user's ear is the last check.

## Code layout

- `audiobook/extract.py` — Docling conversion, cached in `.cache/docling/<pdf sha256>.json`; PDFs
  with no text layer are re-run with OCR (RapidOCR, torch backend).
- `audiobook/plan.py` — pure `DoclingDocument → BookPlan`: walk (skip labels + their children),
  chapter labels placed, heading levels from numbering, the book's own contents page, the title,
  chapters, section filters, citations, paragraph joining, front matter, empty headings, then
  corrections + `speech.for_speech`. Every drop is a `Skipped`.
- `audiobook/names.py` — pure: a title and author from a file name (download sites' tags), the cut at
  the title page's heading, placeholder titles, and a chapter's audio file name (`render` makes it,
  `operations` finds it again).
- `audiobook/speech.py` — pure rewrites for what the voice misreads, each verified by synthesis +
  Whisper (see its docstring); per-book corrections (`book.corrections.txt` next to the PDF).
- `audiobook/preview.py` — pure `BookPlan → preview.md` (chapter table, exact text, skipped summary).
- `audiobook/operations.py` — `plan_book`, `preview_book`, `render_pdf`, and what the MCP door needs on
  top: `book_overview`, `chapter_text`, corrections, `list_audiobooks`, `start_*`, `job_status`. What
  both front doors call.
- `audiobook/background.py` — analysing, rendering and voice work as detached background jobs.
- `audiobook/mcp_server.py` — the MCP door (17 tools); `./mcp` launches it.
- `audiobook/speaking.py` — `Speaker`: a chat reply spoken while someone waits (the `speak` tool; see below).
- `audiobook/voices.py` — `add_voice` (window search scored by WavLM similarity), `test_voice`,
  `list_voices`; metadata in `voices/NAME.json`.
- `audiobook/__main__.py` — CLI and `.env` loading.
- `audiobook/chunk.py` — sentence chunks ≤400 chars. `audiobook/tts.py` — model loaded once per
  process and placed on a GPU when there is one (`place`), `Narrator`, `resolve_voice`, `to_array`. `audiobook/render.py` — speaks a plan `Chapter` with pauses,
  caches each chunk in `.cache/audio/<voice id>[-int8]/<text hash>.npy`, reports `Progress` (with time
  left) through a callback, encodes MP3/M4B. `audiobook/workers.py` — how many pieces a render makes at once, and
  the worker processes that make them.
- `tests/` — rule unit tests; golden `tests/golden/paper.preview.md` from
  `tests/fixtures/paper.docling.json.gz`. Accept an intended change with `UPDATE_GOLDEN=1` and
  **read the diff** before committing it.

## PDF extraction: Docling

- Pipeline options: `PdfPipelineOptions(do_ocr=False, do_table_structure=False)`. Measured: 125 s
  for a 36-page two-column paper (~3.5 s/page). Cache the result as JSON keyed by PDF hash.
- `doc.iterate_items()` yields body content only; running headers, page numbers and page footnotes
  are in the *furniture* content layer and excluded by default. Don't re-implement header removal.
- Labels to skip: `table`, `formula` (text is empty), `picture`, `caption`, `code`. Skip their
  **children** too — Docling nests table cells and figure text as `text` items inside them.
- `key_value_area` groups are **not** forms here: Docling uses them for "Label: prose" runs
  ("Initialization: …"). Read their children; skipping them lost real content.
- **Docling reports every `section_header` as level 1**, "5." and "5.1." alike. Derive levels from
  the heading numbering.
- Paragraphs interrupted by a figure, formula or page break come out as two `text` items; join
  them when the first lacks sentence-final punctuation and the second doesn't start with an ASCII
  capital or digit (it can start with "Φ(e)").
- The reference list is a `References` heading followed by `list_item`s — drop that section.
- **`footnote` labels are unreliable in books**: dialogue at the foot of a page gets labelled
  `footnote`. Only skip footnotes that start with a marker (`*`, `†`, `1`, `[1]`); read the rest.
- Docling tags some dialogue paragraphs as `list_item`; paragraph joining must treat them like
  paragraphs.
- Title/author come from the PDF's metadata (`pdf_metadata`, via pypdfium2) — ebook title pages are
  often images — unless it is a placeholder a program filled in (`about:blank` from Chrome, `Microsoft Word
  - x.docx`). Without one, see "How a book's title and chapters are found" below.
- Measured on the book (163 pages, calibre ebook): Docling 6 min 8 s (~2.3 s/page), no OCR needed.
- OCR: RapidOCR's default onnxruntime backend isn't installed — use `backend="torch"`. Measured on
  2 scanned pages: 98% word accuracy; errors are run-together words ("theagent") and dropped
  spaces, e.g. "et al.,2024" (citation regex tolerates it). Slow: ~1 min/page under load.

## How a book's title and chapters are found (2026-10-30)

From a real ebook (*Dreams and Visions*, a Z-Library PDF, 154 pages). Before: its title was "Praise for", its
16 chapters were 15 words each (4 to 13 seconds of audio), and "Introduction" was the whole book, 4 h 09 min
in one file. After: 19 chapters, each starting on its own first page, named as its contents page names them.

- **Docling read the contents page as headings**, each entry ("Chapter 1 God's Purpose…") followed by a line
  about it, so every entry was a chapter. `find_contents` leaves out an entry: a top-level heading that is the
  same chapter as a later one (its label, "chapter 3", or else its words), with at most 60 words before the next
  *top-level* heading, two or more of them. Counted to the next heading instead, a real chapter that opens
  straight onto a section is taken for one when a book numbers its chapters again in each part (tested).
  The entry's text names the chapter ("God's Purpose…", where the chapter's page says "GOD'S PURPOSE…" or has
  no title at all), and a "Contents" heading goes with them.
- **"Chapter 3" on a line of its own is text to Docling, and not in its place**: at the foot of the chapter's
  first page, after the title, or with no title heading at all (8 of 16 chapters). `place_chapter_labels`
  makes it a heading at the top of its page; an unnumbered heading right after it on the same page joins it.
  Only a label read as *text* moves: one read as a heading is in its place, and moving it would take the end
  of the chapter before when two chapters share a page. **Not handled:** a text label mid-page in a book
  whose chapters run on without a page break would still take that page's start.
- **A chapter's own title page right under its announcement** ("Chapter 16 A Charge to Dreamers", then "A
  CHARGE TO DREAMERS") is skipped as a `repeated heading`, so it is not read twice.
- **The title**, in order: the PDF's own; the file name cut where a heading on the title page ends
  ("Dreams and Visions Understanding Your Dreams…" and "DREAMS AND VISIONS" → "Dreams and Visions"); the file
  name when it is two words or more; the book's first heading (a paper's title, when the file is
  `2609.09153v1` or `paper`). A file name loses what download sites add: "(Z-Library)", "(Author [Last,
  First])" → the author, Library Genesis's "Author - Title (Year, Publisher) - libgen.li". Before the book is
  read (`book_overview` of an unread PDF, `start_analysis`'s job), only the metadata and the file name exist.
- **Each chapter's audio is found by its whole file name** (`names.chapter_audio`): number and title, any
  speed. `book_overview` gives each chapter its files and lists the rest as `other_audio` (the .m4b, and files
  from an earlier reading whose chapters were numbered differently, which the page shows apart). Jobs carry the
  book's `title`, so the page and Overview stop naming a book by its 120-character file name.
- **Run for real:** the book re-planned from its Docling cache (only pages 15–17 left out as contents, 392
  words); `list_audiobooks` in the container; in Chrome, a never-seen PDF uploaded, read by itself, its
  chapters shown, deleted. Twenty deliberate breaks of these rules, each caught by a test. **Not run:** a
  render with the new chapters (the book's audio is still the old split, shown as "From an earlier reading").

## Architecture rules

Stages: extract → plan → voice → speak → assemble (details in plan.md §3).

- Only `extract` imports Docling; only `speak` imports Pocket TTS; only `assemble` writes output
  audio with ffmpeg.
- `plan` is pure (no I/O, no models) and records every dropped element with a reason, so the
  `preview` command can show exactly what is and isn't spoken.
- Front doors (the CLI and the MCP door) call functions in `operations.py`; neither wraps the other.

## The suite integration (2026-10-10)

How it was joined to the suite, and the rules that came out of running it for real:

- **Long work is a detached process, not a thread.** `background.start` launches
  `python -m audiobook …` inside `bash -c '"$@"; echo "[exit $?]"'` with `start_new_session`, so the
  backend restarting (or dying) does not stop it. Verified: a render survived `pkill` of the backend
  and the restarted backend picked up the same job id, mid-render, and saw it finish. The wrapper's
  `[exit N]` line is how a crash, a finish and a kill are told apart — **`interrupted` means that
  line never appeared**. Progress is parsed from the CLI's own output (`[ 40%] chapter 2: …`), so
  changing those print formats in `__main__.py` breaks `background.PROGRESS`; the tests say so.
- **One job at a time, any kind.** Docling and the voice model each use every core. State is
  `.jobs/<id>.json` plus `.log` (git-ignored); a pid is trusted only if `/proc/<pid>/cmdline` shows
  our marker and the job's target.
- **A stopped render loses nothing:** every spoken chunk is in `.cache/audio/<voice id>/`, so
  starting it again continues, and a new speed is only a re-encode. Docling's cache is keyed by the
  PDF's content hash, so a re-uploaded copy of a book is already "read".
- **Everything that can be wrong is checked before a job exists** (`operations.start_render`: analysed,
  voice, speed, chapters): a render failing in its first second is a job nobody should have to poll.
- **The gate is the tools' own annotations.** Eight tools only read (`list_*`, `describe_audiobook`,
  `preview_book`, `read_chapter`, `get_corrections`, `job_status`, `inventory`); the eight that start work, write a
  file or delete one (`release` among them) are not read-only, so chat asks first and `tests/test_mcp_door.py` pins
  the split.
- **Deleting a book's audio (2026-10-30), `delete_audiobook`.** It removes `output/<book>/` and nothing else.
  Not the PDF (the suite's assistant owns uploads), not a voice, and **not the two shared caches**: the spoken
  chunks in `.cache/audio/<voice id>/` are keyed by voice and text, so they belong to no one book, and Docling's
  `.cache/docling/<pdf hash>.json` is kept on purpose so a re-uploaded book is already read. Its rules, each with
  a test that fails without it: the argument is a **name, never a path**; `output/voices` (the samples
  `voice test` makes, which `list_audiobooks` also lists as a "book") is refused; a link is refused, even one
  to another book's folder (it passes every location check and would empty the other book); a folder holding
  anything but plain files is left exactly as it was; and it is **refused while a render or reading of that book
  runs** (matched by the job's PDF name, so a job on another book or a voice does not block it). Deleting what
  is not there removes nothing and says so. Its approval shows `describe_audiobook`'s summary (file names and
  sizes, a warning if the book is busy, what is not touched), declared in `_meta` like mail-ai's send.
  `<book>.corrections.txt` sits beside the PDF in the assistant's uploads folder, so it is left behind.
- **Cloning needs a consent statement, and the model must not write it.** `start_voice_clone` refuses an
  empty `consent`, its description tells the model to ask the user, and the text is kept in
  `voices/NAME.json`. In chat the approval card shows it before anything runs.
- **Corrections are reported, not guessed at.** `set_corrections` returns every line that did not become
  a correction (`parse_corrections` skips them silently, so a typo would otherwise do nothing and say
  nothing). A line with **nothing to find** (`=> PG`) is one of them: applied, `replace("", "PG")`
  puts PG between every character of the book.
- **A chapter selection is validated before it is expanded.** A reversed `5-3` selected nothing, and
  nothing selected means *render everything*; `1-99999999999` built the whole set first. Each part is
  now checked against the book's chapter count before `range()` sees it (`operations.parse_selection`,
  shared with the CLI).
- **A sample is for a voice by name, never a path.** `voice test NAME` writes
  `output/voices/NAME-test.mp3`; with an absolute path as the name that lands wherever it points. A
  *render* may still clone from an audio file, and gets it as a full path (a `~` would not be expanded
  by the job).
- **Ask whether the process is alive before reading its log** (`background.refresh`). Read in the other
  order, a job that wrote `[exit 0]` and exited between the two looks gone with no exit line, and is
  recorded as `interrupted` for good. `interrupted` is final, and jobs are ordered by id, never by
  file timestamp (re-saving a dead job used to move it ahead of newer ones). Two `start` calls at
  once were both let through until `_START` made check-and-launch atomic.
- **Cancel stops the whole process group, and writes its marker first.** `background.cancel` writes
  `.jobs/<id>.cancel`, *then* sends SIGTERM to the group (the job is its own session, so its pid is
  its group), then SIGKILL if anything is left after 5 s. The marker has to come first: once the
  process is gone, any status poll must be able to tell `cancelled` from `interrupted` (which tells
  people "starting again resumes"), and an answer only written after the kill loses that race. A job
  that had in fact finished — its `[exit 0]` is in the log — is `done`, whatever the marker says.
- **"Is the job alive" means "is anything alive in its process group", not "is the wrapper".** The
  first cancel watched only the wrapper: SIGTERM killed it at once, the check said "stopped", and
  members that ignore SIGTERM kept running (found because a test leaked them). The same weakness let
  a killed wrapper turn a still-rendering job into "interrupted", inviting a second render beside it.
  `is_our_job` now scans `/proc` for group members that name the target and the marker or
  `python -m audiobook`; `cancel` waits for the group to empty, not for one pid.
  A render stopped this way loses nothing (chunk cache); reading a book and cloning start over.
- **Audio is served by the assistant, from `output/` only** (`tools.yaml`: `files: [output, voices, voice]`; see
  `assistant/CLAUDE.md`). Nothing here knows about HTTP.
- **In the suite, finished work is handed over and let go (`keeping.py`, 2026-11-01; the suite's layer 1b, phase B).**
  `inventory` (read-only) lists what is worth keeping, labelled: each chapter MP3 (book, number, title, album, speed,
  and since 2026-11-01 voice, PDF, length and **the exact text it speaks**, which `render_book` writes beside it as
  `<mp3 stem>.json` before announcing the chapter finished), each M4B, each voice sample, audio left loose at the top
  of `output/` (four early tests on the real data), each book's title and author (`book`, from `book_names`: `plan.json`,
  else the file name; **needed because once a book's audio is kept the tool no longer lists it, and a chapter's own tag
  can be from an early wrong reading: Dreams and Visions showed as "Praise for" until the page read the book**), each
  voice (record, state, sample, source recording), each book's corrections, each finished job (its log with progress lines collapsed: read as bytes, since reading as text turns
  every `\r` into a line). The suite files them and calls `release`, which deletes only finished audio in `output/`
  whose SHA-256 is the filed copy's (and the chapter's `.json`). **Voices, corrections and jobs are never released**:
  a render needs the first two, `job_status` reads the third. A render still running hands over only the chapters its
  log says are finished. Alone, none of this runs and `output/` is as it always was. A chapter rendered before the
  text was written down has its MP3's own tags (title, album, track) and no text: today's plan may not be what it says.
  `book_overview` gives each chapter its `stem` (`names.chapter_stem`), which the page matches kept audio by, as
  `chapter_audio` matches files here.
- **Verified for real (2026-10-10):** a voice sample in `abigail` from the new venv, transcribed with
  Whisper, matched its text 100%; a chapter rendered to MP3 + M4B (chapter marker present) with live
  percent and time left; the same through chat (preview, approval card, render) and through the
  web panel in Chrome. The new venv resolved `transformers` 5.19.0 where the old one had 5.17.0;
  nothing in the plan rules, the golden tests or the speech changed.

## Conventions

- Python, run via `.venv/bin/python`. Keep dependencies of any extra engines optional so only
  Pocket TTS is required.
- Output and cache directories (e.g. `output/`, `.cache/`) and user reference voice clips are
  not committed.
- Test plan rules against saved Docling JSON fixtures (golden `preview.md` snapshot) so tests need
  no models, network or token. Docling and TTS get opt-in smoke tests.
- Test PDFs in `/home/philip/Documents/books/`: `2609.09153v1.pdf` (36-page arXiv paper: two
  columns, tables, formulas, citations, references, appendices) and `final-quest.pdf` (163-page
  copyrighted book — its fixture is in the git-ignored `tests/fixtures/local/`; never commit it).
