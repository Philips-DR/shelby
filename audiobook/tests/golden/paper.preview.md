# Procedural Graphs: Self-Evolving Execution Structures for LLM Agents

Source: `2609.09153v1.pdf`  
13 chapters · ~1 h 18 min of speech · ~39 min to render on this machine

| # | Chapter | Words | Speech | |
|---|---|---|---|---|
| 1 | Opening | 222 | 2 min |  |
| 2 | 1. Introduction | 577 | 4 min |  |
| 3 | 2. Related Work | 199 | 2 min |  |
| 4 | 3. The Procedural Graph Framework | 1,123 | 8 min |  |
| 5 | 4. Experimental Setup | 281 | 2 min |  |
| 6 | 5. Results | 1,378 | 9 min |  |
| 7 | 6. Conclusion | 121 | 1 min |  |
| 8 | A. Extended Related Work and Comparison | 1,498 | 12 min | appendix |
| 9 | B. Experimental Details | 1,601 | 11 min | appendix |
| 10 | C. Long-Horizon Analysis on EnterpriseArena | 1,696 | 12 min | appendix |
| 11 | D. Procedural Graph Construction: Supplementary Results | 1,018 | 7 min | appendix |
| 12 | E. Round-by-Round Self-Evolution on EnterpriseArena | 889 | 6 min | appendix |
| 13 | F. Additional Execution Cases | 203 | 1 min | appendix |

Everything below is the exact text that will be read aloud. The `#` column is what `--chapters` selects.

---

## [1] Opening

*Announced: “Opening”*

**Procedural Graphs: Self-Evolving Execution Structures for LLM Agents**

Large language models are increasingly deployed as agents that plan over long horizons and act through external tools. Most agents select actions through unconstrained generation over an accumulating history, leaving implicit the procedural knowledge of what to do, in what order, and under which conditions. As trajectories lengthen, agents can lose track of their objectives, invoke tools out of order, and repeat unproductive actions. We introduce the Procedural Graph: just as a knowledge graph organizes factual knowledge into (entity, relation, entity) triplets for what-is questions, a Procedural Graph organizes procedural knowledge into (procedure, relation, procedure) triplets for what-to-do questions. At each decision step, the framework localizes the agent's active node, and a guidance model translates the surrounding subgraph into step-level situational guidance that biases the solver's next action without dictating it. The graph is self-evolving: an LLM refiner contrasts failed trajectories with successful ones and edits the graph's topology and attributes, committing edits that preserve or improve held-out validation performance while retaining rejected ones to discourage repetition. Starting from a minimal skeleton, the loop builds graphs that match or surpass hand-designed ones. It can also repair a flawed expert prior. Across multiple datasets, task types, and LLMs, the Procedural Graph delivers consistent gains over memory-based baselines, and self-evolution further improves performance without manual engineering.

<details><summary>Not read aloud in this chapter</summary>

- **2 × front matter**
  - p1: Yuxing Lu 1,2,3 , Yicheng Chen 1 , Shanchan Wu 1 and Sercan Ö. Arık 1
  - p1: 1 Google, 2 Georgia Institute of Technology, 3 Peking University
- **1 × figure**
  - p1: (no text)

</details>

---

## [2] 1. Introduction

*Announced: “Introduction”*

Large language models (LLMs) are increasingly deployed as autonomous agents that plan over long horizons and act through external tools. Most agents make decisions through unconstrained generation conditioned on a flat, growing log of prior actions and observations. This places the burden of procedural coherence on free-form generation: the agent must identify relevant observations, infer which steps remain, and choose an action that respects their dependencies. As trajectories lengthen, agents can lose track of their objectives, invoke tools out of order, and repeat unproductive actions.

Existing approaches provide procedural structure through textual memory, conditional guidelines, and explicit workflows. Memory and self-reflection methods record past experience as free-form text and retrieve it for reuse in the context. Although these records preserve useful experience, the solver must still reconstruct how it applies to the current step and how it constrains the steps that follow. State-conditioned guidelines provide more targeted advice, but retrieve rules without explicitly connecting successive procedural steps. Workflows and state machines make those steps explicit and constrain execution, but often require manual design. Automated workflow search reduces manual design effort by optimizing workflow structure offline. The remaining challenge is to combine an editable procedure representation with guidance that is conditioned on the agent's current progress.

We argue that an agent needs procedural knowledge that is structured enough to steer it away from invalid behavior, flexible enough to preserve reasoning freedom, responsive to its current progress, and able to improve from experience. We address these requirements with the Procedural Graph (PG), an explicit and editable directed graph of procedural knowledge. The design mirrors a familiar structure (Figure 1): just as a knowledge graph organizes factual knowledge into (entity, relation, entity) triplets to answer what-is questions, a PG organizes procedural information into (procedure, relation, procedure) triplets to answer what-to-do questions. Its nodes abstract tool actions, reasoning steps, and states; its edges encode permissible transitions, each annotated with textual attributes describing how and when the transition should be taken. The PG keeps a task domain's procedural knowledge outside the model weights, where it can be inspected, retrieved at each step, and edited without retraining.

Our framework puts this prior to work in two complementary phases. During online inference, the framework localizes the active node from the agent's trajectory, and a guidance model reads the surrounding subgraph in its topological context and translates the relevant edge attributes into situational guidance for the next step. During offline self-evolution, after each batch of training tasks, an LLM refiner contrasts failed trajectories with successful ones and proposes edits to the graph's topology and attributes, adding missing nodes and edges, pruning failure-inducing ones, and revising edge attributes. A structurally valid candidate graph is adopted if it matches or improves performance on a held-out validation set, and rejected candidates are retained as negative constraints. The validation gate filters out candidates that reduce the measured score, while rejection memory discourages repeated unsuccessful proposals. We summarize our contributions as follows:

- We introduce the Procedural Graph (PG), an explicit and editable graph of procedural knowledge that steers LLM-agent execution while preserving reasoning flexibility.

- We propose Generative PG Guidance, an online mechanism that converts the static graph and the live trajectory into step-level situational guidance.

- We develop a self-evolution loop that refines graph topology and attributes using execution feedback.

- Across different tasks and LLMs, PG consistently outperforms other memory baselines; evolution from scratch produces graphs that match or surpass hand-designed ones, and the loop can also repair flawed expert priors.

<details><summary>Not read aloud in this chapter</summary>

- **5 citations** removed from the text
- **1 × figure**
  - p2: (no text)

</details>

---

## [3] 2. Related Work

*Announced: “Related Work”*

LLM Agents and Action Selection. The dominant paradigm follows a free-form action-selection loop: ReAct interleaves reasoning with environment actions, and successors extend it with self-critique, branching search, or richer action spaces. These approaches rely on the LLM to select valid next actions from in-context information, leaving admissible transitions implicit. Documented failure modes include planning hallucination, drift, and repetitive loops.

Structured Priors for Agent Planning. A second line provides explicit structure for planning, including textual procedure rules, workflow knowledge in text, code, or flowchart form, searched workflow graphs, and graph-organized tool catalogs. These methods organize procedural knowledge as action rules, workflows, or tool graphs. PG combines attributed procedure transitions, local retrieval from the current execution context, and refinement of graph topology and attributes.

Self-Improving Agents from Trajectories. A third line distills reusable knowledge from past trajectories, stored as self-critiques, insights, state-conditioned guidelines, workflows, or procedural memories. These artifacts retain different forms of structure, including conditional rules and ordered steps within workflows. PG connects transitions across procedure steps in an explicitly editable graph. Its typed, attributed edges support local structural retrieval and refinement from execution feedback. An extended survey and an eight-dimension comparison of 24 methods are provided in Appendix A.

<details><summary>Not read aloud in this chapter</summary>

- **12 citations** removed from the text

</details>

---

## [4] 3. The Procedural Graph Framework

*Announced: “The Procedural Graph Framework”*

We introduce the Procedural Graph (PG), a directed graph of procedural knowledge that guides agent execution online while iteratively optimizing its topology and attributes offline. As illustrated in Figure 2, the framework operates in two complementary phases:

Online Inference (Section 3.2): During task solving, the graph is frozen. The agent combines the PG with its trajectory to generate dynamic situational guidance.

Offline Evolution (Section 3.3): After executing a batch of training tasks, an LLM refiner analyzes the diagnostic traces and modifies the graph topology and attributes via an automated feedback loop.

### Formal Representation of Procedural Graphs

