from applyai.claims import check_claims
from applyai.sources import CONFIRMED, Line, units

CV = """\
# Philip Baah Afriyie

Accra, Ghana — open to remote

## Experience

### Machine Learning Engineer — Ayadata GH

- **Computer vision for agriculture.** Engineered object detection models on drone imagery for automated crop counting, reaching 91.8% precision on banana trees with MMDetection and 94% precision on palm trees with Ultralytics YOLOv8, to improve harvest planning.
- **Real-time voice AI survey platform (prototype, not deployed to production).** Designed an unattended IVR system that conducts spoken telephone surveys in a local Ghanaian language.
- Built agentic RAG systems on LangChain and LangGraph, with Kafka producers and consumers for high-throughput event processing; our cloud engineer provisions and operates the underlying clusters.

## Skills

- **Languages:** Python, TypeScript, SQL, Bash
- **Tools:** Git and GitHub, Docker, QGIS
- **Infrastructure:** Kafka, Redis (application/producer-consumer layer), nginx, Ansible (IaC authoring)

## Education

### BSc. Information Technology — BlueCrest University College

Accra, Ghana · CGPA 3.63
"""


def material(extra: list[str] | None = None) -> list[Line]:
    return [Line("cv.md", u) for u in units(CV)] + [Line(CONFIRMED, f) for f in (extra or [])]


def run(draft: str, extra: list[str] | None = None, posting: str = ""):
    return check_claims(draft, material(extra), posting)


def kinds(report):
    return {(f.kind, f.token) for f in report.findings}


# The four things found by hand in a real tailoring: each added by a model trying to sound good, to a CV
# whose source said none of it. These are the check's reason to exist.
def test_it_catches_the_four_overstatements_that_were_found_by_hand():
    draft = (
        "- Ran daily object detection on drone imagery for automated crop counting.\n"
        "- Built an open tool for automated crop counting on drone imagery.\n"
        "- Counted crops on drone imagery whose output was fed directly into harvest planning.\n"
        "- Spent most of my time on object detection on drone imagery.\n"
    )
    assert {("claim word", "daily"), ("claim word", "open"), ("claim word", "directly"),
            ("claim word", "most")} <= kinds(run(draft))


def test_open_is_in_the_material_but_not_in_a_line_about_this():
    report = run("- Built an open tool for crop counting.")
    finding = next(f for f in report.findings if f.token == "open")
    assert "appears in your material, but not in a line about this" in finding.why
    assert "open to remote" in finding.nearest["line"] or finding.nearest["line"]


def test_a_figure_that_is_not_in_the_material_is_found_and_one_that_is_is_traced():
    report = run("- Engineered object detection models on drone imagery, reaching 98% precision on banana trees.")
    assert ("figure", "98") in kinds(report)
    ok = run("- Engineered object detection models on drone imagery, reaching 91.8% precision on banana trees.")
    assert ok.findings == []
    assert ok.traced and ok.traced[0]["figure"] == "91.8" and "banana trees" in ok.traced[0]["line"]


def test_a_figure_from_another_claim_is_not_support_for_this_one():
    # 94% is in the CV, for PALM trees; a draft that moves it to a different thing is not supported.
    report = run("- Reached 94% uptime for the voice survey platform.")
    assert ("figure", "94") in kinds(report)
    assert "not in a line about this" in next(f for f in report.findings if f.token == "94").why


def test_spelled_out_figures_are_figures():
    assert ("figure", "5") in kinds(run("- Led a team of five engineers building the survey platform."))


def test_a_draft_that_says_not_deployed_is_not_claiming_deployment():
    # The check flagged "(prototype, not deployed to production)" in its own first run.
    report = run("- Agentic document extraction (prototype, not deployed to production).")
    assert not any(f.token in ("deployed", "production") for f in report.findings)


def test_a_draft_that_claims_what_the_material_denies_is_told_so_with_the_line():
    report = run("- Deployed the voice survey platform to users.")
    finding = next(f for f in report.findings if f.token == "deployed")
    assert "the opposite" in finding.why and "not deployed to production" in finding.why


def test_hyphenated_watch_words_are_found():
    assert ("claim word", "open-source") in kinds(run("- Maintained an open-source library for crop counting."))
    assert ("claim word", "end-to-end") in kinds(run("- Owned the end-to-end pipeline."))


def test_a_tool_the_material_never_names_is_a_finding_and_a_tool_it_names_is_not():
    report = run("- Analysed survey data in Stata and Python.")
    assert ("tool", "Stata") in kinds(report) and ("tool", "Python") not in kinds(report)


