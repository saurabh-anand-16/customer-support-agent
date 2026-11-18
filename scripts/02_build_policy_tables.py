"""
02_build_policy_tables.py - turn the policy pages into data tables.

It writes six files into data/clean/:
  return_rules.csv         one row per policy type + window (what each type allows)
  category_rules.csv       the mapping rules themselves, in the order they are tried (INFERRED, review it)
  category_policy_map.csv  every product category path -> a policy type   (INFERRED, review it)
  products.csv             products_base.csv + the policy_code / window of each product
  refund_timelines.csv     how long a refund takes, per payment method
  policy_facts.csv         single numbers and yes/no rules (13 days, 24 hours, Rs.100 ...)

IMPORTANT - what is Amazon's and what is ours:
  * return_rules, refund_timelines and policy_facts are transcribed from the polished
    policy pages. Each row names its source file.
  * category_policy_map is NOT from Amazon. Amazon's pages describe six policy types but
    never say which product category gets which type: that label is printed on each product
    page, and the Kaggle file does not contain it. The mapping below is our best guess from
    the product kind. Every row has a `confidence` and a `basis` so you can review it.

Run:  python scripts/02_build_policy_tables.py     (after script 01)
"""
import pandas as pd

from config import CLEAN_DIR

# ======================================================================================
# 1. RETURN RULES
# ======================================================================================
# Amazon writes windows as "7/10 Days" or "10/30 Days": the number is chosen per product.
# We turn each "7/10" family into two rows (7 and 10) so every product gets one exact window.
#
# Columns
#   policy_code                short id used as a foreign key everywhere
#   policy_label               the name as shown on Amazon product pages
#   window_days                days counted from delivery (delivery day = day 1)
#   defect_report_window_days  how long the customer has to report a damaged/defective/wrong item
#   buyer_remorse_return       True if the customer may return just because they changed their mind
#   exchange_size_colour       True if exchange for another size/colour is offered
#   resolution_damaged_wrong   what the policy promises for damaged / different / wrong items
#   resolution_defective       what the policy says for defective items
#   resolutions_*              the same promises as codes (see RESOLUTIONS below)
#   source_file                where in the policy folder this comes from
RULES_SRC = "returns-policy.md (Return Policy Types table)"

_SC_DEFECT = ("Customer contacts the brand's service centre. Amazon may arrange a technician visit "
              "for troubleshooting only. Final resolution (repair, refund, replacement) is by the brand.")
_BRAND_DEFECT = ("Brand gives on-call support, then a technician inspects at the customer's location. "
                 "Brand repairs or replaces; Amazon gives the resolution based on the technician's report.")
_REPL_DEFECT = ("Free replacement. For a few items Amazon may schedule a technician visit; "
                "resolution follows the technician's report.")
_REPL_DAMAGE = "Free replacement."
_RET_DEFECT = "Free return or replacement."
_NONRET = "Full refund or free replacement, as applicable."


def rule(code, label, window, defect_window, remorse, exchange, damaged, defective):
    return dict(policy_code=code, policy_label=label, window_days=window,
                defect_report_window_days=defect_window, buyer_remorse_return=remorse,
                exchange_size_colour=exchange, resolution_damaged_wrong=damaged,
                resolution_defective=defective, source_file=RULES_SRC)


RETURN_RULES = [
    rule("SC_REPL_7",   "7 Days Service Centre Replacement",  7,  7,  False, False, _REPL_DAMAGE, _SC_DEFECT),
    rule("SC_REPL_10",  "10 Days Service Centre Replacement", 10, 10, False, False, _REPL_DAMAGE, _SC_DEFECT),
    rule("BRAND_REPL_7",  "7 Days Replacement by Brand",      7,  7,  False, False, _REPL_DAMAGE, _BRAND_DEFECT),
    rule("BRAND_REPL_10", "10 Days Replacement by Brand",     10, 10, False, False, _REPL_DAMAGE, _BRAND_DEFECT),
    rule("REPL_7",      "7 Days Replacement",                 7,  7,  False, False, _REPL_DAMAGE, _REPL_DEFECT),
    rule("REPL_10",     "10 Days Replacement",                10, 10, False, False, _REPL_DAMAGE, _REPL_DEFECT),
    rule("RET_10",      "10 Days Returnable",                 10, 10, True,  False, _RET_DEFECT,  _RET_DEFECT),
    rule("RET_30",      "30 Days Returnable",                 30, 30, True,  False, _RET_DEFECT,  _RET_DEFECT),
    rule("FREE_RET_EXCH_10", "10 Day Free Returns & Exchange", 10, 10, True, True,  "Return, or exchange for another size/colour, or full refund.",
         "Return, or exchange for another size/colour, or full refund."),
    # Non-returnable: no window for changing your mind (window 0), but damaged/defective/wrong
    # items can still be reported within 5 days of delivery (Returns Policy, Note under the General Policy).
    rule("NON_RETURNABLE", "Non-Returnable",                  0,  5,  False, False, _NONRET, _NONRET),
]

