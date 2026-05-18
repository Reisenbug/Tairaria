# Terraria Agent — 项目概览

## 目标

让 AI Agent 自主在 Terraria 中移动、探索、最终击败 Wall of Flesh。当前阶段：**任意位置导航（指哪去哪）**，包含挖掘、pillar、bridge、jump 的复合路径。

---

## 架构总览

```
Python (scripts/)          mod TerraBlind (C#, 60fps)
  NavWand (游戏内)  ────────▶  PathPlanner.PlanTo(wx,wy)
                               └─ A* 规划（含 mine/jump/pillar/bridge 边）
                               └─ PathVisSystem（可视化叠加）
  scripts/         ────POST──▶  NavCoordinator.StartTo(wx,wy)
                               └─ 执行状态机
```

**原则：时序敏感逻辑全在 mod 端 60fps 执行，Python 只负责触发和轮询状态。**

---

## 关键文件

### Mod 端 (`~/Library/Application Support/Terraria/tModLoader/ModSources/TerraBlind/`)

| 文件 | 作用 |
|------|------|
| `PathPlanner.cs` | A* 路径规划，支持 move/fall/jump/pillar/bridge/mine_* 边 |
| `NavCoordinator.cs` | 导航状态机：Idle/Move/Fall/Jump/Bridge/Pillar/Mine/MineAlign/Done/Failed |
| `NavWand.cs` | 左键规划+可视化，右键执行 |
| `SkillExecutor.cs` | pillar_jump 技能回放，dig 方向技能 |
| `MineCoordinator.cs` | 挖掘 tile 列表执行 |
| `PathVisSystem.cs` | 路径可视化：jump=黄/bridge=紫/fall=蓝/pillar=红/mine=橙 |
| `HttpServerSystem.cs` | HTTP API，端口 17878 |
| `DiagLog.cs` | 写日志到 `~/Library/.../TerraBlindLogs/jump_trace.log` |
| `StateSnapshotPlayer.cs` | 每帧调用各 Coordinator.ApplyControls() |
| `DECISIONS.md` | 关键设计决策记录（中文） |

### Python 端

| 文件 | 作用 |
|------|------|
| `scripts/vis_terrain.py` | ASCII 地形可视化，`python vis_terrain.py cx cy w h` |
| `scripts/vis_dig_targets.py` | 实时显示挖掘目标格（橙色） |
| `scripts/cursor_pos.py` | 实时报备光标位置 |

---

## HTTP API（端口 17878）

| 端点 | 方法 | 参数 | 说明 |
|------|------|------|------|
| `/state` | GET | — | 完整游戏状态快照 |
| `/nav_start` | POST | `{"sign":1}` | 地表方向导航（sign=1右/-1左） |
| `/nav_set_path` | POST | path JSON | 直接注入路径执行 |
| `/nav_stop` | POST | `{}` | 停止导航（**必须调用**，kill Python 不够） |
| `/nav_done` | GET | — | `{"status":"running/done/failed"}` |
| `/plan_path` | POST | `{"sign":1}` | 只规划不执行，返回路径 JSON |
| `/terrain` | POST | `{"cx":N,"cy":N,"w":40,"h":20}` | 返回 tile ASCII 地图（#=实心 -=平台 +=其他 .=空气） |
| `/skill` | POST | `{"name":"dig_down"}` | 执行 dig_down/dig_left/dig_right/dig_up |
| `/mine` | POST | `{"tiles":[{"wx":N,"wy":N},...]}` | 挖掘指定 tile 列表 |
| `/mine_stop` | POST | `{}` | 停止挖掘 |
| `/path_vis_tiles` | POST | `[{"wx":N,"wy":N,"r":255,"g":165,"b":0},...]` | 叠加任意颜色格子 |
| `/cursor` | GET | — | `{"mx":F,"my":F,"tile_x":N,"tile_y":N}` 光标相对玩家偏移 |
| `/control` | POST | `{"left":true,...}` | 单帧控制输入 |
| `/health` | GET | — | `{"ok":true}` |

---

## NavCoordinator 状态机

