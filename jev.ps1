# jev.ps1 — gọi TypeSafe Jev (decision model) để hỗ trợ kiểm thử.
#
# Jev KHÔNG phải chat model: nó nhận "state" (văn bản) + "questions" và trả
# quyết định (choice / score / noul) kèm xác suất. Dùng để phân loại kết quả
# test, đánh giá màn hình có khớp mô tả, hoặc quyết định "đủ điều kiện ship".
#
# Cách dùng:
#   .\jev.ps1 -Preset triage -StateFile .\test-log.txt
#   .\jev.ps1 -StateFile .\state.txt -QuestionsFile .\questions.json
#   .\jev.ps1 -Preset triage -StateFile .\log.txt -DryRun   # chỉ in body
#
# Key: biến môi trường EXPERIENTIAL_API_KEY, nếu không có thì đọc
#      C:\Users\Bafise\.local\share\opencode\auth.json (provider experientiallabs).
# Không bao giờ in key ra output.

param(
    [ValidateSet("triage", "ui", "ship", "custom")]
    [string]$Preset = "triage",

    [string]$StateFile,
    [string]$State,
    [string]$QuestionsFile,

    [string]$Model = "jev-latest",
    [string]$Endpoint = "https://api.experientiallabs.ai/v1/systemone",
    [int]$TimeoutSec = 40,
    [int]$MaxStateChars = 60000,
    [switch]$DryRun,
    [switch]$Raw
)

$ErrorActionPreference = "Stop"

# ---------- 1. Đọc state ----------
if ($StateFile) {
    if (-not (Test-Path $StateFile)) { throw "Khong tim thay file state: $StateFile" }
    $stateText = Get-Content -Path $StateFile -Raw -Encoding UTF8
} elseif ($State) {
    $stateText = $State
} else {
    throw "Can -StateFile hoac -State."
}

if ($null -eq $stateText) { $stateText = "" }
if ($stateText.Length -gt $MaxStateChars) {
    Write-Warning ("State dai " + $stateText.Length + " ky tu, cat con " + $MaxStateChars + " (Jev ~32k token).")
    $stateText = $stateText.Substring($stateText.Length - $MaxStateChars)
}

# ---------- 2. Bộ câu hỏi theo preset ----------
$presets = @{
    # Phân loại một lần chạy test: hỏng thật, test sai, flaky, hay môi trường?
    triage = @{
        action = @{
            type         = "choice"
            instructions = "What should the developer do next about this test run?"
            criteria     = @{
                "pass"       = "All checks passed; nothing to fix."
                "fix-code"   = "A real defect in the changed application code."
                "fix-test"   = "The test itself is wrong, outdated, or asserts the wrong thing."
                "flaky"      = "Passes and fails nondeterministically without a code change."
                "env"        = "Environment, dependency, network, database, or CI setup problem."
                "needs-human"= "Evidence is insufficient or contradictory; a human must decide."
            }
        }
        blocking = @{
            type         = "noul"
            instructions = "This failure blocks merging or continuing work."
        }
        evidence = @{
            type         = "score"
            instructions = "How clear is the evidence for the chosen action?"
            criteria     = @(
                "Little evidence, mostly guessing",
                "Some concrete signal in the logs",
                "Clear, specific evidence such as a stack trace pointing at the change"
            )
        }
    }

    # Đánh giá màn hình app có khớp mô tả/yêu cầu không (state = mô tả text).
    ui = @{
        match = @{
            type         = "choice"
            instructions = "Does the actual screen match the expected screen described in the state?"
            criteria     = @{
                "match"          = "Every required element and text is present and correct."
                "minor-mismatch" = "Main flow works; wording, spacing, or a non-critical element differs."
                "major-mismatch" = "A required element is missing, wrong, or unusable."
            }
        }
        blocks_task = @{
            type         = "noul"
            instructions = "A user could not complete the main task on this screen."
        }
    }

    # Trước khi báo xong / chuyển trạng thái: đã đủ chắc để ship chưa?
    ship = @{
        decision = @{
            type         = "choice"
            instructions = "Should this change be reported as done to the requester?"
            criteria     = @{
                "ship"   = "Requirement met and verified by tests or a real run."
                "review" = "Looks right but needs a human check on a real device or data."
                "hold"   = "Requirement not met, or a known defect remains."
            }
        }
        regressions = @{
            type         = "noul"
            instructions = "The state shows evidence of a regression in existing behaviour."
        }
        confidence = @{
            type         = "score"
            instructions = "How strong is the evidence that the work is complete?"
            criteria     = @(
                "Only claims, no test or run output",
                "Tests pass but the real flow was not exercised",
                "Tests and a real end-to-end run both confirm it"
            )
        }
    }
}

