"""Step 2 — The Refinery.

Reads raw_data.us_accidents_march23 into pandas, then:
  * Cleaning        - fix data types, handle missing values and outliers
  * Transformation  - feature engineering (time parts, weather groups, bands, flags)
  * Joining         - join a state dimension (code -> name / region)
  * Aggregation     - one summary table per business question

Everything is written to the `production` schema, which feeds the dashboard.
"""
import logging

import numpy as np
import pandas as pd

import config
from db_utils import read_table, write_table

log = logging.getLogger("transform")

POI_COLUMNS = [
    "Amenity", "Bump", "Crossing", "Give_Way", "Junction", "No_Exit", "Railway",
    "Roundabout", "Station", "Stop", "Traffic_Calming", "Traffic_Signal", "Turning_Loop",
]

RENAME = {
    "ID": "accident_id", "Source": "source", "Severity": "severity",
    "Start_Time": "start_time", "End_Time": "end_time",
    "Start_Lat": "lat", "Start_Lng": "lng", "Distance(mi)": "distance_mi",
    "Description": "description", "Street": "street", "City": "city", "County": "county",
    "State": "state", "Zipcode": "zipcode", "Timezone": "timezone", "Airport_Code": "airport_code",
    "Temperature(F)": "temperature_f", "Humidity(%)": "humidity_pct", "Pressure(in)": "pressure_in",
    "Visibility(mi)": "visibility_mi", "Wind_Direction": "wind_direction",
    "Wind_Speed(mph)": "wind_speed_mph", "Weather_Condition": "weather_condition",
    "Sunrise_Sunset": "day_night", "Civil_Twilight": "civil_twilight",
    **{c: c.lower() for c in POI_COLUMNS},
}

# Columns dropped on purpose (see data-quality notes in README)
DROP_COLUMNS = [
    "End_Lat", "End_Lng",            # 100% missing
    "Wind_Chill(F)",                 # 96% missing
    "Precipitation(in)",             # 93% missing
    "Country",                       # always "US"
    "Weather_Timestamp", "Nautical_Twilight", "Astronomical_Twilight",
    "_source_file", "_ingested_at",
]

STATES = {
    "AL": ("Alabama", "South"), "AK": ("Alaska", "West"), "AZ": ("Arizona", "West"),
    "AR": ("Arkansas", "South"), "CA": ("California", "West"), "CO": ("Colorado", "West"),
    "CT": ("Connecticut", "Northeast"), "DE": ("Delaware", "South"), "DC": ("District of Columbia", "South"),
    "FL": ("Florida", "South"), "GA": ("Georgia", "South"), "HI": ("Hawaii", "West"),
    "ID": ("Idaho", "West"), "IL": ("Illinois", "Midwest"), "IN": ("Indiana", "Midwest"),
    "IA": ("Iowa", "Midwest"), "KS": ("Kansas", "Midwest"), "KY": ("Kentucky", "South"),
    "LA": ("Louisiana", "South"), "ME": ("Maine", "Northeast"), "MD": ("Maryland", "South"),
    "MA": ("Massachusetts", "Northeast"), "MI": ("Michigan", "Midwest"), "MN": ("Minnesota", "Midwest"),
    "MS": ("Mississippi", "South"), "MO": ("Missouri", "Midwest"), "MT": ("Montana", "West"),
    "NE": ("Nebraska", "Midwest"), "NV": ("Nevada", "West"), "NH": ("New Hampshire", "Northeast"),
    "NJ": ("New Jersey", "Northeast"), "NM": ("New Mexico", "West"), "NY": ("New York", "Northeast"),
    "NC": ("North Carolina", "South"), "ND": ("North Dakota", "Midwest"), "OH": ("Ohio", "Midwest"),
    "OK": ("Oklahoma", "South"), "OR": ("Oregon", "West"), "PA": ("Pennsylvania", "Northeast"),
    "RI": ("Rhode Island", "Northeast"), "SC": ("South Carolina", "South"), "SD": ("South Dakota", "Midwest"),
    "TN": ("Tennessee", "South"), "TX": ("Texas", "South"), "UT": ("Utah", "West"),
    "VT": ("Vermont", "Northeast"), "VA": ("Virginia", "South"), "WA": ("Washington", "West"),
    "WV": ("West Virginia", "South"), "WI": ("Wisconsin", "Midwest"), "WY": ("Wyoming", "West"),
}

