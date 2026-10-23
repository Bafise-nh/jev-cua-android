# jev-cua-android

Điều khiển app Android để **kiểm thử giao diện** bằng [Jev](https://typesafe.ai)
của TypeSafe, kết hợp `adb` và cây accessibility của Android.

Jev là **decision model**, không phải chat model: nó nhận `state` (chữ) + câu hỏi
dạng `choice` / `score` / `noul` và trả lời kèm xác suất. Repo này dựng vòng lặp
computer-use quanh nó:

```
quan sát (uiautomator) → state chữ → Jev chọn 1 hành động
      → guard theo xác suất → bấm/gõ/vuốt → quan sát lại
```

Jev **không** thấy ảnh và **không** tự bấm. Toàn bộ toạ độ, ảnh, quyết định thực
thi nằm ở phía máy bạn.

## Vì sao dùng cách này

- Jev rẻ và trả lời nhanh, không sinh văn bản — phù hợp chọn "bấm vào đâu tiếp".
- Vòng lặp chỉ định **một** hành động mỗi bước, có ngưỡng xác suất, nên sai thì
  dừng chứ không bấm bừa.
- Kết quả kiểm tra là **bằng chứng trên màn hình** (`--expect`), không phải lời
  model.

## Kết quả đo

Cùng một bài 2 tap trên emulator (xem [BENCHMARK.md](BENCHMARK.md)):

| Cách | Thời gian |
|---|---|
| Tự bấm bằng chuột (Windows MCP) | 39 s |
| Jev, gọi API mỗi bước | 35 s |
| Jev + cache quyết định | 13 s |
| **Jev + phát lại kế hoạch** | **3.2 s** |

## Yêu cầu

- Python 3.11+
- Android SDK platform-tools (`adb`) và một emulator/điện thoại đang chạy
- Key Jev: đặt biến môi trường `EXPERIENTIAL_API_KEY`
  (hoặc trỏ `JEV_AUTH_FILE` tới file `auth.json` của opencode)

```powershell
$env:EXPERIENTIAL_API_KEY = "..."        # hoặc setx để giữ lại
```

Không cần cài thêm gói Python nào — chỉ dùng thư viện chuẩn.

## Dùng nhanh

```powershell
# 1. Kiểm tra thiết bị + app đang mở
python -m cua.run --doctor

# 2. Xem state sẽ gửi Jev (không tốn phí, không bấm gì)
python -m cua.run --goal "Open the Menu tab" --package com.example.app --dry

# 3. Chạy thật: điền dữ liệu + điều kiện thành công
python -m cua.run --goal "Dang nhap quan demo" `
  --package com.delitech.deli_merchant `
  --fill "Email=demo@example.com" --fill "Mat khau=123456" `
  --expect "Tổng quan" --steps 15 --shots runs\shots
```

- `--fill "Nhãn=giá trị"`: chỉ gõ khi trường đó đang focus và nhãn khớp.
  `adb input text` không gõ được dấu tiếng Việt → dùng dữ liệu ASCII.
- `--expect "chữ"`: điều kiện thành công của test (lặp lại được). Không có
  `--expect` thì dùng câu hỏi `DONE` của Jev với ngưỡng 0.90.
- `--no-fast`: tắt phát lại kế hoạch đã học.
- Trace từng bước: `runs/run-*.jsonl`; cache: `runs/decisions.json`,
  kế hoạch: `runs/plans.json`.

## Phân loại kết quả test (không cần thiết bị)

```powershell
python -m cua.triage --workdir . --command "flutter test"
python -m cua.triage --workdir . --command "php artisan test"
```

Test xanh → thoát 0, không gọi API. Test đỏ → gửi phần cuối log cho Jev và in
`action` (pass / fix-code / fix-test / flaky / env / needs-human), `blocking`,
`evidence`.

## Cách hoạt động

1. **Quan sát**: `adb shell uiautomator dump` → các phần tử có id tạm `e1..eN`,
   nhãn, vai trò, vị trí thô, cờ enabled/focused/editable. Không gửi toạ độ cho Jev.
2. **Quyết định**: một request Jev với `nextOperation` (choice), `tapTarget`
   (choice), `scrollDirection`, `completionVerified` / `consequential` /
   `explicitAuthorization` (noul).
3. **Guard**:

   | Loại | Ngưỡng |
   |---|---|
   | Bấm/vuốt/gõ | prob ≥ 0.55, conf ≥ 0.35 |
   | Có hệ quả (gửi/đặt/huỷ/xoá) | prob ≥ 0.85, conf ≥ 0.75, cho phép ≥ 0.90 |
   | `DONE` | prob ≥ 0.90 và "đã hoàn thành" ≥ 0.90 |

4. **Quan sát lại trước khi bấm**: bám lại đúng phần tử; mất thì bỏ qua bước.
5. **Tối ưu**: cache quyết định theo trạng thái màn hình (đã chuẩn hoá số/giờ),
   học kế hoạch sau lần chạy thành công, phát lại theo toạ độ thiết bị và kiểm
   tra bằng chứng ở cuối. UI đổi → tự quay về vòng lặp đầy đủ.
6. **Dừng an toàn**: quá số bước/thời gian, lặp cùng hành động 3 lần, app khác
   đang foreground, hoặc thiếu bằng chứng `--expect`.

## Giới hạn

- Flutter chỉ dựng cây accessibility khi có dịch vụ hỗ trợ; nếu `--doctor` thấy
  quá ít phần tử thì bật accessibility (hoặc dùng cầu `integration_test`).
- `uiautomator dump` tốn ~2.2 s/lần — đây là sàn hiện tại.
- Chỉ nên chạy trên tài khoản/dữ liệu demo.

## Cấu trúc

```
cua/
  jev_client.py   gọi /v1/systemone (không log key)
  observe.py      adb + uiautomator → Frame (phần tử + toạ độ)
  agent.py        vòng lặp, guard, cache, phát lại kế hoạch
  run.py          CLI điều khiển app
  triage.py       chạy test + phân loại bằng Jev
tests/            11 test (Jev giả, adb giả — không cần máy, không tốn phí)
jev.ps1           gọi Jev trực tiếp với preset (triage/ui/ship)
BENCHMARK.md      số đo và các bước tối ưu
```

## Kiểm thử

```powershell
python -m unittest discover -s tests
```

## Giấy phép

MIT — xem [LICENSE](LICENSE).