Formally, a Procedural Graph is a directed, attributed graph where V is the set of abstract nodes, R is a vocabulary of transition relations, and each element of E is a directed, attributed triplet: an edge e = (u, r, v) ∈ E states that node v is admissible after node u under relation r. Each node abstracts a tool function, a skill, an internal reasoning step, or a task status. The attribute mapping Φ associates each edge with a set of named attributes whose schema can be specified for the task. In our implementation, we use three textual fields: condition, guidance, and pitfalls, describing when the transition applies, how to proceed, and what to avoid. As an illustrative example, a financial-planning edge (cash flow forecast, Leads to, fund raising request) could carry the attributes "condition: projected runway falls below the safety buffer; guidance: submit the request early to allow for the financing delivery delay; pitfalls: do not stack a second request while one is pending."

By structuring task knowledge into triplets, G makes admissible transitions explicit and guides the agent toward valid tool calls and action sequences. The graph can be initialized from an expert prior or from scratch; Section 5.3 compares these construction strategies.

### Generative Guidance at Inference Time

Independent retrieval of transition attributes, such as top-k similarity search, can omit the connections between procedural steps. For example, retrieving guidance for submit without the preceding check answer transition can omit the verification step that makes submission appropriate. Retrieving the connected neighborhood exposes both the action and its procedural prerequisites.

Generative Procedural Graph Guidance addresses this by combining three operations: locate, extract, and generate. Let q be the user query and Tt = (a1, o1,... , at-1, ot-1) be the interleaved history of actions and observations up to decision step t. We use a0 = Start as an initialization marker, so the first step is localized at u1 = Start. At each step, where Match locates the agent by exactly matching its most recent procedure (e.g., a tool call) to a node in V. The directed edge neighborhood Nh(ut) contains ut and the outgoing transitions reached by expanding for up to h steps. The window Tt-w:t contains the last w trajectory steps, and Ψ is the guidance language model. This connected neighborhood lets Ψ read transitions in their topological context and consider possible next steps up to h transitions ahead. Ψ translates the static attributes Φ(e) of the surrounding edges into situational guidance gt, identifying the agent's immediate goal and the formatting or logical errors to avoid.

The guidance gt is appended to the task solver's prompt. The solver then selects its next action from the query, trajectory, and guidance:

This soft integration allows the agent to maintain flexible reasoning while being steered toward the procedural structure encoded in G. Guidance uses the localized neighborhood when matching succeeds and the full graph otherwise, together with a recent trajectory window. Section 5.5 evaluates the resulting performance and efficiency; Appendix F provides execution cases.

### Self-Evolution of Procedural Graphs

An offline self-evolution loop adapts graph topology and attributes from execution feedback, reducing the need for manual design (Algorithm 1). Let G0 be the initial Procedural Graph and Gk the retained graph after round k. Each round starts from Gk-1; a rejected candidate never becomes the starting graph of the next round. Across generations k = 1,... , K, the evolution engine executes a four-step loop:

Step 1: Diagnostic Rollout. Using the retained graph Gk-1, the solver runs on a batch of training tasks Bk ⊂ Dtrain, and we record the diagnostic traces together with their evaluation scores, Ek = � (qi, T (k) i, S (k) i ) �Bk i=1, where S (k) i ∈ is the final task score. The refiner compares high-scoring traces with low-scoring ones; for tasks with binary outcomes, this reduces to successes versus failures.

Step 2: Feedback-Driven Mutation. An offline LLM refiner inspects the partitioned traces to identify repeated error loops in failure trajectories and multi-step reasoning shortcuts in successful runs. Based on this feedback, the refiner generates a structured edit set ΔGk comprising two topological edit operations: Add: Inserting missing verification nodes or edges; Delete: Removing nodes or edges that repeatedly steer trajectories into failure or prevent progress.

Attribute revisions use the same edit interface: an edge is deleted and re-added with updated attribute values. This operation applies to any attribute defined by the chosen schema. The candidate graph is obtained by applying the proposed edits, G cand k = Gk-1 ⊕ ΔGk, where ⊕ applies edits to a copy and performs any configured cycle repair.

Step 3: Validation Gating. To assess whether structural mutations improve performance beyond the training batch, a candidate that passes edit application and structural checks is evaluated on an independent validation set Dval. Invalid candidates are discarded before validation rollout, leaving the retained graph and its cached validation score unchanged. The mean validation task score is computed as:

The initial graph is evaluated once to establish the reference score. For a structurally valid candidate, the retained graph is updated as follows:

The gate retains candidates whose measured validation score matches or exceeds the cached score of the current graph. Section 5.4 examines these decisions under stochastic evaluation.

Step 4: Rejection Memory as a Safeguard. Iterative self-correction can repeatedly propose equivalent unsuccessful edits. If a candidate graph is rejected by the validation gate (Sval (G cand k ) < Sval (Gk-1)), we log the candidate graph and its proposed edits, together with the associated training trajectories Ek and validation outcomes, into a rejection memory Hrejected. For the trajectory context supplied to the refiner, we concatenate the training trajectories and, if the configured maximum token length Lmax is exceeded, discard tokens from the beginning while preserving the final Lmax tokens in their original order. This retains the trajectory ending rather than an initial prefix; the resulting context is denoted as Ck. When proposing edits for round k + 1, the refiner receives Hrejected as negative evidence:

The rejection history Hrejected helps the refiner avoid previously unsuccessful edits. Proposed changes are evaluated by the gate before they enter the retained graph.

<details><summary>Not read aloud in this chapter</summary>

- **1 citations** removed from the text
- **6 × formula**
  - p3: (no text)
  - p4: (no text)
  - p5: (no text)
  - … and 3 more
- **1 × figure**
  - p4: (no text)

</details>

---

## [5] 4. Experimental Setup

*Announced: “Experimental Setup”*

Implementation details are provided in Appendix B.

Benchmarks. We evaluate procedural reasoning across seven benchmarks: HotpotQA for multi-hop question answering with search tools; MultiChallenge for instruction retention across multi-turn conversations; GDPval for open-ended professional tasks scored against expert rubrics; ALFWorld for embodied household tasks with strict action ordering; τ-bench for policy-compliant tool use under live user interaction; BFCL for multi-turn function calling; and EnterpriseArena for long-horizon financial decision-making under delayed feedback and macroeconomic shocks. Dataset splits and preprocessing are detailed in Appendix B.1, and all metrics are defined in Appendix B.2.

Baselines. All methods share an identical ReAct solver and differ only in how procedural experience is stored and reused; every learning-based baseline consumes the same training trajectories as our self-evolution loop. Ordered by increasing structure, we compare: Vanilla ReAct (no memory), MemoryBank, which maintains summarized experience with forgetting; RAP, which retrieves past trajectories as in-context exemplars; ExpeL, which distills trajectories into natural-language insights; AutoGuide, which retrieves state-conditioned guidelines; AWM, which induces linear workflows; and KnowAgent, which maintains textual actiontransition rules. Implementation and adaptation details for each baseline are given in Appendix B.3.

Models. We evaluate four LLMs: Claude Sonnet 4.6, Gemini 3.1 Pro, Gemini 3.5 Flash, and Grok 4.1 Fast. The guidance model and the offline refiner always share the same underlying LLM as the solver. All calls use greedy decoding (temperature 0) for reproducibility.

Procedural Graph Configuration. Online guidance uses the h=2 hop neighborhood of the localized node and a recent trajectory window of w=3. Different construction strategies are compared in Section 5.3 and formalized in Appendix D.2. Statistics of the graphs used for each benchmark (node and triplet counts, relation types, attribute coverage) are given in Appendix B.4.

<details><summary>Not read aloud in this chapter</summary>

- **15 citations** removed from the text

</details>

---

## [6] 5. Results

*Announced: “Results”*

### Main Results across Benchmarks and Models

Table 1 compares the Procedural Graph against seven baselines across six benchmarks and four LLM families, all using the same ReAct solver. PG ranks first or joint first in 21 of 24 model-benchmark settings. Compared with the strongest baseline in each setting, PG records 19 wins, two ties, and three losses (one-sided exact binomial sign test excluding ties, p = 4.3 × 10 -4 ). Its largest margins are on BFCL v3 with Gemini 3.5 Flash (67.00% vs. 58.00%, +9.00 points), GDPval with Gemini 3.1 Pro (78.78 vs. 71.37, +7.41 points), and τ-bench with the same model (80.00% vs. 73.04%, +6.96 points). Baseline rankings vary across tasks and models, with no single method consistently placing second. These results suggest that combining conditional guidance, reusable action sequences, and explicit transitions in a connected graph is useful across diverse settings.

The gains also extend across model families. On GDPval and BFCL v3, PG outperforms every baseline under all four LLMs, indicating that its advantage on these tasks is not confined to a particular solver. On MultiChallenge, PG ranks first or joint first across all four models, matching AWM on Claude Sonnet 4.6 and both AWM and KnowAgent on Gemini 3.5 Flash. HotpotQA shows a different pattern: margins over the strongest baseline range from -0.90 to +1.30 points. The magnitude of the gains therefore varies substantially across benchmarks.