DOW_LABELS = ["1-Mon", "2-Tue", "3-Wed", "4-Thu", "5-Fri", "6-Sat", "7-Sun"]


# --------------------------------------------------------------------------- #
# Cleaning
# --------------------------------------------------------------------------- #
def clean(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.drop(columns=[c for c in DROP_COLUMNS if c in raw.columns])
    df = df.drop_duplicates(subset="ID").rename(columns=RENAME)
    n0 = len(df)

    # --- data types ---
    df["severity"] = pd.to_numeric(df["severity"], errors="coerce").astype("Int64")
    for col in ["start_time", "end_time"]:
        # some rows carry nanoseconds ("...:00.000000000"), so parse with format="mixed"
        df[col] = pd.to_datetime(df[col], format="mixed", errors="coerce")
    numeric = ["lat", "lng", "distance_mi", "temperature_f", "humidity_pct",
               "pressure_in", "visibility_mi", "wind_speed_mph"]
    for col in numeric:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in [c.lower() for c in POI_COLUMNS]:
        df[col] = df[col].str.strip().str.lower().eq("true")

    # rows without a usable time / severity cannot be analysed
    df = df.dropna(subset=["start_time", "end_time", "severity"])
    log.info("Dropped %s rows with invalid time/severity", n0 - len(df))

    # --- missing values ---
    # Wind: "Calm" direction means 0 mph; fill the rest with the median of the same month
    month_key = df["start_time"].dt.to_period("M")
    calm = df["wind_direction"].str.upper().eq("CALM") & df["wind_speed_mph"].isna()
    df.loc[calm, "wind_speed_mph"] = 0.0
    for col in ["temperature_f", "humidity_pct", "pressure_in", "visibility_mi", "wind_speed_mph"]:
        df[col] = df[col].fillna(df.groupby(month_key)[col].transform("median"))
        df[col] = df[col].fillna(df[col].median())

    for col in ["city", "county", "street", "airport_code", "timezone", "wind_direction"]:
        df[col] = df[col].fillna("Unknown")
    df["weather_condition"] = df["weather_condition"].fillna("Unknown")
    df["zipcode"] = df["zipcode"].fillna("").str[:5].replace("", "Unknown")

    # Day/Night: fill the few gaps from the hour of day
    hour = df["start_time"].dt.hour
    df["day_night"] = df["day_night"].fillna(pd.Series(np.where(hour.between(6, 17), "Day", "Night"), index=df.index))
    df["civil_twilight"] = df["civil_twilight"].fillna(df["day_night"])

    # --- outliers ---
    df["duration_min"] = (df["end_time"] - df["start_time"]).dt.total_seconds() / 60
    df = df[df["duration_min"] > 0].copy()  # negative / zero durations are bad records
    # 99.9th percentile: trims extreme records (e.g. 7,800-min events) but keeps real long ones.
    # (In this sample ~99.6% of distances are <= 0.01 mi, so a 99th-pct cap would erase the column.)
    dur_cap = df["duration_min"].quantile(0.999)
    dist_cap = df["distance_mi"].quantile(0.999)
    df["is_duration_outlier"] = df["duration_min"] > dur_cap
    df["is_distance_outlier"] = df["distance_mi"] > dist_cap
    df["duration_min_capped"] = df["duration_min"].clip(upper=dur_cap).round(1)
    df["distance_mi_capped"] = df["distance_mi"].clip(upper=dist_cap).round(3)
    df["duration_min"] = df["duration_min"].round(1)
    log.info("Outlier caps (99.9th pct): duration=%.0f min, distance=%.2f mi", dur_cap, dist_cap)
    return df


# --------------------------------------------------------------------------- #
# Feature engineering
# --------------------------------------------------------------------------- #
def weather_group(cond: str) -> str:
    c = str(cond).lower()
    if c == "unknown":
        return "Unknown"
    if any(k in c for k in ("thunder", "t-storm", "heavy rain", "tornado", "squall")):
        return "Thunderstorm / Heavy Rain"
    if any(k in c for k in ("snow", "sleet", "ice", "wintry", "hail", "freezing")):
        return "Snow / Ice"
    if any(k in c for k in ("rain", "drizzle", "shower")):
        return "Rain"
    if any(k in c for k in ("fog", "haze", "mist", "smoke", "dust", "sand")):
        return "Fog / Haze / Smoke"
    if any(k in c for k in ("cloud", "overcast")):
        return "Cloudy"
    if any(k in c for k in ("clear", "fair")):
        return "Clear / Fair"
    return "Other"


def time_of_day(h: int) -> str:
    if 6 <= h < 10:
        return "1-Morning rush (06-09)"
    if 10 <= h < 15:
        return "2-Midday (10-14)"
    if 15 <= h < 19:
        return "3-Evening rush (15-18)"
    if 19 <= h < 24:
        return "4-Night (19-23)"
    return "5-Late night (00-05)"


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    st = df["start_time"]
    df["start_date"] = st.dt.date
    df["year"] = st.dt.year
    df["month"] = st.dt.month
    df["year_month"] = st.dt.strftime("%Y-%m")
    df["month_name"] = st.dt.strftime("%m-%b")
    df["day_of_week"] = st.dt.dayofweek.map(dict(enumerate(DOW_LABELS)))
    df["is_weekend"] = st.dt.dayofweek >= 5
    df["hour"] = st.dt.hour
    df["time_of_day"] = df["hour"].map(time_of_day)

    df["severity_label"] = df["severity"].map({1: "1-Low", 2: "2-Moderate", 3: "3-High", 4: "4-Severe"})
    df["is_severe"] = df["severity"] >= 3

    df["weather_group"] = df["weather_condition"].map(weather_group)
    df["is_wet"] = df["weather_group"].isin(["Rain", "Thunderstorm / Heavy Rain", "Snow / Ice"])
    df["visibility_band"] = pd.cut(
        df["visibility_mi"], [-0.1, 1, 3, 5, 9.99, np.inf],
        labels=["1) <1 mi", "2) 1-3 mi", "3) 3-5 mi", "4) 5-10 mi", "5) 10+ mi (clear)"],
    ).astype(str)
    df["temperature_band"] = pd.cut(
        df["temperature_f"], [-np.inf, 32, 50, 65, 80, np.inf],
        labels=["1) <=32F freezing", "2) 33-50F cold", "3) 51-65F cool", "4) 66-80F warm", "5) >80F hot"],
    ).astype(str)
    df["wind_band"] = pd.cut(
        df["wind_speed_mph"], [-0.1, 0, 10, 20, np.inf],
        labels=["1) Calm", "2) 1-10 mph", "3) 11-20 mph", "4) >20 mph"],
    ).astype(str)

    poi = [c.lower() for c in POI_COLUMNS]
    df["poi_count"] = df[poi].sum(axis=1)
    df["lat_lng"] = df["lat"].round(5).astype(str) + "," + df["lng"].round(5).astype(str)

    df["risk_combo"] = (
        df["day_night"] + " | "
        + np.where(df["is_wet"], "Wet weather", "Dry weather") + " | "
        + np.where(df["junction"], "Junction", "No junction")
    )
    return df


# --------------------------------------------------------------------------- #
# Joining
# --------------------------------------------------------------------------- #
def build_dim_state() -> pd.DataFrame:
    return pd.DataFrame(
        [(code, name, region) for code, (name, region) in STATES.items()],
        columns=["state", "state_name", "region"],
    )


def join_state(df: pd.DataFrame, dim_state: pd.DataFrame) -> pd.DataFrame:
    out = df.merge(dim_state, on="state", how="left")
    out["state_name"] = out["state_name"].fillna(out["state"])
    out["region"] = out["region"].fillna("Unknown")
    return out


# --------------------------------------------------------------------------- #
# Aggregation (one table per business question)
# --------------------------------------------------------------------------- #
def _summary(g) -> pd.DataFrame:
    return g.agg(
        accidents=("accident_id", "count"),
        avg_severity=("severity", "mean"),
        severe_rate=("is_severe", "mean"),
        median_duration_min=("duration_min", "median"),
        avg_distance_mi=("distance_mi_capped", "mean"),
    )


def _finish(df: pd.DataFrame, total: int) -> pd.DataFrame:
    df = df.reset_index()
    df["share_of_accidents"] = df["accidents"] / total
    for c in ["avg_severity", "severe_rate", "share_of_accidents", "avg_distance_mi"]:
        df[c] = df[c].astype(float).round(4)
    df["median_duration_min"] = df["median_duration_min"].round(1)
    return df


def aggregate(fact: pd.DataFrame) -> dict[str, pd.DataFrame]:
    total = len(fact)
    t = {}

    # Q1 — when do accidents happen?
    t["agg_hour_weekday"] = _finish(_summary(fact.groupby(["day_of_week", "hour", "time_of_day"])), total)
    t["agg_daily"] = _finish(_summary(fact.groupby(["start_date", "day_of_week", "is_weekend"])), total)
    t["agg_monthly"] = _finish(_summary(fact.groupby(["year_month", "month_name"])), total)

    # Q2 — where?
    city = fact.groupby(["region", "state", "state_name", "county", "city"])
    city_df = _finish(_summary(city), total)
    centroid = city.agg(lat=("lat", "mean"), lng=("lng", "mean")).reset_index(drop=True)
    city_df["lat_lng"] = centroid["lat"].round(4).astype(str) + "," + centroid["lng"].round(4).astype(str)
    city_df["rank_by_accidents"] = city_df["accidents"].rank(ascending=False, method="min").astype(int)
    t["agg_city"] = city_df.sort_values("accidents", ascending=False)
    t["agg_county"] = _finish(_summary(fact.groupby(["state", "state_name", "county"])), total) \
        .sort_values("accidents", ascending=False)
    t["agg_state"] = _finish(_summary(fact.groupby(["region", "state", "state_name"])), total)

    # Q3 — weather
    t["agg_weather"] = _finish(_summary(fact.groupby("weather_group")), total)
    t["agg_weather_condition"] = _finish(_summary(fact.groupby(["weather_group", "weather_condition"])), total) \
        .sort_values("accidents", ascending=False)
    band_frames = []
    for band in ["visibility_band", "temperature_band", "wind_band"]:
        b = _finish(_summary(fact.groupby(band)), total).rename(columns={band: "band"})
        b.insert(0, "factor", band.replace("_band", ""))
        band_frames.append(b)
    t["agg_weather_bands"] = pd.concat(band_frames, ignore_index=True)

    # Q4 — road features (POI)
    rows = []
    base_rate = fact["is_severe"].mean()
    for col in [c.lower() for c in POI_COLUMNS]:
        present = fact[fact[col]]
        absent = fact[~fact[col]]
        rows.append({
            "road_feature": col,
            "accidents_with_feature": len(present),
            "share_of_accidents": round(len(present) / total, 4),
            "severe_rate_with": round(present["is_severe"].mean(), 4) if len(present) else None,
            "severe_rate_without": round(absent["is_severe"].mean(), 4) if len(absent) else None,
            "avg_severity_with": round(present["severity"].mean(), 4) if len(present) else None,
            "severity_lift_vs_overall": round(present["is_severe"].mean() / base_rate, 3) if len(present) else None,
        })
    t["agg_road_feature"] = pd.DataFrame(rows).sort_values("accidents_with_feature", ascending=False)

    # Q5 — day vs night
    t["agg_day_night"] = _finish(_summary(fact.groupby(["day_night", "time_of_day"])), total)

    # Q6 — impact by severity
    sev = fact.groupby("severity_label").agg(
        accidents=("accident_id", "count"),
        median_duration_min=("duration_min", "median"),
        avg_duration_min_capped=("duration_min_capped", "mean"),
        p90_duration_min=("duration_min", lambda s: s.quantile(0.9)),
        median_distance_mi=("distance_mi", "median"),
        avg_distance_mi_capped=("distance_mi_capped", "mean"),
    ).reset_index().round(2)
    sev["share_of_accidents"] = (sev["accidents"] / total).round(4)
    t["agg_severity_impact"] = sev

    # Q7 — risk factor combinations
    combo = _finish(_summary(fact.groupby(["risk_combo", "day_night", "is_wet", "junction"])), total)
    combo["severity_lift_vs_overall"] = (combo["severe_rate"] / base_rate).round(3)
    t["agg_risk_combo"] = combo.sort_values("severe_rate", ascending=False)

    # KPI cards
    t["kpi_summary"] = pd.DataFrame([{
        "total_accidents": total,
        "date_from": str(fact["start_time"].min().date()),
        "date_to": str(fact["start_time"].max().date()),
        "states": fact["state"].nunique(),
        "cities": fact["city"].nunique(),
        "avg_severity": round(fact["severity"].mean(), 3),
        "severe_rate": round(base_rate, 4),
        "median_duration_min": round(fact["duration_min"].median(), 1),
        "avg_distance_mi": round(fact["distance_mi_capped"].mean(), 3),
        "night_share": round((fact["day_night"] == "Night").mean(), 4),
        "wet_weather_share": round(fact["is_wet"].mean(), 4),
    }])
    return t


FACT_COLUMNS = [
    "accident_id", "source", "severity", "severity_label", "is_severe",
    "start_time", "end_time", "start_date", "year", "month", "year_month", "month_name",
    "day_of_week", "is_weekend", "hour", "time_of_day",
    "duration_min", "duration_min_capped", "is_duration_outlier",
    "distance_mi", "distance_mi_capped", "is_distance_outlier",
    "street", "city", "county", "state", "state_name", "region", "zipcode", "timezone",
    "lat", "lng", "lat_lng",
    "temperature_f", "humidity_pct", "pressure_in", "visibility_mi", "wind_speed_mph", "wind_direction",
    "weather_condition", "weather_group", "is_wet", "visibility_band", "temperature_band", "wind_band",
    "day_night", "civil_twilight",
    *[c.lower() for c in POI_COLUMNS], "poi_count", "risk_combo", "description",
]


def run() -> dict[str, int]:
    engine = config.get_engine()
    config.ensure_schemas(engine)

    log.info("Reading %s.%s", config.RAW_SCHEMA, config.RAW_TABLE)
    raw = read_table(engine, config.RAW_SCHEMA, config.RAW_TABLE)
    log.info("Raw rows: %s", f"{len(raw):,}")

    dim_state = build_dim_state()
    fact = join_state(add_features(clean(raw)), dim_state)[FACT_COLUMNS]
    log.info("Fact rows after cleaning: %s", f"{len(fact):,}")

    tables = {"dim_state": dim_state, "fact_accidents": fact, **aggregate(fact)}
    written = {}
    for name, frame in tables.items():
        written[name] = write_table(frame, engine, config.PROD_SCHEMA, name)
        log.info("  production.%-24s %8s rows", name, f"{written[name]:,}")
    return written


if __name__ == "__main__":
    run()
