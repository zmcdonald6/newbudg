import streamlit as st
import pandas as pd

def dashboard(df_budget, df_expense, selected_budget, load_budget_state_monthly, save_budget_state_monthly):
    """This renders the classification dashboard
    Parameters:
        df_budget (pd.Dataframe): dataframe for budget file
        df_expense (pd.Dataframe): Dataframe for expense file
        selected_budget (str): File name of selected budget file
        load_budget_state_monthly (callable): Function(budget_name) → Dataframe
        save_budget_state_monthly (callable): Function(budget_name, df, email) → None
    """
    # Budget Dashboard Classification
    st.subheader("📊Budget Classification Dashboard")

    saved_state = load_budget_state_monthly(selected_budget)

    status_options = [
        "Wishlist", "To be confirmed", "Spent", "To be spent", "To be spent (Projects)", "To be spent (Recurring)", "Will not be spent", "Out of Budget"
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

    # ---- Compute classified totals ----
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
        )
        classified_summary = classified_summary.set_index("Status Category").reindex(status_options, fill_value=0).reset_index()

    # --------------------
    # DISPLAY DASHBOARD
    # --------------------

    # First row → Budget Total + Budget Balance
    top_cols = st.columns(2)

    budget_total = df_budget['Total'].sum()
    expense_total = df_expense["Amount (USD)"].sum()
    budget_balance = budget_total - expense_total

    with top_cols[0]:
        st.markdown(
            f"""
            <div style="
                background:{status_colors['Budget Total']};
                padding:16px;
                border-radius:12px;
                color:white;
                text-align:center;
                min-height:110px;">
                <strong>Budget Total</strong><br>
                <span style="font-size:24px;">{budget_total:,.2f}</span>
            </div>
            """,
            unsafe_allow_html=True
        )

    with top_cols[1]:
        st.markdown(
            f"""
            <div style="
                background:{status_colors['Budget Balance']};
                padding:16px;
                border-radius:12px;
                color:white;
                text-align:center;
                min-height:110px;">
                <strong>Budget Balance</strong><br>
                <span style="font-size:24px;">{budget_balance:,.2f}</span>
            </div>
            """,
            unsafe_allow_html=True
        )

    # Second row → All classification totals
    # ----------------------------------------------------
    # 🔄 TWO-ROW STATUS DASHBOARD (4 per row)
    # ----------------------------------------------------
    rows = 2
    cols_per_row = 4

    for r in range(rows):
        row_cols = st.columns(cols_per_row)

        for c in range(cols_per_row):
            idx = r * cols_per_row + c
            if idx >= len(status_options):
                break  # No more statuses

            status = classified_summary.loc[idx, "Status Category"]
            total = classified_summary.loc[idx, "Total"]

            with row_cols[c]:
                st.markdown(
                    f"""
                    <div style="
                        background:{status_colors[status]};
                        padding:18px;
                        border-radius:14px;
                        color:white;
                        text-align:center;
                        min-height:110px;
                        font-size:16px;">
                        <strong>{status}</strong><br>
                        <span style="font-size:22px;">{total:,.2f}</span>
                    </div>
                    """,
                    unsafe_allow_html=True
                )


    if st.button("🔄 Refresh Dashboard"):
        st.rerun()
    
    # ===============================================================
    # 🧩 MONTHLY BUDGET CLASSIFICATIONS (INTERACTIVE GRID)
    # ===============================================================
    st.subheader("📘 Budget Classifications (Interactive Monthly Grid)")

    # Define the 12 month columns in order
    months = [
        "January","February","March","April","May","June",
        "July","August","September","October","November","December"
    ]

    # df_budget already contains: Category, Sub-Category, Jan-Dec, Total
    editor_base = df_budget[["Category","Sub-Category"] + months].copy()

    # Load saved monthly classifications for this budget
    saved = load_budget_state_monthly(selected_budget)

    # Convert saved long-format -> wide (month columns)
    if not saved.empty:
        saved_pivot = saved.pivot_table(
            index=["Category","Sub-Category"],
            columns="Month",
            values="Status Category",
            aggfunc="first"
        ).reset_index()
    else:
        saved_pivot = pd.DataFrame(columns=["Category","Sub-Category"] + months)

    # Merge budget amounts with saved statuses
    editor_df = editor_base.merge(
        saved_pivot,
        on=["Category","Sub-Category"],
        how="left",
        suffixes=("", "_saved")
    )

    # Ensure month columns exist
    for m in months:
        if m not in editor_df.columns:
            editor_df[m] = None

    # ---------------------------------------------------------------
    # ⭐ ADD AMOUNT COLUMNS (visible to user)
    # Creates e.g. "January Amount", "February Amount", etc.
    # ---------------------------------------------------------------
    for m in months:
        editor_df[f"{m} Amount"] = editor_df[m.replace(" Amount", "")] if m in editor_df else 0

    # ---------------------------------------------------------------
    # ⭐ Reorder columns so that: [Month Amount] | [Status] appear together
    # ---------------------------------------------------------------
    ordered_cols = ["Category", "Sub-Category"]
    for m in months:
        ordered_cols.append(f"{m} Amount")   # budgeted amount
        ordered_cols.append(m)               # status dropdown

    editor_df = editor_df[ordered_cols]

    # ---------------------------------------------------------------
    # Dropdown status options (NO Budget Total, NO Budget Balance)
    # ---------------------------------------------------------------
    status_options = [
        "Wishlist",
        "To be confirmed",
        "Spent",
        "To be spent",
        "To be spent (Projects)",
        "To be spent (Recurring)",
        "Will not be spent",
        "Out of Budget"
    ]

    # Build selectbox columns for every month
    editor_cols = {
        m: st.column_config.SelectboxColumn(
            options=status_options,
            default="To be confirmed",
            help=f"Assign classification for {m}"
        )
        for m in months
    }

    # Amount columns → numeric format
    for m in months:
        editor_cols[f"{m} Amount"] = st.column_config.NumberColumn(
            help=f"Budgeted amount for {m}",
            format="$%0.2f",
            disabled = True             #Making the amount rows read only
        )


    # ---------------------------------------------------------------
    # Render the interactive grid
    # ---------------------------------------------------------------
    edited = st.data_editor(
        editor_df,
        column_config=editor_cols,
        use_container_width=True,
        key="monthly_editor_with_amounts"
    )


    # ===============================================================
    # SAVE CLASSIFICATIONS
    # ===============================================================
    if st.button("💾 Save Classifications"):
        # Melt back to long format (statuses only)
        melted = edited.melt(
            id_vars=["Category","Sub-Category"],
            value_vars=months,    # ONLY the status columns
            var_name="Month",
            value_name="Status Category"
        )

        # Melt budget amounts
        budget_melt = editor_base.melt(
            id_vars=["Category","Sub-Category"],
            value_vars=months,
            var_name="Month",
            value_name="Amount"
        )

        # Merge amounts into final melted form
        melted = melted.merge(
            budget_melt,
            on=["Category","Sub-Category","Month"],
            how="left"
        )

        # Save to Google Sheet
        save_budget_state_monthly(selected_budget, melted, st.session_state.email)

        st.success("Classifications saved successfully!")
        st.rerun()