### Long-Horizon Decision Making and Resilience

To evaluate agent resilience on long-horizon tasks, we deploy agents in EnterpriseArena, a simulator in which the agent makes monthly financial decisions over up to 132 months under strict liquidity constraints and three scheduled crises that are not disclosed to the agent. Figure 3 plots the Kaplan-Meier survival curves and the ensemble cash trajectories for all four models; complete metrics are reported in Table 8 in Appendix C. PG achieves the highest or joint-highest full-horizon survival and the longest average lifespan across all four LLMs. It raises survival from 44.0% to 58.0% for Claude Sonnet 4.6, from 6.0% to 34.0% for Gemini 3.1 Pro, and from 26.0% to 40.0% for Grok 4.1 Fast, where it also delivers the best average enterprise score ($39.62M).

What changes under guidance is which tools are called and when, rather than simply how many. The unguided Gemini 3.5 Flash baseline repeatedly queries cash and market state within a single turn, adding redundant observations to its context. It issues 18.94 tool calls per month, which the graph reduces to 12.53 while improving the average enterprise score. On Claude Sonnet 4.6 and Gemini 3.1 Pro, tool calls instead increase from 0.13 to 0.36 and from 0.89 to 3.18 per month, respectively, while survival also improves. In these settings, the graph guides the agent to run forecast and market checks before a financing decision (Appendix C.2).

The behavior that does track survival across all four models is anticipatory fundraising. Because capital arrives one to six months after it is requested, surviving a crisis requires asking well before liquidity runs out. The full trajectories show that the unguided Gemini 3.5 Flash baseline does not initiate fundraising sufficiently early, whereas PG-guided agents initiate requests during stable months. Average capital raised is $0.00M for the Flash baseline, compared with $9.39M for PG-guided Flash and $30.11M for PG-guided Grok 4.1 Fast. Appendix C.3 contrasts step-by-step traces of the unguided baseline, a memory-summarization agent, and a PG-guided agent entering the first crisis.

### Procedural Graph Construction Strategies

We compare five PG construction strategies against the unguided baseline, spanning expert versus minimal initialization and fixed, one-time, or iterative refinement. Modes 3 and 5 instantiate the full evolution loop, while Modes 1, 2, and 4 provide fixed or one-time alternatives (supplementary results and mode definitions are provided in Appendix D). The performance metrics of HotpotQA and MultiChallenge are presented in Table 2.

We compare initialization from an expert prior (Modes 1-3) with initialization from scratch (Modes 4-5). On HotpotQA, Mode 5 (Scratch + Online Evolution) achieves the highest performance across all configurations, scoring 78.79% Ans F1 and 66.30% Ans EM (gains of 7.58 F1 points and 7.50 EM points over the unguided baseline). On MultiChallenge, which requires retaining multiple constraints across dialogue turns, Mode 5 achieves an Overall Success Rate of 91.07% without a human prior, while Mode 3 (Expert + Online Evolution) performs best at 92.86%.

The loop also self-corrects from a flawed expert prior. On MultiChallenge, using the hand-crafted expert graph (Mode 1) lowers success from 87.50% to 58.93%. A single offline update (Mode 2) further lowers success to 53.57%. The iterative configuration (Mode 3), which combines fresh execution feedback with validation gating, recovers to 92.86%, a gain of 33.93 points over the expert initialization. The loop therefore recovers from an expert prior that initially reduces performance (Appendix F.2). Resource and stability statistics for all five modes, including a 45.7% reduction in parsing failures and the token overhead carried by expert-written guidance, are reported in Appendix D.1.

### Procedural Graph Self-Evolution

We examine ten rounds of PG self-evolution (Section 3.3) on EnterpriseArena, where the agent manages liquidity through successive macroeconomic crises. Figure 4 tracks the resulting changes in lifespan and capital raised; Appendix E reports the per-round results.

On the validation split, the unguided baseline has a full-horizon survival rate of 0.0% and a mean lifespan of 34.8 months. Since capital takes one to six months to arrive, fundraising must begin before cash runs out. Validation performance improves in several distinct rounds, separated by periods with no accepted update. Round 1 discovers the sequential backbone that guides the agent to audit cash and forecast runway before a financing decision, producing the largest single jump (0.0%→ 45.0% validation survival); Round 2 adds recall notes to reuse the notes saved by the Round 1 graph and lifts survival to 80.0%, with tool usage falling from 17.23 to 3.08 calls per month relative to the unguided baseline. Rounds 3-6 produce no committed update; one candidate fails structural verification before rollout. Round 7 prunes the pass action branch, and Round 8 introduces the administrative bypass described in Appendix E.3. Validation survival reaches 90.0% in Round 8 and remains at that level in Round 9 before Round 10 is rejected and the loop terminates.

The test results distinguish the returned graph from intermediate candidates. The returned graph reaches 85.0% test survival against the baseline's 0.0% (Fisher's exact p = 2.6 × 10 -8 ), while the best single round observed during the search reached 95.0%; we report the former, since quoting the latter would amount to selecting on the test set. With 20 episodes per split, individual accept/reject decisions turn on one or two episodes and should be read as a search trace rather than as significance tests. Topological changes and cross-dataset validation are detailed in Appendices E.3 and E.4.

### Efficiency Analysis

Table 3 examines two key design choices behind our guidance mechanism: what portion of the graph the agent sees (full graph vs. localized subgraph) and how it is consumed (raw injection vs. generative guidance). The three PG configurations compare generative guidance with raw injection for the full graph and assess localization under generative guidance, alongside a no-graph baseline. All configurations use Gemini 3.5 Flash and a shared solver prompt template; the PG configurations use the same underlying graph (Appendix B.5).

Injecting the raw full graph improves performance on structured dialogue (MultiChallenge rises from 80.27 to 86.60) but lowers success on embodied execution (ALFWorld drops from 72.58 to 70.34). Full-graph generative guidance further reduces ALFWorld success to 54.48 while increasing token consumption. These results favor guidance grounded in the agent's local graph neighborhood over guidance generated from the full graph. Given the same graph, the localized generative configuration achieves the highest performance across all three benchmarks (89.31, 63.99, and 81.53), exceeding the best alternative in each setting, including the no-graph baseline, by 2.0, 6.8, and 9.0 points, respectively.

Localization reduces total tokens relative to full-graph generative guidance on all three benchmarks: by 70.9% on ALFWorld, 18.1% on GDPval, and 14.8% on MultiChallenge. It also shortens trajectories on GDPval and ALFWorld. The additional guidance call introduces token overhead relative to the no-graph baseline. On GDPval and ALFWorld, localized guidance reduces average solver steps from 28.20 to 18.57 and from 21.84 to 18.80, respectively, while total token consumption remains 33.4% and 55.4% higher.

<details><summary>Not read aloud in this chapter</summary>

- **1 citations** removed from the text
- **3 × table**
  - p7: (no text)
  - p9: (no text)
  - p10: (no text)
- **2 × figure**
  - p8: (no text)
  - p9: (no text)

</details>

---

## [7] 6. Conclusion

*Announced: “Conclusion”*

We introduced the Procedural Graph, an explicit and editable representation of procedural knowledge that gives LLM agents a queryable answer to what to do next. PG connects the agent's current progress with relevant transitions and execution advice while preserving reasoning flexibility. Across tasks and model families, it delivers consistent gains over memory-based baselines. Self-evolution builds effective graphs from minimal initializations and repairs expert priors that initially hinder performance. These results support learning and revising procedural knowledge from execution feedback without updating model weights. Guidance increases token use even when it reduces solver steps; future work could reuse guidance across steps or generate it selectively. Evaluating transfer across solvers and tool interfaces would clarify how widely the learned procedures can be reused.

<details><summary>Not read aloud in this chapter</summary>

- **55 × references section**
  - p12: References
  - p12: Besta, N. Blach, A. Kubicek, R. Gerstenberger, M. Podstawski, L. Gianinazzi, J. Gajda, T. …
  - p12: Deshpande, V. Sirdeshmukh, J. B. Mols, L. Jin, E.-Y. Hernandez-Cardona, D. Lee, J. Kritz, …
  - … and 52 more

</details>

---

## [8] A. Extended Related Work and Comparison *(appendix)*

*Announced: “Extended Related Work and Comparison”*

This appendix expands Section 2. It covers procedural memory (Appendix A.1), action selection (Appendix A.2), structured planning (Appendix A.3), and self-improvement from trajectories (Appendix A.4). A comparison along eight design dimensions appears in Appendix A.5.

### Procedural Graphs as Procedural Memory: A CoALA View

