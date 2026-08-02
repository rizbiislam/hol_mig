# Holding Tax Data Migrator v2

Rule-driven migration tool, built directly from
`Instruction_for_master_data_rtf.doc` — not a generic column-renamer.
Ships pre-loaded with the `HT_TaxAssessment_Master` schema (95 columns)
and every rule the SOP specifies, so you configure the ~7 things that
actually need per-project decisions instead of re-deriving 95 rules
from scratch each time.

## Run it

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Architecture

- `rule_engine.py` — pure Python, no Streamlit. Defines the `Rule`
  dataclass and `apply_rules()`. Kept separate from the UI so it's
  testable on its own and reusable from a CLI script if you ever need
  batch/headless runs instead of the interactive tool.
- `default_schema.py` — the 95-column `HT_TaxAssessment_Master` schema
  and `sop_default_rules()`, which encodes every rule from the
  instruction document as a `Rule` object, with the SOP's own wording
  preserved in each rule's `note` field so you can see *why* a rule
  exists, not just what it does.
- `app.py` — the Streamlit UI: 5 tabs (source, rules, lookup
  resolution, generate & validate, save/load config).

## Status as of the Durgapur reference files (Ward/Street/PropertyType lookups)

Confirmed and pre-wired:
- **ZoneInfoId = 145** for Durgapur — cross-checked from both `Durgapur-Ward.xlsx`
  and `Durgapur-Street.xlsx` (consistent across every row of both). Pre-filled
  in the default rules; just verify it's still current before shipping.
- `WardId` and `StreetId` are both now `lookup_id` rules (StreetId was
  previously `manual_external` — see below for why that changed), with the
  actual reference tables bundled in `reference_data/`.
- `PropertyType`, `PropertyUse`, `TaxPayerType` lookup tables bundled
  (`reference_data/PropertyType_TaxPayerType_PropertyUse.xlsx`, 3 sheets —
  the lookup-upload UI in Tab 3 now makes you pick the sheet explicitly
  when a file has more than one, since silently defaulting to sheet 1
  three times in a row would have been a real footgun here).

New problems this surfaced, handled rather than ignored:
- **`Ward No.` in the source register is genuinely inconsistent**: mixes
  English digits (`1`, `8`), Bengali digits (`০৪`, `০৯`, `০২`, `৩`, `০৬`,
  `০৭`, `০১`), and at least one malformed hybrid (`০6`). Added a
  Bengali-digit normalization toggle in Tab 3's auto-suggest — tested
  against all 12 real observed spellings from your source file, resolves
  every one correctly including the hybrid.
- **`StreetId` reclassified from `manual_external` to `lookup_id`**: the
  SOP describes a manual PRM_Street DB import/filter process, but
  `Durgapur-Street.xlsx` (22 rows, already filtered to `ZoneInfoId=145`)
  is exactly that process's output — so it's already done. Two caveats
  kept in the rule's note: (1) the source register's own `Street` column
  is 0% filled across all 4508 rows, so there's currently nothing to map
  from regardless of lookup readiness; (2) the street name 'ঝুপদোয়ার'
  appears under two different Ids in the lookup table (duplicate name,
  different sub-areas) — a name-only match would be ambiguous for that
  one street if street data does show up later.
- **`IUser` discrepancy, flagged not guessed**: the SOP describes IUser
  as a fixed 3-digit pourashava code (example: Chatak=360). But the
  actual `IUser` values in the Durgapur reference tables are `1` (Ward)
  and `4525`/`2698` (Street, varying per row) — these look like
  individual user-account login IDs recorded per database edit, not a
  stable pourashava constant. Left blank rather than guessing; ask
  whoever owns the SOP/live system which number is actually correct.
- One data point worth knowing: I checked whether the packed "Property
  Use" composite strings (e.g. `১১-০/ ০৩ পাকা, ০৯-০/ঝুপদোয়ার`) contain
  embedded street names from the Durgapur street list — confirmed on at
  least one row (`ঝুপদোয়ার` appears both in that composite string and
  in the Street reference table), but it's not a reliable general
  pattern (only 1 of 3158 populated Property Use values matched). Doesn't
  solve the composite-parsing problem, but worth knowing if you tackle
  that column later.

