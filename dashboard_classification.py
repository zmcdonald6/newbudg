import streamlit as st
import pandas as pd

def dashboard(df_budget, df_expense, selected_budget, load_budget_state_monthly, save_budget_state_monthly):
    """
    Classification dashboard using Streamlit data_editor without reruns
    until Save is clicked. Uses apply-buffer → save pattern and reloads
    previous classifications correctly.
    """

    # ============================================================
    # 🔸 MUST INITIALIZE ALL SESSION STATE KEYS HERE — FIRST LINES
    # ============================================================
    if "loaded_budget_key" not in st.session_state:
        st.session_state.loaded_budget_key = None

    if "status_editor_buffer" not in st.session_state:
        st.session_state.status_editor_buffer = None

    if "status_pending_changes" not in st.session_state:
        st.session_state.status_pending_changes = None

    if "keep_report_open" not in st.session_state:
        st.session_state.keep_report_open = True

    # ============================================================
    # TOP SUMMARY SECTION
    # ============================================================
    st.subheader("📊Budget Classification Dashboard")

    saved_state = load_budget_state_monthly(selected_budget)

    status_options = [
        "Wishlist", "To be confirmed", "Spent", "To be spent",
        "To be spent (Projects)", "To be spent (Recurring)",
        "Will not be spent", "Out of Budget"
    ]

    status_colors = {
        "Wishlist": "#BD9D69",
        "To be confirmed": "#F43FEE73",
        "Spent": "#3CE780",
        "To be spent": "#33FF00FF",
        "To be spent (Projects)": "#3498DB",
        "To be spent (Recurring)": "#1ABC9C",
        "Will not be spent": "#EE0909",
        "Out of Budget": "#F39C12",
        "Budget Total": "#FFFFFF00",
        "Budget Balance": "#FFFFFF00"
    }

    # Compute summary
    if saved_state.empty:
        classified_summary = pd.DataFrame({
            "Status Category": status_options,
            "Total": [0] * len(status_options)
        })
    else:
        classified_summary = (
            saved_state.groupby("Status Category")["Amount"]
            .sum()
            .reset_index()
            .rename(columns={"Amount": "Total"})
            .set_index("Status Category")
            .reindex(status_options, fill_value=0)
            .reset_index()
        )

    # Budget totals
    top_cols = st.columns(2)
    budget_total = df_budget["Total"].sum()
    spent_usd = df_expense["Amount (USD)"].sum()
    budget_balance = budget_total - spent_usd

    with top_cols[0]:
        st.markdown(
            f"""
            <div style="background:{status_colors['Budget Total']}; padding:16px;
                        border-radius:12px; text-align:center;">
                <strong>Budget Total</strong><br>
                <span style="font-size:24px;">{budget_total:,.2f}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with top_cols[1]:
        st.markdown(
            f"""
            <div style="background:{status_colors['Budget Balance']}; padding:16px;
                        border-radius:12px; text-align:center;">
                <strong>Budget Balance</strong><br>
                <span style="font-size:24px;">{budget_balance:,.2f}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # Two-row status display
    rows = 2
    cols_per_row = 4
    for r in range(rows):
        row_cols = st.columns(cols_per_row)
        for c in range(cols_per_row):
            idx = r * cols_per_row + c
            if idx >= len(status_options):
                break

            status = classified_summary.loc[idx, "Status Category"]
            total = classified_summary.loc[idx, "Total"]

            with row_cols[c]:
                st.markdown(
                    f"""
                    <div style="background:{status_colors[status]}; padding:18px;
                                border-radius:14px; text-align:center;">
                        <strong>{status}</strong><br>
                        <span style="font-size:22px;">{total:,.2f}</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    # ============================================================
    # MONTHLY EDITOR — Streamlit data_editor (NO REFRESH!)
    # ============================================================
    st.subheader("📘 Budget Classifications (Interactive Monthly Grid)")

    months = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December"
    ]

    # Base DF
    base_df = df_budget[["Category", "Sub-Category"] + months].copy()

    saved = load_budget_state_monthly(selected_budget)

    # pivot saved statuses
    if not saved.empty:
        saved_pivot = saved.pivot_table(
            index=["Category", "Sub-Category"],
            columns="Month",
            values="Status Category",
            aggfunc="first",
        ).reset_index()
    else:
        saved_pivot = pd.DataFrame(columns=["Category", "Sub-Category"] + months)

    # merge with budget
    merged_df = base_df.merge(saved_pivot, on=["Category", "Sub-Category"], how="left")

    # ensure all month columns exist
    for m in months:
        if m not in merged_df.columns:
            merged_df[m] = None

    # add amount columns
    for m in months:
        merged_df[f"{m} Amount"] = base_df[m]

    # order columns
    ordered_cols = ["Category", "Sub-Category"]
    for m in months:
        ordered_cols.append(f"{m} Amount")
        ordered_cols.append(m)

    merged_df = merged_df[ordered_cols]

    # ============================================================
    # LOAD BUFFER (ONLY WHEN A NEW BUDGET IS SELECTED)
    # ============================================================
    if st.session_state.loaded_budget_key != selected_budget:
        st.session_state.status_editor_buffer = merged_df.copy()
        st.session_state.loaded_budget_key = selected_budget

    # Show editor using buffer
    editor_cols = {}

    for m in months:
        editor_cols[f"{m} Amount"] = st.column_config.NumberColumn(
            disabled=True,
            format="$%.2f"
        )
        editor_cols[m] = st.column_config.SelectboxColumn(
            options=status_options,
            help=f"Status for {m}"
        )

    edited_df = st.data_editor(
        st.session_state.status_editor_buffer,
        column_config=editor_cols,
        use_container_width=True,
        key="monthly_status_editor"
    )

    # Save buffer continuously
    st.session_state.status_editor_buffer = edited_df.copy()

    # ============================================================
    # APPLY → SAVE
    # ============================================================
    if st.button("📝 Apply Changes"):
        st.session_state.status_pending_changes = edited_df.copy()
        st.success("Changes applied. Press Save to store permanently.")

    if st.button("💾 Save Classifications"):
        if st.session_state.status_pending_changes is None:
            st.warning("Please click Apply Changes first.")
            return

        final_df = st.session_state.status_pending_changes.copy()

        # Melt statuses
        melted_status = final_df.melt(
            id_vars=["Category", "Sub-Category"],
            value_vars=months,
            var_name="Month",
            value_name="Status Category"
        )

        # Melt budget amounts
        melted_amounts = base_df.melt(
            id_vars=["Category", "Sub-Category"],
            value_vars=months,
            var_name="Month",
            value_name="Amount"
        )

        final_melted = melted_status.merge(
            melted_amounts,
            on=["Category", "Sub-Category", "Month"],
            how="left"
        )

        save_budget_state_monthly(selected_budget, final_melted, st.session_state.email)

        st.success("🎉 Saved successfully!")
        st.session_state.status_pending_changes = None
