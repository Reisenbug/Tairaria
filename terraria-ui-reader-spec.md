# Task: 实现 Terraria UI Reader（小脑 v0）

## 背景

这是一个 Terraria 视觉 agent 项目的组件。整个系统分四层：大脑(LLM)、脊髓(行为树)、小脑(视觉)、手(键鼠控制)。手已经实现完毕，现在需要实现小脑的最小版本——从 Terraria 游戏截图中读取 UI 信息。

本阶段不需要任何 AI 模型。只需要像素级的图像处理：截图 → 读取固定位置的 UI 元素 → 输出结构化 JSON。

## 游戏设置

- 游戏：Terraria（Steam 版）
- Health and Mana Style: **Fancy 2**（同时显示心形图标和数字文本）
- 分辨率：需要在初始化时自动检测游戏窗口大小
- HP 文字 "Life: xxx/xxx" 显示在屏幕右上角，白色字体
- 快捷栏（Hotbar）在屏幕左上角，共 10 个格子，选中格子有黄色高亮边框
- Buff 图标在快捷栏下方一行

## 需要实现的模块

### 1. `screen_capture.py` — 屏幕截取

- 用 `mss` 库截取 Terraria 游戏窗口
- 提供一个函数 `capture() -> np.ndarray`，返回当前帧的截图（BGR numpy array）
- 支持指定截取区域（用于只截取 UI 部分，减少处理量）
- 需要处理窗口查找（找到 Terraria 窗口的位置和大小）

### 2. `ui_reader.py` — UI 信息读取

核心模块。从截图中提取以下信息：

```python
@dataclass
class UIState:
    hp: int              # 当前生命值
    max_hp: int          # 最大生命值
    mana: int            # 当前魔力值（如果有的话）
    max_mana: int        # 最大魔力值
    selected_slot: int   # 快捷栏当前选中的格子编号（0-9）
    buff_active: bool    # 是否有任何 buff 在生效
    inventory_open: bool # 背包是否打开
```

#### HP 读取策略

HP 文字 "Life: 100/100" 在右上角。两种方案任选其一：

**方案 A（推荐）：OCR**
- 截取右上角 HP 文字区域
- 用 `pytesseract` 或 `easyocr` 识别文字
- 解析 "Life: xxx/xxx" 格式，提取两个数字
- 如果 OCR 失败，fallback 到心形图标计数

**方案 B：心形像素检测**
- Fancy 2 样式下心形图标在 HP 文字左侧
- 每颗心代表 20 HP
- 通过检测红色像素区域计数心的数量
- 精度较低（只能到 20 HP 粒度），但更稳定

#### 快捷栏选中检测

- 快捷栏在左上角，10 个格子水平排列
- 选中的格子边框为黄色（约 RGB: 255, 231, 69 附近）
- 未选中的格子边框为深蓝/紫色
- 策略：对每个格子的边框区域采样像素颜色，黄色通道最高的那个就是选中的

#### Buff 检测

- Buff 图标在快捷栏下方
- 只需要检测"有没有 buff"，不需要识别具体是什么 buff
- 策略：截取 buff 栏区域，检测是否有非空图标（与空白背景的像素差异）

#### 背包状态检测

- 当背包打开时，屏幕左上方会出现大面积的物品栏格子
- 背包关闭时该区域是游戏画面
- 策略：检测左上角特定区域是否出现了格子的紫蓝色背景

### 3. `damage_detector.py` — 受伤检测（代替敌人检测）

当前阶段没有 YOLO 来检测敌人位置，用 HP 变化作为代理信号：

```python
class DamageDetector:
    def __init__(self):
        self.last_hp: int = 0
        self.last_update: float = 0

    def update(self, current_hp: int) -> dict:
        """
        返回:
        {
            "took_damage": bool,       # 是否刚受到伤害
            "damage_amount": int,      # 受到多少伤害
            "hp_trend": str,           # "stable" | "decreasing" | "recovering"
            "danger_level": str        # "safe" | "warning" | "critical"
        }
        """
```

danger_level 判定：
- `safe`: HP > 60% 且近 3 秒内未受伤
- `warning`: HP 30-60%，或近 2 秒内受过伤
- `critical`: HP < 30%

### 4. `game_state.py` — 状态聚合

把上面所有信息聚合成一个完整的游戏状态对象，供行为树消费：

```python
@dataclass
class GameState:
    # UI 信息
    hp: int
    max_hp: int
    mana: int
    max_mana: int
    selected_slot: int
    buff_active: bool
    inventory_open: bool

    # 受伤检测
    took_damage: bool
    damage_amount: int
    danger_level: str  # "safe" | "warning" | "critical"

    # 元信息
    timestamp: float
    frame_number: int
```

提供一个主循环函数：

```python
def read_game_state(capture: np.ndarray, prev_state: GameState | None) -> GameState:
    """从一帧截图 + 上一帧状态，生成当前完整状态"""
```

### 5. `main_loop.py` — 主循环（集成测试用）

一个简单的主循环，每 200ms 截屏一次，打印当前状态：

```python
while True:
    frame = capture()
    state = read_game_state(frame, prev_state)
    print(state)  # 或者用 logging
    prev_state = state
    time.sleep(0.2)
```

用于验证 UI 读取是否正确。后续会接入行为树。

## 技术要求

- Python 3.11+
- 依赖：`mss`, `numpy`, `opencv-python`, `pytesseract`（或 `easyocr`）, `Pillow`
- macOS 兼容（开发机是 MacBook Air M4）
- 所有坐标应该基于相对位置（百分比或相对于窗口大小的比例），而不是硬编码像素值，以适配不同分辨率
- 每个模块独立可测试
- 提供 `requirements.txt`

## 文件结构

```
terraria-agent/
├── requirements.txt
├── src/
│   ├── __init__.py
│   ├── screen_capture.py
│   ├── ui_reader.py
│   ├── damage_detector.py
│   ├── game_state.py
│   └── main_loop.py
├── tests/
│   ├── test_ui_reader.py      # 用保存的截图测试
│   └── test_screenshots/      # 放几张测试截图
└── README.md
```

## 验收标准

1. 运行 `main_loop.py`，在 Terraria 游戏运行时，终端每 200ms 打印一次正确的 `GameState`
2. HP 读取准确（误差 ±5 以内）
3. 快捷栏选中检测准确
4. 背包打开/关闭状态检测准确
5. 受伤后 `took_damage` 在 500ms 内变为 True
6. 帧率不低于 5 FPS（从截屏到状态输出的完整 pipeline）

## 不需要做的事

- 不需要检测游戏画面中的怪物、树、箱子等（那是 YOLO 的工作，后续阶段）
- 不需要检测地形
- 不需要接入行为树（后续阶段）
- 不需要任何 AI 模型
- 不需要识别背包中的具体物品