Still blocking a real run:
- `ReassessmentYear` (fiscal year Id) — no reference file for this yet.
- `Id` starting value — needs the live DB's current max Id.
- `IUser` — see discrepancy above.
- `BankAccountlnfold` — still genuinely `manual_external`, no data provided yet.

## ClientNo (correction applied)

Added a new rule type, `client_id`, specifically for `ClientNo` =
`ward-street-holding` (e.g. `01-01-01`), per explicit correction:
- All digits forced to English (source mixes Bengali/English/malformed
  hybrids — tested against every real spelling found in the source file,
  including the `০6` hybrid).
- Each part zero-padded to a **minimum** of 2 digits — `zfill`, so a
  3-digit holding number like `150` is left as `150`, not truncated.
- Each of the three parts (ward/street/holding) is independently
  configurable as either `source_column` (read straight from a source
  column, digit-normalized) or `lookup_code` (translate an
  already-resolved FK Id — e.g. `WardId` — back to its human Code via an
  uploaded 2-column Id→Code table). This flexibility is intentional:
  per your note, format varies by pourashava, so the tool shouldn't
  hardcode Durgapur's specific column layout.
- Currently **street part exports blank** for all rows: the source
  register's own `Street` column is 0% filled, so there's nothing to
  build it from yet, independent of anything else being ready.
- Caught and fixed a real bug during testing: a missing (NaN) street
  value was producing literal `"01-nan-05"` instead of a clean blank —
  pandas NaN wasn't being checked correctly. Fixed and re-verified.

## Full 4508-row dry run (not a sample — the actual file)

Ran the whole tool against the full source file to see what really
happens at scale, not just spot-checks:

- **`WardId` resolved 100%** (4508/4508, zero manual fallback needed) —
  the digit-normalize toggle from the previous round handled every one
  of the 12 real spellings automatically. Strong result, worth trusting.
- **Found and fixed a real inconsistency**: `HoldingNo` was being copied
  verbatim, so the target field still contained raw Bengali digits
  (`০২`, `০৩`...) even though `ClientNo`'s internal digit-handling was
  already correct. Since the correction was "all numbers should be
  English," that's now fixed too — added a `convert_bn_digits` option
  (digit-script translation only, does NOT strip leading zeros or
  reformat, unlike the more aggressive `normalize_digits` used for
  Ward/Street codes) and enabled it by default on `HoldingNo`,
  `PreviousHoldingNo`, `PreviousClientNo`, `MobileNumber`, `NationalID`,
  and the opening-arrear fields. Also merged digit translation directly
  into `numeric_clean` itself, since a numeric-cleaned field has no
  legitimate reason to keep Bengali digits — one less toggle to forget.
- Re-verified: `HoldingNo` now outputs `02`, `03`, `04`... (English
  digits, original leading-zero formatting preserved).


## Composite Property Use column — investigated, not yet built

You described a bracketed format (`(পাকা, ঝুপদোয়াল)` etc.) for decoding
the packed "Property Use" column. I tested that exact pattern against
the real 3158 populated rows in the source file: **only 1 row matches
it**. The other 3157 follow a different, more variable structure —
something like `code-sub/count type, code-sub/text` (majority),
`code-sub/count type` (no comma), and `type count রুম` (no codes at
all). Building a parser off the bracket examples would silently do
nothing on ~99.97% of real rows, so I didn't build it — I don't want to
ship something that looks like it works and doesn't. Real distinct
values are printed in the investigation script if you want to see them;
the two-part numeric prefixes (`১১-০`, `০৯-০`, `১২-০`...) don't map
cleanly onto any Id range in the PropertyType/PropertyUse lookup tables
provided so far, so I'm not guessing at their meaning. Also worth
noting: whatever scheme resolves this, it likely feeds `PropertyTypeId`
(the phrases are construction-material terms), not `PropertyUseId` —
the source register's own `Property Type` column is 100% empty, which
looks like a data-entry mislabeling, not a design intent to leave it out.


## Rule types (this is the actual vocabulary from the SOP, see
docstring at the top of `rule_engine.py` for full detail)

