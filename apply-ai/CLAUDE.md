# apply-ai — engineering rules

**Checks, not a writer.** apply-ai stands between a job posting, a person's own material and the document
that claims to connect them. It reads, compares and reports. It writes nothing, sends nothing, has no model
and no network, and every tool on its door is `readOnlyHint`, so the assistant's gate never has anything to
stop. The document a draft becomes is written by the assistant's own gated `write_draft` and built by
docu-ai; these are what runs *before* that, so that what a person is asked to approve has been through them.

It exists because of one real tailoring, done by hand on two job applications in a day. The model was not the
weak part there. What was missing was (a) a list of what the posting needs against what the material shows,
with the gaps asked about once, before drafting; (b) a check that a draft claims only what its sources support
— caught by hand were "daily", "open tool", "fed directly into harvest planning" and "most of my time", each
added by a model trying to sound good to a CV that said none of it; and (c) facts only the user had (the images
were from drones, a BSc and no MSc, no French). A prompt asking for honesty had not stopped (b). A check does
not read for meaning at all.

## What it does, and what it cannot

- **`requirements(posting, sources, facts)`** reads the posting into a numbered list (none dropped) and sets
  each item against the material. **Hard checks are exact**: a degree above the one shown, a named tool
  (Stata, R, Linux...) found nowhere, a language never mentioned, years of experience (worked out from the
  dated roles as of today, then left for a person to judge). **Everything else is traced by shared words**:
  which lines share the requirement's distinctive words, and which of its words appear nowhere in the material.
  It points; it does not judge. Statuses: `gap` (a hard check failed: certain), `check` (a person decides),
  `not_found` (no line shares its words: look before asking), `partly`, `trait` (see below), `supported`.
  `ask_the_user` is the list of questions for what the material does not settle, merged so the same one is
  asked once.
- **`claims(draft, sources, facts, posting, public_links, employer)`** checks every figure, every word that overstates,
  every tool, language, degree and name in a draft against the material, and a claim that code is private
  against the addresses found public, and shows the nearest source line for each finding. It is for a CV, a
  letter and the body of the email that goes with them. **It cannot tell that a sentence is true.** `clean: true` means nothing it looks for was
  unsupported, and the result says so. Two things it was shown to miss on a real draft, both left for the
  person approving: "dashboards" where the CV said one, and "specializations" for what is a single course.

## The rules, and the thing that went wrong behind each

- **Sources are read from disk by this tool, never passed in as text.** A model retyping a CV could let a
  paraphrase stand in for the source, and the check would then be against the paraphrase. Reads are confined
  to `APPLY_AI_ROOTS` (tools.yaml injects the folder where the assistant lends a stored document for the length
  of one call, with `.draft` in a draft's copy; since 2026-10-31 the text is in the assistant's database, which
  this tool never reaches), resolved before the test, so `..` and a
  symlink out are refused. The draft and the posting are text, because they are the model's own words and the
  user's pasted page.
- **A draft the assistant wrote is never the user's material.** Found live: on a second application the model
  passed its own earlier cover letter and CV as `sources`, and a claim it had made would then have been
  "supported" by itself. The assistant drops a `.draft` file beside every draft it writes
  (`assistant/documents.py`, `DRAFT_MARKER`) and `read_source` refuses a folder that holds one. A convention
  in a filename, not an import: neither tool knows the other exists. Drafts written before the marker existed
  have none; add `.draft` to such a folder by hand.
- **Presence anywhere is not support.** "open" is in a CV that says "open to remote", and "94" is in a line
  about palm trees. A watched word or a figure is supported only by a line that holds it *and* shares the
  sentence's other distinctive words (two, or one when the sentence is short). A figure may also lean on the
  line above it when its own line is short ("Accra, Ghana · CGPA 3.63" under its degree heading), and only
  then: a bullet must not take a neighbour's subject, or any figure would be supported by the next sentence.
- **A negated word is not support.** "(prototype, not deployed to production)" contains "deployed". A draft
  that says "deployed" is told the material says the opposite; a draft that says "not deployed" is honest and
  is left alone (the first run flagged it). A negator reaches four words back and never across a clause (a
  comma, colon, bracket, dash, "but", "however"...): "has not been deployed to production" denies production
  (four back; a real letter was flagged when the reach was three), "not cheap but deployed" claims deployment.
