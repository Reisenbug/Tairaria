# Debug Infrastructure Design

## A.1 现状分析

### DiagLog.cs 当前实现

```csharp
public static void Write(string msg)
{
    lock (_lock) { File.AppendAllText(_path, $"{Main.GameUpdateCount} {msg}\n"); }
}
```

纯文本行，格式：`{tick} {自由文本}`。无结构化字段，无事件类型区分。

### NavCoordinator.cs DiagLog 调用（关键片段）

```
[nav] Start sign={sign}
[nav] Replan at ({pcx},{feetY}) state={State}
[nav] Replan FAILED
[nav] Replan no-progress FAILED fwd={fwd}
[nav] Replan ok len={newPath.Count}
[nav] node[{_pathIdx}] ({_target.Wx},{_target.Wy}) {_target.Action} from ({pcx},{feetY})
[nav] jump aborted vy={p.velocity.Y} feetY={feetY} → replan
[nav] pillar rise={rise} from ({pcx},{feetY}) to ({_target.Wx},{_target.Wy})
[nav] jump landed ({pcx},{feetY}) expected ({_target.Wx},{_target.Wy})
[nav] bridge blocked at ({pcx},{feetY}) ahead=({aheadX},{feetY}) → replan
```

### PathPlanner.cs DiagLog 调用（关键片段）

```
[plan] goal scan:{goalLog} → chosen=({goalX},{goalY})
[plan] no goal found
[plan] goal=({goalX},{goalY}) start=({pcx},{feetY})
[plan] pillar ({cx},{cy})→({cx},{topY}) rise={rise}
[plan] no usable fallback bestFwd={bestFwd} visited={visited.Count}
[plan] fallback→({best.Item1},{best.Item2}) visited={visited.Count}
[plan] path len={path.Count} cost={cost}
```

### exec_astar.py 状态处理

```python
data = _get("/nav_done")
status = data.get("status", "running")
if status == "done":
    failed_goals.clear()
    _start_nav()
elif status == "failed":
    reason = data.get("reason", "")
    failed_goals[last_goal] = time.time() + BLACKLIST_TTL
    if len(failed_goals) >= MAX_BLACKLIST_SIZE:
        _log_and_pause()
    _start_nav(excluded=list(failed_goals.keys()))
```

### 现状缺口

**Q: plan 出 path 后，有没有完整记录每个节点？**
没有。PathPlanner 只记录 `path len=N cost=C`，不记录节点序列。NavCoordinator 在进入 Idle 时记录单个节点 `node[idx] (wx,wy) action from (pcx,feetY)`，但不批量输出全路径。

**Q: 节点完成/失败时，有没有"期望 vs 实际"的对照？**
只有 jump 有：`jump landed ({pcx},{feetY}) expected ({_target.Wx},{_target.Wy})`。move/bridge/pillar/fall 无对照记录。

**Q: failed 时的信息够不够定位是哪一节点/哪一层失败？**
不够。`nav_failed` 只有 `reason` 字符串（如 `"replan empty at (x,y)"`），没有：
- 失败前最后一个节点的 idx 和 action
- 当前 _pathIdx 和总路径长度
- 玩家实际位置 vs 期望位置的 delta
- 是规划层（Plan 返回空）还是执行层（stall/deviate/jump-abort）触发的

---

## A.2 DragonLens 冻结机制调研

### 冻结实现（Pause.cs）

```csharp
internal class FrameAdvanceSystem : ModSystem
{
    public static bool paused;
    public static bool stepReady;

    public override void Load()
    {
        IL_Main.DoUpdate += FrameAdvanceIL;  // IL hook
    }

    private void FrameAdvanceIL(ILContext il)
    {
        ILCursor c = new(il);
        c.TryGotoNext(n => n.MatchCall<Main>("DoUpdate_Enter_ToggleChat"));
        c.Index += 1;
        ILLabel skipLabel = il.DefineLabel(c.Next);
        c.EmitDelegate(Decide);
        c.Emit(OpCodes.Brtrue, skipLabel);
        c.Emit(OpCodes.Ret);  // 直接 return，跳过整个帧更新
    }

    private bool Decide()
    {
        if (paused)
        {
            if (stepReady) { stepReady = false; return true; }
            return false;  // 返回 false → Emit(Ret) → DoUpdate 直接返回
        }
        return true;
    }
}
```