# Machine-readable version of the resolution text above, so the tools never have to parse
# sentences. Codes:  refund | replacement | exchange | brand_service
#   brand_service = guidance only: the customer is sent to the brand's service centre or
#                   technician, and NO return record is created by us.
# Three columns per policy family: damaged/wrong/not-as-described items, defective items,
# and change-of-mind ("changed_mind"). The value 'none' means the policy does not allow it.
RESOLUTIONS = {
    #                   damaged_wrong        defective              changed_mind
    "SC_REPL":         ("replacement",       "brand_service",       "none"),
    "BRAND_REPL":      ("replacement",       "brand_service",       "none"),
    "REPL":            ("replacement",       "replacement",         "none"),
    "RET":             ("refund|replacement", "refund|replacement", "refund"),
    "FREE_RET_EXCH":   ("refund|exchange",   "refund|exchange",     "refund|exchange"),
    "NON_RETURNABLE":  ("refund|replacement", "refund|replacement", "none"),
}
for _r in RETURN_RULES:
    _code = _r["policy_code"]
    _family = _code.rsplit("_", 1)[0] if _code[-1].isdigit() else _code
    (_r["resolutions_damaged_wrong"], _r["resolutions_defective"],
     _r["resolutions_changed_mind"]) = RESOLUTIONS[_family]

# ======================================================================================
# 2. CATEGORY -> POLICY MAPPING (our inference)
# ======================================================================================
# How it works: a category path looks like  A|B|C|D  . We split it into segments and test
# the rules IN ORDER. The first rule that shares a segment with the path wins.
# Order matters: specific "accessory/non-electronic" and "consumable" rules sit before
# the broad appliance rules, so a "Vacuum bag" is not mistaken for a vacuum cleaner.
#
# confidence:  high   = the product kind is named in the General Returns Policy (item 2 lists
#                       smartphone, tablet, laptop, television, air conditioner... for technician visits)
#              medium = reasoned from the kind of product (electronic accessory, small appliance...)
#              low    = consumables and the catch-all fallback: please review these first
CATEGORY_RULES = [
    # (rule_id, segments that trigger it, policy_code, confidence, basis)
    ("R1", {"Inks,Toners&Cartridges", "BottledInk", "Film", "Paints", "WaterCartridges", "VacuumBags"},
     "NON_RETURNABLE", "low", "Consumable / used-up item; treated as non-returnable by analogy"),

    ("R2a", {"Smartphones&BasicMobiles"},
     "SC_REPL_7", "high", "Smartphones are named in General Returns Policy item 2 (brand/technician support)"),
    ("R2b", {"SmartWatches", "VideoCameras", "SecurityCameras", "Headphones"},
     "SC_REPL_7", "medium", "Branded electronics with a manufacturer service network"),

    ("R3a", {"Televisions", "Laptops", "Tablets", "AirConditioners"},
     "BRAND_REPL_10", "high", "Named in General Returns Policy item 2 (technician visit)"),
    ("R3b", {"Monitors", "Printers", "Projectors", "StorageWaterHeaters", "InstantWaterHeaters",
             "WaterFilters&Purifiers", "HEPAAirPurifiers", "RoboticVacuums", "Sewing&EmbroideryMachines"},
     "BRAND_REPL_10", "medium", "Larger electronics/appliances that usually need brand technician inspection"),

    # Non-electronic accessories and small plain goods: change-of-mind returns allowed.
    ("R4", {"Parts&Accessories", "SmallApplianceParts&Accessories", "StandMixerAccessories",
            "WaterPurifierAccessories", "VacuumAccessories", "MeasuringSpoons", "Kitchen&Dining",
            "IroningAccessories", "LaundryOrganization", "HomeStorage&Organization", "CraftMaterials",
            "OfficePaperProducts", "Arts&Crafts", "Cases", "Cases&Covers", "BasicCases", "ScreenProtectors",
            "Stands", "Mounts", "TVMounts,Stands&Turntables", "Lapdesks", "NotebookComputerStands",
            "MousePads", "DustCovers", "LaptopSleeves&Slipcases", "HardDiskBags", "Caddies", "3DGlasses",
            "Décor", "Earpads", "BackgroundSupports", "Tripods&Monopods", "Tripods", "SelfieSticks",
            "CleaningKits", "CableConnectionProtectors", "CoolingPads", "CameraPrivacyCovers",
            "CordManagement", "AutomobileAccessories"},
     "RET_10", "medium", "Non-electronic accessory or plain goods"),

    ("R5", {"Kitchen&HomeAppliances", "Heating,Cooling&AirQuality", "SatelliteReceivers",
            "AVReceivers&Amplifiers", "DigitalBathroomScales", "AirPurifiers&Ionizers"},
     "REPL_10", "medium", "Powered home/kitchen appliance"),

    ("R6", {"Cables", "Cables&Adapters", "Adapters", "Chargers", "USBHubs", "NetworkingDevices", "Memory",
            "MemoryCards", "ExternalDevices&DataStorage", "InternalHardDrives", "InternalSolidStateDrives",
            "Components", "Keyboards,Mice&InputDevices", "PCGamingPeripherals", "Webcams", "PCSpeakers",
            "PCMicrophones", "PCHeadsets", "Microphones", "HomeAudio", "RemoteControls",
            "UninterruptedPowerSupplies", "PowerAccessories", "GeneralPurposeBatteries&BatteryChargers",
            "Batteries&Chargers", "LaptopChargers&PowerSupplies", "Electrical", "StylusPens", "USBGadgets",
            "Flashes", "SelfieLights", "Calculators", "Headphones,Earbuds&Accessories"},
     "REPL_7", "medium", "Small electronic accessory or component"),
]
FALLBACK = ("R9", "RET_10", "low", "No rule matched: default 10 Days Returnable. Review.")