Sumers et al. propose CoALA (Cognitive Architectures for Language Agents), which adapts the classical memory taxonomy of ACT-R and SOAR to LLM-based agents: working memory holds the current context, episodic memory holds past experiences, semantic memory holds factual knowledge, and procedural memory holds the skills and procedures that govern how to act. This taxonomy distinguishes the roles of different agent memories. Retrieval augmentation, including GraphRAG and its variants, operates on semantic memory; trajectory-based reflection methods such as Reflexion and ExpeL operate on episodic memory. Procedural memory is the quadrant that has received the least explicit treatment: it remains largely implicit in model weights, or is scattered across ad hoc artifacts such as prompt templates, skill libraries, and workflow scripts. PG implements CoALA's procedural-memory module by storing state-conditioned action transitions in a structure that can be retrieved and updated.

### LLM Agents and Action Selection

The dominant execution template is reason-then-act interleaving, established by ReAct and extended along several axes. Reflexion inserts verbal self-criticism between trials; Toolformer shows that tool-call decisions can be learned by self-supervised filtering of LM-generated API calls; Tree-of-Thoughts and Graph-ofThoughts generalize chain-style reasoning into search over branching alternatives; and Plan-and-Solve and ADaPT separate planning from execution, with the latter recursively decomposing sub-tasks only once the executor fails. A parallel line redesigns the action space itself rather than the control flow over it: CodeAct unifies actions as executable Python so as to inherit the compositionality of a programming language, and HuggingGPT treats models hosted on Hugging Face as callable tools coordinated by an LLM controller.

A third body of work scales the tool catalog. ToolLLM contributes a 16,464API benchmark together with a depth-first decision tree for tool selection; Gorilla fine-tunes LLaMA on APIBench with retrieval-augmented training; AnyTool adds a hierarchical three-tier API retriever; and ToolGen collapses retrieval and invocation into next-token generation via virtual tool tokens. API-Bank and MetaTool supply complementary evaluation axes covering when to invoke a tool and which one to invoke.

These methods generally leave admissible transitions implicit, relying on the model to select the next action from in-context information. The resulting failure modes are well documented, and include planning hallucination, trajectory drift on long-horizon tasks, and repetitive loops when execution feedback is ambiguous. These failures motivate the explicit structural priors discussed next.

### Structured Priors for Agent Planning

One approach is to represent procedures explicitly. KnowAgent maintains a textual action knowledge base of admissible action rules and pairs it with knowledgeable self-learning to constrain the agent's action path during trajectory synthesis. FlowBench formalizes workflow knowledge in three formats, text, code, and flowchart, and shows empirically across six domains and 51 scenarios that flowcharts reduce planning hallucination most effectively. AFlow recasts workflow construction as Monte Carlo Tree Search over coderepresented graphs whose nodes are LLM-invoking operators. Decoding constraints provide another form of structure: Tooldec compiles tool syntax schemas into finite-state automata and constrains generation to syntactically valid calls, using the efficient FSM-guided generation algorithm of Outlines. Such methods guarantee surface-form validity but say nothing about whether an action is semantically admissible given the task state.

Other methods organize tool collections as graphs. ToolNet mines a directed tool-transition graph from LLM-generated trajectories and lets the agent walk it at inference time. ControlLLM pre-builds a tool dependency graph from parameter-type matching and introduces Thoughts-on-Graph search over it. COLT targets retrieval completeness through a dual-view query-tool-scene graph trained with LightGCN and contrastive losses. Graph RAGTool Fusion hybridizes vector retrieval with graph traversal over a hand-designed tool knowledge graph, extending GraphRAG to tool selection. The Tool Graph Retriever learns a tool-dependency discriminator and propagates embeddings over the resulting graph, while NaviAgent fuses API schema structure with historical invocations into a continuously evolving heterogeneous dependency graph. On the evaluation side, TaskBench provides a graph-structured tool-automation benchmark with explicit node and edge scoring, and GNN4TaskPlan demonstrates that GNN-based sub-task selection improves over LLM-only planning on it. SkillGraph addresses multimodal multi-agent collaboration: it retrieves reasoning skills from an evolving skill bank and predicts a query-conditioned communication graph over agents.

These methods use graphs for different purposes: tool-transition and dependency graphs support tool selection, workflow graphs organize operator execution, and SkillGraph models communication among agents. Conditional action knowledge also appears in KnowAgent's textual rules and FlowBench's branching workflows. PG combines a graph over tool calls and reasoning steps with condition, guidance, and pitfall attributes on transitions. At each step, it localizes the current procedure and verbalizes the surrounding neighborhood. Per-step retrieval is also used by AutoGuide, which selects state-matched guidelines (Appendix B.3); PG instead retrieves connected transitions and supports explicit edits to their topology and attributes.

### Self-Improving Agents from Trajectories

Another line learns reusable knowledge from the agent's execution history, often through verbal reflection and episodic memory. Reflexion writes self-critiques into an episodic buffer and re-attempts the task; Generative Agents maintain a memory stream ranked by recency, importance, and relevance, with periodic reflection for abstraction; MemoryBank keeps a long-term store of experience summaries governed by an Ebbinghaus-inspired forgetting schedule; and RAP retrieves whole past trajectories as in-context exemplars. Two methods push toward explicitly contrastive distillation: ExpeL contrasts success and failure pairs to extract natural-language insights, and AutoGuide sharpens these into context-aware guidelines of explicit conditional form ("in context X, action

Y is appropriate") retrieved at test time from the agent's current state. ERL uses reflection to guide a second attempt, then trains the base policy to retain the resulting improvements.

A second family stores reusable skills and workflows. Voyager maintains an ever-growing library of Minecraft skills indexed by embeddings of their natural-language descriptions, retrieved top-k per task; TroVE induces a verified Python toolbox and trims it to stay compact; AWM induces reusable workflows combining natural-language descriptions with program-form actions and adds them to prompt memory in both offline and online modes; and SkillWeaver and WebXSkill refine skill discovery and execution for web agents. Several frameworks explicitly model the lifecycle of procedural memory: MemP formalizes build, retrieve, and update as an optimization target, distilling trajectories into both fine-grained step instructions and higher-level script abstractions; EvolveR closes the loop with offline self-distillation, online retrieval of strategic principles, and policy reinforcement; and SEAgent learns computer-use policies from autonomously collected experience. A-Mem and Zep/Graphiti bring knowledge-graph-style structure to agent memory, though their focus is episodic and semantic rather than procedural.

Among these methods, AutoGuide is the closest to our approach. Like our edge attributes, its conditional guidelines associate situations with actions. PG connects these transitions in a typed graph, supporting structural retrieval, dependency inspection, and refinement through graph edits. MemP shares our emphasis on lifecycle operations over procedural memory, storing trajectories and script-like abstractions for retrieval without an explicit procedure graph. The seven baselines we compare empirically in Section 4 are drawn from across this design space, spanning episodic summarization (MemoryBank), trajectory retrieval (RAP), insight distillation (ExpeL), conditional guidelines (AutoGuide), workflow induction (AWM), and textual transition rules (KnowAgent); Table 6 summarizes their storage and injection designs.

### Detailed Comparison Table

Table 4 compares 24 representative methods with PG along eight design dimensions. It summarizes the representations and access mechanisms described in the cited work; the baseline configurations used in our experiments are specified separately in Appendix B.3.

The comparison highlights differences in what is stored, how it is accessed, and what can be updated. Textual rules, code libraries, workflows, and graphs each preserve useful procedural structure. For example, KnowAgent supplies action-transition knowledge as text in the prompt, while FlowBench includes flowcharts with branch conditions. AFlow searches over code-represented operator workflows, and tool graphs support navigation through tool catalogs. PG stores transitions between tool calls and reasoning steps, with conditions, guidance, and pitfalls attached to edges, and retrieves a neighborhood around the current procedure.

The target of improvement also differs across methods. Some revise insights, skills, or workflows; ToolNet derives tool transitions from trajectories, while SkillGraph couples skill-bank updates with query-conditioned communication among agents. PG updates the procedure graph itself through node and edge edits. Its contribution is this combination of attributed transitions, localized guidance, and structural refinement, rather than graph structure or conditional knowledge alone.

Column Definitions. "Form" describes the representation used for action selection, memory, or coordination; "Granularity" is the unit size of stored knowledge; and "Source" describes how the structure is obtained. "Updatable" indicates whether the structure can be revised from new trajectories, and "Retrieval" specifies the inference-time access mode. "Edge Semantics" describes the meaning of edges or relations, if any, while "Scope" identifies the intended deployment setting. "Graph" distinguishes explicit workflow, tool, or communication graphs (yes), auxiliary hierarchies or transitions encoded only in text (partial), and representations without explicit graph organization (no). FlowBench is shown in its flowchart form. For KnowAgent, "Updatable" refers to the action knowledge base, not model self-training. In our implementation, PG edge attributes comprise conditions, guidance, and pitfalls.

