"""
Per-column audit: dtype, % missing, distinct count, sample values. Same logic
used to build DATA_DICTIONARY.md - rerun this after any real data pull to
refresh those numbers.

Usage: python scripts/audit_columns.py data/processed/crashes_cleaned.csv
"""
import sys
import pandas as pd


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "data/processed/crashes_cleaned.csv"
    df = pd.read_csv(path, dtype={"zip_code": str}, low_memory=False)
    print(f"{len(df):,} rows, {len(df.columns)} columns\n")
    print(f"{'column':<32}{'dtype':<10}{'missing%':<10}{'unique':<8}sample")
    print("-" * 100)
    for col in df.columns:
        s = df[col]
        miss_pct = s.isna().mean() * 100
        nunique = s.nunique()
        non_null = s.dropna()
        if len(non_null) == 0:
            sample = "(all missing)"
        elif pd.api.types.is_numeric_dtype(s) and nunique > 15:
            sample = f"{non_null.min()} to {non_null.max()}"
        else:
            sample = ", ".join(str(v) for v in non_null.unique()[:3])
        print(f"{col:<32}{str(s.dtype):<10}{miss_pct:<10.1f}{nunique:<8}{sample}")


if __name__ == "__main__":
    main()
