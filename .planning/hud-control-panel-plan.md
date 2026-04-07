# HUD Control Panel — Implementation Plan

## Goal
悬浮、半透明、可拖动、可开关的控制面板，显示 Cerebellum/Spinal Cord/Hand 状态，可向 Brain 发送指令。

## Decisions (Locked)
- **GUI 框架**: Dear PyGui
- **功能范围**: 基础 — 状态显示 + 指令输入 + 日志（不做 BT 可视化、截图预览、性能图）
- **平台**: macOS only
- **架构**: 后台 thread 跑 agent loop，主 thread 跑 DPG（DPG 必须在主线程）

## Architecture

```
┌──────────────────────────────────────┐
│  Main Thread: HUD (Dear PyGui)       │
│  - Render panels                     │
│  - Read snapshots from bridge        │
│  - Push commands to bridge           │
└────────────┬─────────────────────────┘
             │ StateBridge
┌────────────┴─────────────────────────┐
│  Background Thread: Agent Loop       │
│  Cerebellum → Brain → BT → Hand      │
│  - 5 Hz tick                         │
│  - Publishes snapshots               │
│  - Drains commands                   │
└──────────────────────────────────────┘
```

## File Structure (New)

```
src/terraria_agent/
├── __main__.py                  # Entry point: bridge + orchestrator + HUD
├── hud/
│   ├── __init__.py
│   ├── app.py                   # DPG viewport + render loop + macOS transparency
│   ├── state_bridge.py          # Thread-safe StateBridge + HUDSnapshot
│   └── panels/
│       ├── __init__.py
│       ├── status.py            # HP bar, danger, slot, buffs, inventory
│       ├── spinal_cord.py       # Active BT branch, action buffer
│       ├── hand.py              # Held keys
│       ├── brain.py             # Goal, task queue
│       ├── command.py           # Text input → bridge
│       └── log.py               # Scrolling log
└── orchestrator/
    ├── __init__.py
    └── agent_loop.py            # AgentOrchestrator (background thread)
```

## Files to Modify

### `src/terraria_agent/spinal_cord/context.py`
Add field:
```python
bt_trace: list[str] = field(default_factory=list)
```

### `src/terraria_agent/spinal_cord/bt/composites.py`
Each composite's `tick()` appends the active child's name to `ctx.bt_trace` before returning RUNNING/SUCCESS:
- `Sequence`: append child name on RUNNING (currently running child)
- `Selector`: append child name on SUCCESS or RUNNING
- `PrioritySelector`: append child name on SUCCESS or RUNNING
- `Parallel`: append all running children
- `DynamicSelector`: append currently running child name

The trace is a fresh empty list each tick (set in orchestrator before calling root.tick).

### `pyproject.toml`
Add optional dependency group:
```toml
[project.optional-dependencies]
hud = [
    "dearpygui>=2.0",
    "pynput>=1.7",
    "pyobjc-framework-Cocoa>=10.0",
]

[project.scripts]
terraria-agent = "terraria_agent.__main__:main"
```

## Core Components

### 1. StateBridge (`hud/state_bridge.py`)

```python
@dataclass(frozen=True)
class HUDSnapshot:
    # Cerebellum
    hp: int
    max_hp: int
    danger_level: str
    hp_trend: str
    selected_slot: int
    buffs: list[str]
    inventory_open: bool
    # Spinal cord
    active_bt_branch: str          # "Root > Combat > DangerousCombat"
    bt_status: str                 # "success" | "failure" | "running"
    action_buffer: list[str]       # Human-readable
    # Hand
    held_keys: frozenset[str]
    # Brain
    current_goal: str
    task_queue_summary: list[str]  # ["[HIGH] tree_nearby: chop", ...]
    # Meta
    tick_count: int
    tps: float
    timestamp: float


class StateBridge:
    def __init__(self):
        self._lock = threading.Lock()
        self._snapshot: HUDSnapshot | None = None
        self._command_queue: queue.Queue[str] = queue.Queue()
        self._log_queue: queue.Queue[str] = queue.Queue(maxsize=500)
        self._paused = False
        self._visible = True

    def publish_snapshot(self, s: HUDSnapshot) -> None: ...
    def get_snapshot(self) -> HUDSnapshot | None: ...
    def send_command(self, text: str) -> None: ...
    def drain_commands(self) -> list[str]: ...
    def log(self, msg: str) -> None: ...
    def drain_logs(self) -> list[str]: ...
    def toggle_pause(self) -> None: ...
    def is_paused(self) -> bool: ...
    def toggle_visibility(self) -> None: ...
    def is_visible(self) -> bool: ...
```

