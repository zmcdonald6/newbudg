# analysis.py

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import re

def process_budget(file_path_or_bytes):
    df_budget = pd.read_excel(file_path_or_bytes, sheet_name='Sheet1', skiprows=5)
    df_budget.dropna(how='all', inplace=True)
    df_budget.dropna(axis=1, how='all', inplace=True)
    df_budget.columns = ['Description'] + [str(i) for i in range(1, 13)] + ['Total']
    df_budget.reset_index(drop=True, inplace=True)

    structured = []
    current_category = None

    for _, row in df_budget.iterrows():
        desc = str(row['Description']).strip()
        if re.match(r"^[A-Z]\)\s?.+", desc):
            current_category = re.sub(r"^[A-Z]\)\s?", "", desc).strip()
            structured.append({
                "Category": current_category,
                "Subcategory": None,
                "Monthly": row[1:13].values,
                "Total": row["Total"]
            })
        elif current_category:
            structured.append({
                "Category": current_category,
                "Subcategory": desc,
                "Monthly": row[1:13].values,
                "Total": row["Total"]
            })

    df_structured = pd.DataFrame(structured)
    df_structured["Monthly"] = df_structured["Monthly"].apply(lambda x: np.array(x, dtype=float))
    df_structured["Total"] = pd.to_numeric(df_structured["Total"], errors="coerce").fillna(0)
    return df_structured

def generate_summary(df_structured, df_expense):
    category_exp = df_expense.groupby("Category")["Amount"].sum().reset_index()
    category_exp.columns = ["Category", "Total_Spent"]

    category_budgets = df_structured[df_structured["Subcategory"].isna()][["Category", "Total"]]
    category_budgets.columns = ["Category", "Total_Budget"]

    summary_df = pd.merge(category_budgets, category_exp, on="Category", how="outer").fillna(0)
    summary_df["Variance"] = summary_df["Total_Budget"] - summary_df["Total_Spent"]

    return summary_df

def plot_budget_vs_spent(summary_df):
    fig, ax = plt.subplots(figsize=(10, 5))
    index = range(len(summary_df))
    bar_width = 0.35

    ax.bar(index, summary_df["Total_Budget"], bar_width, label='Budget')
    ax.bar([i + bar_width for i in index], summary_df["Total_Spent"], bar_width, label='Spent')

    ax.set_xlabel("Category")
    ax.set_ylabel("Amount")
    ax.set_title("Budget vs Spent by Category")
    ax.set_xticks([i + bar_width / 2 for i in index])
    ax.set_xticklabels(summary_df["Category"], rotation=45)
    ax.legend()
    return fig

def get_monthly_trend(expense_df):
    expense_df["Month"] = pd.to_datetime(expense_df["Date"]).dt.month
    monthly_summary = expense_df.groupby("Month")["Amount"].sum().reindex(range(1, 13), fill_value=0)
    return monthly_summary
