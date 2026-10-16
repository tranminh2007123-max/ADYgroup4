import pathlib
import sys
import warnings

import pandas as pd
import pyodbc
import requests
import sqlalchemy as sa

warnings.filterwarnings("ignore")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# SECTION 00 · Thiết lập thư mục và SQL Server
ROOT = pathlib.Path(__file__).resolve().parent
RAW_DIR = ROOT / "data" / "raw"
PROC_DIR = ROOT / "data" / "processed"
OUTPUT_DIR = ROOT / "output"

for folder in (RAW_DIR, PROC_DIR, OUTPUT_DIR):
    folder.mkdir(parents=True, exist_ok=True)

SERVER = r"localhost"  # SQL Server mặc định trên chính máy đang chạy code
DATABASE = "malaysia_inflation"
DRIVER = next(
    (d for d in ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server")
     if d in pyodbc.drivers()),
    None,
)
if DRIVER is None:
    raise RuntimeError("Cần cài ODBC Driver 17 hoặc 18 for SQL Server.")


def connection_string(database):
    return (
        f"DRIVER={{{DRIVER}}};SERVER={SERVER};DATABASE={database};"
        "Trusted_Connection=yes;TrustServerCertificate=yes;"
    )


with pyodbc.connect(connection_string("master"), autocommit=True) as conn:
    conn.execute(f"IF DB_ID(N'{DATABASE}') IS NULL CREATE DATABASE [{DATABASE}]")

url = sa.engine.URL.create(
    "mssql+pyodbc", query={"odbc_connect": connection_string(DATABASE)}
)
engine = sa.create_engine(url, fast_executemany=True, pool_pre_ping=True)


def sql(query):
    """Chạy câu lệnh SELECT và trả về DataFrame."""
    with engine.connect() as conn:
        return pd.read_sql_query(sa.text(query), conn)


def sql_dtypes(dataframe):
    """Dùng NVARCHAR để SQL Server giữ nguyên tiếng Việt."""
    return {
        column: sa.types.NVARCHAR(length=255)
        for column in dataframe.select_dtypes(include=["object", "string"]).columns
    }


# SECTION 01 · Thu thập dữ liệu từ OpenDOSM API
API_URL = "https://api.data.gov.my/data-catalogue"

COICOP_MAP = {
    "01": "Thực phẩm và đồ uống",       "02": "Rượu bia và thuốc lá",
    "03": "Quần áo và giày dép",        "04": "Nhà ở, nước, điện, gas và nhiên liệu",
    "05": "Đồ dùng và thiết bị gia đình", "06": "Y tế",
    "07": "Giao thông",                 "08": "Thông tin và truyền thông",
    "09": "Giải trí, thể thao và văn hóa", "10": "Giáo dục",
    "11": "Nhà hàng và dịch vụ lưu trú", "12": "Bảo hiểm và dịch vụ tài chính",
    "13": "Chăm sóc cá nhân và hàng hóa khác",
}


def goi_api(dataset, **filters):
    params = {"id": dataset, "limit": 100_000, **filters}
    response = requests.get(API_URL, params=params, timeout=120)
    response.raise_for_status()
    payload = response.json()
    records = payload.get("data", payload) if isinstance(payload, dict) else payload
    return pd.DataFrame(records)


def thu_thap_du_lieu():
    national = goi_api("cpi_headline")
    malaysia = national[national["division"].eq("overall")].assign(state="Malaysia")
    states = goi_api("cpi_state", filter="overall@division")

    cpi = (
        pd.concat([malaysia, states], ignore_index=True)
        [["date", "state", "division", "index"]]
        .rename(columns={"index": "index_val"})
    )

    category = national[national["division"].ne("overall")].copy()
    category["category"] = category["division"].map(COICOP_MAP)
    category = category[["date", "division", "category", "index"]].rename(
        columns={"index": "index_val"}
    )

    population = goi_api("population_state")
    return cpi, category, population