`skip`, `constant`, `copy`, `copy_default`, `equals_column`, `batch_id`,
`lookup_id`, `generated_sequence`, `sms_account_number`, `manual_external`.

## What's pre-configured out of the box vs. what you still need to do

**Already wired from the SOP (no action needed unless you disagree with
the default):**
- All fixed constants (AssessmentType=1, ApproveStatus=2, dates, etc.)
- `ParentId` forced blank (SOP: a 0 here breaks front-end display —
  this is enforced, not just documented)
- `AnnualValuation`=`FinalValuation`, `TaxOnAnnualValuation`=`TaxOnFinalValuation`,
  `InstallmentStartFinancialYearId`=`ReassessmentYear`
- All the "0.00 if missing" / "0 if missing" / "অজানা if missing" fallback
  fields
- `HoldingType` defaults to 3 (non-commercial) when source has no value
- `SMSAccountNumber` generation algorithm (pourashava code + branch +
  sequence, exactly as specified)

**You still need to do these before generating real output:**
1. Map the ~7 direct-copy columns (HoldingNo, TaxPayerName, etc.) to
   your actual source file's column names — Tab 2.
2. Provide the `batch_id` values: `Zonelnfold`, `ReassessmentYear`,
   `IUser` — these come from separate pourashava-level reference files
   per the SOP, not from this tool. Get Doulatkhan's specific numbers
   first.
3. Upload the `WardId`, `PropertyUseId`, `PropertyTypeId`,
   `TaxPayerTypeId` lookup tables and resolve the distinct source
   values — Tab 3. **Note:** your source register's "Property Use"
   column packs multiple pieces of data into one cell (e.g.
   `১১-০/ ০৩ পাকা, ০৯-০/ঝুপদোয়ার`). This tool maps clean columns to
   IDs — it does not parse packed free text. Split that column first
   with a small preprocessing script, then feed the split result in here.
4. Decide the `Id` starting value — must be "current max Id in the live
   `HT_TaxAssessment_Master` table + 1", which only the DB knows, not
   this file.
5. `StreetId` and `BankAccountlnfold` are flagged `manual_external` —
   per the SOP these require an actual DB round-trip (import into
   `PRM_Street`, filter, manually assign; create Bank records, query
   generated Ids) that cannot happen inside a Streamlit app with no DB
   access. Do that process externally, paste the resolved Ids back into
   your source file as a new column, then map that column here.
6. Confirm two open gaps flagged in `default_schema.py`:
   - `TaxPayerSpouseName` — not mentioned anywhere in the SOP. Currently
     left blank. Ask whoever wrote the SOP.
   - `IsActive` — SOP says derive Active=1/Inactive=0 from source, but
     doesn't say what to do if source has no such column at all.
     Currently defaults everyone to 1 (active) as an assumption, not a
     documented rule.

## Validation on generate (Tab 4)

After generating, the app runs SOP-specific checks — not generic ETL
checks, the specific landmines this document calls out:
- `ParentId` non-blank anywhere → hard warning
- `SMSAccountNumber` duplicates → hard warning
- `AnnualValuation` != `FinalValuation` anywhere → hard warning (should
  be structurally impossible given the `equals_column` rule, but checked
  anyway in case someone reconfigures the rule)
- `HoldingType` default-usage count surfaced explicitly, so you know how
  many rows got the assumed non-commercial default vs. real source data
- Any `batch_id` / `lookup_id` / `manual_external` column still missing
  its required input is called out by name, not silently left blank

## Known limitations

- No fuzzy matching on lookup values by design — exact-match auto-suggest
  only, everything else is a manual human decision. This is deliberate:
  silent fuzzy-matching on government tax records is how errors propagate
  across thousands of rows unnoticed.
- In-memory session state only. Export the JSON config (Tab 5) before
  closing the browser, or you lose your mapping work.
- Doesn't touch the database. `StreetId` and `BankAccountlnfold` require
  you to actually go do the DB import/query steps the SOP describes —
  this tool has no DB connection and isn't pretending otherwise.
- Doesn't parse packed/composite source cells (see point 3 above). Text
  parsing is a separate, harder problem from column mapping and deserves
  its own reviewed script rather than being bolted on here as a guess.
