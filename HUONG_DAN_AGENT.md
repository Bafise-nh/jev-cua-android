# Hướng dẫn dùng jev cho agent khác

Tài liệu bàn giao: đọc xong là chạy được trong **session mới**, không cần hỏi
lại người viết. Toàn bộ lệnh dưới đây chạy trong thư mục repo này.

```
C:\Users\Bafise\Documents\tools\jev
```

---

## 0. Ba câu cần nhớ

1. **Jev là model quyết định, không phải model chat.** Nó nhận `state` (chữ) +
   câu hỏi dạng `choice` / `score` / `noul` và trả về lựa chọn kèm xác suất.
   Jev **không** nhìn ảnh, **không** tự bấm.
2. Mọi thứ "tay chân" (chụp màn hình, đọc cây accessibility, bấm, gõ, vuốt)
   do `cua/` làm bằng `adb` + `uiautomator`.
3. Kết thúc kiểm thử phải bằng **bằng chứng trên màn hình** (`--expect`), không
   phải bằng lời của model.

Luồng chuẩn:

```
quan sát (uiautomator) -> state chữ -> Jev chọn 1 hành động
      -> lọc theo xác suất -> bấm/gõ -> quan sát lại -> ... -> --expect
```

---

## 1. Chuẩn bị (làm một lần mỗi session)

```powershell
cd C:\Users\Bafise\Documents\tools\jev

# 1) Có thiết bị chưa?
adb devices

# 2) Có key Jev chưa? (không in key ra màn hình)
$env:EXPERIENTIAL_API_KEY = "<key>"
# hoặc để trống và dùng file auth của opencode:
#   C:\Users\Bafise\.local\share\opencode\auth.json  (provider: experientiallabs)

# 3) Tự kiểm tra toàn bộ (adb, thiết bị, kích thước màn hình, key)
python -m cua.run --doctor
```

Nếu `--doctor` báo thiếu thiết bị: bật emulator hoặc cắm máy, đợi
`sys.boot_completed = 1`, rồi chạy lại.

**Không dùng cờ `-dns-server` khi bật emulator** — đã gặp trường hợp emulator
mất phân giải tên miền, ứng dụng đứng ở màn hình chờ. Bật mặc định là đủ.

---

## 2. Cách nhanh nhất: một lệnh, có bằng chứng

```powershell
python -m cua.run `
  --goal "Mở tab Tổng quan và kiểm tra có checklist Bắt đầu bán hàng" `
  --package com.delitech.deli_merchant `
  --expect "Bắt đầu bán hàng" `
  --seconds 120
```

Tham số hay dùng:

| Tham số | Ý nghĩa |
|---|---|
| `--goal` | Mục tiêu bằng tiếng Việt, càng cụ thể càng tốt |
| `--package` | Chỉ cho phép bấm trong app này (tránh lạc sang app khác) |
| `--expect` | Chuỗi **phải thấy** trên màn hình cuối. Lặp lại được nhiều lần |
| `--fill "Nhãn=giá trị"` | Điền vào ô nhập có nhãn tương ứng. Lặp lại được |
| `--steps` | Số bước tối đa (mặc định 25) |
| `--seconds` | Giới hạn thời gian (mặc định 180) |
| `--no-fast` | Tắt phát lại kế hoạch đã học (khi màn hình đã đổi khác) |
| `--dry` | Chỉ quan sát + in state, **không** gọi Jev (dùng để chẩn đoán) |
| `--shots <thư mục>` | Lưu ảnh từng bước để xem lại |
| `--trace-dir` | Nơi lưu vết + `plans.json` (mặc định `runs/`) |

Lần đầu chạy sẽ gọi Jev từng bước. Cùng `--goal` + `--expect` ở lần sau sẽ
**phát lại kế hoạch theo toạ độ** (nhanh hơn nhiều, xem `BENCHMARK.md`).

Ví dụ có điền dữ liệu:

```powershell
python -m cua.run `
  --goal "Đăng nhập bằng số điện thoại và mật khẩu" `
  --fill "Số điện thoại=793912978" `
  --fill "Mật khẩu=12345678" `
  --expect "Đặt món" `
  --seconds 150
