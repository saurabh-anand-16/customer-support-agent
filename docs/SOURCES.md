# Sources and credits

This project is an independent demo. It is not affiliated with or endorsed by Amazon.

## Data

The orders, customers and returns in `data/clean/` are **synthetic**. They were generated for this demo. The product list they refer to comes from the Kaggle "Amazon Sales Dataset" (kept untouched in `data/raw/amazon.csv`). Dataset author and Kaggle link: **link and author to be added**.

That dataset is licensed under CC BY-NC-SA 4.0 (https://creativecommons.org/licenses/by-nc-sa/4.0/). The data derived from it in `data/clean/` is shared under the same licence, and this project is non-commercial.

What was changed (see `scripts/01_clean_products.py` to `scripts/04_build_db.py`):
- Prices, percentages and counts were converted from text to numbers, repeated products were reduced to one row each, and the review columns were dropped.
- Each product category was given one of Amazon's return policy types. This mapping is our inference, not Amazon's.
- Customers, orders, delivery dates and returns were generated, with fixed random seeds.

## Policy text

The files in `policy/` are copies of Amazon.in Returns Centre help pages, copied on 2026-11-17 (the `copied_on` value of every row in `data/clean/policy_chunks.csv`). Every place where the text differs from the copied page is listed in `policy/CHANGES.md`.

Starting page: https://www.amazon.in/gp/help/customer/display.html?nodeId=G202111910

Pages used, with the file that holds each one. The link of each page has the form `https://www.amazon.in/gp/help/customer/display.html?nodeId=<node id>`.

| Page | Node id | File |
| --- | --- | --- |
| Add Photos: Frequently Asked Questions | GW425KSGJQ97Q8SZ | `add-photos-faq.md` |
| How to Schedule a Return | GD4HZNRCW2JW4CMC | `how-to-schedule-a-return.md` |
| Return orders placed with a Third-party (Marketplace) seller | Tidow893GJOqa30CNu | `third-party-seller-returns.md` |
| Amazon.in Service Centre Replacement Policy - FAQ | TlK1fdW161vrTDsknx | `service-centre-replacement-faq.md` |
| Wrong Product Delivered | TWc5BVeaQkU6jODP1i | `wrong-product-delivered.md` |
| Amazon.in Refund Policy | G202111770 | `refund-policy.md` |
| Check Status of Your Refund | GMP8PC8KBY5FCPM2 | `check-refund-status.md` |
| About Refunds | G5PG8UG3E7SHGKA6 | `about-refunds.md` |
| Return a Gift | GMTDJ6XPUMN7NWNB | `return-a-gift.md` |
| Send a Gift Receipt | GX93M9BCRC8DGGVQ | `send-a-gift-receipt.md` |
| Return Pick-up and Self-Ship Guidelines | G202111950 | `return-pickup-and-self-ship.md` |
| Returns and Replacements - FAQ | G202115040 | `returns-and-replacements-faq.md` |
| Amazon.in Returns Policy | G202111910 | `returns-policy.md` |
| Amazon.in Replacement Policy | G202111750 | `replacement-policy.md` |
| Return Pick-up Issues | TAgXDdtqErF6Zz6HnQ | `return-pickup-issues.md` |

Not used: "Returns and Refunds-Videos" (GTBSFH734SDPD4Z7). There is no file for it in `policy/`.

Three more pages are in `policy/`; their node ids are to be added:

| Page | Node id | File |
| --- | --- | --- |
| What is the A-to-z Guarantee? | to be added | `a-to-z-guarantee.md` |
| Damaged or Defective Item | to be added | `damaged-or-defective-item.md` |
| Received Someone Else's order | to be added | `received-someone-elses-order.md` |

## Disclaimer

This is an independent demo. It is not affiliated with or endorsed by Amazon. Amazon and Amazon.in are trademarks of their owners. The policy text belongs to its owner and is used here for a non-commercial demonstration.
