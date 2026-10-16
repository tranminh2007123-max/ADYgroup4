# Phân tích Lạm phát Malaysia — Phần Trần Quang Minh

Thư mục này chỉ chứa Section 00–03 của pipeline:

**Thiết lập → Thu thập API → Raw Storage → Cleaning**

## Nội dung chính

- `ThanhVien1_DataEngineer/thanh_vien_1_data_engineer.ipynb`: notebook gồm đúng 8 cell cho Section 00–03.
- `ThanhVien1_DataEngineer/data_engineer.py`: phiên bản Python chạy độc lập.
- `data/raw/`: ba CSV dữ liệu thô lấy trực tiếp từ OpenDOSM API.
- `data/processed/`: ba CSV đã làm sạch và một bản Excel an toàn khi mở trực tiếp.
- `output/`: thư mục trống được chuẩn bị cho sản phẩm đầu ra về sau.

## Yêu cầu

- Python 3.10 trở lên.
- Microsoft SQL Server 2022.
- ODBC Driver 17 hoặc 18 for SQL Server.
- Windows Authentication có quyền tạo database.

## Cài đặt

```powershell
pip install -r requirements.txt
```

## Cấu hình SQL Server

Mặc định notebook và `data_engineer.py` kết nối SQL Server trên chính máy đang chạy:

```python
SERVER = r'localhost'
```

Nếu máy dùng SQL Server Express, đổi thành:

```python
SERVER = r'localhost\SQLEXPRESS'
```

Mỗi thành viên dùng `localhost` sẽ có một database riêng trên máy của họ. `localhost` không cho nhiều máy truy cập chung một SQL Server qua mạng.

Database `malaysia_inflation` sẽ được tạo tự động nếu chưa tồn tại.

## Chạy

Chạy file Python:

```powershell
python ThanhVien1_DataEngineer\data_engineer.py
```

Hoặc mở notebook và chạy lần lượt Section 00, 01, 02, 03.

## Sản phẩm bàn giao

Các bảng SQL Server:

- `dbo.raw_cpi_headline`
- `dbo.raw_cpi_category`
- `dbo.raw_population`
- `dbo.cpi_clean`
- `dbo.cpi_category_clean`
- `dbo.population_clean`

Các file sạch:

- `data/processed/cpi_clean.csv`
- `data/processed/cpi_category_clean.csv`
- `data/processed/population_clean.csv`
- `data/processed/population_clean_excel.xlsx`: bản xem bằng Excel, giữ `age = 10-14` ở dạng Text.

Xem kết quả kiểm tra và thông tin bàn giao tại `BAN_GIAO.md`.

## Mở CSV trong Excel

Các file CSV dùng UTF-8 BOM để giữ tiếng Việt. Cột `division` chứa mã `01`–`13`; Excel có thể tự hiển thị `01` thành `1` vì nhận dạng cột này là số. Dữ liệu gốc không bị mất số `0`.

Nếu cần giữ cách hiển thị `01`, dùng **Data → From Text/CSV** trong Excel và đặt kiểu dữ liệu của cột `division` là **Text**.

Cột `age` trong `population_clean.csv` có giá trị như `10-14`. Khi mở CSV trực tiếp,
Excel có thể tự hiển thị thành `14-Oct` dù dữ liệu gốc vẫn đúng. Để xem bằng Excel,
hãy mở `data/processed/population_clean_excel.xlsx`. Thành viên 2 và 3 vẫn nên dùng
CSV hoặc bảng `dbo.population_clean` khi phân tích bằng Python/SQL.
