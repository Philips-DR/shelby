# web-ai

Reads a web page, checks that a link answers, and asks GitHub what a stranger can see. **Not a browser and not a
model** — it fetches, and returns what the page says, word for word. It writes nothing and logs in to nothing.

```bash
./web read https://example.com/jobs/analyst           # the page's text
./web read https://example.com/careers --links       # and the links on it
./web check https://github.com/you/your-repo         # does it answer? (HEAD only, nothing downloaded)
./web github https://github.com/you                  # which repositories can a stranger see?
./web github you/your-repo                           # is this one public?
```

In Shelby, the assistant uses these when you give it an address: to read a job posting or a company's careers
page, to find the vacancies on it, and to check what a CV says about public repositories and links before it is
made. What it reads from a page it passes to `apply-ai` as the posting.

What it will not do:

- **Read anything that is not on the public internet.** Every address is looked up first, and one that points
  inside a network (this computer, a router, a database, a cloud server's own credentials) is refused, however it
  is written and wherever a redirect sends it.
- **Send anything but the address.** GET and HEAD only; no cookies, no login, no body.
- **Read a PDF or run a page's scripts.** A PDF posting is pasted as text. A page that builds itself in the
  browser may come back almost empty, and says so.
- **Be trusted.** What a page says is whatever its author wrote. Text a reader cannot see is dropped, and the
  assistant is told that anything in a page that reads like an instruction to it is not one.

Its rules, and what went wrong behind each, are in [`CLAUDE.md`](CLAUDE.md).