- **The watch-list compares exact forms, never stems.** "directly" must not be supported by "directed".
  Hyphenated entries ("open-source", "end-to-end") are found as phrases, since the tokenizer splits them.
  The list is in `vocabulary.py`, short and literal on purpose; it grows by a line when a real draft shows a
  new one (it gained "open" from the real tailoring, "extensive" from the second run, and "spent my career"
  and its kin, as phrases, from a letter on 2026-10-30 that said a lab's mission "is work I have spent my
  career doing" for a CV showing one three-year job).
- **A claim about the world is checked against the world, and the world is passed in.** A real CV and letter
  said "Repositories are private" when most were public. The CV itself said it, so the material supported it,
  and only opening the links could tell. apply-ai still has no network: web-ai finds what a stranger can open,
  and the model passes those addresses as `public_links`. A sentence that calls code private (private,
  confidential, proprietary, closed-source, not public; "not private" is the opposite) is then a `public
  link` finding when the address it names, or any repository on a code host, was found public. With nothing
  passed it is `unchecked`, which says how to check. `None` and `[]` differ: `[]` is "checked, none public".
  Three things that went wrong while building it, each now a test: every GitHub account page is public, so
  an account says nothing about its repositories (only a repository counts); "code-switched speech" is not
  code; and a list of addresses can arrive as one string, so each entry is split. The addresses shown are
  the ones the draft links to, else those under an account it links to, else any.
- **An email body is checked like a letter.** The description says so: the email that went with a real
  application on 2026-10-30 was the one text no check had read.
- **A limit that is dropped overstates as much as a word that is added.** Asked to fit a CV on two pages,
  the model cut "our cloud engineer provisions and operates the underlying clusters" and
  "(application/producer-consumer layer)" — the qualifiers that made the CV honest about Kafka and Redis.
  Nothing was added, so nothing was flagged. `dropped limit` finds a source sentence carrying a hedge
  (`HEDGES` in `vocabulary.py`) whose point the draft keeps — a draft sentence with 60% of its other words —
  and flags it only when *no* carrier's paragraph keeps the limit: a real letter said what was fine-tuned in
  one sentence and "configs our cloud engineer applies" in the next, and was flagged until the whole paragraph
  (`unit_blocks` numbers each sentence's paragraph or bullet) counted. It misses a heavily condensed rewrite
  that merges several bullets into one, and it still flags a limit kept in other words ("a colleague runs the
  clusters"); both are limits of a word-overlap check, not promises.
- **The employer's own words are data, and only excuse what is said to them.** A real letter said "Your ACL
  2026 paper argues..." and the year was flagged as missing from the user's material. `employer` takes the
  employer's pages as text (what web-ai's `read_page` returned). A finding whose token is in the posting or
  those pages, in a sentence addressed to them ("you", "your") that says nothing of the user ("I", "my",
  "we", "our"...), moves to `about_the_employer`: listed, not counted. Anything else stays a finding, marked
  `also_on_the_employers_pages`: "my 2026 paper" is a claim whatever their site says, and so is a sentence
  that mixes both ("your 2026 review covers the country I work in"), since telling which half a figure belongs
  to needs grammar. Their product names go to `names_that_come_from_the_employer`. This is text a model
  passes, not a file read from disk, so it can be an excerpt; at worst that moves a sentence about them.
- **Numbers inside a name are not figures.** "Research Assistant_1", "DR4D", "YOLOv8" and the digits of a URL
  or an email are not claims; spelled-out numbers two to twelve are (a claim of "three years" is a figure).
  Number words are not distinctive words, or "five" would support itself.
- **Names are listed apart from findings, and the posting's own names apart again.** "AfricaRice", "Dakar" and
  the role title come from the posting and are not a claim about the user unless the sentence says they
  did something there; they are one comma-separated line. A name in neither the material nor the posting
  ("worked with Wageningen University") is listed for review. `clean` ignores names: a first version that
  counted them could never be clean on a letter.
- **A hard check outranks lexical evidence, and a failed one shows only its own.** "Languages: Python, ..."
  is not evidence for a request for French, however many words they share. A requirement with a failed
  check lists the check's evidence and nothing else.
- **Traits are not questions.** "A proactive, self-starting attitude" cannot be found in a CV by searching,
  and putting every such line to the user as a question made the second real run's list longer without making
  it better. A requirement made mostly of words of character (`TRAIT_WORDS`) and with no hard check is a
  `trait`: drafted from real examples already in the material, never asserted bare, never given an invented
  example. A requirement that merely says "interest in private sector development" stays askable.
- **`not_found` is a candidate to look at, not a verdict.** The lexical trace misses "agentic AI" for "AI
  tools to automate...". The tool says so (`meaning_of_status`), and the descriptions tell the model to look
  through the material before asking.
- **A posting is read as English, once.** A bilingual posting repeats itself in French; the French half is
  dropped and counted, not read as a second, unmatched set of requirements. A posting that is French
  throughout is refused with a reason rather than misread. A heading with no blank line under it
  ("Position responsibilities" directly above its first sentence, which a PDF's layout often leaves) is
  recognised when it is one this reader knows by name; the first version lost every duty on a real posting.
  A bullet is split at semicolons when each side stands alone ("a Master's degree...; a PhD is a plus" is a
  requirement and a bonus), or the master's stopped being required.
- **Procedure lives in the tool's descriptions, not in the assistant's prompt.** `assistant/CLAUDE.md` says
  "no domain logic, ever". The descriptions of `requirements` and `claims` say when to run them, to ask about
  every gap in one message before drafting, to record each answer with `remember`, to pass what has been
  confirmed as `facts`, and to re-run `claims` after *any* edit, including a trim for length (a trim
  rewords, and the second real run re-checked after fixing findings but not after trimming). With no change to
  the prompt, a real run called `requirements` first, asked all its questions in one message, recorded the
  answers, ran `claims` on both drafts, and fixed what it found.

## Not built, on purpose

- **No model.** Whether a sentence is *true* needs judgment; the model and the person approving supply it, and
  the nearest line is shown so that is quick. A model inside the check would be a second thing to trust.
- **No claims check inside the approval prompt.** It would need the assistant to call another tool by name
  or `write_draft` to move here. Today the check is advisory, enforced by the descriptions and by the person
  reading the draft. If a model skips it, nothing stops that; the approval preview of `write_draft` still shows
  the draft whole.
- **Not a harness for every field.** CVs and cover letters. A second field (meeting minutes already has a
  quote rule) earns a generalisation when it needs the same piece, and not before.
- **PDF postings.** The assistant cannot read a PDF posting; it is pasted as text.

## Layout

    applyai/
      posting.py      read a posting into requirements (headings, bullets, clauses, bilingual, header fields)
      evidence.py     requirements against material: hard checks, lexical trace, questions
      claims.py       a draft against material: figures, watch-list, tools, languages, degrees, names, dropped limits
      vocabulary.py   tools, languages, degree levels, the watch-list, hedges, trait words
      sources.py      read the user's files (confined, never drafts) and confirmed facts
      text.py         tokens, stems, numbers, sentences, negation
      operations.py   the two reports, as data
      mcp_server.py   the MCP door; cli.py  ./apply, the human door
    tests/            no model, no network, nothing outside tmp_path

## Commands

    ./apply requirements POSTING.txt CV.md [--fact "..."]...
    ./apply claims DRAFT.md CV.md [--fact "..."]... [--posting POSTING.txt] [--employer PAGES.txt] [--public [URL ...]]
    cd apply-ai && ../.venv/bin/python -m pytest tests -q

## Verified for real (2026-10-15)

Against the two real postings (AfricaRice Research Assistant, World Bank Data Scientist) and the real CV: every
gap found by hand came out — the master's degree, Stata and R, French, Linux, impact evaluations, and 3–5
years against a computed 2 years 11 months. Against the real finished AfricaRice CV the claims check found
exactly one thing, "Linux", added from inference and not yet confirmed by the user. Through the real chat, on
Bedrock, in an isolated copy with its own memory and uploads: the model chose `requirements` first, asked in
one message, recorded the answers, and fixed "daily", "most directly" and "fluent" in its own drafts when the
check flagged them. It then made a second application with what it already knew.

## Verified for real (2026-10-30): career claims, private code, the email body

Tests: 103 (16 new); thirteen deliberate breaks of the new code, each caught (the first run missed one, two
spellings of one address, which then got its test). On seven real documents, old code against new, with the
nine repositories web-ai found public: new findings only where they belong (the three that say "private", in
the 2026-10-24 CV and letter and the 2026-10-15 CV, and "spent my career" in the 2026-10-30 letter), and the
other four (an email body, a final CV, a letter) exactly as before. Through the real chat, after the backend
was rebuilt: asked for an application email, the model ran `claims` on the body before `draft_new` unasked,
fixed "directly" and re-checked. **Not followed:** asked to add "my repositories are private ... as my CV
says", it went straight to `draft_new` without re-checking: a line the user dictates reads to it as
confirmed. Asked to check, it called `github_visibility` first, passed `public_links`, got the `public link`
finding, and told the user the line would be false. Both drafts were declined at the gate.

Later the same day: the employer's pages, a four-word negation that stops at a clause, a limit kept anywhere in
its paragraph. Tests: 111 (8 more); 24 deliberate breaks across both batches, each caught (two were missed at
first because no example put the negator within reach but across a clause; those examples were added). On the
seven real documents with the employer's real homepage and research page: the 2026-10-24 letter lost its
"production" false alarm and today's letter its dropped-limit one, and nothing else changed. The 2026-10-24
letter's "Your ACL 2026 paper ... covers the country I work in" stays a finding, now marked as the employer's:
the sentence also speaks of the user. Through the real chat, after a rebuild: asked to check a letter it had
written from the employer's site, the model passed `employer` (an excerpt of 634 characters holding "ACL 2026"
and "Mansa"), and kept "2026" and "74+" with that marker as its reason. **Not followed:** asked only to *show*
a letter, not save or send it, it did not run the check at all and said "nothing invented"; the description
ties the check to `write_draft` and `draft_new`.