def map_category(path: str):
    segments = set(path.split("|"))
    for rule_id, trigger, code, conf, basis in CATEGORY_RULES:
        if segments & trigger:
            return rule_id, code, conf, basis
    return FALLBACK


# ======================================================================================
# 3. REFUND TIMELINES  (Amazon-delivered column of the refund tables)
# ======================================================================================
# The five refund pages carry the same table (checked). Units are kept exactly as Amazon
# wrote them: "Business Days" and "working days" both appear and neither is defined.
REFUND_SRC = "refund-policy.md / about-refunds.md"
REFUND_TIMELINES = [
    # order_type, refund_method, value, unit, upper_bound ("up to"), text in the source
    ("prepaid", "amazon_pay_balance",   4, "hours",         False, "4 hours"),
    ("prepaid", "credit_debit_card",    5, "business_days", False, "5 Business Days"),
    ("prepaid", "net_banking",          5, "business_days", False, "5 Business Days"),
    ("prepaid", "upi",                  5, "business_days", False, "5 Business Days"),
    ("prepaid", "amazon_pay_later",     5, "working_days",  True,  "up to 5 working days"),
    ("prepaid", "amazon_voucher",       4, "working_days",  True,  "up to 4 working days"),
    ("pay_on_delivery", "neft_bank_account",  5,  "business_days", False, "5 Business Days"),
    ("pay_on_delivery", "amazon_pay_balance", 4,  "hours",         False, "4 hours"),
    ("pay_on_delivery", "paper_cheque",       10, "business_days", True,  "Up to 10 business days"),
]

# ======================================================================================
# 4. POLICY FACTS: single values the agent must quote correctly
# ======================================================================================
FACTS = [
    # key, value, unit, source_file, note
    ("refund_initiated_when", "Amazon receives the returned package", "", "refund-policy.md", ""),
    ("refund_processed_within_days_of_pickup", "13", "days", "refund-policy.md; about-refunds.md",
     "After 13 days with no update, customer should contact Customer Service"),
    ("cancelled_or_refused_order_refund_hours", "24", "hours", "check-refund-status.md",
     "Refund initiated to the original payment method; then the method timeline applies"),
    ("non_returnable_defect_report_days", "5", "days", "returns-policy.md", "Damaged/defective non-returnable item"),
    ("return_shipping_refund_cap_inr", "100", "INR", "refund-policy.md",
     "Return shipping up to Rs.100 refunded for Fulfilled by Amazon / Prime Eligible items, to Amazon Pay Balance"),
    ("replacement_shipping_fee_inr", "40", "INR", "returns-and-replacements-faq.md",
     "Applies if the original order was below Rs.499; non-refundable"),
    ("free_shipping_threshold_inr", "499", "INR", "returns-and-replacements-faq.md", ""),
    ("replacement_needs_same_item_in_stock", "true", "", "returns-policy.md",
     "If not in stock, a refund is issued instead of a replacement"),
    ("original_condition_required", "true", "", "returns-policy.md",
     "Brand box, MRP tags, manual, warranty cards and all accessories"),
    ("eligibility_depends_on_account_history", "true", "", "returns-policy.md",
     "No threshold is stated anywhere in the pages"),
    ("return_processing_fee_inr", "", "INR", "returns-policy.md",
     "Fee exists for excessive returns; AMOUNT NOT STATED in the pages"),
    ("delivery_day_counts_as_day_one", "true", "", "project decision",
     "Not from Amazon (its pages do not say). Last eligible day = delivery date + window - 1"),
    # Staff-approval thresholds: our own design choices for the human-in-the-loop step.
    # Amazon's pages state none of these.
    ("approval_value_limit_inr", "10000", "INR", "project decision",
     "A return/replacement for an item line above this value needs staff approval"),
    ("repeat_returner_review_threshold", "5", "returns", "project decision",
     "More than this many returns in the last 12 months needs staff review"),
    ("exceptions_always_reviewed", "true", "", "project decision",
     "Requests outside the window are never decided by the agent; they go to a reviewer"),
    # Cancellation: Amazon's pages say refunds apply to cancelled orders and give the 24-hour
    # timeline (see cancelled_or_refused_order_refund_hours) but never say WHEN an order can be
    # cancelled. This rule is ours. '|' separates statuses if more are ever allowed.
    ("cancellable_item_status", "processing", "", "project decision",
     "Only items still being processed can be cancelled. Shipped items are returned after delivery"),
]


