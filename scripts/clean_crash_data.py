"""
Cleaning pipeline for NYC Open Data's "Motor Vehicle Collisions - Crashes" dataset
(Socrata ID h9gi-nx95).

Usage:
    python clean_crash_data.py <input.xlsx or .csv> <output_prefix>

Produces:
    <output_prefix>.csv          - cleaned data, ready for the Streamlit/Plotly pipeline
    <output_prefix>.xlsx         - same data + a "Cleaning summary" sheet, for manual review
    <output_prefix>_log.json     - machine-readable cleaning log

Designed to be reusable: rerun this unchanged against the full multi-year pull later,
not just this sample.
"""
import sys
import json
import pandas as pd
import numpy as np

NYC_LAT_RANGE = (40.4, 40.95)
NYC_LON_RANGE = (-74.3, -73.65)

STREET_COLS = ["on_street_name", "off_street_name", "cross_street_name"]
FACTOR_COLS = [f"contributing_factor_vehicle_{i}" for i in range(1, 6)]
VEHICLE_COLS = ["vehicle_type_code1", "vehicle_type_code2",
                "vehicle_type_code_3", "vehicle_type_code_4", "vehicle_type_code_5"]
COUNT_COLS = [
    "number_of_persons_injured", "number_of_persons_killed",
    "number_of_pedestrians_injured", "number_of_pedestrians_killed",
    "number_of_cyclist_injured", "number_of_cyclist_killed",
    "number_of_motorist_injured", "number_of_motorist_killed",
]
TEXT_COLS = STREET_COLS + FACTOR_COLS + VEHICLE_COLS + ["borough"]


