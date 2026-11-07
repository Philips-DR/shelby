# apply-ai

Checks for a job application: a posting against what you have actually done, and a draft against what you
have actually written. **Not a writer and not a model** — it reads and reports, and changes nothing.

```bash
./apply requirements POSTING.txt CV.md                # every requirement, and what your CV shows for it
./apply requirements POSTING.txt CV.md --fact "..."   # plus something you have confirmed since
./apply claims DRAFT.md CV.md --posting POSTING.txt   # every figure and overstating word, traced to a line
```

In Shelby, the assistant runs these for you when you ask it to tailor a CV or write a cover letter, before
it drafts anything:

1. **`requirements`** lists everything the posting asks for and what your material shows for each. Degrees,
   languages, named tools and years of experience are checked exactly (the years are worked out from your
   dated roles); the rest is traced by shared words. What your material does not settle becomes questions,
   asked in one message, and your answers are remembered so you are not asked twice.
2. **`claims`** checks the draft. Every number, every word that claims more than a plain statement of work
   (*daily, most, directly, led, deployed, fluent, extensive…*), every tool, language, degree and name must
   trace to a line you already wrote, or be shown to you with the nearest line. It also notices when a draft
   keeps a point but drops the limit your CV put on it ("our cloud engineer operates the clusters").

It cannot tell that a sentence is true. A clean result means nothing it looks for was unsupported; the
sentences are still yours to read. Your own earlier drafts are never counted as your material.

Reads files only from Shelby's uploads folder (`APPLY_AI_ROOTS`), and only ones you uploaded. Its rules and
the failures behind each are in [`CLAUDE.md`](CLAUDE.md).