### 2. AgentOrchestrator (`orchestrator/agent_loop.py`)

```python
class AgentOrchestrator:
    def __init__(self, bridge: StateBridge, tick_rate: float = 5.0):
        self._bridge = bridge
        self._tick_rate = tick_rate
        self._running = False
        self._thread: threading.Thread | None = None
        self._capture = ScreenCapture()
        self._detector = UIVisionDetector()
        self._hand = HandController()
        self._bt_root = build_root_tree()
        self._task_queue = TaskQueue(goal="idle", task_queue=[])
        self._tick_count = 0

    def start(self): ...   # spawn daemon thread
    def stop(self):  ...   # set _running=False, release_all keys
    def _loop(self): ...   # while _running: _tick(); sleep(interval - elapsed)

    def _tick(self):
        self._tick_count += 1
        # 1. Drain commands
        for cmd in self._bridge.drain_commands():
            self._handle_command(cmd)
        if self._bridge.is_paused():
            return
        # 2. Cerebellum
        frame = self._capture.capture()
        if frame is None:
            self._bridge.log("[WARN] No Terraria window")
            return
        game_state = self._detector.detect(frame)
        # 3. Build TickContext (bt_trace fresh each tick)
        ctx = TickContext(
            game_state=game_state,
            task_queue=self._task_queue,
            dt=1.0/self._tick_rate,
        )
        # 4. BT tick
        status = self._bt_root.tick(ctx)
        # 5. Hand execute
        self._hand.execute(ctx.action_buffer)
        # 6. Publish snapshot
        snap = HUDSnapshot(...)
        self._bridge.publish_snapshot(snap)

    def _handle_command(self, cmd: str):
        # Format:
        #   goal: <text>          → set goal
        #   task: <trigger> <action> <priority>  → append task
        #   clear                 → clear task queue
        #   pause / resume        → toggle pause
        ...
```

### 3. HUD App (`hud/app.py`)

```python
def run_hud(bridge: StateBridge) -> None:
    dpg.create_context()
    dpg.create_viewport(
        title="Terraria Agent HUD",
        width=400,
        height=720,
        always_on_top=True,
        clear_color=(20, 20, 30, 230),
    )

    with dpg.window(tag="main_window", no_title_bar=False):
        # Control bar
        with dpg.group(horizontal=True):
            dpg.add_button(label="Pause", callback=lambda: bridge.toggle_pause())
            dpg.add_text("●", tag="status_dot", color=(0, 255, 0))
            dpg.add_text("0 TPS", tag="tps_text")

        status_panel.create(bridge)
        spinal_cord_panel.create(bridge)
        hand_panel.create(bridge)
        brain_panel.create(bridge)
        command_panel.create(bridge)
        log_panel.create(bridge)

    dpg.set_primary_window("main_window", True)
    dpg.setup_dearpygui()
    dpg.show_viewport()

    _apply_macos_transparency(0.85)
    _start_hotkey_listener(bridge)

    while dpg.is_dearpygui_running():
        snap = bridge.get_snapshot()
        if snap is not None:
            status_panel.update(snap)
            spinal_cord_panel.update(snap)
            hand_panel.update(snap)
            brain_panel.update(snap)
        log_panel.update(bridge.drain_logs())
        _sync_visibility(bridge)
        dpg.render_dearpygui_frame()
    dpg.destroy_context()


def _apply_macos_transparency(alpha: float) -> None:
    """Use NSWindow to make DPG window semi-transparent on macOS."""
    try:
        from AppKit import NSApp
        for w in NSApp.windows():
            title = w.title() or ""
            if "Terraria Agent" in title:
                w.setAlphaValue_(alpha)
                w.setOpaque_(False)
                break
    except Exception as e:
        print(f"[HUD] Transparency unavailable: {e}")


def _start_hotkey_listener(bridge: StateBridge) -> None:
    """Global F12 to toggle visibility (works even when game is focused)."""
    from pynput import keyboard
    def on_toggle():
        bridge.toggle_visibility()
    listener = keyboard.GlobalHotKeys({"<f12>": on_toggle})
    listener.daemon = True
    listener.start()


def _sync_visibility(bridge: StateBridge) -> None:
    """Show/hide DPG window via NSWindow when bridge.is_visible() changes."""
    ...
```