```

---

## 3. Cách chắc ăn nhất: quan sát rồi tự bấm

Khi đã biết chính xác màn hình (test hồi quy, chạy lại nhiều lần), **không cần
model**. Đọc cây giao diện rồi bấm theo toạ độ — nhanh và ổn định nhất.

```python
from cua import observe
import subprocess

frame = observe.observe()          # backend tự chọn (adb trước, u2 sau)
print(frame.package)              # app đang hiện
print(frame.screen_text[:20])     # các dòng chữ đang thấy
for el in frame.elements:
    print(el.label, el.cx, el.cy, el.editable, el.clickable)

# bấm theo nhãn
target = next(e for e in frame.elements if (e.label or "").strip() == "Đặt món")
subprocess.run(["adb", "shell", "input", "tap", str(target.cx), str(target.cy)])
```

`Frame` có: `package`, `width`, `height`, `elements`, `screen_text`,
`secure_input`, `screenshot`.
`Element` có: `label`, `role`, `cx`, `cy`, `editable`, `focused`,
`clickable`, `scrollable`, `password`, `enabled`.

Có sẵn script tiện dụng trong repo:

```powershell
python tap.py "Đơn hàng"            # bấm đúng nhãn
python tap.py "Quan Mì" --contains   # bấm theo chuỗi con
python tap.py --dump                # liệt kê mọi nhãn + toạ độ
```

Mẹo: nếu cây giao diện **rỗng** (thường gặp khi Flutter đang chuyển cảnh, có
hộp thoại, hoặc app vừa văng) thì chụp màn hình để xem thật:

```powershell
adb shell screencap -p /sdcard/s.png
adb pull /sdcard/s.png .\s.png
# rồi mở ảnh bằng công cụ đọc ảnh của agent
```

---

## 4. Chẩn đoán khi test đỏ

### 4.1 Đọc log lỗi (không gọi model)

```powershell
python -m cua.diagnose --file .\build.log
python -m cua.diagnose --text "Error: Failed to compile application for the Web."
```

In ra nguyên nhân gốc, nhóm lỗi và gợi ý sửa theo kinh nghiệm đã tích luỹ.

### 4.2 Chạy lệnh rồi phân loại kết quả

```powershell
python -m cua.triage --workdir C:\duong\dan\repo `
  --command "flutter test" --tail 150
```

`--no-jev` để chỉ lấy log, không gọi API (khi mất mạng hoặc muốn tiết kiệm).

### 4.3 Hỏi Jev một câu quyết định (không điều khiển app)

```powershell
.\jev.ps1 -Preset triage -StateFile .\test-log.txt
.\jev.ps1 -Preset ui -StateFile .\state.txt -Raw
.\jev.ps1 -Preset triage -StateFile .\log.txt -DryRun   # chỉ in body, không gửi
```

Preset có: `triage`, `ui`, `ship`, `custom`.
Endpoint mặc định `https://api.experientiallabs.ai/v1/systemone`,
model `jev-latest`.

---

## 5. Luật đã trả giá mới biết (đọc trước khi debug)

1. **`adb root` làm `uiautomator` hỏng** (`adb shell uiautomator dump` trả rỗng).
   Nếu đã `adb root` thì chạy `adb unroot` và đợi vài giây.
2. **Bàn phím che nút**: khi ô nhập được focus, hộp thoại bị đẩy lên và toạ độ
   đổi. Luôn `uiautomator dump` lại **sau khi bàn phím mở**, đừng dùng toạ độ
   cũ.
3. **`adb shell input text` cắt chuỗi ở dấu cách.** Dùng `%s` cho khoảng trắng:
   `adb shell input text "123%sNguyen%sHue"`.
4. **Đừng `keyevent 4` để đóng bàn phím** — nó đóng luôn hộp thoại (mất dữ
   liệu vừa nhập). Dùng `keyevent 111` (ESC) hoặc bấm thẳng nút.
