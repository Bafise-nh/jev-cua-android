# Đo tốc độ: Jev-CUA vs tự điều khiển (Windows MCP)

Đo ngày 23/10/2026 trên cùng máy (emulator `DeliFood_Test`, 1080×2400), cùng bài:
**Tổng quan → tab Thực đơn → tab Ví**, xác nhận bằng chữ "Ví & Thu nhập" trên
màn hình.

## Kết quả

| Cách | Thời gian | Ghi chú |
|---|---|---|
| Tôi + Windows MCP (3 ảnh, 2 click) | **39 s** | phải tự tính tỉ lệ cửa sổ giả lập |
| Jev-CUA gọi API mỗi bước | 35.3 s | 3 bước, trễ API 7–17 s/bước |
| Jev-CUA + cache quyết định | 12.9 s | 0 ms/bước quyết định |
| Jev-CUA + replay theo nhãn | 5.5 s | 2 lần quan sát |
| **Jev-CUA + replay theo toạ độ** | **3.2 s** | 1 lần quan sát (kiểm tra cuối) |
| Jev bản đầu (hỏi "xong chưa?", ngưỡng 0.90) | 123 s ❌ | kẹt ở DONE 0.85–0.89 |

→ Chạy lặp lại nhanh hơn tự bấm **~12 lần**; vẫn giữ kiểm tra bằng chứng trên
màn hình.

## Thời gian từng pha

| Pha | Thời gian | Ghi chú |
|---|---|---|
| `uiautomator dump` | 2.2–2.3 s | sàn cứng: `--compressed`, `/dev/tty`, tắt animation đều không đổi |
| Gọi Jev | **7–17 s** | không phụ thuộc kích thước state (272 token = 10.7 s; 3.172 token = 6.9 s) → mạng/provider |
| Bấm | ~0.15 s | `adb shell input tap` |
| Kiểm tra `--expect` | ~0 ms | so chuỗi trên cây UI |

## Các bước tối ưu đã làm

1. **Bỏ phán đoán "đã xong" của model** → `--expect "<chữ phải thấy>"`.
   Lý do: xác suất DONE chỉ 0.85–0.89 (dưới ngưỡng an toàn 0.90) nên bị chặn;
   và test phải kết thúc bằng bằng chứng, không bằng lời model.
2. **Cache quyết định** theo trạng thái màn hình (chuẩn hoá số/giờ/số dư) →
   lần chạy lại 0 ms quyết định; màn hình đổi thì tự trượt cache.
3. **Lưu kế hoạch** (goal + expect → danh sách hành động) sau lần chạy thành
   công; lần sau phát lại, kiểm tra bằng chứng ở cuối.
4. **Phát lại theo toạ độ thiết bị** (kèm độ phân giải) → bỏ được lần quan sát
   đầu, chỉ còn 1 lần kiểm tra cuối.

## An toàn

- Phát lại sai (UI đổi, thiếu phần tử, sai kết quả) → **trả về None và quay lại
  vòng lặp đầy đủ**, không bao giờ báo xanh giả.
- Đã thử với `--expect` sai: dừng với `stuck: thiếu: <chuỗi>` sau 67 s, không
  crash, không pass nhầm.
- Hành động có hệ quả vẫn cần prob ≥ 0.85, conf ≥ 0.75, cho phép ≥ 0.90.

## Còn tối ưu được

- Thay `uiautomator` bằng cầu `integration_test` (lấy cây widget trong app):
  ~5–20 ms thay vì 2.2 s → mỗi bước còn dưới 1 s.
- Cache theo chuỗi hành động cho cả bộ test (hiện đã có theo từng goal).