**机制**：MonoMod IL hook 拦截 `Main.DoUpdate`，在 `DoUpdate_Enter_ToggleChat` 之后插入判断。`paused=true` 时 `DoUpdate` 直接 `Ret`，整个帧不更新。`stepReady=true` 时放行一帧（单步）。

**Hook 位置**：`IL_Main.DoUpdate`（MonoMod.Cil，tModLoader 提供的 On/IL 钩子体系）

### 冻结时游戏状态

完全停止：`DoUpdate` 是 Terraria 所有逻辑的入口（AI、物理、时间、实体更新均在此）。`Ret` 之后什么都不跑。绘制循环（`Draw`）与 `DoUpdate` 分离，继续运行，所以画面保持可见但静止。

### 可用方案分析

**A 方案：copy 冻结逻辑到 TerraBlind**
- 需要 MonoMod 依赖（tModLoader 已内置，可用）
- `IL_Main.DoUpdate` hook 在同一进程只能有一个有效（多 mod hook 相同方法会叠加，顺序不可控）
- 如果 DragonLens 也加载，两个 hook 同时存在，`paused` 状态不同步 → 行为不可预测
- **结论：不可用（冲突风险）**

**B 方案：mod 间通信调用 DragonLens**
- tModLoader 支持 `ModContent.GetInstance<T>()` 跨 mod 访问 public static 字段
- `FrameAdvanceSystem.paused` 是 `public static`，可直接访问
- 需要 DragonLens 同时加载（用户已有）
- 弱依赖：用 `try { ... } catch { }` 包裹，DragonLens 不存在时降级为无冻结
- **结论：可用，推荐**

**C 方案：TerraBlind 自己实现**
- 同 A 方案的 hook 冲突问题
- 如果保证不同时加载 DragonLens，可行
- 但用户同时使用两者，不可行
- **结论：不可用**

### 推荐方案：B（借用 DragonLens）

```csharp
// TerraBlind FreezeSystem.cs
public static bool TryFreeze()
{
    try
    {
        var fas = ModLoader.TryGetMod("DragonLens", out var dl) ? dl : null;
        if (fas == null) return false;
        // 通过反射或 cross-mod Call 设置 FrameAdvanceSystem.paused
        var fasType = dl.Code.GetType("DragonLens.Content.Tools.Developer.FrameAdvanceSystem");
        fasType.GetField("paused", System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Static)
               .SetValue(null, true);
        return true;
    }
    catch { return false; }
}
```

**原因**：DragonLens 的 IL hook 已经正确处理单步逻辑，借用它等于复用一个经过测试的冻结实现，不引入新的 MonoMod hook，不产生冲突。

---

## A.3 P0 设计：结构化日志 + 异常事件包

### A.3.1 JSONL 事件 schema

每行一个 JSON 对象，写入 `TerraBlindLogs/nav_events.jsonl`。

#### plan_start
```json
{
  "e": "plan_start",
  "tick": 12345,
  "sign": -1,
  "px": 1234, "py": 456,
  "excluded_goals": [[1200, 300], [1210, 302]]
}
```
字段：`e:string`, `tick:int`, `sign:int(-1|1)`, `px:int(tile)`, `py:int(tile)`, `excluded_goals:int[][]`

#### plan_done
```json
{
  "e": "plan_done",
  "tick": 12346,
  "goal": [1280, 450],
  "path_len": 18,
  "cost": 34.5,
  "path": [
    {"wx": 1235, "wy": 456, "action": "move"},
    {"wx": 1240, "wy": 454, "action": "jump"},
    ...
  ],
  "candidates_checked": 12,
  "envelope_len": 11
}
```
字段：`e:string`, `tick:int`, `goal:int[2]`, `path_len:int`, `cost:float`, `path:NavNode[]`, `candidates_checked:int`, `envelope_len:int`

NavNode: `{"wx":int, "wy":int, "action":string}`

