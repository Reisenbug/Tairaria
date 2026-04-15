# Terraria Agent

## Mod 控制協議教訓

### JSON 格式敏感
Python `json.dumps` 產出 `{"key": true}`（冒號後有空格）。C# 用 `Contains` 匹配時必須先 `Replace(" ", "")` 去空格，否則永遠匹配不上。

### 邊緣觸發 vs 電平觸發
Terraria 的輸入系統對不同控制有不同語義：
- **Jump**：需要 false→true 邊緣觸發。持續 true = 只跳一次。連跳必須留 gap 幀。
- **SmartCursor**：toggle 型，rising edge 切換。持續 true = 閃爍。改用 pyautogui 模擬 ctrl 按鍵。
- **Move/Attack**：電平觸發，持續 true 即可。

### Jump hold 時長
hold 時間決定跳躍高度。1 幀 = 矮跳，36 幀 = 阻塞再觸發。15 幀 = Terraria 默認 jumpHeight，最優。

### Timeout 必須 > hold + gap
ControlInput timeout 必須大於 JumpHoldFrames + gap 幀，否則 pending jump 在消費前就過期了。

### Tick 率 vs 遊戲幀率
5TPS（200ms）對跳躍時機太慢。解法：把時序敏感邏輯（auto-jump）放 mod 端 60fps 處理。Python BT 決定「做什麼」，mod 處理「什麼時候」。

### 兩個 jump 源 = 衝突
Python StuckJump + mod auto-jump 搶同一個 `_jumpFramesLeft`，導致間歇性失敗（heisenbug）。原則：一個機制只能有一個控制源。跳躍現在完全由 mod 端負責。

### 手動序列化陷阱
`StateSerializer.cs` 是手寫 StringBuilder，不會自動反射新欄位。加新欄位到 data class（如 `HotbarSlot`）後，**必須同步改 `AppendSlot`**，否則 JSON 裡不會出現。

## 架構規則

### 動作歸屬
- **Mod /control**：移動（WASD）、跳躍（auto-jump 60fps）、槽位選擇、useItem
- **pyautogui**：鼠標座標/點擊（攻擊、交互）、SmartCursor 切換（ctrl 鍵）
- 不要在兩條路徑上重複控制同一行為

### 改完先測
改動代碼/mod 後，先給用戶測試步驟，等確認通過再 commit。不要盲提交。
