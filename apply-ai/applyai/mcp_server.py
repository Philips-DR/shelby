"""apply-ai's MCP front door: the same operations the CLI exposes, reachable by a model.

Both doors sit directly on operations.py; neither wraps the other. Every tool here only reads, so every
tool is annotated read-only and nothing on this door can be held at an approval gate -- there is nothing
for one to gate. Writing the draft is the assistant's own gated tool, and these are what a model runs
first, so that what a person is asked to approve has already been through them.

Source files are read from disk by this tool, never passed in as text: a model retyping a CV could let a
paraphrase stand in for the source, and then the check would be against the paraphrase. They are confined
to the folders in APPLY_AI_ROOTS (tools.yaml injects the folder where the assistant lends a stored document
for one call; the text itself is in its database, which no tool reaches).
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from applyai.operations import claims_report, requirements_report
from applyai.sources import SourceError, roots_from_environment

VERSION = "0.1.0"
READS_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)


def create_apply_ai_server(roots: list | None = None) -> MCPServer:
    folders = roots if roots is not None else roots_from_environment()
    server = MCPServer(name="apply-ai", version=VERSION)

    @server.tool(
        name="requirements",
        title="Set a job posting's requirements against the user's own material",
        description=(
            "USE THIS FIRST when asked to tailor a CV or write a cover letter for a job posting, before "
            "drafting anything. Reads the posting, lists every requirement and duty in it (none dropped), "
            "and for each says what the user's own material shows: the lines that support it, or that "
            "nothing does. Degrees, languages, named tools (Stata, R, Linux...) and years of experience "
            "are checked exactly; the rest is traced by shared words. Returns `ask_the_user`: the gaps the "
            "material does not settle. Ask the user about ALL of them in ONE message, before drafting, and "
            "record each answer with `remember`; never draft a claim for a gap the user has not answered. "
            "Pass the posting as text (one language: English), the user's documents as `sources` (paths "
            "from list_uploads: the CV, past letters), and any facts the user has already confirmed in "
            "`facts`. Reads only; changes nothing."
        ),
        annotations=READS_ONLY,
    )
    def _requirements(posting: str, sources: list[str], facts: list[str] | None = None) -> dict[str, Any]:
        try:
            return requirements_report(posting, sources, facts or [], folders)
        except SourceError as error:
            return {"error": str(error)}

    @server.tool(
        name="claims",
        title="Check a draft's claims against the user's own material",
        description=(
            "USE THIS ON EVERY DRAFT CV, COVER LETTER OR APPLICATION EMAIL BEFORE YOU SHOW IT TO THE USER, "
            "and so before write_draft and before draft_new: a letter only shown in chat is read and believed "
            "as much as a saved one, and an email claims things too. Checks that every figure, every word "
            "that overstates (daily, most, directly, led, deployed, production, open, fluent, expert, spent "
            "my career...), every tool, language, degree and name in the draft is traceable to the user's "
            "own material, and shows the nearest line for anything that is not. `clean: true` means nothing "
            "it looks for was unsupported, not that every sentence is true. Fix each finding (cut the claim, "
            "or ask the user and record their answer) and run it again; say in your reply which you kept "
            "and why. Run it AGAIN on the final text after ANY edit, including trimming a draft to fit a "
            "page (a trim rewords, and a reworded sentence can claim what the original did not) and a line "
            "the user asks you to add (their own CV once said something false). "
            "If the draft says code is private or confidential, check its addresses with web-ai first "
            "(github_visibility for a GitHub account or repository, check_link for another address) and pass "
            "every address a stranger can open as `public_links` ([] if none is): the user's own CV once "
            "said its repositories were private when most were public. "
            "Pass the draft as text, the user's documents as `sources` (paths), the facts the user has "
            "confirmed as `facts`, the posting as `posting` so a finding that merely echoes the "
            "posting is marked, and the text of the employer's own pages you read (read_page) as `employer`, "
            "so a sentence about them (\"your 2026 paper\") is not taken for a claim about the user. "
            "Reads only; changes nothing."
        ),
        annotations=READS_ONLY,
    )
    def _claims(draft: str, sources: list[str], facts: list[str] | None = None, posting: str = "",
                public_links: list[str] | None = None, employer: str = "") -> dict[str, Any]:
        try:
            return claims_report(draft, sources, facts or [], posting, folders, public_links=public_links,
                                 employer=employer)
        except (SourceError, ValueError) as error:
            return {"error": str(error)}

    return server


def main() -> None:
    create_apply_ai_server().run()


if __name__ == "__main__":
    main()