### 4. Panels (each in `hud/panels/*.py`)

Pattern: `create(bridge)` once, `update(snap)` each frame.

**status.py** (Cerebellum):
- Progress bar HP / max_hp with overlay text
- Color: green safe, orange warning, red critical
- Text: danger_level, hp_trend, selected_slot, buffs, inventory_open

**spinal_cord.py**:
- Active BT branch text
- BT status colored
- Action buffer list (last N actions)

**hand.py**:
- Held keys as comma-separated text

**brain.py**:
- Current goal text
- Task queue list with priority badges

**command.py**:
- Text input with hint
- Send button (also Enter)
- Format help text

**log.py**:
- Read-only scrolling text area
- Auto-scroll to bottom

## Entry Point (`__main__.py`)

```python
def main():
    from terraria_agent.hud.state_bridge import StateBridge
    from terraria_agent.orchestrator.agent_loop import AgentOrchestrator
    from terraria_agent.hud.app import run_hud

    bridge = StateBridge()
    orchestrator = AgentOrchestrator(bridge, tick_rate=5.0)
    orchestrator.start()
    try:
        run_hud(bridge)  # blocks on main thread
    finally:
        orchestrator.stop()

if __name__ == "__main__":
    main()
```

## Implementation Order

1. **state_bridge.py** — pure stdlib, unit-testable
2. **context.py + composites.py** — add bt_trace, update tests
3. **agent_loop.py** — orchestrator, can mock bridge
4. **panels/*.py** — each panel independently
5. **app.py** — wire panels, viewport, transparency, hotkey
6. **__main__.py** — entry point
7. **pyproject.toml** — dependencies + script
8. **Tests** — bridge unit test, orchestrator test with mock bridge, bt_trace test

## Key Risks / Notes

- **macOS transparency**: DPG/GLFW 不原生支持。用 NSWindow.setAlphaValue_ hack。需要在 viewport 创建之后、渲染之前调用，可能要 retry 几次直到 NSWindow 可用
- **F12 全局热键**: 用 pynput.GlobalHotKeys（不会拦截游戏输入，仅监听）
- **DPG 主线程要求**: 所有 dpg.* 调用必须在主线程。bridge 是唯一的跨线程边界
- **agent thread 异常**: try/except 包住 _tick，错误写入 log，避免线程死掉
- **bt_trace 重置**: 每个 tick 创建新的 TickContext，trace 默认空列表，无需手动 clear
- **Hide/show viewport**: DPG 没有原生 API，用 NSWindow.orderOut_/orderFront_

## Tests

- `tests/test_hud/test_state_bridge.py` — 多线程读写、命令队列、日志队列
- `tests/test_hud/test_orchestrator.py` — mock bridge + mock detector，验证 tick 流程
- `tests/test_bt/test_bt_trace.py` — 验证 bt_trace 在各 composite 下正确填充

## Acceptance Criteria

1. `python -m terraria_agent` 启动后 HUD 出现
2. HUD 半透明、悬浮、可拖动
3. F12 切换显示/隐藏
4. 状态面板实时显示 GameState（HP、slot、buff）
5. 指令面板能发送 `goal: xxx` 和 `task: xxx`
6. Pause/Resume 工作正常
7. 所有现有测试继续通过
