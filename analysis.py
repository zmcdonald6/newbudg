import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

def process_budget(file_path_or_bytes):
    # Step 1: Read and clean
    df = pd.read_excel(file_path_or_bytes, sheet_name=0, skiprows=5)
    df.dropna(how="all", inplace=True)
    df.dropna(axis=1, how="all", inplace=True)
    df.reset_index(drop=True, inplace=True)

    # Step 2: Rename columns manually to match your known format
    new_columns = ['Description'] + [str(i) for i in range(1, 13)] + ['Total']
    df.columns = new_columns + list(df.columns[len(new_columns):])  # keep extras if any

    # Step 3: Skip first 2 rows — those are still header/label clutter
    df = df.iloc[2:].reset_index(drop=True)

    # Step 4: Build structured format
    structured = []
    current_category = None

    for _, row in df.iterrows():
        desc = str(row["Description"]).strip()
        if pd.isna(desc):
            continue
        if desc and desc[0].isupper() and ')' in desc:
            current_category = desc.split(')', 1)[-1].strip()
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