```
StartTo(goalWx, goalWy)
  └─ Idle → 读下一个 path 节点
             ├─ move       → Move
             ├─ fall       → Fall（controlDown 穿平台）
             ├─ jump       → ResimJump → ReplaySystem → Jump
             ├─ bridge     → Bridge（PlaceCoordinator 放砖）
             ├─ pillar     → PillarAlign → SkillExecutor.StartPillarJump → Pillar
             ├─ mine_down  → MineAlign → Mine（光标向下，等落地）
             ├─ mine_right → Mine（持续右走+挖，pcx>=target.Wx 完成）
             ├─ mine_left  → Mine（持续左走+挖，pcx<=target.Wx 完成）
             └─ mine_up    → Mine（光标向上，头顶净空完成）

  stall 检测排除：Pillar/PillarAlign/Jump/Mine/MineAlign
  replan no-progress：fixedGoalWx 模式下跳过检查
```

---

## PathPlanner A* 逻辑

### 两种规划模式

| 模式 | 函数 | goal 选取 | fallback |
|------|------|---------|---------|
| 地表导航 | `Plan(sign)` | 自动选最远前进节点 | 有 |
| 指哪去哪 | `PlanTo(wx,wy)` | 指定坐标，BFS r=3 找附近 Standable | 无 |

### 节点签名
`(cx, cy, bool hc)`，`hc=head_clear` 表示头顶已挖空。mine_up 将 dst.hc 置 true，jump/pillar 需要 headClear || hc。

### 边类型与 cost

| 边 | cost | 触发条件 |
|----|------|---------|
| move | `1 + dtg` | Standable/mineNode/bridgeNode/pillarTop，头顶净空 |
| fall | `0.5/格` | cx 和 cx+1 两列脚下都无 floor |
| jump | `max(col+overhead-riseBonus, 1)` | headClear 或 hc，JumpMinCol=0 |
| pillar | `3 + rise×6` | rise>7，leftClear 双列 |
| bridge | `10 + col×4 + penalty` | Standable 或 pillarTop，无硬上限 |
| mine_right | `solidCount×6 + 1` | canMineFrom，目标列非 Standable |
| mine_left | `solidCount×6 + 1` | 同上 |
| mine_down | `solidCount×6 + 0.5` | canMineFrom，脚下无 floor |
| mine_up | `solidCount×6` | canMineFrom，hc=false，头顶有 solid |

### 关键常量
```
GoalRangeFwd/Back = 60    AStarScanUp/Down = 50
HeuristicWeight = 1       maxMineDepth = |dx|+|dy|+8（动态）
JumpMinCol = 0            pillar rise 下限 = 7（待修复）
BridgeDtgThresh = 12      MineCostPerTile = 6
```

### 已知规划失败场景
- 目标被大面积实心包围，直线挖掘距离 > maxMineDepth
- pillar rise=7 被过滤（门槛 `rise <= 7` 待修复）
- HPA*（分层规划）未实现，复杂地形单层 A* 性能瓶颈

---

## 可视化

NavWand 左键规划后，游戏内叠加显示：
- 白色：玩家位置 / 黄色：jump / 紫色：bridge / 蓝色：fall / 红色：pillar / 橙色：mine

---

## 调试工具

```bash
LOG="$HOME/Library/Application Support/Terraria/tModLoader/TerraBlindLogs/jump_trace.log"
> "$LOG"  # 清空
grep -E "plan\]|wand|verify" "$LOG"       # 规划结果
grep -E "node|Replan|stall|mine" "$LOG"   # 执行流

# ASCII 地形
python3 scripts/vis_terrain.py                    # 以玩家为中心
python3 scripts/vis_terrain.py 2449 318 60 25     # 指定中心和范围
```

---

## 物理参数（裸玩家）

| 参数 | 值 |
|------|-----|
| jumpSpeed | 5.01 px/frame |
| jumpHeight | 15 帧 |
| gravity | 0.4 px/frame² |
| maxRunSpeed | 3.0 px/frame |
| accRunSpeed | 0.08 |
| runSlowdown | 0.2（仅地面） |

HoldFrameOptions = {8, 12, 15}，水下 = {10, 16, 22, 30}

---

## 编译工作流

1. 改 `.cs` 文件
2. 游戏内 `/build TerraBlind`，完成回复 1
3. 清空日志，NavWand 测试，读日志验证
4. 验证通过再 commit

---

## 当前待解决问题

1. pillar rise<=7 过滤门槛太高（应改为 0 或删除）
2. HPA*（分层规划）未实现，复杂地形规划失败率高
3. mine_up 执行层未充分测试
4. fix/planner-constraints branch 未 merge 进 main
5. ArcClipsWall 下降阶段不检查碰撞（已知缺陷，低优先级）