# SECTION 02 · Lưu dữ liệu thô vào CSV và SQL Server
def luu_du_lieu_tho(cpi, category, population):
    datasets = {
        "raw_cpi_headline": (cpi, "cpi_headline.csv"),
        "raw_cpi_category": (category, "cpi_category.csv"),
        "raw_population": (population, "population_state.csv"),
    }

    for table, (dataframe, filename) in datasets.items():
        dataframe.to_csv(RAW_DIR / filename, index=False, encoding="utf-8-sig")
        dataframe.to_sql(
            table, engine, schema="dbo", if_exists="replace",
            index=False, chunksize=1_000, dtype=sql_dtypes(dataframe),
        )

    print(sql("""
        SELECT 'raw_cpi_headline' AS table_name, COUNT(*) AS row_count
        FROM dbo.raw_cpi_headline
        UNION ALL
        SELECT 'raw_cpi_category', COUNT(*) FROM dbo.raw_cpi_category
        UNION ALL
        SELECT 'raw_population', COUNT(*) FROM dbo.raw_population
    """).to_string(index=False))


# SECTION 03 · Làm sạch toàn bộ dữ liệu và bàn giao
def lam_sach_du_lieu():
    cpi = sql("SELECT * FROM dbo.raw_cpi_headline")
    category = sql("SELECT * FROM dbo.raw_cpi_category")
    population = sql("SELECT * FROM dbo.raw_population")
    rows_before = [len(cpi), len(category), len(population)]

    # 1. CPI tổng theo quốc gia và bang
    cpi["date"] = pd.to_datetime(cpi["date"], errors="coerce")
    cpi["index_val"] = pd.to_numeric(cpi["index_val"], errors="coerce")
    cpi["state"] = (
        cpi["state"].astype("string").str.strip()
        .replace("", pd.NA).fillna("Malaysia")
        .str.replace(r"^W\.P\.\s*", "", regex=True)
    )
    cpi = (
        cpi[cpi["index_val"].between(50, 300)]
        .dropna().drop_duplicates()
        .sort_values(["state", "date"]).reset_index(drop=True)
    )

    # 2. CPI theo nhóm hàng COICOP
    category["date"] = pd.to_datetime(category["date"], errors="coerce")
    category["index_val"] = pd.to_numeric(category["index_val"], errors="coerce")
    for column in ["division", "category"]:
        category[column] = category[column].astype("string").str.strip()
    category = (
        category[category["index_val"].gt(0) & category["index_val"].le(300)]
        .dropna().drop_duplicates()
        .sort_values(["division", "date"]).reset_index(drop=True)
    )

    # 3. Dân số theo bang
    population["date"] = pd.to_datetime(population["date"], errors="coerce")
    population["population"] = pd.to_numeric(population["population"], errors="coerce")
    for column in ["state", "age", "sex", "ethnicity"]:
        population[column] = population[column].astype("string").str.strip()
    population["state"] = population["state"].str.replace(
        r"^W\.P\.\s*", "", regex=True
    )
    population = (
        population[population["population"].ge(0)]
        .dropna().drop_duplicates()
        .sort_values(["state", "date", "sex", "age", "ethnicity"])
        .reset_index(drop=True)
    )

    clean_data = {
        "cpi_clean": (cpi, "cpi_clean.csv"),
        "cpi_category_clean": (category, "cpi_category_clean.csv"),
        "population_clean": (population, "population_clean.csv"),
    }
    for table, (dataframe, filename) in clean_data.items():
        dataframe.to_sql(
            table, engine, schema="dbo", if_exists="replace",
            index=False, chunksize=1_000, dtype=sql_dtypes(dataframe),
        )
        dataframe.to_csv(PROC_DIR / filename, index=False, encoding="utf-8-sig")

    # Bản Excel để cột age như 10-14 không bị tự đổi thành ngày 14-Oct.
    population.to_excel(
        PROC_DIR / "population_clean_excel.xlsx", index=False, freeze_panes=(1, 0)
    )

    print("\nKết quả làm sạch:")
    for (table, (dataframe, _)), before in zip(clean_data.items(), rows_before):
        print(f"{table:<22}: {before:>6,} → {len(dataframe):>6,} dòng")
    print("\n3 dòng đầu của cpi_clean:")
    print(cpi.head(3).to_string(index=False))


if __name__ == "__main__":
    try:
        print("1. Thu thập dữ liệu")
        df_cpi, df_category, df_population = thu_thap_du_lieu()

        print("\n2. Lưu dữ liệu thô")
        luu_du_lieu_tho(df_cpi, df_category, df_population)

        print("\n3. Làm sạch dữ liệu")
        lam_sach_du_lieu()
        print("\nPipeline của Trần Quang Minh đã hoàn tất.")
    finally:
        engine.dispose()