#### plan_failed
```json
{
  "e": "plan_failed",
  "tick": 12346,
  "reason": "no_goal",
  "px": 1234, "py": 456,
  "candidates_rejected": [
    {"wx": 1270, "wy": 445, "reason": "excluded"},
    {"wx": 1265, "wy": 447, "reason": "no_progress"}
  ]
}
```
字段：`e:string`, `tick:int`, `reason:string`, `px:int`, `py:int`, `candidates_rejected:array[{wx:int,wy:int,reason:string}]`

#### node_enter
```json
{
  "e": "node_enter",
  "tick": 12400,
  "node_idx": 3,
  "action": "jump",
  "exp_start_wx": 1245, "exp_start_wy": 453,
  "exp_end_wx": 1252, "exp_end_wy": 451,
  "actual_px": 1245, "actual_py": 453,
  "vx": 3.0, "vy": 0.0
}
```
字段：`e:string`, `tick:int`, `node_idx:int`, `action:string`, `exp_start_wx:int`, `exp_start_wy:int`, `exp_end_wx:int`, `exp_end_wy:int`, `actual_px:int(tile)`, `actual_py:int(tile)`, `vx:float`, `vy:float`

#### node_exit
```json
{
  "e": "node_exit",
  "tick": 12440,
  "node_idx": 3,
  "action": "jump",
  "status": "done",
  "exp_end_wx": 1252, "exp_end_wy": 451,
  "actual_end_wx": 1253, "actual_end_wy": 451,
  "delta_x": 1, "delta_y": 0,
  "duration_ticks": 40
}
```
字段：`e:string`, `tick:int`, `node_idx:int`, `action:string`, `status:string(done|failed)`, `exp_end_wx:int`, `exp_end_wy:int`, `actual_end_wx:int`, `actual_end_wy:int`, `delta_x:int`, `delta_y:int`, `duration_ticks:int`

#### nav_failed
```json
{
  "e": "nav_failed",
  "tick": 12500,
  "reason": "stall",
  "last_node_idx": 3,
  "last_action": "jump",
  "px": 1246, "py": 453,
  "stall_count": 4
}
```
字段：`e:string`, `tick:int`, `reason:string(stall|deviate|replan_empty|replan_no_progress|jump_abort|bridge_blocked|no_platform)`, `last_node_idx:int`, `last_action:string`, `px:int`, `py:int`, `stall_count:int(-1 if not applicable)`

#### state_snapshot
```json
{
  "e": "state_snapshot",
  "tick": 12500,
  "px": 1246.3, "py": 453.1,
  "vx": 0.1, "vy": 0.0,
  "hp": 100,
  "on_ground": true,
  "terrain": "1246,453:0,1246,454:1,1247,453:0,..."
}
```
字段：`e:string`, `tick:int`, `px:float`, `py:float`, `vx:float`, `vy:float`, `hp:int`, `on_ground:bool`, `terrain:string(RLE编码 wx,wy:solid)`

terrain 格式：`"wx,wy:s"` 其中 s=0(air)/1(solid)，±20 格范围，用逗号分隔。

#### jump_frame（高频，仅在 Jump 状态）
```json
{
  "e": "jump_frame",
  "tick": 12415,
  "px_tile": 1248, "py_tile": 451,
  "vx": 3.0, "vy": -2.5,
  "air_frames": 15
}
```
每 5 帧记录一次（减少 IO）。字段：`e:string`, `tick:int`, `px_tile:int`, `py_tile:int`, `vx:float`, `vy:float`, `air_frames:int`

### A.3.2 异常触发条件

| 触发器 | 条件 | 初始阈值 |
|--------|------|---------|
| nav_failed | NavCoordinator.State → Failed | 立即 |
| stall | 同 tile x 连续 N 次（每 60 帧检查一次） | N=4 |
| jump_deviate | node_exit delta_x > N 格（jump action） | N=2 |
| bridge_deviate | node_exit delta_x > N 格（bridge action） | N=2 |
| move_miss | move 状态 feetY > segStartY+DeviateY | N=10（已有） |
| blacklist_full | failed_goals 达到 MAX | 20（已有） |

每个触发器都调用 `WriteDebugReport(trigger_id, trigger_reason)`。

### A.3.3 事件包内容

文件：`TerraBlindLogs/debug_reports/{tick}_{trigger}.json`