def test_linux_added_from_inference_is_caught_which_is_what_happened():
    posting = "Experience with Linux/Unix environments and command-line tools."
    report = run("- Comfortable on the Linux command line (Bash, Docker).", posting=posting)
    finding = next(f for f in report.findings if f.token == "Linux")
    assert finding.in_posting  # the dangerous kind: a draft echoing the posting
    assert finding.as_dict()["also_in_the_posting"] is True
    # Once the user confirms it, it is material.
    assert run("- Comfortable on the Linux command line (Bash, Docker).", extra=["I use Linux daily as my main machine"]).findings == [] or \
        ("tool", "Linux") not in kinds(run("- Comfortable on the Linux command line.", extra=["I use Linux as my main machine"]))


def test_a_degree_above_the_one_shown_and_a_language_never_mentioned_are_findings():
    report = run("- Hold an MSc in Data Science and speak French.")
    assert ("credential", "a master's degree") in kinds(report)
    assert ("language", "French") in kinds(report)
    assert ("credential", "a bachelor's degree") not in kinds(run("- BSc in Information Technology."))


def test_english_is_never_a_finding():
    assert ("language", "English") not in kinds(run("- Fluent in English."))


def test_a_clean_draft_is_clean_and_names_nothing_to_review():
    draft = ("- Engineered object detection models on drone imagery for automated crop counting, reaching 91.8% "
             "precision on banana trees with MMDetection.\n- Built agentic RAG systems on LangChain and LangGraph.")
    report = run(draft)
    assert report.findings == [] and report.names == []


def test_a_name_in_neither_the_material_nor_the_posting_is_listed_apart_from_findings():
    report = run("- Collaborated with Wageningen University on crop counting for drone imagery.")
    assert report.findings == []                      # a name is not a figure or an overstatement
    assert "Wageningen" in {f.token for f in report.names}


def test_a_name_from_the_posting_is_marked_as_coming_from_it():
    report = run("- Interested in the work of AfricaRice in Dakar.", posting="AfricaRice, based in Dakar")
    assert {f.token: f.in_posting for f in report.names} == {"AfricaRice": True, "Dakar": True}


def test_a_dated_line_and_digits_inside_names_are_not_figures():
    report = run("15 October 2026\n\nApplication: Research Assistant_1 (Ref: GSS/DR4D)\n\n- Used YOLOv8 for crop counting.")
    assert not any(f.kind == "figure" for f in report.findings)


def test_sentences_with_the_least_basis_in_the_material_are_listed():
    report = run("- Quarterly regulatory compliance reporting for pension fund clients across Europe.")
    assert report.weak and int(report.weak[0]["found_in_your_material"].rstrip("%")) < 40


def test_findings_come_overstatements_first():
    report = run("- Collaborated with Wageningen University using Stata, reaching 99% precision, mostly daily.")
    order = [f.kind for f in report.findings]
    assert order == sorted(order, key=("figure", "claim word", "credential", "tool", "language", "name").index)


# Found on the first real run: asked to fit a CV on two pages, the model cut "our cloud engineer provisions and
# operates the underlying clusters" and "(application/producer-consumer layer)" -- the qualifiers that made the CV
# honest about Kafka and Redis. Nothing was added, so nothing added was flagged.
def test_a_limit_the_material_puts_on_a_claim_is_flagged_when_the_draft_keeps_the_claim_without_it():
    draft = ("- Built agentic RAG systems on LangChain and LangGraph, with Kafka producers and consumers "
             "for high-throughput event processing.")
    finding = next(f for f in run(draft).findings if f.kind == "dropped limit")
    assert "cloud engineer" in finding.token
    assert "keeps the point without" in finding.why and "provisions and operates" in finding.why


def test_a_parenthetical_limit_dropped_from_a_skills_line_is_flagged():
    report = run("- **Infrastructure:** Kafka, Redis, nginx, Ansible (IaC authoring)")
    assert [f.token for f in report.findings if f.kind == "dropped limit"] == ["application/producer-consumer layer"]


def test_a_limit_that_is_kept_is_not_flagged():
    draft = ("- Built agentic RAG systems on LangChain and LangGraph, with Kafka producers and consumers for "
             "high-throughput event processing; our cloud engineer provisions the underlying clusters.\n"
             "- **Infrastructure:** Kafka, Redis (application/producer-consumer layer), nginx, Ansible (IaC authoring)")
    assert not [f for f in run(draft).findings if f.kind == "dropped limit"]


def test_a_sentence_that_only_shares_a_label_s_words_is_not_the_point_carried():
    # "(prototype, not deployed to production)" sits on the label; the sibling sentence that follows it shares
    # the label's words but is a different sentence. The first version flagged it.
    draft = ("- **Real-time voice AI survey platform (prototype, not deployed to production).** Designed an "
             "unattended IVR system.\n- Built real-time voice survey front ends over a shared engine.")
    assert not [f for f in run(draft).findings if f.kind == "dropped limit"]


def test_a_sentence_that_is_not_in_the_material_at_all_has_no_limit_to_drop():
    assert not [f for f in run("- Quarterly reporting for pension fund clients across Europe.").findings
                if f.kind == "dropped limit"]


