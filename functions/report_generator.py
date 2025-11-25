# functions/report_generator.py

import streamlit as st
import pandas as pd
#import gspread
import re
import requests
from io import BytesIO
from .db import get_uploaded_files
#from google.oauth2 import service_account


def render_generate_report_section(
    process_budget,
    process_expenses,
    get_usd_rates,
    convert_row_amount_to_usd,
    dashboard,
    load_budget_state_monthly,
    save_budget_state_monthly,
    variance_color_style,
    get_variance_status
):
    """This function contains the FULL Generate Report section EXACTLY as in main.py."""

    # =========================================================
    # Generate Report (collapsed, no auto-selection)
    # =========================================================
    with st.expander("🧾 Generate Report", expanded=True):

        # Load Google Sheet logs
        #creds = service_account.Credentials.from_service_account_info(
        #    dict(st.secrets["GOOGLE"]), scopes=SCOPE
        #)
        #client = gspread.authorize(creds)
        #upload_log = client.open_by_key(SHEET_ID).worksheet("UploadedFiles")
        #records = upload_log.get_all_records()

        records = get_uploaded_files()

        if not records:
            st.info("📭 No uploaded files yet. Please upload at least one budget and one expense file.")
            return

        df_files = pd.DataFrame(records)

        # budgets can be 'budget(opex)' or 'budget(capex)' (backward compat with plain 'budget')
        ft = df_files["file_type"].astype(str).str.lower()
        is_budget = ft.str.startswith("budget")
        budget_files = df_files[is_budget]
        expense_files = df_files[ft == "expense"]

        budget_options = ["— Select Budget File —"] + budget_files["file_name"].tolist()
        expense_options = ["— Select Expense File —"] + expense_files["file_name"].tolist()

        selected_budget = st.selectbox("📘 Budget File", budget_options, index=0)
        selected_expense = st.selectbox("💸 Expense File", expense_options, index=0)

        # Backward-compat type chooser
        legacy_type_choice = None

        if "report_open" not in st.session_state:
            st.session_state.report_open = False

        run_report = st.button("Generate Report")

        if run_report:
            st.session_state.report_open = True

        if not st.session_state.report_open:
            st.stop()


        # Validate selection
        if selected_budget == budget_options[0] or selected_expense == expense_options[0]:
            st.error("Please select both a Budget and an Expense file.")
            st.stop()

        # Resolve URLs
        budget_row = budget_files[budget_files["file_name"] == selected_budget].iloc[0]
        expense_row = expense_files[expense_files["file_name"] == selected_expense].iloc[0]

        budget_url = budget_row["file_url"]
        expense_url = expense_row["file_url"]

        # Budget type (OPEX/CAPEX)
        file_type_val = str(budget_row["file_type"]).lower()
        m = re.search(r"budget\((opex|capex)\)", file_type_val, flags=re.I)

        if m:
            selected_budget_type = m.group(1).upper()
        else:
            legacy_type_choice = st.selectbox(
                "🏷️ This budget isn’t typed; choose how to treat expenses:",
                ["OPEX", "CAPEX"], index=0
            )
            selected_budget_type = legacy_type_choice

        # --- Parse Budget ---
        df_budget = process_budget(BytesIO(requests.get(budget_url).content))
        df_budget = df_budget[~df_budget["Sub-Category"].str.strip().str.lower().eq("total")]

        # --- Parse Expenses ---
        try:
            df_expense = process_expenses(BytesIO(requests.get(expense_url).content))
        except Exception as e:
            st.error(f"❌ Could not process Expenses file: {e}")
            st.stop()

        # Filter by type
        df_expense["Classification"] = df_expense["Classification"].astype(str).str.upper().str.strip()
        df_expense = df_expense[df_expense["Classification"] == selected_budget_type].copy()

        if df_expense.empty:
            st.warning(f"No {selected_budget_type} expenses found.")
            st.stop()

        df_expense["Budget Category"] = df_expense["Category"]

        # --- FX Conversion ---
        try:
            fx_rates = get_usd_rates()
            provider = st.session_state.get("fx_provider", "unknown")
            fetched = st.session_state.get("fx_fetched_at")
            if fetched:
                st.caption(f"FX provider: {provider} • fetched {fetched}")
        except Exception as e:
            st.error(f"Unable to fetch FX rates: {e}")
            fx_rates = {}

        df_expense["Amount (USD)"] = df_expense.apply(
            lambda r: convert_row_amount_to_usd(r, fx_rates, df_expense),
            axis=1
        )

        # ===============================================================
        # -------------- INSERT YOUR DASHBOARD CALL ---------------------
        # ===============================================================
        dashboard(
            df_budget=df_budget,
            df_expense=df_expense,
            selected_budget=selected_budget,
            load_budget_state_monthly=load_budget_state_monthly,
            save_budget_state_monthly=save_budget_state_monthly
        )

        # ===============================================================
        # EVERYTHING BELOW IS 100% YOUR ORIGINAL REPORT CODE
        # ===============================================================

        # Filters
        st.markdown("Reports")

        with st.expander("📂 Filter by Categories"):
            all_cats = sorted(df_expense["Budget Category"].dropna().unique().tolist())
            select_all_cat = st.checkbox("Select All Categories", value=True, key="all_categories")
            selected_categories = st.multiselect(
                "Choose Categories", options=all_cats,
                default=all_cats if select_all_cat else []
            )

        with st.expander("🏷️ Filter by Vendors"):
            all_vendors = sorted(df_expense["Vendor"].dropna().unique().tolist())
            select_all_ven = st.checkbox("Select All Vendors", value=True, key="all_vendors")
            selected_vendors = st.multiselect(
                "Choose Vendors", options=all_vendors,
                default=all_vendors if select_all_ven else []
            )

        filtered_df = df_expense[
            df_expense["Budget Category"].isin(selected_categories) &
            df_expense["Vendor"].isin(selected_vendors)
        ].copy()


        # ===============================================================
        # Subcategory view
        # ===============================================================
        expenses_agg = (
            filtered_df.groupby(["Budget Category", "Sub-Category"], dropna=False, as_index=False)["Amount (USD)"]
            .sum()
        )

        df_budget_for_merge = (
            df_budget.rename(columns={"Category": "Budget Category"})[
                ["Budget Category", "Sub-Category", "Total"]
            ].drop_duplicates()
        )

        merged = expenses_agg.merge(
            df_budget_for_merge,
            how="left",
            on=["Budget Category", "Sub-Category"]
        )

        final_view = merged.rename(columns={
            "Budget Category": "Category",
            "Total": "Amount Budgeted",
            "Amount (USD)": "Amount Spent (USD)"
        }).copy()

        final_view["Variance (USD)"] = final_view["Amount Budgeted"].fillna(0) - final_view["Amount Spent (USD)"].fillna(0)
        for col in ["Amount Budgeted", "Amount Spent (USD)", "Variance (USD)"]:
            final_view[col] = (final_view[col].astype(float).round(2)).fillna(0)

        final_view["Status"] = final_view.apply(
            lambda row: get_variance_status(
                row["Amount Budgeted"],
                row["Amount Spent (USD)"],
                row["Variance (USD)"],
            ),
            axis=1
        )

        final_view = final_view[
            ["Category", "Sub-Category", "Amount Budgeted", "Amount Spent (USD)", "Variance (USD)", "Status"]
        ]
        final_view.sort_values(["Category", "Sub-Category"], inplace=True)

        with st.expander("📄 Expenditures (USD) — Subcategory", expanded=False):
            styled_final = (
                final_view.style
                .apply(variance_color_style, axis=1)
                .format({
                    "Amount Budgeted": "{:,.2f}",
                    "Amount Spent (USD)": "{:,.2f}",
                    "Variance (USD)": "{:,.2f}",
                })
            )
            st.dataframe(styled_final, use_container_width=True)


        # ===============================================================
        # Category view
        # ===============================================================
        budget_per_cat = (
            df_budget.groupby("Category", as_index=False)["Total"].sum()
            .rename(columns={"Total": "Amount Budgeted"})
        )

        spent_per_cat = (
            filtered_df.groupby("Budget Category", as_index=False)["Amount (USD)"].sum()
            .rename(columns={"Budget Category": "Category", "Amount (USD)": "Amount Spent (USD)"})
        )

        cat_view = budget_per_cat.merge(spent_per_cat, how="outer", on="Category")
        cat_view["Amount Budgeted"] = cat_view["Amount Budgeted"].fillna(0.0)
        cat_view["Amount Spent (USD)"] = cat_view["Amount Spent (USD)"].fillna(0.0)
        cat_view["Variance (USD)"] = cat_view["Amount Budgeted"] - cat_view["Amount Spent (USD)"]

        for col in ["Amount Budgeted", "Amount Spent (USD)", "Variance (USD)"]:
            cat_view[col] = cat_view[col].astype(float).round(2)

        cat_view["Status"] = cat_view.apply(
            lambda row: get_variance_status(
                row["Amount Budgeted"],
                row["Amount Spent (USD)"],
                row["Variance (USD)"]
            ),
            axis=1
        )

        cat_view = cat_view[["Category", "Amount Budgeted", "Amount Spent (USD)", "Variance (USD)", "Status"]]
        cat_view.sort_values("Category", inplace=True)

        with st.expander("📊Expenditure Summary (USD) — Category", expanded=False):
            styled_cat = (
                cat_view.style
                .apply(variance_color_style, axis=1)
                .format({
                    "Amount Budgeted": "{:,.2f}",
                    "Amount Spent (USD)": "{:,.2f}",
                    "Variance (USD)": "{:,.2f}",
                })
            )
            st.dataframe(styled_cat, use_container_width=True)


                # ===============================================================
        # Full Budget View (Hierarchy)
        # ===============================================================

        full_view = final_view.copy()

        # Add category totals
        cat_totals = (
            full_view.groupby("Category", as_index=False)[
                ["Amount Budgeted", "Amount Spent (USD)", "Variance (USD)"]
            ].sum()
        )
        cat_totals["Sub-Category"] = ""  # blank
        cat_totals["is_total"] = True
        full_view["is_total"] = False

        hierarchy_view = pd.concat([cat_totals, full_view], ignore_index=True)
        hierarchy_view.sort_values(["Category", "is_total"], ascending=[True, False], inplace=True)

        # ===============================================================
        # Full Budget View — Including Out-of-Budget (OOB)
        # ===============================================================

        # 1. Baseline: every budgeted subcategory
        budget_full = (
            df_budget.rename(columns={
                "Category": "Category",
                "Sub-Category": "Sub-Category",
                "Total": "Amount Budgeted"
            })[["Category", "Sub-Category", "Amount Budgeted"]].copy()
        )

        budget_full["Amount Budgeted"] = pd.to_numeric(
            budget_full["Amount Budgeted"], errors="coerce"
        ).fillna(0)

        # 2. Expense aggregates
        expenses_agg = (
            filtered_df.groupby(["Budget Category", "Sub-Category"], dropna=False, as_index=False)["Amount (USD)"]
            .sum()
            .rename(columns={"Budget Category": "Category", "Amount (USD)": "Amount Spent (USD)"})
        )

        # 3. Merge budget + expenses
        merged_full = budget_full.merge(
            expenses_agg,
            how="outer",
            on=["Category", "Sub-Category"]
        )

        # 4. Variance
        merged_full["Amount Spent (USD)"] = merged_full["Amount Spent (USD)"].fillna(0)
        merged_full["Variance (USD)"] = merged_full["Amount Budgeted"] - merged_full["Amount Spent (USD)"]

        # 5. Identify Out-of-Budget
        budget_keys = set(budget_full.set_index(["Category", "Sub-Category"]).index)
        expense_keys = set(expenses_agg.set_index(["Category", "Sub-Category"]).index)

        oob_keys = expense_keys - budget_keys

        if oob_keys:
            oob_items = (
                expenses_agg.set_index(["Category", "Sub-Category"])
                .loc[list(oob_keys)]
                .reset_index()
            )

            oob_items["Category"] = "Out of Budget"
            oob_items["Amount Budgeted"] = 0.0
            oob_items["Variance (USD)"] = -oob_items["Amount Spent (USD)"]
            oob_items["is_oob"] = True

            merged_full = merged_full[
                ~merged_full.set_index(["Category", "Sub-Category"]).index.isin(oob_keys)
            ]

            merged_full = pd.concat([merged_full, oob_items], ignore_index=True)

            # Ensure duplicates removed
            merged_full = merged_full[
                ~merged_full.set_index(["Category","Sub-Category"]).index.isin(oob_keys)
            ]
            merged_full = pd.concat([merged_full, oob_items], ignore_index=True)

        # 6. Category totals (OOB categories get total budget = 0)
        def total_budget(series):
            if (series == "OOB").any():
                return 0
            return series.sum()

        cat_totals = (
            merged_full.groupby("Category", as_index=False)
            .agg({
                "Amount Budgeted": total_budget,
                "Amount Spent (USD)": "sum",
                "Variance (USD)": "sum"
            })
        )
        cat_totals["Sub-Category"] = ""
        cat_totals["is_total"] = True
        merged_full["is_total"] = False

        hierarchy_view = pd.concat([cat_totals, merged_full], ignore_index=True)

        # 7. Sorting order: normal → subcats → Out-of-Budget
        hierarchy_view["sort_key"] = hierarchy_view.apply(
            lambda r: (
                1 if r["Category"] == "Out of Budget" else 0,
                0 if r.get("is_total") else 1,
                str(r["Sub-Category"])
            ),
            axis=1
        )
        hierarchy_view.sort_values("sort_key", inplace=True)
        hierarchy_view.drop(columns=["sort_key"], inplace=True)

        # 8. Formatting helper
        def fmt_budget(val):
            if isinstance(val, (int, float)) and val == 0:
                return "OOB"
            try:
                return f"{val:,.2f}"
            except Exception:
                return val

        # 9. Display Full Hierarchy View
        with st.expander("📘 Full Budget View (USD) — Category + Subcategories", expanded=False):

            df_display = hierarchy_view.copy()

            # Sort categories in same order as budget file, OOB last
            budget_order = df_budget["Category"].drop_duplicates().tolist()
            df_display["Category"] = pd.Categorical(
                df_display["Category"],
                categories=budget_order + ["Out of Budget"],
                ordered=True
            )
            df_display.sort_values(["Category", "Sub-Category"], inplace=True)

            # Add indentation for subcategories
            INDENT = "\u2003\u2003\u2003"
            df_display.loc[
                df_display["Sub-Category"].notna() & (df_display["Sub-Category"] != ""),
                "Sub-Category"
            ] = (
                INDENT + "→ " +
                df_display.loc[
                    df_display["Sub-Category"].notna() & (df_display["Sub-Category"] != ""),
                    "Sub-Category"
                ].astype(str)
            )

            df_display.reset_index(drop=True, inplace=True)

            # Recalculate variance status
            df_display["Status"] = df_display.apply(
                lambda row: get_variance_status(
                    row["Amount Budgeted"],
                    row["Amount Spent (USD)"],
                    row["Variance (USD)"],
                ),
                axis=1
            )

            display_cols = [
                "Category", "Sub-Category",
                "Amount Budgeted", "Amount Spent (USD)",
                "Variance (USD)", "Status"
            ]

            st.dataframe(
                df_display[display_cols].style
                    .apply(
                        lambda row: [
                            "font-weight: bold"
                            if not row["Sub-Category"] or row["Sub-Category"] == "→ "
                            else ""
                            for _ in row
                        ],
                        axis=1
                    )
                    .apply(variance_color_style, axis=1)
                    .format({
                        "Amount Budgeted": lambda v, is_oob=None: "OOB" if is_oob else f"{v:,.2f}",
                        "Amount Spent (USD)": "{:,.2f}",
                        "Variance (USD)": "{:,.2f}",
                    }),
                use_container_width=True
            )

