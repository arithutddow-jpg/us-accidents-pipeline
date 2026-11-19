# US Accidents Data Pipeline (Kaggle → PostgreSQL → Google Sheets → Data Studio)

ไปป์ไลน์ข้อมูลอัตโนมัติสำหรับชุดข้อมูล **[US Accidents (2016 - 2023)](https://www.kaggle.com/datasets/sobhanmoosavi/us-accidents)**
(ไฟล์ `US_Accidents_March23.csv` ตัดมา 120,000 แถวแรก) อัปเดตข้อมูลทั้งหมดได้ด้วยคำสั่งเดียว:

```bash
python run_pipeline.py
```

## สถาปัตยกรรม (Architecture)

```
 Kaggle CSV ──► ingest.py ──► PostgreSQL (Docker)          transform.py (pandas)
 (120k rows)    pandas +       schema raw_data      ──────► clean / features / join / aggregate
                SQLAlchemy     us_accidents_march23              │
                                                                 ▼
 Data Studio ◄── Google Sheets ◄── publish.py ◄──── schema production
 (dashboard)     (1 tab/table)     gspread            fact_accidents + agg_* + kpi_summary
```

| ขั้นตอน | ไฟล์ | ทำอะไร |
|---|---|---|
| Extract & Load | `ingest.py` | อ่าน CSV (ถ้าไม่มีไฟล์จะดาวน์โหลดจาก Kaggle API แล้วตัด 120k แถว) → โหลดดิบทุกคอลัมน์เป็น text ลง `raw_data.us_accidents_march23` (ใช้ COPY) |
| Transform | `transform.py` | Cleaning, Feature Engineering, Join กับ `dim_state`, Aggregation → เขียนลง schema `production` |
| Publish | `publish.py` | อ่านตารางใน `production` → เขียนลง Google Sheets ทีละ worksheet (ตาราง fact เขียนเป็น chunk) |
| Orchestrate | `run_pipeline.py` | เรียก ingest → transform → publish ตามลำดับ หยุดทันทีถ้าขั้นใดล้มเหลว |

ไฟล์อื่น: `config.py` (อ่าน `.env` + สร้าง DB engine), `db_utils.py` (เขียน DataFrame ด้วย COPY), `sql/init.sql` (สร้าง schema), `docker-compose.yml`

## การแปลงข้อมูล (transform.py)

**Cleaning**
- แปลงชนิดข้อมูล: `Start_Time`/`End_Time` → datetime (`format="mixed"` เพราะบางแถวมี nanoseconds), `Severity` → int, ตัวเลขสภาพอากาศ → float, คอลัมน์ POI 13 ตัว `"True"/"False"` → boolean
- ตัดคอลัมน์ที่ใช้ไม่ได้: `End_Lat`, `End_Lng` (ว่าง 100%), `Wind_Chill(F)` (ว่าง 96%), `Precipitation(in)` (ว่าง 93%), `Country` (ค่าเดียว)
- Missing values: `Wind_Speed` = 0 เมื่อ `Wind_Direction = Calm` ที่เหลือเติมค่า median ของเดือนนั้น; Temperature / Humidity / Pressure / Visibility เติม median รายเดือน; ข้อความ (City, Weather_Condition ฯลฯ) เติม `Unknown`; `Sunrise_Sunset` เติมจากชั่วโมง
- Outliers: ระยะเวลา (`End-Start`) และระยะทาง ถูก cap ที่เปอร์เซ็นไทล์ 99.9 (คอลัมน์ `*_capped`) และติด flag `is_*_outlier` (เช่น ระยะเวลา 7,800 นาที); ระยะเวลา ≤ 0 ถูกตัดทิ้ง

**Feature engineering**: `hour`, `day_of_week`, `is_weekend`, `time_of_day`, `year_month`, `severity_label`, `is_severe` (ระดับ ≥ 3), `duration_min`, `weather_group` (จัด 46 สภาพอากาศเป็น 7 กลุ่ม), `is_wet`, `visibility_band`, `temperature_band`, `wind_band`, `poi_count`, `lat_lng` (สำหรับแผนที่), `risk_combo` (กลางวัน/คืน × ฝน × ทางแยก)

**Joining**: join กับตาราง dimension `dim_state` (รหัสรัฐ → ชื่อรัฐ, ภูมิภาค)

**ตารางใน schema `production`**

| ตาราง | ตอบคำถาม |
|---|---|
| `fact_accidents` | ข้อมูลระดับแถวที่ทำความสะอาดแล้ว (ใช้กับ filter / แผนที่) |
| `kpi_summary` | ตัวเลขสรุป (scorecards) |
| `agg_hour_weekday`, `agg_daily`, `agg_monthly` | Q1 ช่วงเวลาที่เกิดอุบัติเหตุ |
| `agg_state`, `agg_county`, `agg_city` | Q2 พื้นที่เสี่ยง |
| `agg_weather`, `agg_weather_condition`, `agg_weather_bands` | Q3 สภาพอากาศ |
| `agg_road_feature` | Q4 ลักษณะถนน |
| `agg_day_night` | Q5 กลางวัน vs กลางคืน |
| `agg_severity_impact` | Q6 ผลกระทบตามระดับความรุนแรง |
| `agg_risk_combo` | Q7 ปัจจัยเสี่ยงรวม |

## วิธีรันโปรเจค

### 1. สิ่งที่ต้องมี
- Python 3.10+
- Docker Desktop
- บัญชี Google (สำหรับ Google Sheets / Data Studio)

### 2. ติดตั้ง
```bash
git clone <repo-url>
cd us-accidents-pipeline
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # macOS/Linux: cp .env.example .env
```

### 3. ข้อมูลจาก Kaggle
เลือกอย่างใดอย่างหนึ่ง:
- **ดาวน์โหลดเอง**: วาง `US_Accidents_March23_120k.csv` ไว้ที่ `data/` หรือ
- **ให้สคริปต์ดาวน์โหลด**: ไปที่ Kaggle → Settings → API → *Create New Token* แล้ววาง `kaggle.json` ไว้ที่ `~/.kaggle/kaggle.json` (Windows: `C:\Users\<you>\.kaggle\kaggle.json`) — `ingest.py` จะดาวน์โหลด (~650 MB zip) และตัด 120,000 แถวแรกให้อัตโนมัติ

### 4. เปิด PostgreSQL
```bash
docker compose up -d
```
ฐานข้อมูลจะอยู่ที่ `localhost:5433` (user `de_user`, password `de_password`, db `us_accidents` — แก้ได้ใน `.env`)

### 5. ตั้งค่า Google API Credentials
1. ไปที่ [Google Cloud Console](https://console.cloud.google.com/) → สร้าง Project ใหม่
2. **APIs & Services → Library** → เปิดใช้ **Google Sheets API** และ **Google Drive API**
3. **APIs & Services → Credentials → Create credentials → Service account** → ตั้งชื่อ → Done
4. คลิก service account ที่สร้าง → แท็บ **Keys → Add key → Create new key → JSON** → ไฟล์จะถูกดาวน์โหลด
5. เปลี่ยนชื่อไฟล์เป็น `credentials.json` แล้ววางไว้ที่โฟลเดอร์โปรเจค (**ไฟล์นี้อยู่ใน `.gitignore` ห้าม commit**)
6. สร้าง Google Sheet เปล่าใน Google Drive → กด **Share** → ใส่อีเมลของ service account (`...@<project>.iam.gserviceaccount.com` ดูได้ใน `credentials.json` ช่อง `client_email`) ให้สิทธิ์ **Editor**
7. คัดลอก Sheet ID จาก URL `https://docs.google.com/spreadsheets/d/<SHEET_ID>/edit` ใส่ใน `.env` → `GOOGLE_SHEET_ID=...`

### 6. รันไปป์ไลน์
```bash
python run_pipeline.py                  # ingest -> transform -> publish
python run_pipeline.py --skip-publish   # เฉพาะในเครื่อง (ไม่ส่งขึ้น Google Sheets)
python run_pipeline.py --only transform # รันขั้นเดียว
python publish.py --dry-run             # ตรวจจำนวน cell โดยไม่เชื่อม Google
```
ใช้เวลาประมาณ 15 วินาทีสำหรับ ingest + transform และ 1–3 นาทีสำหรับ publish

### 7. Dashboard
ดูวิธีสร้างแต่ละกราฟใน [docs/dashboard_guide.md](docs/dashboard_guide.md)

## ข้อควรระวัง
- Google Sheets จำกัด 10 ล้าน cell ต่อไฟล์: `publish.py` ส่งตาราง fact เพียง 29 คอลัมน์ (~3.5 ล้าน cell รวมทุกแท็บ) และหยุดก่อนถ้าเกิน 95% ของขีดจำกัด
- ข้อมูล 120k แถวนี้เป็นแถวแรกของไฟล์เต็ม จึงครอบคลุม ก.พ. 2016 – ม.ค. 2017 และ ~96% เป็นรัฐ California
- `Distance(mi)` ในตัวอย่างนี้ ≤ 0.01 ไมล์ถึง 99.6% ของแถว จึงไม่เหมาะใช้สรุปผลกระทบเชิงระยะทาง

## โครงสร้างไฟล์
```
├── ingest.py  transform.py  publish.py  run_pipeline.py
├── config.py  db_utils.py
├── docker-compose.yml  sql/init.sql
├── requirements.txt  .env.example  .gitignore
├── data/            (CSV — ไม่ถูก commit)
└── docs/dashboard_guide.md
```
