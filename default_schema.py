from rule_engine import Rule

TARGET_COLUMNS = [
    "Id", "ParentId", "AssessmentType", "AssessmentDate", "HoldingNo",
    "ClientNo", "ZoneInfold", "IsActive", "InactiveDate",
    "ValuationDuringInactive", "ArrearDuringInactive", "TaxPayerName",
    "AnnualValuation", "TaxOnAnnualValuation", "FinalValuation",
    "TaxOnFinalValuation", "FinalValuationDate", "TotalTaxRates",
    "ReassessmentYear", "ReassessmentPeriod",
    "AnnualValuationBeforeInterimOrReAssessment",
    "ArrearYearDuringReassessment", "InstallmentStartYear",
    "InstallmentStartMonth", "InstallmentStartFinancialYearId",
    "InstallmentStartPeriodOfBill", "RemarkForTaxRevise",
    "TaxReviseAttachment", "PreviousHoldingNo", "PreviousClientNo",
    "TaxPayerFatherName", "TaxPayerMotherName", "TaxPayerSpouseName",
    "BillingAddress", "MobileNumber", "NationalID", "EmailAddress",
    "Images", "Attachment", "WardId", "StreetId", "BankAccountInfoId",
    "HoldingType", "PropertyUseId", "PropertyTypeId", "TaxPayerTypeId",
    "YearlyRent_OwnersPart", "MonthlyRent_TenantsPart",
    "LandDevelopmentRate", "FullBuildingValue", "YearlyRent_FreeLand",
    "YearlyInterest_Loan", "TotalArea_OwnersPart", "TotalArea_TenantsPart",
    "TotalFreeLand", "LandArea_Height", "LandArea_Width", "LandArea_Total",
    "OpeningArrearStYear", "OpeningArrearStPeriod", "Remarks",
    "IsFreedomFighter", "AnnualValuationForFreedomFighter",
    "RemarkForOtherHoldingType", "RebateSFForFreedomFighter",
    "Notice_Date", "Notice_AssessmentActivationYear",
    "Notice_AssessmentActivationDate", "Notice_SharokNo", "AppealDate",
    "IsEffectedInMainAssessment", "IsFirstAssessmentHistory",
    "InterimAssessmentId", "InterimEffectiveBillYearId",
    "InterimEffectivePeriodOfBill", "FinalTaxSetBy", "FinalTaxSetDate",
    "InterimAssessmentSetBy", "InterimAssessmentSetDate",
    "NoticeDataSetBy", "NoticeDataSetDate", "ActiveStatusChangedBy",
    "ActiveStatusChangeDate", "SMSAccountNumber", "SecondaryMobile",
    "BuildingShortInfo", "PreviousBuildingShortInfo",
    "NewBuildingShortInfo", "ApproveStatus", "SubmissionDate",
    "ApproveOrRejectDate", "IUser", "IDate", "EUser", "EDate",
]

assert len(TARGET_COLUMNS) == 95, f"expected 95 target columns, got {len(TARGET_COLUMNS)}"