示例结构：
```json
{
  "triggered_by": {
    "reason": "stall",
    "tick": 12500,
    "node_idx": 3,
    "action": "jump"
  },
  "pre_window": [
    {"e": "plan_done", "tick": 12346, ...},
    {"e": "node_enter", "tick": 12400, ...},
    {"e": "jump_frame", "tick": 12405, ...},
    ...
  ],
  "state": {
    "px": 1246.3, "py": 453.1,
    "vx": 0.1, "vy": 0.0,
    "path": [{"wx":1235,"wy":456,"action":"move"}, ...],
    "path_idx": 3,
    "blacklist": [[1200,300], [1210,302]],
    "terrain_around": "1226,433:0,..."
  },
  "layer_hints": ["execution", "jump"],
  "repro": {
    "player_tile_x": 1245,
    "player_tile_y": 453,
    "sign": -1,
    "excluded_goals": [[1200, 300]]
  }
}
```

`pre_window`：触发前 300 ticks（5 秒）的所有 JSONL 事件（内存环形缓冲，不从文件读）。

### A.3.4 双层 Bug 自动定位策略

#### 例 1：跳跃落点偏差

**报告必含字段**
- 规划层（来自 `plan_done`）：`path[node_idx]` 的 `exp_start_wx/wy`、`exp_end_wx/wy`；`envelope_len`；`cost`
- 执行层（来自 `node_enter`）：起跳时的 `vx`、`vy`
- 执行层（来自多个 `jump_frame`）：每 5 帧的 `px_tile`、`py_tile`、`vx`、`vy`、`air_frames`
- 执行层（来自 `node_exit`）：`actual_end_wx`、`actual_end_wy`、`delta_x`、`delta_y`

**判定规则**

```python
# 从报告中提取
env = plan_done["envelope"]  # dy 数组
frames = [f for f in pre_window if f["e"] == "jump_frame"]
enter = next(f for f in pre_window if f["e"] == "node_enter" and f["action"] == "jump")

# 比较实际轨迹 vs envelope 预测
start_x = enter["actual_px"]
vx_actual = abs(enter["vx"])
TILE = 16.0

for f in frames:
    col = int(round((f["px_tile"] - start_x) * sign))  # 飞行列数
    if 0 < col < len(env):
        predicted_dy = env[col]
        actual_dy = f["py_tile"] - enter["actual_py"]
        delta = abs(actual_dy - predicted_dy)
        if delta > 1:
            trajectory_diverges = True
            break
else:
    trajectory_diverges = False

if not trajectory_diverges:
    # 实际轨迹符合 envelope → 执行层问题
    # 检查 stopAhead 和落地判定
    conclusion = "execution: stopAhead or landing detection"
elif abs(vx_actual - 3.0) > 0.3:
    # 起跳 vx 不够
    conclusion = "execution: vx not at max at takeoff"
else:
    # 轨迹偏离且 vx 正常 → 规划层 envelope 公式错
    conclusion = "planning: envelope formula"
```

#### 例 2：走进死路（goal 为 wall-foot 或 pit-bottom）

**报告必含字段**
- `plan_done`：`goal`、`path`、`candidates_checked`
- `plan_failed`（若本次 replan）：`candidates_rejected`，每条含 `{wx, wy, reason}`
- `nav_failed`：`reason="replan_no_progress"`，`px`、`py`
- `state_snapshot`：`terrain_around`

**判定规则**

```python
goal = plan_done["goal"]  # [wx, wy]
gx, gy = goal

# 从 terrain_around 重建地形
terrain = parse_terrain(state["terrain_around"])

def solid(wx, wy): return terrain.get((wx, wy), 0) == 1

# 检查 goal 是否为死路
is_wall_foot = solid(gx + sign, gy) or solid(gx + sign, gy - 1)
is_pit_bottom = not solid(gx, gy + 1)  # 脚下无地
can_move_forward = any(
    not solid(gx + sign * i, gy) and solid(gx + sign * i, gy + 1)
    for i in range(1, 4)
)

if is_wall_foot:
    conclusion = "planning: CanProgress false-positive on wall-foot goal"
elif is_pit_bottom:
    conclusion = "planning: goal selected at pit bottom"
elif not can_move_forward:
    conclusion = "planning: CanProgress K=3 insufficient for this terrain"
else:
    conclusion = "execution: player physically cannot reach goal despite valid plan"
```

