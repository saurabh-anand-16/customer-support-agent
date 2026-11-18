"""
01_clean_products.py - turn the raw Kaggle CSV into a clean `products` table.

What is wrong with the raw file (all checked against the actual data):
  * 1,465 rows but only 1,351 distinct product_id. The extra rows are the same
    product repeated with different review text, image links or rating counts.
  * Prices look like "₹1,099" and discounts like "64%": text, not numbers.
  * One product (B08L12N5H1) has rating "|", which is not a number.
  * Two products have no rating_count.
  * Each row carries ~7 reviews glued together with commas in user_id, user_name,
    review_id, review_title and review_content. The returns agent does not need
    them, so they are dropped. (If you want reviews later, split them in a
    separate script, not here.)

Output: data/clean/products_base.csv   (policy columns are added by script 02)
Run:    python scripts/01_clean_products.py
"""
import pandas as pd

from config import CLEAN_DIR, RAW_CSV


def money_to_float(series: pd.Series) -> pd.Series:
    """'₹1,099' -> 1099.0  (remove the rupee sign and the thousands commas)."""
    return series.str.replace("₹", "", regex=False).str.replace(",", "", regex=False).astype(float)


def main() -> None:
    # dtype=str: read everything as text first, so pandas does not guess types and
    # silently turn "|" or "24,269" into something wrong. We convert on purpose below.
    raw = pd.read_csv(RAW_CSV, dtype=str)
    print(f"raw rows: {len(raw)}   distinct product_id: {raw.product_id.nunique()}")

    df = raw.copy()

    # ---- numbers --------------------------------------------------------------
    df["discounted_price_inr"] = money_to_float(df["discounted_price"])
    df["actual_price_inr"] = money_to_float(df["actual_price"])
    df["discount_pct"] = df["discount_percentage"].str.rstrip("%").astype(float)

    # errors="coerce" turns anything that is not a number (the "|") into NaN (missing)
    # instead of crashing. We count them so the cleanup is visible, not silent.
    df["rating"] = pd.to_numeric(df["rating"], errors="coerce")
    print(f"ratings that were not numbers (set to missing): {df['rating'].isna().sum()}")

    # "24,269" -> 24269. Int64 (capital I) is pandas' integer type that allows missing values.
    df["rating_count"] = pd.to_numeric(df["rating_count"].str.replace(",", "", regex=False), errors="coerce").astype("Int64")

    # ---- remove repeated products ---------------------------------------------
    # Keep the copy with the largest rating_count: it is the most complete record.
    # sort_values puts missing counts last (na_position), drop_duplicates keeps the first.
    df = df.sort_values("rating_count", ascending=False, na_position="last")
    n_before = len(df)
    price_conflicts = df.groupby("product_id")["discounted_price_inr"].nunique()
    print(f"products whose repeated rows disagree on price: {(price_conflicts > 1).sum()} (first/most-rated copy kept)")
    df = df.drop_duplicates(subset="product_id", keep="first").sort_index()
    print(f"dropped {n_before - len(df)} repeated rows -> {len(df)} products")

    # ---- category helpers -----------------------------------------------------
    # The category is one string "Electronics|Mobiles&Accessories|Smartphones&BasicMobiles|Smartphones".
    # We keep the full path (script 02 maps on it) and add the first and last part for convenience.
    parts = df["category"].str.split("|")
    df["category_path"] = df["category"]
    df["category_top"] = parts.str[0]
    df["category_leaf"] = parts.str[-1]

    out = df[[
        "product_id", "product_name", "category_path", "category_top", "category_leaf",
        "discounted_price_inr", "actual_price_inr", "discount_pct",
        "rating", "rating_count", "about_product", "img_link", "product_link",
    ]]

    # ---- sanity checks: stop loudly if the data is not what we assume ----------
    assert out["product_id"].is_unique, "product_id must be unique"
    assert (out["discounted_price_inr"] > 0).all(), "prices must be positive"
    assert (out["discounted_price_inr"] <= out["actual_price_inr"]).all(), "sale price above list price"
    assert out["category_path"].notna().all()

    CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(CLEAN_DIR / "products_base.csv", index=False)
    print(f"wrote {CLEAN_DIR / 'products_base.csv'}  ({len(out)} rows)")


if __name__ == "__main__":
    main()