<details><summary>Not read aloud in this chapter</summary>

- **52 citations** removed from the text
- **1 × table**
  - p19: (no text)

</details>

---

## [9] B. Experimental Details *(appendix)*

*Announced: “Experimental Details”*

This appendix provides the dataset splits, evaluation metrics, baseline implementation details, prompt templates, and the full self-evolution algorithm (Appendix B.6).

### Datasets and Splits

Table 5 summarizes the sample counts and splits used in all experiments.

During self-evolution, the training split is processed in sequential strides of S=100 samples on HotpotQA and S=20 on MultiChallenge. The validation set Dval consumed by the acceptance gate is held out separately from both splits above and never overlaps the test set; its size is 1,000 for HotpotQA and 100 for MultiChallenge (Appendix D.3), and 20 episodes for EnterpriseArena. For EnterpriseArena, each configuration runs 50 training and 50 test episodes; the full environment mechanics are given in Appendix C.1.

### Evaluation Metrics

For HotpotQA, the main comparison reports LLM-judged answer accuracy: a Gemini 3.1 Pro judge model receives the question, the gold answer, and the agent's answer, and returns a binary equivalence verdict; the construction study (Section 5.3) additionally reports strict string Exact Match and wordlevel F1. For MultiChallenge, an LLM judge based on Gemini 3.1 Pro scores the Overall Success Rate together with four axes: Inference Memory, Instruction Retention, Reliable Versioned Editing, and Self Coherence. For GDPval, deliverables are scored against per-task rubrics and we report the mean rubric score. For ALFWorld, we report the task success rate on the test games. For τ-bench, we report Pass@1, i.e., the fraction of episodes whose final database state matches the annotated goal state. For BFCL v3, we report the official multi-turn accuracy. For EnterpriseArena, we report the full-horizon survival rate, the average lifespan in months, the mean time-averaged enterprise score, and the average capital raised (see Appendix C.1 for definitions).

### Baseline Implementation Details

All baselines share the same ReAct solver, tool interface, and decoding configuration as our method, and every learning-based baseline consumes exactly the same training split that our self-evolution loop uses; they differ only in the artifact distilled from those trajectories and in how that artifact is injected at inference time. Table 6 summarizes the compared mechanisms: what each method stores, how that knowledge is organized, and how it enters the solver's context at inference time.

MemoryBank maintains a long-term store of per-task experience summaries updated after each completed task; at inference, relevant summaries are retrieved with recencyweighted relevance and prepended to the solver prompt.

RAP embeds completed trajectories and, at each new task, retrieves the most similar past trajectories as in-context exemplars.

ExpeL contrasts success and failure trajectories to distill a pool of naturallanguage insights, which are injected into the system prompt alongside retrieved successful exemplars.

AutoGuide extracts state-conditioned guidelines from contrastive trajectory pairs; at each step, the current state is summarized and the applicable guidelines are retrieved and injected.

AWM induces reusable workflows from successful trajectories, retaining natural-language descriptions and action sequences as workflow memory in the solver prompt.

KnowAgent maintains a textual action-knowledge base describing available actions and admissible transition rules, injected as a static prompt prefix.

### Procedural Graph Statistics

Table 7 summarizes the size of the Procedural Graph used for each benchmark in the main experiments. The graphs are compact: outside of BFCL v3, whose 131 nodes mirror its large function catalog, every graph has between 7 and 17 nodes and between 7 and 27 triplets. Across all graphs, the relation vocabulary R comprises four types: Leads to, Triggers, Provides Input for, and Converges to. Most edges carry the full condition/guidance/pitfalls attribute triple of Section 3.1, with guidance the most consistently populated field.

### Prompt Templates

We use three families of prompts: a solver execution prompt that governs the ReAct loop, guidance generation prompts that translate the (sub)graph into situational guidance at each step, and a refiner prompt that drives offline self-evolution. The same templates are shared across all benchmarks; only the tool lists and task descriptions vary. Curly braces denote runtime placeholders.

### Solver Execution Prompt (ReAct loop)

Example:

Thought: I need to check the files in the workspace directory to locate the source documents.

Action: list dir(path=".")

DO NOT write any "Observation:" block or any subsequent steps. Only output exactly one Thought and one Action block. Do NOT simulate the environment's responses.

Thought:

### Guidance Generation Prompt (Local subgraph; default)

Serialized Graph Context Example. We reconstruct the graph-context text below from the saved HotpotQA Mode 2 graph using the implemented local serializer. The active-node header supplies the node ID, type, and description. Directed transitions are grouped by hop and followed by their condition, guidance, and pitfalls, preserving the checkpoint's field text. The two stored relation labels, Leads to and Provides Input for, are not printed by this serializer.

### Serialized Local Graph Context (HotpotQA; excerpt)

Active Cognitive Node: First Hop Retrieve (Type: Action) Description: Execute first hop retrieve to fetch primary evidence passages.

Immediate Transition Options (Hop 1):

- Transition: First Hop Retrieve → Scan Index (Condition: first hop retrieve)

- Guidance: Review the retrieved primary passages via Scan Index to locate specific bridge terms (such as birth dates, locations, or associated entities).

- Pitfalls to Avoid: Do not skip reading evidence details; missing the exact bridge entity name causes second-hop search failure.

Subsequent Horizon (Hop 2):

- Transition: Scan Index → Bridge Extract (Condition: scan index)

- Guidance: Extract the explicit connecting entity or bridge term linking the first passage to the target question.

- Pitfalls to Avoid: Ensure the extracted bridge term matches exact Wikipedia capitalization conventions.

### Guidance Generation Prompt (Full graph variant)

The full-graph variant is textually identical to the prompt above; the only difference is the content bound to the graph context slot, which is the complete Procedural Graph rather than the localized subgraph. Concretely, requirements are unchanged, so the two ablation rows in Table 3 differ only in graph scope and not in prompt wording or requested output length.

### Refiner Prompt (Self-evolution)

You are an expert cognitive architect optimizing a Procedural Graph for an intelligent agent. The Procedural Graph encodes structured procedural guidance.

Your job is to refine the Procedural Graph. Follow these guidelines based on the mode:

- static onetime / static incremental: Prune edges/nodes that lead to loops, deadlocks, or failures. Add missing nodes and edges that could fix the failures and improve performance for future tasks.

- scratch onetime / scratch incremental: If starting from scratch (the graph contains only Start → End), synthesize a brand new, complete Procedural Graph using the Available Tool Actions list, Status, and successful patterns in the trajectories. Otherwise, prune edges/nodes that lead to loops, deadlocks, or failures, and add missing nodes and edges based on the given graph.

Rules for nodes and edges. Rules 2-4 describe the edge attributes in Φ(e): condition, guidance, and pitfalls. The remaining rules govern node compatibility, generality, and graph structure.

- Action Nodes. Any node of type Action must match one of the action/tool names in the "Available Tool Actions" list above.

- Transition Conditions. If an edge has a condition, provide a natural-language semantic precondition under which this transition should fire (e.g., "When dialogue history has been parsed but target constraints are unknown"). Use null if the transition is unconditional.

- Execution Guidance. For every edge added in add edges, you MUST provide a guidance string detailing exactly what action to take next and the strategic rationale behind it.

- Pitfalls. Provide a pitfalls string warning about premature actions, forbidden words, or common formatting pitfalls to avoid during this step.

- Generality and Leak Prevention. The updated Procedural Graph must guide the agent effectively without overfitting to specific details of a single trajectory. Use high-level conceptual descriptions.

- Node ID Compatibility. If refining an existing graph (static modes), you MUST preserve the existing node IDs (such as Month Start, Decide Capital, and the tool names) so they remain compatible with the environment's state tracker. Do not rename them.

- Graph Structure. Follow the task's configured cycle policy. Every edge must reference existing nodes, and every node must have a directed path to a terminal node. The environment loop handles repetition across simulation cycles.

Please propose the exact set of edits to perform. You must output your edits as a single valid JSON block containing four arrays: add nodes, delete nodes, add edges, and delete edges. Output format must be exactly:

Each entry in delete edges removes all edges with the specified source and target, regardless of relation. To retain selected transitions between the same endpoints, include them in add edges, which is applied after deletion.

### Self-Evolution Algorithm

Algorithm 1 makes the retained-checkpoint state explicit. Sk is the cached validation score of Gk, and c specifies whether cycles are allowed. TailLmax preserves the ending of its input by removing excess tokens from the beginning, leaving shorter inputs unchanged. The graph stays fixed during each training or validation episode. SerializeRejections supplies prior candidate graphs and their validation scores, or structural-failure diagnostics, to the refiner; the associated training traces remain part of the rejection record.

