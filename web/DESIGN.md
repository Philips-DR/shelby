# The web app's design system

How the interface is built, so a new panel or chart looks like it belongs. Read this before changing
how anything looks. The look lives in `src/styles/`; the pieces are in `src/ui/` and `src/charts/`.

## Identity

A calm instrument panel. Cool slate neutrals with a hint of teal, **one brand accent** (teal), and a
validated chart palette used only for data and for *which tool* something belongs to. Boldness is kept
to the accent and the data; everything else is quiet. Type: **Bricolage Grotesque** for page titles and
section headings (`--font-display`), **Instrument Sans** for everything else (`--font-ui`, including
big numbers), **JetBrains Mono** for tool names, timestamps and code (`--font-mono`). All three are
bundled (`@fontsource-variable/*`): the app makes no request to any font service.

## Rules that are not negotiable

1. **Never write a literal colour, size or duration.** Use a token from `styles/tokens.css`
   (`var(--ink)`, `var(--brand)`, `var(--r-card)`, `var(--dur-2)`). Both themes (light, dark) are
   defined there, so a component that uses tokens is correct in both; one that uses `#fff` is not.
2. **Never name a theme in a component.** No `[data-theme]`, no `prefers-color-scheme` outside tokens.css.
3. **Colour follows the entity.** A tool has one colour everywhere (`charts/palette.ts`: `toolColor('meet-ai')`
   → `var(--s1)`). Status colours (`--ok-fill`, `--warn-fill`, `--bad-fill`) mean good/warning/bad and
   nothing else, and always come with an icon and a word. Never use a series colour for status or the reverse.
4. **Text never wears a series colour.** Marks carry colour; text uses `--ink`, `--ink-2`, `--ink-3`.
5. **Mobile first.** Every panel works at 390px wide with no horizontal scroll (tables become stacked rows,
   master/detail becomes list-then-detail), touch targets are at least 40px, inputs are 16px on a phone.
6. **Motion is tokenised and optional.** Use `--dur-*` and `--ease`, or the keyframes in `motion.css`.
   `prefers-reduced-motion` zeroes them all; never add a transition that carries information only through motion.
7. **Keep every behaviour.** A restyle changes how it looks and is operated, never what it does: the same
   tool calls, the same approvals, the same error messages, the same keyboard access.
8. **Nothing untrusted becomes markup.** Email bodies, transcripts, tool output: React text only, never
   `dangerouslySetInnerHTML`.
9. **Real data only in charts.** A chart plots what the tools returned. An empty period is an empty chart
   with a sentence saying so, never invented points.

## Layout and breakpoints (`styles/shell.css`)

`>=1024` sidebar; `640-1023` icon rail plus top bar; `<640` top bar plus bottom tab bar (four tabs and
"More"). The document scrolls. A page is `<PageHead/>` (rendered by `App.tsx`) followed by cards. Page
content max width is 1200px; the gutter is `--gutter` (16/24/32px). Use `.grid-2`, `.grid-3`, `.grid-split`
(wide + narrow) for card layouts; they collapse on their own. **Pick a column count the items fill**: an
odd card left alone on a row is a bug.

## Back (`ui/useRoute.ts`, `ui/useLayer.ts`)

A page is the URL hash, so changing page is a history entry and Back goes to the page before. Anything that opens
*inside* a page (a book on Audiobooks, a message in Mail, a meeting on a phone, the More sheet, the search box) was
only React state, so Back skipped it: from an open book it went to Chat, if that was where you had come from, and
the More sheet stayed open over the page it landed on (reproduced in Chrome as a phone, 2026-10-31). Such a thing is
now a **layer**: `useLayer(key, value, set)` keeps its value in `history.state`, so opening pushes an entry, Back
closes it, the on-screen "All books" button goes Back too (the same history either way), and leaving for another
page and coming Back finds it open again. Rules for the next one:

- **Use it where a thing takes the page's place or sits over it.** Not for an accordion or text that opens inline
  (a chapter's text, "Upload audio"): those are part of the page, and Back leaving the page is right.
- **Only where it is a layer.** Meetings opens its newest meeting by itself when the list and the meeting sit side
  by side, so there it is not a layer (a history entry for it would make Back re-open it for ever): the call is
  gated on `!wide`.
- **A sheet or search box is `modal`**: choosing a page from it replaces its entry (`go()`), so Back from that
  page goes to the page you were on, not to the sheet.
- **Not a layer yet:** the delete confirmation (`ConfirmDelete`) and a chapter's text; Back from either leaves the page.

## Building blocks

| Need | Use |
|---|---|
| A surface | `<div className="card">`; `className="card lift"` when the whole card is clickable |
| Card heading with icon, title, sub, actions | `<CardHead icon={IconX} tool="meet-ai" title sub>actions</CardHead>` (`ui/CardHead`) |
| Nothing here yet | `<Empty icon title action>text</Empty>` (`ui/Empty`): say what will appear and how to add the first one |
| Rows in a card | `<ul className="list"><li>…</li></ul>`; `.list-main` for a row's title line |
| Chips, status | `.badge` (+ `.ok`, `.warn`, `.bad`), `.chip` (brand tint) |
| Segmented control | `<div className="seg" role="radiogroup"><button role="radio" aria-checked>` |
| Progress | `.bar` > `<div style={{width}}/>`, or `<Ring value label/>` (`charts/Ring`) |
| Big numbers | `.stat` tiles: see `pages/Overview.tsx` (`Stat`) |
| Drop files on a card | `<DropZone accepts onFiles label>` (`ui/DropZone`) plus `PickFiles` (`components/Upload`) |
| Ask before deleting | `<ConfirmDelete title facts keeps verb ready busy error onConfirm onCancel>` (`ui/ConfirmDelete`): says what goes and what is not touched, Cancel has the focus, the delete button waits until `ready`. It is drawn into `<body>` through a portal: inside a card whose entrance animates `transform`, a `position: fixed` dialog is fixed to the card, and its button presses the row underneath (found live) |
| Play audio | `open({key, title, blob})` from `usePlayerActions()` (`player/engine`); the page shows `<AudioPlayer onClose>` (`ui/AudioPlayer`) for the current file. Never an `<audio>` of your own: the one player lives above the pages, so playback survives moving between them, and `ui/MiniPlayer` docks it when the full one is not in view |
| Something that opens over a page (a book, a message, a sheet) | `useLayer(key, value, set)` (`ui/useLayer`), so the phone's Back closes it: see "Back" below |
| Icons | import from `ui/icons.ts` only (lucide). 16px in buttons, 17–20px in tiles. `aria-hidden` on decoration |
| Tables | `<div className="table-wrap stack-rows"><table>…`, with `data-label="Column"` on each `<td>`: on a phone each row becomes a stacked block |
| Forms | plain `input`, `select`, `textarea`, `button` are already styled; `.row` lays controls out, `.stack` stacks them |
| Page-level layout | `.panel` (vertical stack of cards, gap 16) |
| Muted / small / hint text | `.muted`, `.small`, `.hint` |
| Staggered entrance | add `className="stagger"` to a parent and `style={{'--i': index}}` to each child |

Buttons: default is quiet; `.primary` is the brand fill (one per view, the main thing to do);
`.danger` for destructive confirmations; `.ghost` for borderless; `.icon` for square icon-only (give it
an `aria-label`).

## Anything that must outlive a page (`src/player/`)

Pages mount one at a time (`<main key={section}>`), so whatever a page owns dies when you leave it. The
audio player learned this the hard way: its `<audio>` lived in the Audiobooks panel and stopped the
moment you opened another tab. It now lives in `PlayerProvider` (`main.tsx`, above `App`); the panel's
`AudioPlayer` and the docked `MiniPlayer` are only views of it. A view re-renders only for what it shows
(three contexts: slow state, the clock, actions), and the bar moves by writing `--progress` into the views'
DOM nodes each frame. `--mini-h` (set while a file is loaded) keeps room at the foot of every page and
shortens Chat, so the dock never covers the composer. Anything else that has to keep going across pages
(an upload, a live stream) belongs in a provider up there too, never inside the page that started it.

## Charts (`src/charts/`)

Plain SVG, no chart library, built to the dataviz skill's mark specs. Components:
`StackedColumns` (magnitude per day by tool), `HBars` (named things, thin bars, optional toggling),
`ShareBar` (parts of a whole, with icon + word legend), `Sparkline`, `Ring`, and `ChartCard`/`DataTable`
(a chart's frame with a Table view toggle, which every chart gets). Scales and formats are in
`scale.ts` (`niceMax`, `compact`, `duration`). Helpers for the audit log are in `pages/overviewData.ts`
(tested: `npm test`).

When adding a chart: choose the form by the data's job (stat tile for one number, bars for comparing
magnitude, stacked bars for parts of a whole, line only for time series); one series → one colour; thin
marks (bars ≤ 24px, 4px rounded at the data end, 2px surface gap between segments); hairline solid grid;
value labels on the bar tips or in a tooltip; a legend whenever there are two or more series; a table
view; a sentence for the empty case. No dual axes, no donuts for comparing close values, never a number
on every point. Categorical colour slots are fixed and validated (`charts/palette.ts`, `tokens.css`
`--s1..--s8`); a ninth category folds into "Other", never a new hue.

## Tool identity colours

meet-ai `--s1` blue · docu-ai `--s2` orange · mail-ai `--s3` aqua · assistant `--s4` yellow ·
audiobook `--s5` magenta · apply-ai (Applications) `--s6` green · web-ai (Web) `--s7` purple. The last two have no page of
their own, so they show on Settings, in approvals and, once used, on the Overview. Slot 6 is a green close to the UI's "ok": a tool
that wears it is always named and iconed beside it, never told apart by colour alone. Slot 8 is the UI's red and stays unused.
Use `toolColor(name)`; for a tinted tile use `style={{'--tile': toolColor(tool)}}`
on a `.navtile`.

## Theme

`ui/useTheme.ts` keeps light / dark / system in this browser only and sets `data-theme` on `<html>`;
`index.html` applies it before first paint so there is no flash.

## Verifying a change

`npx tsc --noEmit`, `npm test`, and look at it: with the dev server running
(`npm run dev`, see `web/README.md`), screenshot at 390×844 (phone), 820×1180 (tablet), **about 1066
(a laptop)** and 1440×900 in both themes, and confirm `document.documentElement.scrollWidth <=
window.innerWidth` at 390. The laptop width is the narrowest card of all: the sidebar is shown and a
`.grid-split` still has two columns, so its wide card is narrower than on a tablet. A row laid out by the
window's width (`@media`) squeezed the Audiobooks chapter titles to a letter a line there while 390, 820 and
1440 all looked right (2026-10-30): **lay out a row inside a card by the card's width** (`container-type:
inline-size` on the list, `@container` for the row), and keep `@media` for the page.