def clean_crash_data(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    log = {"input_rows": len(df)}
    df = df.copy()

    # --- Dates & times: Excel serial numbers -> real datetime ---------------
    # pd.api.types.is_numeric_dtype, not np.issubdtype: pandas 3 defaults to
    # pyarrow-backed StringDtype, which np.issubdtype cannot interpret and which
    # raises "Cannot interpret '<StringDtype(na_value=nan)>' as a data type".
    # The Excel sample this was written against never exercised that path.
    if pd.api.types.is_numeric_dtype(df["crash_date"]):
        dates = pd.to_datetime(df["crash_date"], unit="D", origin="1899-12-30")
    else:
        dates = pd.to_datetime(df["crash_date"], errors="coerce")

    if pd.api.types.is_numeric_dtype(df["crash_time"]):
        secs = (df["crash_time"] * 24 * 3600).round().astype("Int64")
        time_str = pd.to_datetime(secs, unit="s", errors="coerce").dt.strftime("%H:%M")
    else:
        time_str = df["crash_time"].astype(str)

    df["crash_date"] = dates.dt.date
    df["crash_time"] = time_str
    df["crash_datetime"] = pd.to_datetime(
        dates.dt.strftime("%Y-%m-%d") + " " + time_str, errors="coerce"
    )
    log["date_range"] = [str(dates.min().date()), str(dates.max().date())]
    year_counts = dates.dt.year.value_counts().sort_index()
    log["rows_per_year"] = {str(k): int(v) for k, v in year_counts.items()}

    # --- Duplicates -----------------------------------------------------------
    before = len(df)
    df = df.drop_duplicates()
    df = df.drop_duplicates(subset=["collision_id"], keep="first")
    log["duplicate_rows_dropped"] = before - len(df)

    # --- Text columns: trim whitespace, normalize dtype, keep NaN as NaN -----
    for col in TEXT_COLS:
        df[col] = df[col].apply(lambda v: str(v).strip() if pd.notna(v) else pd.NA)
        df[col] = df[col].replace({"": pd.NA, "nan": pd.NA})

    # --- Coordinates FIRST: coerce, then scrub, then flag -------------------
    # Order matters and used to be wrong. The "recoverable via lat/long" count
    # below must be computed AFTER bad coordinates are nulled, or it counts
    # (0,0) and out-of-bounds rows as recoverable and inflates the headline
    # number this project is built on.
    #
    # Coercion is not optional either: the Socrata API returns every numeric as
    # a STRING, so without this the comparison below is `str < float` on an
    # object-dtype Series and raises TypeError on the real pull. The old code
    # only ever saw an Excel sample, where pandas had already inferred floats.
    for col in ("latitude", "longitude"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    bad_coord = (
        df["latitude"].notna()
        & df["longitude"].notna()
        & (
            (df["latitude"] < NYC_LAT_RANGE[0]) | (df["latitude"] > NYC_LAT_RANGE[1])
            | (df["longitude"] < NYC_LON_RANGE[0]) | (df["longitude"] > NYC_LON_RANGE[1])
        )
    )
    log["invalid_coordinates_nulled"] = int(bad_coord.sum())
    cols_to_null = [c for c in ("latitude", "longitude", "location") if c in df.columns]
    df.loc[bad_coord, cols_to_null] = np.nan
    df["has_valid_location"] = df["latitude"].notna() & df["longitude"].notna()

    # --- Borough / zip: leave missing as missing (do not guess) --------------
    missing_borough = df["borough"].isna().sum()
    missing_zip = df["zip_code"].isna().sum()
    # Computed against SCRUBBED coordinates. This is the instrument behind the
    # project's headline claim, so it must not count coordinates we just nulled.
    recoverable_via_geocoding = int(
        (df["borough"].isna() & df["has_valid_location"]).sum()
    )
    # A zip that will not parse becomes missing rather than killing a 20-minute
    # pull at its final step. One malformed value in 812,318 rows should not
    # cost the whole run.
    zip_numeric = pd.to_numeric(df["zip_code"], errors="coerce")
    log["zip_codes_unparseable"] = int(zip_numeric.isna().sum() - df["zip_code"].isna().sum())
    df["zip_code"] = zip_numeric.apply(
        lambda v: f"{int(v):05d}" if pd.notna(v) else pd.NA
    )
    log["missing_borough"] = int(missing_borough)
    log["missing_zip_code"] = int(missing_zip)
    log["borough_missing_but_recoverable_via_lat_long"] = recoverable_via_geocoding

    # --- Injury/fatality counts: force numeric, missing -> 0 (assumption) ----
    for col in COUNT_COLS:
        missing = df[col].isna().sum()
        if missing:
            log.setdefault("count_columns_filled_with_zero", {})[col] = int(missing)
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    # --- Sparse-by-design columns: leave untouched, just document ------------
    log["sparse_by_design_columns"] = FACTOR_COLS[1:] + VEHICLE_COLS[1:]

    # `location` is deliberately absent: it duplicates latitude/longitude, no
    # chart reads it, and its embedded newlines make CSV line counts overcount
    # records by ~2.9x, which has already caused one wrong size estimate.
    col_order = [
        "collision_id", "crash_date", "crash_time", "crash_datetime",
        "borough", "borough_recovered", "borough_source",
        "zip_code", "latitude", "longitude", "has_valid_location",
        "on_street_name", "cross_street_name", "off_street_name",
        *COUNT_COLS, *FACTOR_COLS, *VEHICLE_COLS,
    ]
    # This used to be a silent allowlist: `df[[c for c in col_order if c in
    # df.columns]]` dropped any column not named above without a word. That
    # would have silently deleted borough_recovered/borough_source on a re-run
    # after the recovery, destroying the finding's own columns. Now it says so.
    unexpected = [c for c in df.columns if c not in col_order and c != "location"]
    if unexpected:
        raise ValueError(
            f"unexpected column(s) not in col_order: {unexpected}. "
            "Add them to col_order deliberately rather than letting them be "
            "dropped silently."
        )
    df = df[[c for c in col_order if c in df.columns]]

    log["output_rows"] = len(df)
    log["output_columns"] = len(df.columns)
    return df, log


def main():
    if len(sys.argv) != 3:
        print("Usage: python clean_crash_data.py <input.xlsx|csv> <output_prefix>")
        sys.exit(1)
    in_path, out_prefix = sys.argv[1], sys.argv[2]

    df = pd.read_csv(in_path) if in_path.endswith(".csv") else pd.read_excel(in_path)
    cleaned, log = clean_crash_data(df)

    cleaned.to_csv(f"{out_prefix}.csv", index=False)
    with open(f"{out_prefix}_log.json", "w") as f:
        json.dump(log, f, indent=2)

    print(json.dumps(log, indent=2))


if __name__ == "__main__":
    main()