### Algorithm 1 Offline Closed-Loop Procedural Graph Self-Evolution

Candidate Preparation and Structural Checks. PrepareCandidate applies edits to a copy of the retained graph, deleting edges and nodes before adding nodes and edges. It reports malformed edits, invalid node or relation types, and missing edge endpoints as failures. When cycles are disallowed, the implementation removes detected cycle-closing edges before validation; when cycles are allowed, that repair and the acyclicity check are skipped. The remaining checks require valid edge endpoints and a directed path from every node to a terminal node, defined by zero out-degree. This is a reachability check to a terminal node, not specifically to the node named End. Matching action-node names to the available tool list is a refiner-prompt requirement; the generic structural validator does not independently enforce tool-catalog membership. On failure, dk contains diagnostics and G cand k may be unavailable; on success, dk = ∅.

<details><summary>Not read aloud in this chapter</summary>

- **6 citations** removed from the text
- **9 × prompt template**
  - p21: {system_prompt} Procedural Graph Guidance: {procedural_graph_guidance} You must interleave…
  - p22: Current Trajectory: {trajectory}
  - p22: You are an expert cognitive architect and execution guide for an AI agent solving the task…
  - … and 6 more
- **3 × table**
  - p20: (no text)
  - p21: (no text)
  - p21: (no text)