5. **Nút có nhãn chưa chắc bấm được**: kiểm tra `clickable` / `enabled` của
   node cha. Nếu `clickable=false` thì đó là nút đang bị khoá theo điều kiện
   nghiệp vụ, bấm mãi cũng không được.
6. **Flutter + chuyển cảnh** có lúc trả cây rỗng 1–2 giây: chờ rồi quan sát
   lại, đừng kết luận app treo.
7. **Đóng app không xoá dữ liệu**: nếu app "treo ở splash" sau khi sửa cấu
   hình phiên, thử `adb shell pm clear <package>` rồi đăng nhập lại.
8. **Đừng chạy build nặng song song với emulator** (máy 14 GB RAM): emulator
   chết im lặng. Dừng `java`/Gradle trước khi bật emulator.
9. **Không dùng jev cho web.** Web thì điều khiển trình duyệt; repo này chỉ
   Android.
10. **Luôn kết thúc bằng `--expect`.** Nếu model nói "đã xong" mà màn hình
    không có chuỗi đó thì coi như chưa xong.

---

## 6. Bảng lỗi nhanh

| Hiện tượng | Nguyên nhân thường gặp | Cách xử lý |
|---|---|---|
| `Khong co thiet bi/emulator nao` | Emulator chưa bật / adb daemon chết | `adb devices`, bật emulator, `adb start-server` |
| Cây giao diện rỗng | `adb root`, chuyển cảnh, app văng | `adb unroot`, chờ, chụp màn hình |
| Bấm đúng toạ độ mà không có tác dụng | Bàn phím che / toạ độ cũ | Dump lại, bấm theo node mới |
| Chữ nhập bị cắt | Dấu cách trong `input text` | Dùng `%s` |
| `401` khi gọi API Jev | Hết key / sai key | Đặt lại `EXPERIENTIAL_API_KEY` |
| Kế hoạch phát lại sai | Màn hình đã đổi | Chạy lại với `--no-fast` |
| `--expect` không bao giờ thấy | Chuỗi khác dấu/khác hoa thường | Dùng `tap.py --dump` xem chữ thật |

---

## 7. Bàn giao sang session mới (checklist)

Sao chép nguyên khối này vào session mới, điền phần còn trống:

```
Repo tool      : C:\Users\Bafise\Documents\tools\jev
Thiết bị       : emulator-5554  (hoặc <serial>)
App cần test   : <package, ví dụ com.delitech.deli_merchant>
Tài khoản test : <số điện thoại> / <mật khẩu>
Mục tiêu       : <mô tả 1 câu>
Bằng chứng xong: --expect "<chuỗi phải thấy>"
Giới hạn       : --seconds 120 --steps 15
```

Lệnh chạy đầu tiên trong session mới:

```powershell
cd C:\Users\Bafise\Documents\tools\jev
python -m cua.run --doctor
python -m cua.run --goal "<mục tiêu>" --package <package> --expect "<bằng chứng>"
```

Nếu `--doctor` xanh mà `cua.run` vẫn sai, chạy `--dry` để xem agent đang "nhìn"
thấy gì; 90% lỗi nằm ở bước này (sai app đang mở, cây rỗng, hoặc chữ có dấu
khác với `--expect`).

---

## 8. Cấu trúc repo (để đọc thêm)

```
cua/observe.py     đọc cây giao diện -> Frame/Element (adb hoặc uiautomator2)
cua/agent.py       vòng lặp: state -> Jev -> hành động, cache + phát lại
cua/run.py         CLI chính (--goal/--expect/--fill/--dry/--doctor)
cua/diagnose.py    chẩn đoán log lỗi
cua/triage.py      chạy lệnh + phân loại kết quả
cua/jev_client.py  gọi API Jev (đọc key, timeout, parse)
jev.ps1            gọi Jev trực tiếp cho câu hỏi quyết định
tap.py, stage.py   tiện ích: bấm theo nhãn, đo thời gian từng giai đoạn
step_*.py          ví dụ thật của một vòng đăng nhập/đặt món (tham khảo)
runs/              vết chạy + plans.json (kế hoạch đã học)
tests/             test của chính tool
```

Giấy phép MIT. Key và dữ liệu chạy không nằm trong repo.
