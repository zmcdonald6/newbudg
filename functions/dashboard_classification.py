import streamlit as st
import pandas as pd
"""
Provides function to display budget classification dashboard.

Author: Zedaine McDonald
Date: 2025-11-26
"""

def dashboard(df_budget, df_expense, selected_budget,
              load_budget_state_monthly, save_budget_state_monthly):
    
    """
    Logic to display a budget dashboard summary using coloured dashboard buttons.

    This function loads, saves and displays budget state as well as well as a summarized dashboard.

    Parameters:
    - df_budget: dataframe
        Budget dataframe.
    - df_expense: dataframe
    -selected budget: file name of budget selected for the dashboard
    - load_budget_state_monthly: callable 
        Function that loads the state of the current budget
    - save_budget_state_monthly: callable
        Function that saves the current state of the budget
    """

    # ============================================================
    # SESSION STATE
    # ============================================================
    if "editor_version" not in st.session_state:
        st.session_state.editor_version = 0   # bump after save

    months = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December"
    ]

    # ============================================================
    # ALWAYS LOAD STATE FROM MYSQL
    # ============================================================
    saved_state = load_budget_state_monthly(selected_budget)

    # Build base budget DF with amounts
    base_df = df_budget[["Category", "Sub-Category"] + months].copy()
    base_df = base_df.rename(columns={m: f"{m} Amount" for m in months})

    # Pivot saved statuses
    if not saved_state.empty:
        saved_pivot = saved_state.pivot_table(
            index=["Category", "Sub-Category"],
            columns="Month",
            values="Status Category",
            aggfunc="first"
        ).reset_index()
    else:
        saved_pivot = pd.DataFrame(columns=["Category", "Sub-Category"] + months)

    # Ensure pivot column names exactly match month names
    saved_pivot = saved_pivot.rename(columns={m: m for m in months})

    # ============================================================
    # MERGE BUDGET AMOUNTS + SAVED STATUS
    # ============================================================
    merged_df = base_df.merge(saved_pivot, on=["Category", "Sub-Category"], how="left")

    # Create missing status columns if not present
    for m in months:
        if m not in merged_df.columns:
            merged_df[m] = None

    # Column order
    ordered_cols = ["Category", "Sub-Category"]
    for m in months:
        ordered_cols += [f"{m} Amount", m]

    merged_df = merged_df[ordered_cols]

    # ============================================================
    # DASHBOARD SUMMARY — Tiles + Totals
    # ============================================================
    st.subheader("📊 Budget Classification Dashboard")

    status_options = [
        "Wishlist", "To be confirmed", "Spent", "To be spent",
        "To be spent (Projects)", "To be spent (Recurring)",
        "Will not be spent", "Out of Budget"
    ]

    # Compute summary
    if saved_state.empty:
        rows_summary = pd.DataFrame({
            "Status Category": status_options,
            "Total": [0] * len(status_options)
        })
    else:
        rows_summary = (
            saved_state.groupby("Status Category")["Amount"]
            .sum()
            .reset_index()
            .rename(columns={"Amount": "Total"})
            .set_index("Status Category")
            .reindex(status_options, fill_value=0)
            .reset_index()
        )

    # Top totals
    budget_total = df_budget["Total"].sum()
    spent_usd = df_expense["Amount (USD)"].sum()
    balance = budget_total - spent_usd

    col1, col2 = st.columns(2)
    with col1: st.metric("Budget Total", f"{budget_total:,.2f}")
    with col2: st.metric("Budget Balance", f"{balance:,.2f}")

    # ============================================================
    # STATUS TILES (Restored)
    # ============================================================
    status_colors = {
        "Wishlist": "#BD9D69",
        "To be confirmed": "#F43FEE73",
        "Spent": "#3CE780",
        "To be spent": "#33FF00FF",
        "To be spent (Projects)": "#3498DB",
        "To be spent (Recurring)": "#1ABC9C",
        "Will not be spent": "#EE0909",
        "Out of Budget": "#F39C12",
    }

    rows = 2
    cols_per_row = 4

    for r in range(rows):
        row_cols = st.columns(cols_per_row)
        for c in range(cols_per_row):
            idx = r * cols_per_row + c
            if idx >= len(status_options):
                break

            st_status = rows_summary.loc[idx, "Status Category"]
            total = rows_summary.loc[idx, "Total"]

            with row_cols[c]:
                st.write(
                    f"""
                    <div style="background:{status_colors[st_status]};
                                padding:18px; border-radius:12px;
                                text-align:center; color:white;">
                        <strong>{st_status}</strong><br>
                        <span style="font-size:22px;">{total:,.2f}</span>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

    # ============================================================
    # MONTHLY EDITOR
    # ============================================================
    st.subheader("📘 Budget Classifications (Interactive Monthly Grid)")

    editor_cols = {
        **{f"{m} Amount": st.column_config.NumberColumn(disabled=True, format="$%.2f")
           for m in months},
        **{m: st.column_config.SelectboxColumn(options=status_options)
           for m in months},
    }

    # Unique key ensures Streamlit never restores old data
    editor_key = f"editor_{selected_budget}_{st.session_state.editor_version}"

    edited_df = st.data_editor(
        merged_df,
        column_config=editor_cols,
        use_container_width=True,
        key=editor_key
    )

    # ============================================================
    # ONE-BUTTON SAVE — Writes to MySQL
    # ============================================================
    if st.button("💾 Save Classifications"):

        # Melt statuses
        melted_status = edited_df.melt(
            id_vars=["Category", "Sub-Category"],
            value_vars=months,
            var_name="Month",
            value_name="Status Category"
        )

        # Melt budget amounts
        melted_amounts = df_budget[["Category", "Sub-Category"] + months].melt(
            id_vars=["Category", "Sub-Category"],
            value_vars=months,
            var_name="Month",
            value_name="Amount"
        )

        # Full final table
        final_melted = melted_status.merge(
            melted_amounts,
            on=["Category", "Sub-Category", "Month"],
            how="left"
        )

        # Replace NaN with None for MySQL compatibility
        final_melted = final_melted.where(pd.notnull(final_melted), None)

        save_budget_state_monthly(selected_budget, final_melted, st.session_state.email)

        # Force clean widget reload
        st.session_state.editor_version += 1

        st.success("🎉 Saved! Reloading updated classifications...")
        st.rerun()