- **3 × code**
  - p23: Task context: {task_description} Refinement mode: {mode} Available Tool Actions (the agent…
  - p23: { "add_nodes": [{"id":..., "type": "ACTION", "description":...}], "delete_nodes": ["node_i…
  - p24: Require: Initial graph G0; training/validation sets Dtrain, Dval; round budget K; trajecto…
- **2 × repeated heading**
  - p22: Solver Execution Prompt (ReAct loop) (continued)
  - p23: Guidance Generation Prompt (Full graph variant) (continued)

</details>

---

## [10] C. Long-Horizon Analysis on EnterpriseArena *(appendix)*

*Announced: “Long-Horizon Analysis on EnterpriseArena”*

This appendix describes the EnterpriseArena simulator and evaluation metrics, reports survival and cash trajectories, and compares traces from the baseline, memory-summarization, and PG-guided agents.

### EnterpriseArena Mechanics and Crisis Schedule

The Chief Financial Officer (CFO) simulator models the balance sheet dynamics of a microfinance lending institution over a long-term horizon of up to 132 months. The state of the environment at month t is formalized as a multi-dimensional tuple:

where Ct is the cash balance, Lt is the gross loan portfolio, At is the allowance for loan losses, IRt and PRt are interest and principal receivables, APt is accounts payable, Dt is total outstanding debt, Et is total equity raised, and Ut is the active user base.

The agent interacts with the simulator through a discrete action space. The primary stateadvancing action is book closing(), which simulates the transition from month t to t + 1. During this transition, the environment executes the following operations:

- Loan Amortization: A fraction of the loan portfolio Lt matures, generating principal payments and interest income based on the lending rate.

- User and Operational Costs: The active user base Ut grows or decays organically. Fixed operational costs and user acquisition costs are deducted from the cash balance Ct.

- Write-Offs: Defaulted loans are written off against the allowance At, and new provisions are calculated.

To manage liquidity, the agent can invoke fund raising request(type, amount), where the type is either 'equity' or 'debt'. Fundraising is subject to two realistic constraints:

- Market Delivery Lag: Capital is not delivered immediately. There is a stochastic delay of 1 to 6 months between the request step and the cash injection.

- Market Capacity Cap: The maximum amount of capital that can be raised in a single request is dynamically capped by the environment based on the current macroeconomic state and the institution's financial health.

The simulation terminates immediately if the cash balance goes negative (Ct < 0), representing corporate bankruptcy. The environment simulates three successive macroeconomic crises to test the agent's long-term resilience:

- Crisis 1 (Month 32): A mild contraction where loan repayment rates drop slightly from 98% to 90%.

- Crisis 2 (Month 59): A severe economic recession. Repayment rates plunge to 60%, write-offs surge, and organic user growth turns negative.

- Crisis 3 (Month 112): A systemic liquidity freeze. Repayment rates drop to 40%, and the market capacity cap for fundraising is severely restricted, making new capital acquisition extremely difficult.

Evaluation Metrics. Full Surv. is the percentage of runs that complete the 132-month horizon without bankruptcy; the crisis columns report the fractions reaching months 32, 59, and 112. Avg. Months averages run duration, including early terminations. Tools/Mo averages the per-run ratio of arena information-tool calls to simulated months, excluding memory operations and state-changing actions. Raised is the mean cumulative equity and debt financing actually received per run, in millions of dollars.

We use EnterpriseArena's revenue-based valuation and tool-use penalty to compute the score at each recorded month:

where Rev (12) i,t is trailing-twelve-month revenue (annualized from the available monthly average when fewer than twelve months are recorded), Ci,t is cash in dollars, and Ni,t is the cumulative number of arena information-tool calls. Avg. Score first averages these monthly scores within each run up to termination, then averages across runs, reporting the result in millions of dollars. Thus, a run ending in bankruptcy can still have a positive time-averaged score.

### Results and Survival Analysis

Figure 3 compares cash trajectories and Kaplan-Meier survival curves for four planning configurations on Claude Sonnet 4.6, Gemini 3.1 Pro, Gemini 3.5 Flash, and Grok 4.1 Fast. Each model panel places survival curves above cash trajectories, which show individual sample paths, the mean, and the 95% confidence interval. Survival gains vary across the four solvers.

The unguided baseline reaches full-horizon survival rates of 44.0% for Claude Sonnet 4.6, 6.0% for Gemini 3.1 Pro, 26.0% for Grok 4.1 Fast, and 0.0% for Gemini 3.5 Flash (Table 8). In the Flash baseline, mean lifespan is 33.58 months and no episode reaches the second crisis.

The Procedural Graph configuration (solid blue line) improves full-horizon survival for three solvers and mean lifespan for all four:

- Claude Sonnet 4.6: PG achieves the highest survival rate of 58.0% (a 14.0-point gain over the baseline). Its mean cash trajectory remains stable and ends at $76.03M, well above the liquidity warning threshold of $5.0M.

- Gemini 3.1 Pro: The Procedural Graph provides the largest absolute survival gain, raising the survival rate from 6.0% (baseline) to 34.0%, and securing a final mean cash of $22.99M, approximately 10.5 times the baseline's $2.18M.

- Grok 4.1 Fast: Survival improves from 26.0% to 40.0%, with the final mean cash increasing from $23.62M to $30.20M.

- Gemini 3.5 Flash: All four configurations have 0.0% full-horizon survival in this evaluation, while PG increases mean lifespan from 33.58 to 40.62 months. This result describes the configurations evaluated here; the separate self-evolution experiment is reported in Section 5.4.

MemoryBank achieves higher full-horizon survival than RAP on Gemini 3.1 Pro (22.0% vs. 6.0%) and Claude Sonnet 4.6 (56.0% vs. 50.0%). PG exceeds both on these two solvers and on Grok 4.1 Fast, while all methods tie at 0.0% on Gemini 3.5 Flash.

Relative to the unguided baseline, PG raises full-horizon survival by 28 points on Gemini 3.1 Pro and 14 points on both Claude Sonnet 4.6 and Grok 4.1 Fast. Appendix C.3 examines the actions taken in one matched task instance.

### Case Study: Three Agents Facing the First Crisis

To understand the mechanisms driving the quantitative performance gap, we contrast the step-bystep reasoning traces of a baseline agent, a memory summarization agent, and a Procedural Graph guided agent. The following traces are extracted directly from real experimental logs of Grok 4.1 Fast operating on an identical task instance (Seed 14) during the critical transition into the first macroeconomic crisis (Months 29 to 33). Traces are condensed from the raw logs; bracketed italic text is editorial annotation, not model output.

In this baseline trace, the agent reports no bankruptcy risk despite declining cash reserves. It later submits requests that violate the environment's constraints:

### Baseline Agent Trace (Sample 14) - Myopia and Rule Violation

### Step 45 (Month 31):

Thought: Month 31 confirms trajectory: cash $14.2M (down ∼$7.4M but infinite runway >12mos) ... no bankruptcy risk. With 1 action left, book closing to advance month, lock YTD financials, sustain momentum, and maximize valuation...

Action: book closing()

### Step 46 (Month 32):

Thought: Month 32: cash $6.2M (down sharply ∼$8M, runway ∼2-3mos, bankruptcy risk emerging)... Prior book closing advanced month but cash burn accelerating; cannot risk another book closing or pass. Raise equity to bolster cash...

Action: fund raising request(type='equity', amount=20000000)

### Step 47 (Month 33):

Thought: Month 33: cash critically low at $683K (runway <1mo, imminent bankruptcy risk)... Equity raise ($20M requested, pending 1-6mos) submitted but not received; cannot pass or book closing. Submit debt raise for immediate bridge funding to avoid bankruptcy...

Action: fund raising request(type='debt', amount=10000000)

Observation: Your fundraising request was rejected: you already have a pending fundraising request.

Observed behavior: The agent requests debt financing while an equity request is still pending. The environment rejects the additional request under the single-pending-request constraint.

The memory summarization agent uses an LLM-generated running summary of past events. In this example, it recognizes the shrinking cash runway but submits fundraising amounts inconsistent with its stated intentions and repeats requests while earlier funding is still pending:

### Memory Summarization Agent (Sample 14) - Hallucination and Constraint Blindness

### Step 51 (Month 29):

Thought: Cash $25.3M (MoM -$5.4M, runway ∼4mo per updated forecast)... pending equity ($18M, submitted M26, now ∼3mo in)... Runway critically eroding (4mo < 6mo buffer); pending raise may arrive soon but unreliable. Check market for raise viability...

Action: check market data(data type='VIX')

### Step 53 (Month 30):

Thought: Cash $25.3M (runway 4mo)... VIX 10.51 very low... Submit equity raise now per rules (prefer equity $15-20M)...

Action: fund raising request(type='equity', amount=18)

Observation: Your fundraising request was rejected: you already have a pending fundraising request.

### Step 57 (Month 32):

Thought: Cash $11.8M (runway 2mo)... low-risk equity raise $18M fits rules... submit to extend runway... Action: fund raising request(type='equity', amount=18)

### Step 59 (Month 32):

Thought: Cash $4.3M... runway 1mo critical... must raise now despite pending... submit $20M equity to buffer urgency...

Action: fund raising request(type='equity', amount=20)

Observation: Your fundraising request was rejected: you already have a pending fundraising request.

Observed behavior: The agent submits amounts of $18 and $20 despite referring to $18M and $20M in its reasoning, and repeatedly submits requests while earlier funding is pending.

Guided by the Procedural Graph, the proposed agent maintains a clear structural prior of the task's temporal rules. It initiates fundraising with the correct scale well in advance, chaining sequential reasoning steps while remaining strictly compliant with environment constraints during the stochastic delivery lag:

### Procedural Graph Agent Trace (Sample 14) - Strategic Foresight and Adherence

At the opening of Month 30, an equity request submitted in Month 27 delivers: $28.8M after the market-capacity cap. Step 37 (Month 30): Thought: Equity raise succeeded (capped at ∼$28.8M, added to cash for $47.6M total)... VIX at 10.51 is exceptionally low (indicating calm markets, ideal for equity raise to minimize dilution cost)... with escalating burn ahead of the projected contraction, raise equity again now for ∼$50M, preserving no-debt status... Action: fund raising request(type='equity', amount=50000000) Step 38 (Month 30): Thought: Request submitted (pending, 1-6 month delivery)... run forecast to confirm new runway... Action: cash flow forecast calculation(months=12) Step 42 (Month 32): Thought: ... forecast confirms 6-mo runway... pending $50M equity (submitted M30) likely delivers soon... advance month via book closing to progress raise delivery... Action: book closing() Step 44 (Month 33): Thought: ... pending $50M equity (submitted M30, now 3 mos in) likely delivers soon... no bankruptcy imminent... advance via book closing to progress raise delivery... Action: book closing()

Result: The agent strictly adheres to the delivery-lag and single-pending constraints, successfully bridges the crisis months, and survives to the end of the simulation at Month 132.

In this task instance, the PG-guided agent tracks pending funding, checks projected runway, and advances the month while awaiting delivery. The baseline and memory-summary traces show invalid requests. These observations illustrate different behaviors on the same instance; they do not establish how frequently each behavior occurs across runs.

<details><summary>Not read aloud in this chapter</summary>

- **1 citations** removed from the text
- **2 × formula**
  - p25: (no text)
  - p26: (no text)
- **1 × table**
  - p26: (no text)

</details>

---

## [11] D. Procedural Graph Construction: Supplementary Results *(appendix)*

*Announced: “Procedural Graph Construction: Supplementary Results”*

This appendix provides quantitative results, diagnostic case studies of construction failure modes, formulations of the five PG construction strategies, and the detailed experimental configurations.

### Efficiency and Robustness Statistics

Tables 9 (HotpotQA) and 10 (MultiChallenge) compare task performance, resource use, and parsing failures across the five construction modes and the unguided baseline.

Solver Steps and Latency. On MultiChallenge, Mode 5 uses 5.05 steps and 92.81 seconds per sample, compared with 8.02 steps and 166.57 seconds for Mode 4. Mode 2 has the lowest average step count (4.32) and latency (65.93 seconds), but also the lowest success rate (53.57%). Mode 3 achieves the highest success rate (92.86%), with 6.73 steps and 128.50 seconds per sample. These results show why resource use should be read alongside task performance; aggregate statistics alone do not identify the graph edits responsible for the differences.

Compared with the hand-crafted Mode 1 graph (6.60 steps and 117.70 seconds), Mode 5 uses fewer steps and less time on MultiChallenge. On HotpotQA, Mode 5 has the lowest latency among the PG configurations (31.53 seconds).

Action Formatting and Parsing Robustness. On HotpotQA, expert-initialized Modes 1-3 have fewer parsing failures per sample than scratch-initialized Modes 4-5. Mode 2 has the lowest value (0.005), followed by Mode 1 (0.007) and Mode 3 (0.009); Modes 4 and 5 each have 0.016. On MultiChallenge, Mode 5 records 0.57 parsing failures per sample compared with Mode 4's 1.07. The association between initialization and formatting therefore differs across tasks, and does not by itself establish that a particular graph schema causes the reduction.

Token Use. On MultiChallenge, Modes 1 and 3 use approximately 11.0k and 12.2k tokens per sample, respectively. Mode 2 uses approximately 6.0k, alongside its lower success rate. Mode 5 uses 7,984.50 tokens, compared with 14,859.80 for Mode 4 and 7,403.98 for the unguided baseline. The Mode 4-5 comparison reverses on HotpotQA: Mode 5 uses 10,115.89 tokens versus Mode 4's 6,396.90. Total token use reflects the complete interaction, including the number of steps and generated outputs, and cannot alone establish that a graph representation is more compact.

### Graph Construction Modes

We provide the formulation and implementation details for each of the five PG construction modes. Here, online evolution refers to incremental graph updates between training batches; the graph remains fixed within each episode and during test evaluation.

### Mode 1: Hand-crafted Expert PG (Zero-shot Baseline)

Initialization: A human-engineered directed graph Gexpert = (V, E) containing expert-designed tool nodes, valid transitions, and manually annotated natural language guidance.

Training Strategy: None. Zero-shot execution on the test set.

Evolutionary Mutation: None. The graph structure and guidance remain static. Validation and Safeguard: None.

### Mode 2: Expert PG + Static One-time Update (Offline)

Refinement Mode: static onetime.

Initialization: Initialized with the hand-crafted expert graph Gexpert fromMode 1.

Training Strategy: Static offline execution. The agent runs on the entire training split in a single pass to collect all successful and failed trajectories.

Evolutionary Mutation: Single-pass. The LLM refiner ingests all trajectories in a single large-context window to perform a one-time global offline update to transitions and guidance.

Validation and Safeguard: None. The refined graph is directly committed.

### Mode 3: Expert PG + Online Evolution (Incremental)

Refinement Mode: static incremental.

Initialization: Initialized with the hand-crafted expert graph Gexpert fromMode 1.

Training Strategy: Online incremental batches. The training split is partitioned into sequential strides (S = 100 samples for HotpotQA; S = 20 samples for MultiChallenge).

Evolutionary Mutation: After each stride, the refiner uses the latest failure logs to update nodes, transitions, and local guidance.

Validation and Safeguard: The candidate is evaluated on the validation split. If performance declines, the previous best graph is restored.

### Mode 4: Scratch + Static One-time Build (Offline)

Refinement Mode: scratch onetime.

Initialization: Minimal skeleton graph Gskeleton = (Start → End) with no intermediate nodes or additional transitions. Training Strategy: Static offline execution. The agent runs on the entire training split in a single pass to collect all successful and failed trajectories.

Evolutionary Mutation: Single-pass. The LLM refiner ingests all trajectories in a single large-context window to perform a one-time global offline update to transitions and guidance.

Validation and Safeguard: None. The refined graph is directly committed.

### Mode 5: Scratch + Online Evolution (Incremental)

Refinement Mode: scratch incremental.

Initialization: Minimal skeleton graph Gskeleton = (Start → End) with no intermediate nodes or additional transitions. Training Strategy: Online incremental batches. The training split is partitioned into sequential strides (S = 100 samples for HotpotQA; S = 20 samples for MultiChallenge).

Evolutionary Mutation: After each stride, the refiner uses the latest failure logs to update nodes, transitions, and local guidance.

Validation and Safeguard: The candidate is evaluated on the validation split. If performance declines, the previous best graph is restored.

### Experimental Setup

To ensure reproducibility, we detail the core experimental settings and dataset splits below:

Model Selection and Hyperparameters. All construction-strategy experiments in this appendix, including agent execution and evolutionary refinement, are powered by the frozen Gemini 3.5 Flash model snapshot. To ensure deterministic and reproducible tool-calling reasoning paths, the sampling temperature is set strictly to 0 and top-k sampling is configured with k = 1, enforcing greedy decoding across all model calls. Additionally, to prevent random execution deviations, the API safety filtering thresholds are unified and held constant to eliminate premature trajectory blocking, and the maximum generation length is locked at 2, 048 tokens for the agent and 8, 192 tokens for the evolutionary refiner to guard against truncated reasoning paths.

HotpotQA Environment Setup. The HotpotQA experiments are conducted on a standard multi-hop reasoning split consisting of 1, 000 training samples, 1, 000 validation samples, and 1, 000 test samples. The agent's performance is measured using strict string Exact Match (EM) and word-level overlap F1 score between the agent's generated answer and the ground truth.

MultiChallenge Environment Setup. The MultiChallenge dialogue experiments are conducted on a dataset split consisting of 100 training samples, 100 validation samples, and 56 test samples. Task performance is evaluated via an LLM judge based on Gemini 3.1 Pro, measuring the Overall Success Rate, alongside four core challenge subcategory axes: Inference Memory (IM), Instruction Retention (IR), Reliable Versioned Editing (RVE), and Self Coherence (SC).

<details><summary>Not read aloud in this chapter</summary>

- **2 × table**
  - p29: (no text)
  - p29: (no text)

</details>

---

## [12] E. Round-by-Round Self-Evolution on EnterpriseArena *(appendix)*

*Announced: “Round-by-Round Self-Evolution on EnterpriseArena”*

Table 11 presents the round-by-round metrics of the 10-generation CFO evolution. The delta (Δ) rows track metric changes relative to the active best validation checkpoint. Appendix E.1 examines tool use, and Appendix E.2 discusses candidate screening.

### Computational Efficiency

Beyond task performance, the evolved graphs also help reduce redundant tool use. As detailed in Table 11, the average number of tool invocations per simulation month (Tools/Mo) on the validation split drops from 17.23 in the Baseline to 3.08 in Round 2, stabilizing at 3.13 by Round 8. The baseline agent, operating under zero-shot ReAct, repeatedly queries the environment for cash balances and market metrics within the same turn. The evolved PG guides the agent through these queries once per cycle. This is an 81.8% reduction in tool invocations per simulation month, showing that the evolved graph reduces environment interactions in this experiment. We report tool calls rather than tokens here because the simulation logs record invocation counts but not per-month token consumption.

### Candidate Screening: Three Cases

The evolution loop combines validation checks with structural verification to filter unsuccessful candidates, as illustrated by three cases:

- Performance Rollback (Rounds 3, 4, 6): In Round 3, the mutation engine attempted to lower the cash threshold that triggers fundraising. While this succeeded on specific training seeds, it led to premature dilution and cash shortages on validation seeds, dropping validation survival by 15.0 points and average lifespan by 10.45 months. The gate rejected the candidate and restored the Round 2 checkpoint.

- Execution Constraint Rollback (Round 5): In Round 5, the candidate failed structural verification before simulation, so validation was skipped. The reported validation metrics for this round carry forward the Round 4 results.

- Validation Safeguard (Round 10): In Round 10, training survival was 90.0%, but validation survival fell to 85.0% (-5.0 points) and the mean time-averaged enterprise score on the validation split decreased by $0.184M. The validation gate rejected the mutation because its strong training performance did not carry over to validation, and the loop terminated with the Round 9 graph.

### Step-by-Step Topological Analysis

Figure 5 visualizes the topological changes of the CFO Procedural Graph across key evolutionary stages.

- Initialization (Round 0 - Baseline): The agent has no structural prior (Start → End). Without intermediate procedural guidance, the LLM must infer the action sequence from the running trajectory, leading to high computational cost, redundant tool calls, and missed tasks such as cash forecasts.

- Generation A (Round 1 - Backbone Discovery): The loop suggests the following sequence: Start → Month Start → check cash in bank → cash flow forecast calculation → save note → check market data → Decide Capital. This structure guides the agent to audit cash, project runway, save context, and check market valuation before making a financing decision.

- Generation B (Rounds 2-6 - Working Memory): The loop inserts recall notes immediately after Month Start. By guiding the agent to use save note after the forecast and recall notes at the start of the next month, the Procedural Graph provides durable external working memory that preserves key metrics across months.

- Generation C (Round 7 - Branch Pruning): The loop prunes the pass action node (the "do nothing" action) and its incident edges. The resulting graph retains the branches from Decide Capital to fund raising request and book closing. This topology is adopted in Round 7.

- Generation D (Rounds 8-10 - Administrative Bypass): The edge from fund raising request to book closing is replaced with a direct link to End in Round 8, and this topology is retained through Round 10. Because the environment adapter already advances the month after a fundraising request, the revised graph suggests ending the current procedure and reassessing the new month's state instead of immediately following the request with another month-advancing action.

### Self-Evolution on HotpotQA and MultiChallenge

We also examine self-evolution on HotpotQA (multi-hop reasoning; Appendix E.4.1) and MultiChallenge (complex instruction following; Appendix E.4.2), comparing Mode 3 (evolving from an expert-designed prior) with Mode 5 (evolving from scratch). Figure 6 shows the resulting trajectories.

### HotpotQA: Emergent Simplicity

In Figure 6(a), Mode 5 starts from scratch with an F1 score of 77.59%, below Mode 3. It subsequently surpasses Mode 3 and reaches a peak validation F1 of 83.31% at Generation 10.

These results show that, in our HotpotQA study, evolution from a minimal skeleton can yield more effective guidance than evolution from the hand-designed prior used here. The test-set statistics in Table 9 also show that Mode 5 uses fewer solver steps than the expert-initialized modes. Its total token use remains higher than in Modes 1, 2, and 4, so shorter trajectories do not imply lower token cost.

### MultiChallenge: Prior Correction and Recovery

Figure 6(b) demonstrates the loop's robustness when initialized with a mismatched or poorly designed prior. The hand-designed graph used to initialize Mode 3 was unsuited for the MultiChallenge task, guiding the agent toward incorrect tool loops and yielding an initial validation accuracy of only 54.0%. The self-evolution loop successfully repaired this prior through two phases:

- Pruning: The mutation engine identified and deleted the mismatched transition edges, reducing the graph's edge count from 13 to 10 by Generation 5.

- Restructuring: The loop reconstructed the control flow to align with the task's constraints, raising validation accuracy to 93.9% (ultimately approaching the scratch-built Mode 5 at 94.9%).

These results show that iterative evolution can recover from an unsuitable human-designed initialization.

<details><summary>Not read aloud in this chapter</summary>

- **2 × figure**
  - p34: (no text)
  - p35: (no text)
- **1 × table**
  - p32: (no text)

</details>

---

## [13] F. Additional Execution Cases *(appendix)*

*Announced: “Additional Execution Cases”*

The following cases use Gemini 3.5 Flash and examine stopping decisions on BFCL (Appendix F.1) and graph revision on MultiChallenge (Appendix F.2). Quotations come from solver traces or saved graph attributes, as labeled.

### BFCL: Stopping After a Requested Quote

In test sample 051, both agents receive the same request for an economy-class airfare and retrieve a $220 quote. The PG agent uses a graph built from scratch by a one-time offline update and ends the turn after reporting the price; the baseline continues into payment and booking operations.

The PG run advances to the next user instruction and eventually succeeds; the baseline fails on the first turn after taking actions beyond the requested quote.

### MultiChallenge: Correcting the Response Objective

Validation sample 059 asks for a joke about renewable energy or Sheffield under an earlier instruction to use only passive voice. The environment also exposes the target question, "Did the model consistently use passive sentence construction?" We compare Generation 2 and Generation 3 candidate evaluations fromMode 3; their initial query and full dialogue history are identical.

The saved success indicator changes from 0 to 1. The revised outgoing path and edge advice correspond to a shift from evaluating the dialogue to answering the user.

<details><summary>Not read aloud in this chapter</summary>

- **2 × figure**
  - p36: (no text)
  - p36: (no text)

</details>