def test_amplifiers_that_the_material_does_not_use_are_flagged():
    # "required extensive data cleaning" passed the first version of the check and a human reader caught it.
    report = run("- Work that required extensive data cleaning and numerous pipelines.")
    assert {("claim word", "extensive"), ("claim word", "numerous")} <= kinds(report)


# A real letter (2026-10-30): a lab's mission "is work I have spent my career doing", for a CV showing one
# three-year job. No figure and no watched word, so it passed.
def test_a_claim_that_spans_a_whole_career_is_flagged():
    finding = next(f for f in run("- AI for Africans, by Africans, is work I have spent my career doing.").findings
                   if f.token == "spent my career")
    assert finding.kind == "claim word" and "(how long)" in finding.why
    assert ("claim word", "lifelong") in kinds(run("- A lifelong interest in object detection on drone imagery."))


def test_a_whole_career_claim_the_material_makes_is_supported():
    draft = "- I have spent my career building object detection models on drone imagery."
    assert ("claim word", "spent my career") in kinds(run(draft))
    fact = "Spent my career building object detection models on drone imagery"
    assert ("claim word", "spent my career") not in kinds(run(draft, extra=[fact]))


# A real CV and letter (2026-10-24) said "Repositories are private" when most were public. The CV itself said
# it, so the material supported it; only opening the links could tell, and this tool has no network.
PRIVATE = "- Repositories are private; I'm glad to grant access on request."


def private_findings(draft: str, public: list[str] | None, extra: list[str] | None = None):
    return [f for f in check_claims(draft, material(extra), "", public).findings if f.kind in ("public link", "unchecked")]


def test_a_private_claim_about_code_is_flagged_when_the_code_was_found_public():
    found = private_findings(PRIVATE, ["https://github.com/Philips-DR/docu-ai", "https://www.africanlanguageslab.com"],
                             extra=["Repositories are private; I'm glad to grant access on request."])
    assert [(f.kind, f.token) for f in found] == [("public link", "private")]
    assert "github.com/Philips-DR/docu-ai" in found[0].why
    assert "africanlanguageslab" not in found[0].why     # a public web page is not public code


def test_a_private_claim_about_code_that_nothing_checked_says_how_to_check_it():
    found = private_findings(PRIVATE, None)
    assert [(f.kind, f.token) for f in found] == [("unchecked", "private")]
    assert "github_visibility" in found[0].why and "public_links" in found[0].why


def test_checked_with_none_public_is_not_a_finding():
    assert private_findings(PRIVATE, []) == []


def test_saying_code_is_not_private_is_not_a_private_claim():
    assert private_findings("- The code is not private: github.com/x/y.", None) == []
    assert private_findings("- The code is not private: github.com/x/y.", ["https://github.com/x/y"]) == []


def test_a_private_claim_that_is_not_about_code_is_left_alone():
    # "code-switched" is not code, and client data is not a repository.
    for draft in ("- Fine-tuned Whisper on private, code-switched farmer speech.",
                  "- Kept client survey data confidential."):
        assert private_findings(draft, ["https://github.com/Philips-DR/shelby"]) == [], draft
        assert private_findings(draft, None) == [], draft


def test_an_address_in_the_sentence_found_public_is_named_whatever_its_host():
    found = private_findings("- My portfolio, philip-portfolio-five.vercel.app, is private.",
                             ["https://philip-portfolio-five.vercel.app/", "https://github.com/Philips-DR/shelby"])
    assert len(found) == 1 and "vercel.app" in found[0].why and "github.com" not in found[0].why


def test_one_address_written_two_ways_is_one_address():
    # A model passes what web-ai returned; a draft writes the address its own way.
    found = private_findings("- My portfolio at https://www.Philip-Portfolio-Five.vercel.app/ is private.",
                             ["philip-portfolio-five.vercel.app"])
    assert len(found) == 1 and found[0].kind == "public link"
    assert len(private_findings("- My code at github.com/a/b is private.", ["https://www.github.com/A/B.git"])) == 1


def test_the_public_addresses_shown_are_the_ones_the_draft_links_to():
    draft = ("- Voice AI survey platform: [github.com/Philips-DR/voice-ai-survey-platform]"
             "(https://github.com/Philips-DR/voice-ai-survey-platform)\n" + PRIVATE)
    found = private_findings(draft, ["https://github.com/Philips-DR/shelby",
                                     "https://github.com/Philips-DR/voice-ai-survey-platform"])
    assert len(found) == 1 and "voice-ai-survey-platform" in found[0].why and "/shelby" not in found[0].why