if ($QuestionsFile) {
    if (-not (Test-Path $QuestionsFile)) { throw "Khong tim thay file questions: $QuestionsFile" }
    $questions = Get-Content -Path $QuestionsFile -Raw -Encoding UTF8 | ConvertFrom-Json -AsHashtable
} elseif ($Preset -eq "custom") {
    throw "Preset custom can -QuestionsFile."
} else {
    $questions = $presets[$Preset]
}

$body = @{
    model     = $Model
    state     = $stateText
    questions = $questions
}

$json = $body | ConvertTo-Json -Depth 20

if ($DryRun) {
    Write-Output "--- body (khong goi API) ---"
    Write-Output $json
    return
}

# ---------- 3. Key ----------
$key = $env:EXPERIENTIAL_API_KEY
if ([string]::IsNullOrWhiteSpace($key)) {
    $authPath = "C:\Users\Bafise\.local\share\opencode\auth.json"
    if (-not (Test-Path $authPath)) { throw "Thieu EXPERIENTIAL_API_KEY va khong thay auth.json." }
    $auth = Get-Content $authPath -Raw | ConvertFrom-Json
    $key = $auth.experientiallabs.key
}
if ([string]::IsNullOrWhiteSpace($key)) { throw "Khong tim thay key experientiallabs." }

# ---------- 4. Gọi ----------
try {
    $response = Invoke-RestMethod -Uri $Endpoint -Method Post `
        -Headers @{ Authorization = "Bearer $key" } `
        -ContentType "application/json; charset=utf-8" `
        -Body ([Text.Encoding]::UTF8.GetBytes($json)) `
        -TimeoutSec $TimeoutSec
} catch {
    $status = $null
    if ($_.Exception.Response) { $status = [int]$_.Exception.Response.StatusCode }
    Write-Output ("LOI: HTTP " + $status)
    if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
        Write-Output ("Body: " + $_.ErrorDetails.Message)
    } else {
        Write-Output ("Body: " + $_.Exception.Message)
    }
    exit 1
}

if ($Raw) {
    $response | ConvertTo-Json -Depth 20
    return
}

# ---------- 5. In kết quả gọn ----------
Write-Output ("model: " + $response.model + "  |  tokens: " + $response.usage.input_tokens + " in / " + $response.usage.output_tokens + " out")
foreach ($name in $response.answers.PSObject.Properties.Name) {
    $a = $response.answers.$name
    switch ($a.type) {
        "choice" {
            $sorted = $a.probabilities.PSObject.Properties | Sort-Object { $_.Value } -Descending | Select-Object -First 3
            $alt = ($sorted | ForEach-Object { $_.Name + "=" + [math]::Round($_.Value, 2) }) -join ", "
            Write-Output ("  " + $name + ": " + $a.choice + "  (conf " + [math]::Round($a.confidence, 2) + "; " + $alt + ")")
        }
        "score" {
            $idx = [int][math]::Round($a.score)
            $label = ""
            if ($a.legend -and $a.legend.PSObject.Properties.Name -contains "$idx") { $label = $a.legend."$idx" }
            Write-Output ("  " + $name + ": " + [math]::Round($a.score, 2) + "  (" + $label + "; conf " + [math]::Round($a.confidence, 2) + ")")
        }
        "noul" {
            Write-Output ("  " + $name + ": " + [math]::Round($a.noul, 3))
        }
        default {
            Write-Output ("  " + $name + ": " + ($a | ConvertTo-Json -Compress -Depth 5))
        }
    }
}