def main() -> None:
    rules = pd.DataFrame(RETURN_RULES)
    products = pd.read_csv(CLEAN_DIR / "products_base.csv")

    # ---- category map ----------------------------------------------------------
    counts = products["category_path"].value_counts()
    rows = []
    for path, n in counts.items():
        rule_id, code, conf, basis = map_category(path)
        rows.append(dict(category_path=path, n_products=int(n), policy_code=code,
                         confidence=conf, rule_id=rule_id, basis=basis))
    cmap = pd.DataFrame(rows).sort_values(["policy_code", "category_path"])

    # every policy_code we use must exist in return_rules (stops typos)
    assert set(cmap["policy_code"]) <= set(rules["policy_code"])

    # ---- attach the policy to every product ------------------------------------
    products = products.merge(cmap[["category_path", "policy_code"]], on="category_path", how="left")
    products = products.merge(rules[["policy_code", "window_days", "defect_report_window_days"]],
                              on="policy_code", how="left")
    assert products["policy_code"].notna().all(), "a product has no policy"
    assert len(products) == products["product_id"].nunique()

    # ---- the rules themselves, as a table you can read and review -----------------
    # Generated from CATEGORY_RULES above, so this file can never drift from what the code does.
    per_rule = cmap.groupby("rule_id").agg(n_categories=("category_path", "count"),
                                           n_products=("n_products", "sum"))
    rule_rows = [dict(priority=i, rule_id=rid, matches_any_segment="|".join(sorted(trigger)),
                      policy_code=code, confidence=conf, basis=basis)
                 for i, (rid, trigger, code, conf, basis) in enumerate(CATEGORY_RULES, start=1)]
    rule_rows.append(dict(priority=len(rule_rows) + 1, rule_id=FALLBACK[0], matches_any_segment="(anything not matched above)",
                          policy_code=FALLBACK[1], confidence=FALLBACK[2], basis=FALLBACK[3]))
    category_rules = pd.DataFrame(rule_rows).merge(per_rule, on="rule_id", how="left").fillna({"n_categories": 0, "n_products": 0})
    category_rules[["n_categories", "n_products"]] = category_rules[["n_categories", "n_products"]].astype(int)
    assert category_rules["n_products"].sum() == len(products), "every product must be covered by exactly one rule"

    # ---- write -----------------------------------------------------------------
    category_rules.to_csv(CLEAN_DIR / "category_rules.csv", index=False)
    rules.to_csv(CLEAN_DIR / "return_rules.csv", index=False)
    cmap.to_csv(CLEAN_DIR / "category_policy_map.csv", index=False)
    products.to_csv(CLEAN_DIR / "products.csv", index=False)
    pd.DataFrame(REFUND_TIMELINES, columns=["order_type", "refund_method", "time_value", "time_unit",
                                            "is_upper_bound", "source_text"]
                 ).assign(source_file=REFUND_SRC).to_csv(CLEAN_DIR / "refund_timelines.csv", index=False)
    pd.DataFrame(FACTS, columns=["fact_key", "fact_value", "unit", "source_file", "note"]
                 ).to_csv(CLEAN_DIR / "policy_facts.csv", index=False)

    # ---- report ----------------------------------------------------------------
    print("products per policy:")
    print(products["policy_code"].value_counts().to_string())
    print("\ncategory paths per confidence:")
    print(cmap["confidence"].value_counts().to_string())
    low = cmap[cmap.confidence == "low"]
    print(f"\n{len(low)} low-confidence categories ({int(low.n_products.sum())} products) -> review these first")


if __name__ == "__main__":
    main()
