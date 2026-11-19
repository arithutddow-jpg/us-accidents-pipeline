# Data Studio Dashboard Guide

## 1. เชื่อมแหล่งข้อมูล
1. เปิด <https://datastudio.google.com> → **Create → Report**
2. **Add data → Google Sheets** → เลือก Spreadsheet ที่ `publish.py` เขียนไว้ → เลือก worksheet → ติ๊ก *Use first row as headers* → **Add**
3. ทำซ้ำสำหรับแต่ละแท็บที่ใช้ (แนะนำ: `kpi_summary`, `fact_accidents`, `agg_hour_weekday`, `agg_city`, `agg_weather`, `agg_weather_bands`, `agg_road_feature`, `agg_day_night`, `agg_severity_impact`, `agg_risk_combo`)
4. ตรวจชนิดฟิลด์ (Resource → Manage added data sources → Edit):
   - `start_time` → *Date & Time*, `start_date` → *Date*
   - `lat_lng` → *Geo → Latitude, Longitude*
   - `severe_rate`, `share_of_accidents`, `severe_rate_with`, `severe_rate_without` → *Percent*
   - `hour` → *Number* (ไม่ใช่ Sum ในแกน)
5. Share → **Anyone with the link can view**

## 2. Layout แนะนำ (หน้าเดียว 1200×2000 หรือ 2 หน้า)

**แถวบน — Scorecards** (`kpi_summary`): total_accidents, avg_severity, severe_rate, median_duration_min, night_share
**Filter controls** (`fact_accidents`): Date range (`start_date`), Drop-down `state_name`, `weather_group`, `severity_label`

## 3. ห้า Visualization หลัก (ตอบคำถามธุรกิจ)

| # | คำถาม | กราฟ | Data source | Dimension | Metric |
|---|---|---|---|---|---|
| 1 | เกิดอุบัติเหตุมากที่สุดช่วงใด | **Pivot table + heatmap** | `agg_hour_weekday` | Row: `day_of_week`, Column: `hour` | SUM `accidents` (Conditional formatting: heatmap) |
| 1b | แนวโน้มรายเดือน | **Time series / Line** | `agg_monthly` | `year_month` | SUM `accidents`, AVG `severe_rate` (แกนขวา) |
| 2 | พื้นที่เสี่ยง | **Google Maps bubble map** + **Bar (Top 15 cities)** | `agg_city` | `lat_lng` / `city` | Size: `accidents`, Color: `severe_rate` |
| 3 | สภาพอากาศกับความรุนแรง | **Combo chart** (bar + line) | `agg_weather` | `weather_group` | Bar: `accidents`, Line: `severe_rate` |
| 3b | ทัศนวิสัย / อุณหภูมิ | **Column chart** + filter `factor` | `agg_weather_bands` | `band` | `severe_rate` |
| 4 | ลักษณะถนน | **Clustered bar** | `agg_road_feature` | `road_feature` | `severe_rate_with` vs `severe_rate_without` |
| 5 | กลางวัน vs กลางคืน | **Donut** + **Stacked column** | `agg_day_night` | `day_night` / `time_of_day` | `accidents`, `severe_rate` |
| 6 | ผลกระทบตามความรุนแรง | **Table with bars** | `agg_severity_impact` | `severity_label` | `accidents`, `median_duration_min`, `p90_duration_min` |
| 7 | คอมโบปัจจัยเสี่ยง | **Horizontal bar (sorted)** | `agg_risk_combo` | `risk_combo` | `severe_rate` (+ reference line = overall 45.1%) |

> ข้อกำหนดขั้นต่ำคือ 5 visualization — #1, #2, #3, #4, #5 ครอบคลุมแล้ว ส่วน #6, #7 เป็นส่วนเสริม

## 4. ตัวเลขที่ได้จากการรันจริง (ใช้ตรวจว่ากราฟถูกต้อง)
- รวม 120,000 เหตุการณ์, 8 ก.พ. 2016 – 26 ม.ค. 2017, 4 รัฐ, 978 เมือง
- severe_rate (ระดับ ≥ 3) = 45.1%, ระยะเวลากระทบ median = 44.5 นาที
- ชั่วโมงสูงสุด: 11:00 (9,313) และ 20:00 (9,076); วันพฤหัสสูงสุด (22,039) เสาร์–อาทิตย์ต่ำกว่าครึ่งของวันธรรมดา
- เมืองสูงสุด: Los Angeles 12,727, Sacramento 5,223, San Diego 4,074 (San Diego severe_rate 68%, Oakland 78%)
- Traffic signal: severe_rate 16% vs 49% ไม่มีสัญญาณไฟ; Junction: 59% vs 44%
- Thunderstorm / Heavy Rain severe_rate 57% (สูงสุด) แต่มีเพียง 248 เหตุการณ์
- Risk combo สูงสุด: Day | Dry | Junction 59.7% (lift 1.32×)