def sop_default_rules():
    """Returns a fresh {column: Rule} dict every call (mutable Rule
    objects, don't share instances across calls)."""
    r = {}

    def const(col, val, note=""):
        r[col] = Rule(type="constant", value=val, note=note)

    def skip(col, note=""):
        r[col] = Rule(type="skip", note=note)

    def copy_def(col, default, numeric=False, bn_digits=False, note=""):
        r[col] = Rule(type="copy_default", value=default, numeric_clean=numeric, convert_bn_digits=bn_digits, note=note)

    def copy(col, numeric=False, bn_digits=False, note=""):
        r[col] = Rule(type="copy", numeric_clean=numeric, convert_bn_digits=bn_digits, note=note)

    def eq(col, ref, note=""):
        r[col] = Rule(type="equals_column", value=ref, note=note)

    def batch(col, note=""):
        r[col] = Rule(type="batch_id", note=note)

    def lookup(col, note=""):
        r[col] = Rule(type="lookup_id", note=note)

    def manual(col, note=""):
        r[col] = Rule(type="manual_external", note=note)

    r["Id"] = Rule(type="generated_sequence", seq_start=1, seq_pad=0,
                    note="SOP: 'set Id based on total data'. Start value should be (current max Id in live HT_TaxAssessment_Master) + 1 — get this from the DB before running, it is NOT derivable from this file.")

    const("ParentId", "", note="CRITICAL (SOP explicit): must stay blank. A 0 here breaks front-end display of the record.")
    const("AssessmentType", "1", note="SOP: always 1 = New Assessment.")
    const("AssessmentDate", "01-07-2026 12:00:00 AM", note="SOP: fixed for this batch.")
    copy("HoldingNo", bn_digits=True, note="Bengali digits found mixed with English in real source data ('০২','০৩'...) — auto-converted to English, formatting/leading-zeros otherwise untouched.")
    r["ClientNo"] = Rule(
        type="client_id", cid_pad_width=2, cid_separator="-",
        cid_ward_mode="source_column", cid_street_mode="source_column", cid_holding_mode="source_column",
        note="CORRECTED per explicit instruction: ClientNo = ward-street-holding, e.g. '01-01-01'. Each part in English digits, minimum 2 digits (longer numbers like a 3-digit holding no. are NOT truncated, just not padded further). Defaults to reading all three parts straight from source columns (digit-normalized). Set Ward/Holding source columns in Tab 2. Street part currently has no usable source (register's Street column is 0% filled) — will export blank until street data exists or you switch that part to lookup_code mode once StreetId is resolved.",
    )
    batch("ZonelnfoId", note="SOP: one fixed Id per pourashava from the 'ZoneInfoId' reference file. CONFIRMED for Durgapur = 145 (cross-checked from both Durgapur-Ward.xlsx and Durgapur-Street.xlsx, ZoneInfoId column is 145 on every row of both). Pre-filled, but verify it's still current before shipping.")
    r["ZonelnfoId"].value = "145"
    copy_def("IsActive", "1", note="ASSUMPTION, not explicitly in SOP for the no-source-indicator case: SOP says Active=1/Inactive=0 from source, but if your source has no active/inactive column, this defaults everyone to 1 (active). Override if your source data does carry that signal.")
    skip("InactiveDate")
    skip("ValuationDuringInactive")
    skip("ArrearDuringInactive")
    copy("TaxPayerName")
    eq("AnnualValuation", "FinalValuation", note="SOP: AnnualValuation and FinalValuation must be identical.")
    eq("TaxOnAnnualValuation", "TaxOnFinalValuation", note="SOP: TaxOnAnnualValuation and TaxOnFinalValuation must be identical.")
    copy("FinalValuation", numeric=True)
    copy("TaxOnFinalValuation", numeric=True)
    const("FinalValuationDate", "01-07-2026 12:00:00 AM")
    copy("TotalTaxRates", numeric=True, note="SOP: e.g. source '17%' becomes 17.00. numeric_clean strips the % sign; confirm decimal format matches target expectations.")
    batch("ReassessmentYear", note="SOP: one fixed Id per pourashava from the 'Fiscal Year Id for all Pourosova' file, for FY 2026-2027.")
    skip("ReassessmentPeriod")
    const("AnnualValuationBeforeInterimOrReAssessment", "0.00")
    skip("ArrearYearDuringReassessment")
    const("InstallmentStartYear", "2026")
    const("InstallmentStartMonth", "July")
    eq("InstallmentStartFinancialYearId", "ReassessmentYear", note="SOP: must equal ReassessmentYear's value.")
    const("InstallmentStartPeriodOfBill", "1")
    skip("RemarkForTaxRevise")
    skip("TaxReviseAttachment")
    copy_def("PreviousHoldingNo", "", bn_digits=True, note="SOP: from source if available, blank if not.")
    copy_def("PreviousClientNo", "", bn_digits=True, note="SOP: from source if available, blank if not.")
    copy_def("TaxPayerFatherName", "অজানা", note="SOP: 'অজানা' (unknown) if source is missing this.")
    copy_def("TaxPayerMotherName", "অজানা", note="SOP: 'অজানা' (unknown) if source is missing this.")
    skip("TaxPayerSpouseName", note="GAP: not covered anywhere in the SOP document. Confirm the rule before shipping — currently left blank.")
    copy_def("BillingAddress", "অজানা", note="SOP: 'অজানা' (unknown) if source is missing this.")
    copy_def("MobileNumber", "0", bn_digits=True, note="SOP: 0 if source is missing this.")
    copy_def("NationalID", "0", bn_digits=True, note="SOP: 0 if source is missing this.")
    skip("EmailAddress")
    skip("Images")
    skip("Attachment")
    lookup("WardId", note="SOP: per-pourashava Ward Id reference file, per-row match required. Durgapur-Ward.xlsx provided: 9 wards, Id range 867-875, Name = ward number (1-9) as plain digits. WARNING: the source register's Ward No. column is genuinely messy — mixes English digits ('1','8'), Bengali digits ('০৪','০৯','০২','৩','০৬','০৭','০১'), and at least one malformed hybrid ('০6'). Use the 'normalize Bengali digits' toggle in Tab 3 to auto-resolve most of these, then manually check the rest (the '০6'-style entries are likely typos and need a human judgment call, not an automated guess).")
    lookup("StreetId", note="UPDATED: originally flagged manual_external per the SOP's multi-step PRM_Street DB process, but Durgapur-Street.xlsx (22 rows, ZoneInfoId=145, already filtered for this pourashava) is exactly the output that process produces — so this can now be resolved as a normal per-row lookup instead of requiring you to repeat that DB round-trip. Two caveats: (1) the source register's own 'Street' column is 0% filled across all 4508 rows — there is currently nothing to map FROM, so this stays unresolved regardless of the lookup table's readiness, unless street names get extracted from elsewhere (see StreetId-in-PropertyUse note below). (2) the street name 'ঝুপদোয়ার' appears twice in the lookup table under two different Ids (37077 and 37094) — if you ever do get per-row street text, a name match alone can be ambiguous for that one street; you'll need extra context (which sub-area) to pick the right Id.")
    manual("BankAccountInfoId", note="SOP: create Bank records in the live system from source info, then query the DB for the generated Id. Some pourashavas already have bank info pre-created — check before creating duplicates. Map a source column here only once you have the resolved Ids.")
    copy_def("HoldingType", "3", note="SOP: defaults to 3 (অবানিজ্যিক / non-commercial) ONLY when source has no holding-type data. If your source data does carry this, map it as the source column instead of relying on the default.")
    lookup("PropertyUseId", note="SOP: match source text against the PropertyUseId reference file (per-row).")
    lookup("PropertyTypeId", note="SOP: match source text against the PropertyTypeId reference file (per-row).")
    lookup("TaxPayerTypeId", note="SOP: match source text against the TaxPayerTypeId reference file (per-row).")
    for col in ["YearlyRent_OwnersPart", "MonthlyRent_TenantsPart", "LandDevelopmentRate",
                "FullBuildingValue", "YearlyRent_FreeLand", "YearlyInterest_Loan",
                "TotalArea_OwnersPart", "TotalArea_TenantsPart", "TotalFreeLand",
                "LandArea_Height", "LandArea_Width", "LandArea_Total",
                "AnnualValuationForFreedomFighter", "RebateSFForFreedomFighter"]:
        copy_def(col, "0.00", numeric=True, note="SOP: 0.00 if source is missing this.")
    copy_def("OpeningArrearStYear", "", bn_digits=True, note="SOP: from source if available, blank if not.")
    copy_def("OpeningArrearStPeriod", "", bn_digits=True, note="SOP: from source if available, blank if not.")
    skip("Remarks")
    copy_def("IsFreedomFighter", "0", note="SOP: 1 if freedom fighter, else 0 — needs a source indicator column.")
    skip("RemarkForOtherHoldingType")
    skip("Notice_Date"); skip("Notice_AssessmentActivationYear")
    skip("Notice_AssessmentActivationDate"); skip("Notice_SharokNo"); skip("AppealDate")
    const("IsEffectedInMainAssessment", "0")
    const("IsFirstAssessmentHistory", "0")
    for col in ["InterimAssessmentId", "InterimEffectiveBillYearId", "InterimEffectivePeriodOfBill",
                "FinalTaxSetBy", "FinalTaxSetDate", "InterimAssessmentSetBy", "InterimAssessmentSetDate",
                "NoticeDataSetBy", "NoticeDataSetDate", "ActiveStatusChangedBy", "ActiveStatusChangeDate"]:
        skip(col)

    r["SMSAccountNumber"] = Rule(
        type="sms_account_number", sms_branch="01", seq_start=1,
        note="SOP algorithm: concat(3-digit pourashava code, '01', row sequence starting at 1, no padding). Example: pourashava 224 with 6420 rows -> 224011 ... 224016420. Set the pourashava code before generating.",
    )

    skip("SecondaryMobile"); skip("BuildingShortInfo")
    skip("PreviousBuildingShortInfo"); skip("NewBuildingShortInfo")
    const("ApproveStatus", "2", note="SOP: 2 = this taxpayer record has been approved.")
    skip("SubmissionDate"); skip("ApproveOrRejectDate")
    batch("IUser", note="SOP describes this as a fixed 3-digit number, one per pourashava, example Chatak=360. DISCREPANCY: the actual IUser values observed in Durgapur-Ward.xlsx (=1) and Durgapur-Street.xlsx (=4525, 2698, varying per row) don't match that description — they look like individual user-account login IDs recorded per edit, not one stable 3-digit pourashava constant. Do not guess; ask whoever owns the SOP/live system which number is actually correct for Durgapur before filling this in.")
    const("IDate", "01-07-2026 12:00:00 AM")
    skip("EUser"); skip("EDate")

    missing = set(TARGET_COLUMNS) - set(r.keys())
    assert not missing, f"rule template missing columns: {missing}"
    return r
