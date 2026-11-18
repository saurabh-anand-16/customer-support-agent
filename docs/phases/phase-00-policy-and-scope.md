# Phase 0: policy pages and scope decisions

**Status:** Done

## Goal
Collect the Amazon.in policy text the agent must stay faithful to, and fix the scope before building anything.

## Files
| File | Action | Why |
| --- | --- | --- |
| `policy/*.md` (18 pages) | Created | Amazon.in returns, refunds and replacement pages, converted to Markdown |
| `policy/README.md` | Created | Index of pages, with the copy date 2026-11-17 |
| `policy/CHANGES.md` | Created | Every place where the text differs from the copied page |

## What it does
The 18 pages are the single source of policy wording. Eight are word-for-word the copied text; ten differ only by the edits logged in `CHANGES.md`.

**Scope decisions (ours):**
- Amazon-fulfilled orders only. Seller-fulfilled orders, the A-to-Z Guarantee, gifts and international orders are out of scope. Their pages are kept for reference.
- "Today" is fixed at 2026-11-17 so every answer is reproducible.
- The delivery date counts as day 1.
- Where pages conflict, use the default reading. The 48 hours versus three business days conflict only affects seller-fulfilled orders, so it drops out.
- The repository stays private, because the policy text belongs to Amazon.

## How it is checked
A word-comparison script confirmed the eight word-identical pages and listed the differences in the other ten. That script is not in the repo.

## Known gaps and open questions
- Source URLs in `policy/README.md` are blank.
- One word ("are") in `wrong-product-delivered.md` is a reconstruction and should be checked against the live page.
- Amazon's pages do not say which product category gets which policy type, how days are counted, the return processing fee amount, or the account-history threshold. These are listed in the main README.

## Done when
All 18 pages are in `policy/` with logged changes. Yes.