#### 例 3：bridge 没建好

**报告必含字段**
- `node_enter`（bridge）：`exp_end_wx`、`exp_end_wy`；进入时 `vx`、`vy`
- `node_exit`（bridge）：`status`、`actual_end_wx`、`actual_end_wy`、`delta_x`
- `nav_failed`：`reason`（可能是 `bridge_blocked` 或 `replan_empty`）
- `state_snapshot`：`terrain_around`（重建当时地形）

**判定规则**

```python
enter = node_enter  # bridge action
exit_ = node_exit

terrain = parse_terrain(state["terrain_around"])
exp_wx = enter["exp_end_wx"]
exp_wy = enter["exp_end_wy"]

def solid(wx, wy): return terrain.get((wx, wy), 0) == 1
def standable(wx, wy): return not solid(wx, wy) and solid(wx, wy + 1)

# 检查 bridge 目标位置是否可站
target_standable = standable(exp_wx, exp_wy)
# 检查路径上是否有墙阻挡
start_wx = enter["actual_px"]
path_blocked_at = None
for wx in range(start_wx, exp_wx + sign, sign):
    if solid(wx, exp_wy) or solid(wx, exp_wy - 1) or solid(wx, exp_wy - 2):
        path_blocked_at = wx
        break

if not target_standable:
    conclusion = "planning: bridge target not standable (cliff case, yMax too small)"
elif path_blocked_at is not None:
    if exit_["status"] == "failed" and nav_failed["reason"] == "bridge_blocked":
        conclusion = "execution: bridge blocked mid-span, replan triggered"
    else:
        conclusion = "execution: bridge blocked but not detected"
else:
    conclusion = "execution: platform placement failed (no item or wrong cursor)"
```

#### 例 4：pillar 选不出 / 选错落点

**报告必含字段**
- `plan_done`：检查 `path` 中是否有 `action="pillar"` 节点，以及该节点的 `wy` vs 实际墙顶
- `node_enter`（pillar）：`exp_end_wy`（期望上升后 feetY）
- `nav_failed`（若发生）：`reason`，`px`、`py`
- `state_snapshot`：`terrain_around`（重建墙的高度）

**判定规则**

```python
terrain = parse_terrain(state["terrain_around"])
px, py = state_snapshot["px_tile"], state_snapshot["py_tile"]

def solid(wx, wy): return terrain.get((wx, wy), 0) == 1

# 重建墙顶 Y
wall_x = px + sign
top_y = py
while top_y > py - 20 and solid(wall_x, top_y - 1):
    top_y -= 1
wall_height = py - top_y

# 检查 plan 里的 pillar 节点
pillar_node = next((n for n in plan_done["path"] if n["action"] == "pillar"), None)

if pillar_node is None:
    # 规划层根本没生成 pillar
    if wall_height > 0 and not solid(px, top_y) and not solid(px, top_y - 1):
        conclusion = "planning: pillar edge not generated (cost too high or bridge preferred)"
    else:
        conclusion = "planning: wall not blocking or space insufficient"
elif pillar_node["wy"] != top_y:
    conclusion = f"planning: pillar target wy={pillar_node['wy']} != wall_top={top_y}"
elif nav_failed is not None:
    conclusion = "execution: SkillExecutor.StartPillarJump failed to reach target"
else:
    conclusion = "ok: pillar succeeded"
```

---

## A.4 P1 设计：断点 + 远程控制

### A.4.1 断点条件 schema

`POST /breakpoint_set`
```json
{
  "id": "string",
  "on": "nav_failed | node_action_eq | position_in_box | delta_gt | blacklist_size_gte",
  "value": "string (for node_action_eq)",
  "x": [int, int],
  "y": [int, int],
  "field": "string (for delta_gt)",
  "threshold": "float (for delta_gt)",
  "n": "int (for blacklist_size_gte)"
}
```

`POST /breakpoint_clear`
```json
{"id": "string"}
```

`GET /breakpoints` → `{"breakpoints": [...]}`

### A.4.2 冻结接口（基于 B 方案）

`POST /freeze` → `{"ok": true, "frozen": true}`
`POST /unfreeze` → `{"ok": true, "frozen": false}`

