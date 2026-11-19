# Evaluation data

These files are the answer keys used to measure the system. They are separate from the synthetic orders in `data/clean/`, which are the data the agent works on. Every row has a `reviewed` column, set to `no` until a person has read it and agrees.

## Which file tests what

| File | Tests | Used by | Needs the database? |
| --- | --- | --- | --- |
| `retrieval_questions.csv` | Policy search only: does it find the right page for a customer's question, and does it return nothing when the policy has no answer? | Phase 3d | No |
| `router_messages.csv` | The router only: does it pick the right branch for a message, with or without earlier conversation? | Phase 4 and phase 10 | No |
| End-to-end scenarios (not written yet) | The whole agent on a real customer and order: right tools called, right decision, right wording | Phase 10 | Yes |
| `data/clean/*.csv` (synthetic orders) | Not an answer key. It is the data the tools read | Everything | Yes |

End-to-end scenarios get their expected decisions from the tools themselves (the same oracle used in `tests/`), so they are not hand-written answers that could drift from the data.

## retrieval_questions.csv
| Column | Meaning |
| --- | --- |
| `id` | `RQ001`, `RQ002`, ... |
| `question` | The customer's words. Most are not copied from page headings |
| `category` | `exact_wording`, `paraphrase`, `multi_page`, `policy_gap`, `scope_guard`, `unanswerable_related`, `off_topic` |
| `expected` | Where the answer is. `file.md::heading` as written in the page. ` \| ` separates acceptable alternatives (any one counts). ` && ` separates groups that must all be found (multi-page questions). `NONE` means the policy has no answer and search should return nothing useful |
| `forbidden_files` | Pages that must not appear in the results (the out-of-scope pages). Separated by `\|` |
| `notes` | Why the row exists |
| `reviewed` | `no` until a person has checked it |

Categories: `exact_wording` is easy, the control group. `paraphrase` is how real customers write. `multi_page` needs passages from more than one place. `policy_gap` is a question where the page exists but does not give the answer, so the agent must say so. `scope_guard` checks the out-of-scope pages stay hidden. `unanswerable_related` shares words with the policy but is not covered, which is the hardest case for the no-match rule. `off_topic` has nothing to do with the policy.

The expected pages and headings were checked against the 18 policy pages by a script: every one exists. Whether each is the best answer is for a reviewer to judge.

## router_messages.csv
| Column | Meaning |
| --- | --- |
| `id` | `RT001`, ... |
| `message` | What the customer types |
| `context` | `none`, a pending action, or a summary of the previous turn |
| `expected_route` | `order_status`, `policy_question`, `return_or_replace`, `cancel_item`, `human_help`, `out_of_scope`, `clarify` (the router should ask one short question), or `confirm_step` (a pending action takes the message before the router) |
| `category` | `clear`, `ambiguous`, `chat`, `injection`, `follow_up`, `topic_change`, `pending_action` |
| `notes`, `reviewed` | As above |

## How to review
Open the CSV in VS Code or a spreadsheet. For each row ask: would a real customer write this? Is the expected answer the one I would accept? Fix the row, or delete it, and set `reviewed` to `yes`. Rows you disagree with matter most: they show where the policy or our design is unclear.