def test_a_linked_repository_outranks_ones_only_under_a_linked_account():
    # The real CV links the account in its header and two repositories in its projects.
    names = ("shelby", "audiobook", "assistant", "meet-ai", "mail-ai", "voice-ai-survey-platform")
    public = [f"https://github.com/Philips-DR/{n}" for n in names]
    header = "GitHub: [github.com/Philips-DR](https://github.com/Philips-DR)\n"
    why = private_findings(header + "- Survey platform: github.com/Philips-DR/voice-ai-survey-platform\n" + PRIVATE,
                           public)[0].why
    assert "voice-ai-survey-platform" in why and "/shelby" not in why
    # With only the account linked, its repositories are what is shown.
    assert "/shelby" in private_findings(header + PRIVATE, public)[0].why


def test_a_list_that_arrives_as_one_string_is_still_a_list():
    found = private_findings("- My code at github.com/a/b is private.", ["https://github.com/x/y https://github.com/a/b"])
    assert len(found) == 1 and "https://github.com/a/b" in found[0].why and "x/y https" not in found[0].why


def test_a_public_account_page_says_nothing_about_its_repositories():
    # Every account page is public. Only a repository found public contradicts "the code is private".
    assert private_findings("- The survey code at github.com/Philips-DR/survey is private.",
                            ["https://github.com/Philips-DR"]) == []
    assert private_findings(PRIVATE, ["https://github.com/Philips-DR"]) == []
    # Naming the account itself as private is contradicted by it, and naming the account covers its repositories.
    assert len(private_findings("- My GitHub, github.com/Philips-DR, is private.", ["https://github.com/Philips-DR"])) == 1
    assert len(private_findings("- My code at github.com/Philips-DR is private.",
                                ["https://github.com/Philips-DR/shelby"])) == 1


def test_a_draft_that_says_has_not_been_deployed_is_not_claiming_production():
    # A real letter (2026-10-24): "the voice agent is a prototype that has not been deployed to production".
    report = run("To be clear about scope: the voice survey platform is a prototype that has not been deployed to "
                 "production, and our cloud engineer runs the clusters.")
    assert not any(f.token in ("deployed", "production") for f in report.findings)


# A real letter (2026-10-30) said what was fine-tuned in one sentence and "the configs our cloud engineer applies
# to provision the cluster" in the next, and was flagged for dropping the limit.
LIMIT_NEXT_SENTENCE = ("I built agentic RAG systems on LangChain and LangGraph, with Kafka producers and consumers for "
                       "high-throughput event processing. Our cloud engineer provisions and operates the underlying "
                       "clusters, and I write the code that runs on them.")


def test_a_limit_in_another_sentence_of_the_same_paragraph_is_kept():
    assert not [f for f in run(LIMIT_NEXT_SENTENCE).findings if f.kind == "dropped limit"]


def test_a_limit_in_another_paragraph_is_still_dropped():
    apart = LIMIT_NEXT_SENTENCE.replace(" Our cloud engineer", "\n\nOur cloud engineer")
    assert [f.token for f in run(apart).findings if f.kind == "dropped limit"] == [
        "our cloud engineer provisions and operates the underlying clusters"]


# A real letter (2026-10-24) said "Your ACL 2026 paper argues ...", and its year was flagged as missing from the
# user's material: only the posting had been given as context.
EMPLOYER = "Research. Our ACL 2026 paper shows that data, not model size, is the bottleneck for African languages."


def employer_run(draft: str):
    return check_claims(draft, material(), "", None, EMPLOYER)


def test_a_sentence_about_the_employer_in_their_own_words_is_listed_apart():
    draft = "- Your ACL 2026 paper argues that data, not model size, is the bottleneck for African languages."
    assert ("figure", "2026") in kinds(run(draft))                 # without their pages: a finding
    report = employer_run(draft)
    assert report.findings == []
    assert [(f.kind, f.token) for f in report.about_them] == [("figure", "2026")]
    assert report.about_them[0].as_dict()["also_on_the_employers_pages"] is True


def test_the_employer_s_words_do_not_excuse_a_claim_about_the_user():
    # First person, or no one addressed: a claim about the user, whatever the employer's pages say.
    for draft in ("- My ACL 2026 paper argues that data is the bottleneck.",
                  "- Published an ACL 2026 paper on African languages.",
                  "- Your ACL 2026 paper builds on work I published."):
        report = employer_run(draft)
        assert ("figure", "2026") in kinds(report) and report.about_them == [], draft
        assert next(f for f in report.findings if f.token == "2026").in_employer, draft


def test_a_figure_in_a_short_lead_line_leans_on_the_heading_above_it_and_a_bullet_does_not():
    ok = run("- BSc in Information Technology from BlueCrest University College, CGPA 3.63.")
    assert not any(f.kind == "figure" for f in ok.findings)
    # 94% belongs to palm trees in a long bullet; the bullet after it must not lend a subject.
    assert ("figure", "94") in kinds(run("- Reached 94% uptime for the voice survey platform."))