冻结状态下可用端点：`/state`, `/inspect`, `/nav_path`, `/step_node`
冻结状态下禁用：`/control`, `/nav_start`, `/nav_stop`, `/plan_path`（返回 `{"error":"frozen"}`）

### A.4.3 远程检查接口

`GET /inspect`
```json
{
  "tick": 12500,
  "frozen": true,
  "nav_state": "Jump",
  "path_idx": 3,
  "path_len": 18,
  "px": 1246.3, "py": 453.1,
  "vx": 0.1, "vy": -2.0,
  "blacklist": [[1200, 300]],
  "recent_events": [
    {"e": "node_enter", "tick": 12400, ...},
    {"e": "jump_frame", "tick": 12405, ...}
  ]
}
```

`POST /step_node` → 解冻一帧直到下一个 `node_exit`，然后重新冻结
```json
{"ok": true, "completed_node_idx": 3, "status": "done"}
```

`POST /continue` → 解冻，继续运行（等下次断点）
```json
{"ok": true}
```

---

## A.5 实现计划

| 文件 | 改动 | 估算行数 |
|------|------|---------|
| `DiagLog.cs` | 加 `WriteEvent(string json)` 写 JSONL；内存环形缓冲 300 ticks；`FlushWindow()` 返回切片 | ~60 |
| `NavCoordinator.cs` | node_enter/node_exit 事件；nav_failed 事件；state_snapshot 触发；接入 BreakpointSystem | ~80 |
| `PathPlanner.cs` | plan_start/plan_done/plan_failed 事件；candidates_rejected 收集 | ~60 |
| `HttpServerSystem.cs` | 加 `/freeze` `/unfreeze` `/inspect` `/step_node` `/continue` `/breakpoint_set` `/breakpoint_clear` 端点 | ~100 |
| `FreezeSystem.cs`（新） | 借用 DragonLens FrameAdvanceSystem；`Freeze()` / `Unfreeze()` 反射实现 | ~40 |
| `BreakpointSystem.cs`（新） | 断点注册/评估；触发时调 FreezeSystem.Freeze() + WriteDebugReport() | ~80 |
| `exec_astar.py` | jump_deviate 触发判定（从 `/nav_path` 读 node_exit delta）；写 debug_reports JSON；轮询 debug_reports/ 打印新报告 | ~60 |

每项改动理由：
- `DiagLog.cs`：所有结构化事件的底层写入，其他文件依赖它
- `NavCoordinator.cs`：执行层事件的唯一来源（node enter/exit/failed）
- `PathPlanner.cs`：规划层事件唯一来源（candidates、envelope、path）
- `HttpServerSystem.cs`：对外暴露所有新接口
- `FreezeSystem.cs`：隔离 DragonLens 依赖，其他模块不直接 import DragonLens
- `BreakpointSystem.cs`：断点评估逻辑集中，不散布在各个文件
- `exec_astar.py`：Python 端事件包写入（因为报告文件在 Python 进程侧更方便 Claude 读取）

---

## A.6 风险

1. **JSONL 写盘 IO 瓶颈**：60fps 下如果每帧写 `jump_frame` 事件，IO 开销大。缓解：`jump_frame` 每 5 帧记一次；其他事件频率低，可接受。极端情况：环形缓冲只写内存，触发时才 flush。

2. **DragonLens 反射冻结稳定性**：`FrameAdvanceSystem.paused` 是 `public static`，反射访问不依赖版本。但若 DragonLens 更新后重命名该字段，反射失败 → 降级为无冻结（不崩溃，只是 P1 功能不可用）。

3. **事件包大小**：terrain ±20 格 = 40×40=1600 格，每格 `wx,wy:s` ≈ 15 bytes → ~24KB per report。pre_window 300 ticks 最多 ~300 行 JSONL ≈ 50KB。总计 ~80KB per report，可接受。

4. **node_exit 时机问题**：step_node 需要等到 `node_exit` 才重新冻结。如果节点执行卡住（stall），step_node 会一直运行不冻结，直到 stall 触发 replan 才产生 nav_failed 事件。需要加超时：step_node 最多解冻 300 ticks，超时强制冻结。
