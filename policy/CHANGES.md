# Changes from the copied pages

This file lists everything that differs between the 18 copied pages and the files in `policy/`. Nothing else was changed.

## How it was checked

- Each polished file was compared word by word with its original. Eight files are word-for-word identical (`returns-policy`, `replacement-policy`, `returns-and-replacements-faq`, `return-pickup-issues`, `third-party-seller-returns`, `return-a-gift`, `send-a-gift-receipt`, `received-someone-elses-order`). The other ten differ only in the places listed under "Edits to the text" below.
- A structural check passed on all 18 files: one H1 each, no skipped heading levels, equal column counts in every table, no tabs, no trailing spaces, LF endings, and every link and in-page anchor resolves. The anchor check uses its own implementation of GitHub's heading-slug rule, so click through a few on GitHub to confirm.

## Formatting fixes

Counts are from the 18 original files.

| Problem in the copied pages | Count | What was done |
| --- | --- | --- |
| Empty heading markers (`\####`, `\#####`) with the real heading as plain text below | 100 | Replaced with proper `##` and `###` headings. Page titles became `#` |
| Backslash escapes (`\&`, `\[`, `\]`, `\.`, `1\.`), not counting the heading markers above | 70 | Removed. `\*` is kept in the refund tables so the asterisk displays |
| `<br />` tags | 52 | Kept as `<br>` only inside table cells (40 remain). Elsewhere replaced with paragraphs and lists |
| Tab characters and `&#x09;` entities | 9 | Removed |
| Runs of three or more blank lines | 245 | Collapsed to one blank line |
| Empty table rows (`\|\|\|`) | 5 | Removed |
| Curly quotes | 24 | Changed to straight quotes, so text search matches |
| Windows line endings (CRLF) | 18 files | Changed to LF |
| Table of contents as plain text | 11 pages | Kept, with each entry linked to its heading |
| Step sequences lost as separate paragraphs | 3 pages | Restored as numbered lists in `how-to-schedule-a-return.md`, `add-photos-faq.md` and `return-pickup-and-self-ship.md` |
| File names cut off (`Return Pick-up and Self-Ship Guidel.md`, `Return orders placed with a Third-p.md`) or containing spaces and apostrophes | 18 | Renamed to lowercase names with hyphens (see README) |
| References to other pages in this set | 47 | Turned into relative links; the words are unchanged |

Other layout changes:

- **Refund timeline tables.** The original has a two-row header and two bold rows ("Prepaid Orders", "Pay on Delivery Orders") inside the table. These became two labelled tables with a single header row. This is in `refund-policy.md`, `check-refund-status.md`, `damaged-or-defective-item.md`, `about-refunds.md` and `wrong-product-delivered.md`. The original super-header "Refund Time Frame" was dropped, since the two column headings say the same.
- **Blank cells.** The Seller-Fulfilled column is blank in six rows of the three-column tables. Those cells show "—", with an Editor's note pointing to About Refunds, which gives one time for both order types.
- **Intro and contents order** in `refund-policy.md`: the introduction paragraph now comes before the table of contents.
- **Contents entries that pointed at table rows.** In `about-refunds.md`, "Prepaid Order" and "Pay on Delivery Order" now both link to the "Processing Time by Payment Method" heading.
- **Returns policy types table** is unchanged in content. Leading `<br />` tags and stray tabs in its cells were removed.

## Edits to the text

| File | Original | Polished | Reason |
| --- | --- | --- | --- |
| `refund-policy.md` | `upto Rs.100` | `up to Rs.100` | Typo |
| `refund-policy.md` | Cheque-clearing cities in a 4 by 4 grid, read down the columns | One alphabetical list of the same 16 cities | The grid's first row was treated as table headings |
| `refund-policy.md` | `mobile app,Go to Orders` and `website,Go to Orders` | `mobile app, Go to Orders` and `website, Go to Orders` | Missing space |
| `damaged-or-defective-item.md` | `Products is expired.` | `Product is expired.` | Typo |
| `damaged-or-defective-item.md` | `a refund will generated` | `a refund will be generated` | Missing word |
| `damaged-or-defective-item.md` | An empty bullet at the start of the Note under question 3 | Removed | No text in it |
| `wrong-product-delivered.md` | `certain items You can return or request a replacement re delivered in different colours` | `certain items are delivered in different colours` | The sentence was corrupted: a link caption seems to have been pasted into it. **"are" is a reconstruction. Check it against the live page** |
| `wrong-product-delivered.md` | Question 7 repeated the sentence "The refund will be issued to the original payment method used for the order." | Kept once | Exact duplicate |
| `service-centre-replacement-faq.md` | Question 4 heading: `What return reasons come under Service Centre Replacement Policy?Is this policy applicable for new products that are defective?` | `What return reasons come under Service Centre Replacement Policy?` | The second question was pasted in from question 3. The contents list already used the short form |
| `service-centre-replacement-faq.md` | `technician visit.Please note`; `Brand Manufacturer Detail Page .` | Space added; space removed | Spacing |
| `how-to-schedule-a-return.md` | `Amazon shall not responsible` | `Amazon shall not be responsible` | Missing word |
| `how-to-schedule-a-return.md` | A stray line `Your Orders` after question 3 | Removed | Leftover link caption |
| `return-pickup-and-self-ship.md` | `it's original state` | `its original state` | Typo |
| `return-pickup-and-self-ship.md` | Three reasons a pickup fails, listed first, then three explanatory bullets in the same order | Each explanation nested under its reason | The structure was lost in the copy |
| `return-pickup-and-self-ship.md` | `...exceed our standard return cost thresholds` | Full stop added | Missing punctuation |
| `a-to-z-guarantee.md` | A two-column table (delivery issues; item condition issues) with `--->` arrows inside a cell | Two subsections with the column headings as headings, and the arrows as bullets | The table cells were too long to read |
| `a-to-z-guarantee.md` | `At least one of the conditions listed in the below table applies.` | `At least one of the conditions listed below applies.` | The table no longer exists |
| `a-to-z-guarantee.md` | `not received-Wait`, `materially different- Wait` | `not received - Wait`, `materially different - Wait` | Spacing |
| `add-photos-faq.md` | `3.Select`, `4.You`, `5.Once` | A single numbered list 1 to 5, with the reason codes nested under step 2 | List broken by the copy |

## Editor's notes added

Four notes were added, each marked **Editor's note**:

- `refund-policy.md`, `check-refund-status.md`, `damaged-or-defective-item.md`: what "—" means in the refund tables.
- `damaged-or-defective-item.md`: the five bullets under "not covered under the Amazon A-to-Z Guarantee" are kept as grouped in the source, although the last three read as general notes. The note also points out that step 5 says three business days where the A-to-z Guarantee pages say 48 hours.

## Left as they were

These are oddities in Amazon's own text. They were not changed, so that the files stay faithful to the source.

- Spelling and style differences: "Aadhar", "fulfilment" and "fulfillment", "colour" and "color", "centre" and "center", `Rs.100` next to `₹499`.
- "Business Days" and "working days" used without definition in the refund tables.
- Contents entries whose wording differs slightly from the heading they link to (for example "sold by a third-party seller" in `damaged-or-defective-item.md`, where the heading says "fulfilled by"). Each link goes to the right heading.
- "Product doesn't meet expectations" listed as a damaged or defective reason in `damaged-or-defective-item.md`.
- Conflicts between pages (for example 48 hours against three business days). These are listed in the analysis, not edited here.
