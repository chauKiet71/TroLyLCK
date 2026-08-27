# Telegram Memory Agent

Trợ lý Telegram cá nhân có thể ghi nhớ tin nhắn, hình ảnh, tài liệu, media và đường link; sau đó tìm lại bằng câu hỏi tự nhiên. Metadata, nội dung trích xuất và vector được lưu trên Neon PostgreSQL. File Telegram được giữ bằng `file_id` để gửi lại nhanh, đồng thời có một bản sao trong thư mục `data/files`.

## Khả năng hiện tại

- Lưu và tìm lại tin nhắn văn bản.
- Phát hiện, tải và đọc nội dung các URL công khai; chặn URL mạng nội bộ để tránh SSRF.
- Lưu ảnh và dùng AI để mô tả ảnh, OCR chữ/số nhìn thấy.
- Trích xuất nội dung PDF, DOCX, XLSX/XLSM, PPTX, TXT, Markdown, CSV, JSON, HTML và một số định dạng văn bản khác.
- Lưu và gửi lại document, photo, audio, video, voice, animation, video note và sticker.
- Tìm kiếm kết hợp `pgvector` (ngữ nghĩa) và PostgreSQL full-text/keyword.
- Tìm và xóa từng mục bằng `/forget` với hai bước chọn và xác nhận; bản sao file cục bộ
  liên quan cũng được dọn an toàn.
- Tự chạy migration idempotent khi khởi động: extension, bảng, cột và index còn thiếu sẽ được tạo.
- Cô lập dữ liệu theo Telegram user ID.

## Kiến trúc dữ liệu

- `memories`: một bản ghi cho mỗi tin nhắn, file, media hoặc URL.
- `memory_chunks`: nội dung được chia đoạn cùng embedding 1536 chiều.
- `parent_id`: liên kết URL với tin nhắn Telegram chứa URL đó.
- `telegram_file_id`: dùng để yêu cầu Telegram gửi lại media mà không cần upload lại.
- `storage_path`: bản sao cục bộ để dự phòng.

Neon hỗ trợ `pgvector`; bot tự chạy `CREATE EXTENSION IF NOT EXISTS vector`. Tài khoản kết nối cần có quyền tạo extension/schema ở lần chạy đầu.

## Cài đặt

Yêu cầu Python 3.11 trở lên.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Điền các biến trong `.env`:

```dotenv
TELEGRAM_BOT_TOKEN=token_lay_tu_BotFather
DATABASE_URL=postgresql://USER:PASSWORD@HOST/DATABASE?sslmode=require&channel_binding=require
OPENAI_API_KEY=sk-...
ALLOWED_TELEGRAM_USER_IDS=123456789
```

`OPENAI_API_KEY` có thể để trống, nhưng khi đó bot chỉ tìm bằng từ khóa, không hiểu nội dung ảnh và câu trả lời sẽ đơn giản hơn. Nên đặt `ALLOWED_TELEGRAM_USER_IDS` để người khác không thể dùng bot và đọc bộ nhớ của bạn. Gửi `/id` cho bot để xem ID sau lần chạy đầu; trước đó có thể tạm để danh sách trống.

## Chạy bot

```powershell
memory-bot
```

Hoặc:

```powershell
python -m memory_bot.main
```

Bot đang dùng long polling, vì vậy không cần domain hay webhook cho MVP.

## Cách sử dụng

- Gửi một câu như `Doanh thu tháng 8 là 500 triệu` → bot ghi nhớ.
- Tin nhắn có cụm `đây là` (không phân biệt chữ hoa/thường) → luôn ghi nhớ.
- Tin nhắn có từ độc lập `k`, `ko` hoặc `không` → tìm trong kho, trừ khi đã có `đây là`.
- Gửi PDF/Excel/Word/ảnh → bot lưu file và lập chỉ mục nội dung đọc được.
- Gửi một URL → bot lưu URL, tiêu đề và nội dung trang.
- Hỏi `Hình như tôi có báo cáo tài chính tháng 8 đúng không?` → bot trả lời và gửi lại file phù hợp.
- `/find báo cáo tài chính tháng 8` → buộc tìm kiếm, bỏ qua bước phân loại ý định.
- `/recent` → xem 10 mục gần nhất.
- `/forget báo cáo tài chính tháng 8` → chọn một kết quả rồi xác nhận trước khi xóa vĩnh viễn.

## Chạy bằng Docker

```powershell
docker build -t telegram-memory-agent .
docker run --env-file .env -v memory-agent-data:/app/data telegram-memory-agent
```

Volume `/app/data` phải được giữ lại khi nâng cấp container. Với triển khai serverless hoặc nhiều instance, nên thay `LocalStorage` bằng S3/R2/MinIO; Neon không nên dùng để chứa toàn bộ binary file lớn.

## Kiểm thử

```powershell
pytest
ruff check .
```

## Giới hạn MVP

- PDF scan không có text layer chỉ được lưu, chưa OCR từng trang. Ảnh Telegram được phân tích bằng model có khả năng nhìn ảnh.
- Nội dung trang web phụ thuộc quyền truy cập; trang yêu cầu đăng nhập hoặc render hoàn toàn bằng JavaScript có thể chỉ lưu được URL.
- File gốc hiện được sao lưu trên ổ đĩa của máy chạy bot. Khi chạy production cần volume bền vững hoặc object storage.
- Bot chưa hỗ trợ xóa hàng loạt hoặc khôi phục mục đã xóa.
