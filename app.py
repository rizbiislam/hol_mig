import io
import json
from datetime import datetime

import pandas as pd
import streamlit as st

from rule_engine import Rule, RULE_TYPES, apply_rules, normalize, normalize_digits, translate_bn_digits
from default_schema import TARGET_COLUMNS, sop_default_rules

st.set_page_config(page_title="Holding Tax Data Migrator v2", layout="wide")


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def read_table(file_bytes, filename):
    name = filename.lower()
    if name.endswith(".csv"):
        df = pd.read_csv(io.BytesIO(file_bytes), dtype=str, keep_default_na=False, na_values=[""])
        return {"Sheet1": df}
    xls = pd.ExcelFile(io.BytesIO(file_bytes))
    return {sn: pd.read_excel(xls, sheet_name=sn, dtype=str, keep_default_na=False, na_values=[""]) for sn in xls.sheet_names}


def df_to_excel_bytes(df):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Master")
    buf.seek(0)
    return buf.getvalue()


def rule_to_dict(r: Rule):
    return r.__dict__.copy()


def rule_from_dict(d):
    return Rule(**d)


def init_state():
    defaults = {
        "source_df": None,
        "target_columns": list(TARGET_COLUMNS),
        "rules": sop_default_rules(),
        "value_maps": {},
        "code_lookups": {},
        "output_df": None,
        "audit": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


init_state()

st.title("Holding Tax Data Migrator v2")
st.caption(
    "Rule-driven: loaded by default with the HT_TaxAssessment_Master schema "
    "and the field rules from the SOP instruction document. Adjust per column, "
    "resolve lookups, generate, validate against the SOP's own constraints."
)

tabs = st.tabs([
    "1. Source file",
    "2. Column rules",
    "3. ID / lookup resolution",
    "4. Generate & validate",
    "5. Save / load config",
])

# ----------------------------------------------------------------------
# TAB 1
# ----------------------------------------------------------------------
with tabs[0]:
    st.subheader("Upload source file")
    src_file = st.file_uploader("Excel or CSV — the register you're migrating from", type=["xlsx", "xls", "csv"])

    if src_file is not None:
        sheets = read_table(src_file.getvalue(), src_file.name)
        sheet_name = st.selectbox("Sheet", list(sheets.keys()))
        df = sheets[sheet_name]

        header_row = st.number_input(
            "Header row (increase if real headers aren't on row 1)",
            min_value=1, max_value=min(20, len(df) + 1), value=1, step=1,
        )
        if header_row > 1:
            new_header = df.iloc[header_row - 2].fillna("").astype(str)
            df2 = df.iloc[header_row - 1:].reset_index(drop=True)
            df2.columns = [c if c else f"col_{i}" for i, c in enumerate(new_header)]
            df = df2

        df = df.dropna(how="all").reset_index(drop=True)
        st.session_state.source_df = df

        st.success(f"Loaded {len(df)} rows, {len(df.columns)} columns from '{sheet_name}'.")
        fill = pd.DataFrame({
            "column": df.columns,
            "non_empty": [df[c].notna().sum() for c in df.columns],
            "fill_%": [round(df[c].notna().sum() / max(len(df), 1) * 100, 1) for c in df.columns],
        })
        st.markdown("**Column fill-rate audit**")
        st.dataframe(fill, use_container_width=True, hide_index=True)
        st.markdown("**Preview**")
        st.dataframe(df.head(20), use_container_width=True)
    else:
        st.info("Upload a source file to continue.")

# ----------------------------------------------------------------------
# TAB 2 - Column rules
# ----------------------------------------------------------------------
with tabs[1]:
    st.subheader("Column rules")
    df = st.session_state.source_df

    c1, c2, c3 = st.columns(3)
    if c1.button("Reset to SOP defaults (HT_TaxAssessment_Master)"):
        st.session_state.rules = sop_default_rules()
        st.session_state.target_columns = list(TARGET_COLUMNS)
        st.rerun()
    if c2.button("Blank all rules (start fresh for a different target table)"):
        st.session_state.rules = {tc: Rule() for tc in st.session_state.target_columns}
        st.rerun()

    with st.expander("Use a different target schema entirely (reuse this tool for another table)"):
        schema_file = st.file_uploader("Target schema file (header row = column names)", type=["xlsx", "xls", "csv"], key="schema_up")
        if schema_file is not None:
            sheets = read_table(schema_file.getvalue(), schema_file.name)
            sn = st.selectbox("Sheet", list(sheets.keys()), key="schema_sheet")
            if st.button("Apply this schema"):
                cols = list(sheets[sn].columns)
                st.session_state.target_columns = cols
                st.session_state.rules = {tc: Rule() for tc in cols}
                st.rerun()

    if df is None:
        st.warning("Upload a source file in Tab 1 first — column pickers need it.")
    else:
        source_cols = ["-- none --"] + list(df.columns)
        target_cols_for_eq = ["-- none --"] + st.session_state.target_columns

        # summary of rule-type counts up top
        rules = st.session_state.rules
        type_counts = pd.Series([rules.get(tc, Rule()).type for tc in st.session_state.target_columns]).value_counts()
        st.markdown("**Rule-type summary**")
        st.dataframe(type_counts.rename("count").to_frame(), use_container_width=True)

        pending = [tc for tc in st.session_state.target_columns if rules.get(tc, Rule()).type == "batch_id" and not rules[tc].value]
        if pending:
            st.warning(f"{len(pending)} batch_id column(s) still need a value from a reference file: {', '.join(pending)}")

        st.divider()

        for tc in st.session_state.target_columns:
            r = rules.get(tc, Rule())
            label = f"**{tc}**"
            if r.type == "batch_id" and not r.value:
                label += "  :orange[● needs value]"
            elif r.type == "manual_external" and not r.source_col:
                label += "  :orange[● external process pending]"
            with st.expander(label, expanded=False):
                if r.note:
                    st.caption(r.note)

                new_type = st.selectbox("Rule type", RULE_TYPES, index=RULE_TYPES.index(r.type), key=f"type_{tc}")
                r.type = new_type

                if new_type == "constant":
                    r.value = st.text_input("Constant value (every row)", value=r.value or "", key=f"val_{tc}")

                elif new_type == "copy":
                    idx = source_cols.index(r.source_col) if r.source_col in source_cols else 0
                    chosen = st.selectbox("Source column", source_cols, index=idx, key=f"col_{tc}")
                    r.source_col = None if chosen == "-- none --" else chosen
                    r.numeric_clean = st.checkbox("Clean numeric (strip %, commas)", value=r.numeric_clean, key=f"num_{tc}")
                    r.convert_bn_digits = st.checkbox("Convert Bengali digits to English (0-9), keep everything else as-is", value=r.convert_bn_digits, key=f"bndig_{tc}")
                    if r.source_col:
                        nn = df[r.source_col].notna().sum()
                        st.caption(f"Fill rate: {nn}/{len(df)} ({nn/max(len(df),1)*100:.1f}%)")

                elif new_type == "copy_default":
                    idx = source_cols.index(r.source_col) if r.source_col in source_cols else 0
                    chosen = st.selectbox("Source column (optional)", source_cols, index=idx, key=f"col_{tc}")
                    r.source_col = None if chosen == "-- none --" else chosen
                    r.value = st.text_input("Default value when source is missing", value=r.value or "", key=f"def_{tc}")
                    r.numeric_clean = st.checkbox("Clean numeric (strip %, commas)", value=r.numeric_clean, key=f"num_{tc}")
                    r.convert_bn_digits = st.checkbox("Convert Bengali digits to English (0-9), keep everything else as-is", value=r.convert_bn_digits, key=f"bndig_{tc}")

                elif new_type == "equals_column":
                    idx = target_cols_for_eq.index(r.value) if r.value in target_cols_for_eq else 0
                    chosen = st.selectbox("Equals which target column's value?", target_cols_for_eq, index=idx, key=f"eq_{tc}")
                    r.value = None if chosen == "-- none --" else chosen

                elif new_type == "batch_id":
                    r.value = st.text_input("Batch value (same Id for every row, from the reference file)", value=r.value or "", key=f"batch_{tc}")

                elif new_type == "lookup_id":
                    idx = source_cols.index(r.source_col) if r.source_col in source_cols else 0
                    chosen = st.selectbox("Source column to resolve", source_cols, index=idx, key=f"col_{tc}")
                    r.source_col = None if chosen == "-- none --" else chosen
                    st.caption("Upload the lookup table and assign values in Tab 3.")

                elif new_type == "generated_sequence":
                    cc1, cc2, cc3 = st.columns(3)
                    r.seq_start = cc1.number_input("Start value", min_value=0, value=r.seq_start or 1, key=f"seqstart_{tc}")
                    r.seq_pad = cc2.number_input("Zero-pad width (0 = none)", min_value=0, value=r.seq_pad or 0, key=f"seqpad_{tc}")
                    r.seq_prefix = cc3.text_input("Prefix", value=r.seq_prefix or "", key=f"seqpre_{tc}")
                    if df is not None and len(df) > 0:
                        w = r.seq_pad
                        first = f"{r.seq_prefix}{str(r.seq_start).zfill(w) if w else r.seq_start}"
                        last_num = r.seq_start + len(df) - 1
                        last = f"{r.seq_prefix}{str(last_num).zfill(w) if w else last_num}"
                        st.caption(f"Preview: {first} ... {last}")

                elif new_type == "sms_account_number":
                    cc1, cc2 = st.columns(2)
                    r.sms_code = cc1.text_input("Pourashava code (3 digits)", value=r.sms_code or "", key=f"smscode_{tc}")
                    r.sms_branch = cc2.text_input("Branch code", value=r.sms_branch or "01", key=f"smsbranch_{tc}")
                    if r.sms_code and df is not None and len(df) > 0:
                        n = len(df)
                        st.caption(f"Preview: {r.sms_code}{r.sms_branch}1 ... {r.sms_code}{r.sms_branch}{n}  ({n} rows)")

                elif new_type == "manual_external":
                    idx = source_cols.index(r.source_col) if r.source_col in source_cols else 0
                    chosen = st.selectbox(
                        "Source column with ALREADY-RESOLVED Ids (leave as none until you've done the external process)",
                        source_cols, index=idx, key=f"col_{tc}",
                    )
                    r.source_col = None if chosen == "-- none --" else chosen

                elif new_type == "client_id":
                    st.caption("Builds a composite code like ward-street-holding (e.g. '01-01-01'). Each part is independently configurable since ward/street code formats vary by pourashava.")
                    r.cid_pad_width = st.number_input("Minimum digits per part (zero-padded, never truncated)", min_value=1, value=r.cid_pad_width or 2, key=f"cidpad_{tc}")
                    r.cid_separator = st.text_input("Separator", value=r.cid_separator or "-", key=f"cidsep_{tc}")

                    def part_ui(label, mode_attr, source_attr, key_prefix):
                        mode = st.radio(f"{label} source", ["source_column", "lookup_code"], index=["source_column", "lookup_code"].index(getattr(r, mode_attr)), key=f"{key_prefix}_mode_{tc}", horizontal=True)
                        setattr(r, mode_attr, mode)
                        if mode == "source_column":
                            cur = getattr(r, source_attr)
                            idx = source_cols.index(cur) if cur in source_cols else 0
                            chosen = st.selectbox(f"{label}: source column (raw value, will be digit-normalized + padded)", source_cols, index=idx, key=f"{key_prefix}_col_{tc}")
                            setattr(r, source_attr, None if chosen == "-- none --" else chosen)
                        else:
                            other_targets = ["-- none --"] + [c for c in st.session_state.target_columns if c != tc]
                            cur = getattr(r, source_attr)
                            idx = other_targets.index(cur) if cur in other_targets else 0
                            chosen = st.selectbox(f"{label}: which already-resolved target column's FK Id to translate?", other_targets, index=idx, key=f"{key_prefix}_tgt_{tc}")
                            setattr(r, source_attr, None if chosen == "-- none --" else chosen)
                            if chosen != "-- none --":
                                cl_file = st.file_uploader(f"{label}: Id→Code lookup table (col1=Id, col2=Code)", type=["xlsx", "xls", "csv"], key=f"{key_prefix}_clfile_{tc}")
                                if cl_file is not None:
                                    csheets = read_table(cl_file.getvalue(), cl_file.name)
                                    csheet = list(csheets.keys())[0] if len(csheets) == 1 else st.selectbox(f"{label}: sheet", list(csheets.keys()), key=f"{key_prefix}_clsheet_{tc}")
                                    cdf = csheets[csheet].iloc[:, :2]
                                    st.session_state.code_lookups[chosen] = {str(row[0]): str(row[1]) for row in cdf.itertuples(index=False)}
                                    st.caption(f"Loaded {len(cdf)} Id→Code entries for '{chosen}'.")
                                elif chosen in st.session_state.code_lookups:
                                    st.caption(f"Using previously-loaded Id→Code table ({len(st.session_state.code_lookups[chosen])} entries) for '{chosen}'.")

                    part_ui("Ward", "cid_ward_mode", "cid_ward_source", "cidw")
                    st.divider()
                    part_ui("Street", "cid_street_mode", "cid_street_source", "cids")
                    st.divider()
                    part_ui("Holding No.", "cid_holding_mode", "cid_holding_source", "cidh")

                rules[tc] = r
        st.session_state.rules = rules

# ----------------------------------------------------------------------
# TAB 3 - lookup resolution
# ----------------------------------------------------------------------
with tabs[2]:
    st.subheader("Resolve lookup_id columns")
    df = st.session_state.source_df
    rules = st.session_state.rules

    if df is None:
        st.warning("Upload a source file first.")
    else:
        lookup_targets = [tc for tc in st.session_state.target_columns if rules.get(tc, Rule()).type == "lookup_id" and rules[tc].source_col]
        if not lookup_targets:
            st.info("No lookup_id columns with a source column set yet — configure those in Tab 2 first.")
        else:
            chosen_tc = st.selectbox("Column to resolve", ["-- select --"] + lookup_targets)
            if chosen_tc != "-- select --":
                src_col = rules[chosen_tc].source_col
                st.markdown(f"**Lookup table for `{chosen_tc}`** (resolving source column `{src_col}`)")
                lut_file = st.file_uploader("Upload lookup table (col 1 = Id, col 2 = Label)", type=["xlsx", "xls", "csv"], key=f"lut_{chosen_tc}")
                lut_key = f"_lut_df_{chosen_tc}"
                if lut_file is not None:
                    lsheets = read_table(lut_file.getvalue(), lut_file.name)
                    if len(lsheets) > 1:
                        sheet_choice = st.selectbox(
                            f"This file has multiple sheets — pick the one for '{chosen_tc}'",
                            list(lsheets.keys()), key=f"lutsheet_{chosen_tc}",
                        )
                    else:
                        sheet_choice = list(lsheets.keys())[0]
                    lut_df = lsheets[sheet_choice].iloc[:, :2]
                    lut_df.columns = ["Id", "Label"]
                    st.session_state[lut_key] = lut_df

                if lut_key in st.session_state:
                    lut_df = st.session_state[lut_key]
                    st.dataframe(lut_df, use_container_width=True, hide_index=True, height=180)

                    label_options = ["-- unmapped --"] + [f"{row.Id} — {row.Label}" for row in lut_df.itertuples()]
                    label_norm_map = {normalize(row.Label): f"{row.Id} — {row.Label}" for row in lut_df.itertuples()}
                    label_digit_map = {normalize_digits(row.Label): f"{row.Id} — {row.Label}" for row in lut_df.itertuples()}

                    distinct_vals = df[src_col].dropna().map(normalize).value_counts().reset_index()
                    distinct_vals.columns = ["value", "count"]
                    st.markdown(f"**{len(distinct_vals)} distinct values** in `{src_col}`, sorted by frequency")

                    vm = st.session_state.value_maps.setdefault(chosen_tc, {})

                    digit_mode = st.checkbox(
                        "Also normalize Bengali digits (০-৯ → 0-9, strip leading zeros) before auto-suggest matching",
                        key=f"digitnorm_{chosen_tc}",
                        help="Useful for numeric codes like Ward No. that were hand-typed inconsistently — e.g. '1', '০৪', '৩' all meaning the same thing. Only affects the auto-suggest button below; manual assignment always still works regardless.",
                    )

                    if st.button(f"Auto-suggest matches", key=f"autosug_{chosen_tc}"):
                        for v in distinct_vals["value"]:
                            if v in label_norm_map:
                                vm[v] = label_norm_map[v]
                            elif digit_mode and normalize_digits(v) in label_digit_map:
                                vm[v] = label_digit_map[normalize_digits(v)]

                    for _, row in distinct_vals.iterrows():
                        v, cnt = row["value"], row["count"]
                        default = vm.get(v, "-- unmapped --")
                        idx = label_options.index(default) if default in label_options else 0
                        chosen = st.selectbox(f"'{v}'  (appears {cnt}x)", label_options, index=idx, key=f"vm_{chosen_tc}_{v}")
                        vm[v] = chosen
                    st.session_state.value_maps[chosen_tc] = vm

                    unmapped_ct = sum(1 for v in distinct_vals["value"] if vm.get(v, "-- unmapped --") == "-- unmapped --")
                    (st.warning if unmapped_ct else st.success)(
                        f"{unmapped_ct} of {len(distinct_vals)} unmapped" if unmapped_ct else "All distinct values mapped."
                    )

# ----------------------------------------------------------------------
# TAB 4 - generate & validate
# ----------------------------------------------------------------------
with tabs[3]:
    st.subheader("Generate & validate")
    df = st.session_state.source_df

    if df is None:
        st.warning("Upload a source file first.")
    else:
        if st.button("Generate output", type="primary"):
            out, audit = apply_rules(df, st.session_state.target_columns, st.session_state.rules, st.session_state.value_maps, st.session_state.code_lookups)
            st.session_state.output_df = out
            st.session_state.audit = audit

        if st.session_state.output_df is not None:
            out = st.session_state.output_df
            audit = st.session_state.audit
            st.success(f"Generated {len(out)} rows x {len(out.columns)} columns.")

            if audit["validation"]:
                st.markdown("### SOP validation warnings")
                for msg in audit["validation"]:
                    st.warning(msg)
            else:
                st.success("No SOP validation warnings.")

            st.markdown("### Column audit")
            rows = []
            for tc in st.session_state.target_columns:
                a = audit["columns"].get(tc, {})
                rows.append({
                    "target_column": tc,
                    "rule_type": a.get("rule_type", "skip"),
                    "filled": a.get("filled", 0),
                    "fill_%": round(a.get("filled", 0) / max(len(out), 1) * 100, 1),
                    "defaulted": a.get("defaulted", 0),
                    "unmapped": a.get("unmapped", 0),
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            st.markdown("### Preview")
            st.dataframe(out.head(30), use_container_width=True)

            xlsx_bytes = df_to_excel_bytes(out)
            st.download_button(
                "Download master-format Excel",
                data=xlsx_bytes,
                file_name=f"master_output_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

# ----------------------------------------------------------------------
# TAB 5 - save/load config
# ----------------------------------------------------------------------
with tabs[4]:
    st.subheader("Save / load config")
    st.caption("Export the full rule set (including lookup value maps) so a re-run on a corrected/updated source file doesn't require redoing manual work.")

    c1, c2 = st.columns(2)
    with c1:
        config = {
            "target_columns": st.session_state.target_columns,
            "rules": {tc: rule_to_dict(r) for tc, r in st.session_state.rules.items()},
            "value_maps": st.session_state.value_maps,
            "code_lookups": st.session_state.code_lookups,
        }
        st.download_button(
            "Download config (JSON)",
            data=json.dumps(config, ensure_ascii=False, indent=2),
            file_name="migration_config.json",
            mime="application/json",
        )
    with c2:
        cfg_file = st.file_uploader("Load config (JSON)", type=["json"])
        if cfg_file is not None and st.button("Apply loaded config"):
            cfg = json.loads(cfg_file.getvalue())
            st.session_state.target_columns = cfg.get("target_columns", TARGET_COLUMNS)
            st.session_state.rules = {tc: rule_from_dict(d) for tc, d in cfg.get("rules", {}).items()}
            st.session_state.value_maps = cfg.get("value_maps", {})
            st.session_state.code_lookups = cfg.get("code_lookups", {})
            st.success("Config loaded. Re-check Tab 2/3 — confirm source columns still line up if this is a different file.")
