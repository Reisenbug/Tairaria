# Terraria Agent — 项目概览

## 目标

让AI Agent自主在Terraria中移动、探索、最终击败Wall of Flesh。当前阶段：**地面水平导航（向左/右连续行走）**。

---

## 架构总览

```
Python (scripts/)          mod TerraBlind (C#, 60fps)
  exec_astar.py  ───POST /nav_start {sign}───▶  NavCoordinator
                 ◀───GET  /nav_done ──────────   └─ PathPlanner (A*)
                                                  └─ JumpCoordinator
                                                  └─ PlaceCoordinator
                                                  └─ SkillExecutor
```

**原则：时序敏感逻辑全在mod端 60fps 执行，Python只负责触发和轮询状态。**

---

## 关键文件

### Python端

| 文件 | 作用 |
|------|------|
| `scripts/exec_astar.py` | 主入口，循环调用 /nav_start，轮询 /nav_done |
| `scripts/debug_astar.py` | 可视化Python端A*(已弃用，用debug_astar2) |
| `scripts/debug_astar2.py` | 可视化mod端 /plan_path 规划结果 |
| `scripts/debug_surface.py` | 可视化地表skyline |
| `src/terraria_agent/terrain_astar2.py` | Python端A*（已有但exec_astar不再用） |
| `src/terraria_agent/terrain_nav.py` | Python端导航状态机（已被mod端NavCoordinator取代） |

### Mod端 (~/Library/Application Support/Terraria/tModLoader/ModSources/TerraBlind/)

| 文件 | 作用 |
|------|------|
| `PathPlanner.cs` | A*路径规划，用真实物理参数算跳跃包络 |
| `NavCoordinator.cs` | 导航状态机：Idle/Move/Fall/Jump/Bridge/Pillar/Done/Failed |
| `JumpCoordinator.cs` | 跳跃执行：走到起跳点→跳→空中按方向→落地检测done |
| `PlaceCoordinator.cs` | 放置方块（bridge用） |
| `SkillExecutor.cs` | pillar_jump技能回放 |
| `HttpServerSystem.cs` | HTTP API，端口17878 |
| `DiagLog.cs` | 写日志到 `~/Library/.../TerraBlindLogs/jump_trace.log` |
| `StateSnapshotPlayer.cs` | 每帧调用各Coordinator.ApplyControls() |

---

## HTTP API

| 端点 | 方法 | 参数 | 说明 |
|------|------|------|------|
| `/nav_start` | POST | `{"sign": 1}` | 开始导航，sign=1右/-1左 |
| `/nav_stop` | POST | `{}` | 停止导航（**必须调用才能停mod**，kill Python进程不够） |
| `/nav_done` | GET | — | `{"status":"running/done/failed","reason":"..."}` |
| `/plan_path` | POST | `{"sign": 1}` | 只规划不执行，返回路径JSON |
| `/jump_envelope` | GET | — | 当前玩家跳跃包络（dy数组） |
| `/state` | GET | — | 完整游戏状态快照 |
| `/control` | POST | `{"left":true,...}` | 单帧控制输入 |
| `/jump` | POST | `{"direction":"right","launch_x":X,"target_x":X}` | 单次跳跃 |
| `/place` | POST | `{"dx":1,"dy":1,"slot":0,"duration_frames":12}` | 放置方块 |
| `/skill` | POST | `{"name":"pillar_jump","direction":"right","rise_tiles":8}` | 执行技能 |

---

## NavCoordinator 状态机

```
Start(sign)
  └─ Idle ──→ 读下一个path节点
               ├─ action=move   → Move（方向由 target.Wx vs pcx 决定，非全局 sign）
               ├─ action=fall   → Fall
               ├─ action=jump   → ResimJump(startVx=p.velocity.X) → ReplaySystem → Jump
               ├─ action=bridge → Bridge (PlaceCoordinator)
               └─ action=pillar → PillarAlign → SkillExecutor.StartPillarJump → Pillar
                   （rise > PillarThresh 的 move 节点也会强制走 PillarAlign）

  Move:       方向键到 targetX，到达→pathIdx++→Idle
  Fall:       方向键，落地检测→pathIdx++→Idle
  Jump:       ReplaySystem 执行帧序列，落地→pathIdx++→Idle
  Bridge:     PlaceCoordinator放砖+走，到达→pathIdx++→Idle
  PillarAlign: 物理预测刹车距离，走到 pillar 起跳 x，停稳→SkillExecutor
  Pillar:     SkillExecutor 跑完→高度校验→pathIdx++→Idle（失败→Replan）

  path空 → PathPlanner.Plan(sign) 重规划
  Stall (60帧×4次pcx不变) → Replan
  Deviate (feetY > segStartY + 10) → Replan
  Done / Failed → 结束
```

---

## PathPlanner (A*) 逻辑

- **起点**：`pcx = centerX/16`, `feetY` 从底部往上找第一个非实心格
- **终点**：扫描 `pcx-60..pcx+60` 范围内每列第一个standable格，取 score 最高的（fwd + rise*2）
- **邻居边**：
  - `move` (dx=±1, dy=0/±1)：cost = `1 + dist_to_ground`
  - `fall` (dy=+1)：cost = `0.5`
  - 不允许纯向上 move
- **跳跃边**：`BuildJumpEdges` 用 PhysicsSimulator 精确积分，扫所有 HoldFrameOptions；cost = `max(col + overhead - rise_bonus, 1)`
  - pillar 后的跳跃节点用 `overrideVx=0f`（玩家从静止起跳）
  - 普通节点用 `sign * MaxRun`
  - `ArcClipsWall`：仅检查上升阶段头行 tile，侧面不拦截
- **pillar边**：同列向上延伸，rise > 7 格触发，cost = `3 + rise`
- **bridge边**：沿方向延伸 1..15格，cost = `4 + col*2 + shallow_penalty`
- **GoalRangeFwd=60, GoalRangeBack=60**（支持规划绕道回退路径）
- **MVP 假设**：maxRunSpeed=3.0（裸玩家），buff 场景加 WARN log 但不处理

---

## JumpCoordinator 逻辑

JumpCoordinator 负责精确对位起跳点（launchX），ReplaySystem 负责执行跳跃帧序列。

```
StartReplay(dirRight, launchX)
  阶段1: 走到 launchX（posOk && vxOk 时触发，标记 _active=false）
  → NavCoordinator 检测到 JumpCoordinator 不再 active，ReplaySystem 开始回放跳跃帧

Start(dirRight, launchX, targetX)  ← 备用，非replay模式
  阶段1: 走到 launchX
  阶段2: 按住 jump (jumpHeight+2帧) + 按方向键
  落地: prevVY > 0 && velocity.Y == 0 → Done
```

**ResimJump**（在 NavCoordinator 内）：进入 Jump 状态时，用 `p.velocity.X` 作为 startVx，遍历 HoldFrameOptions，选落点最接近 target.Wx 的 hold，生成 ReplayFrame 序列。pillar→jump 时 vx≈0，普通 move→jump 时 vx≈MaxRun，两种情况自动处理。

---

## 日志调试

日志路径：
```
~/Library/Application Support/Terraria/tModLoader/TerraBlindLogs/jump_trace.log
```

读日志：
```bash
LOG="$HOME/Library/Application Support/Terraria/tModLoader/TerraBlindLogs/jump_trace.log"
grep "jump landed" "$LOG"
```

典型日志格式：
```
7325 [nav] node[11] (2149,236) jump from (2152,237)
7375 [nav] jump landed (2147,236) expected (2149,236)
```
- 第一列是游戏tick
- `expected (wx,wy)` 是path节点坐标
- 实际落点是 `landed` 后的坐标
- 偏差 = landed_wx - expected_wx

---

## 常见问题

### 1. kill Python后mod还在动
`NavCoordinator` 是mod端状态机，Python进程退出不影响它。必须调用：
```bash
curl -X POST http://localhost:17878/nav_stop -d '{}'
```

### 2. visited=1 / no forward standable
**原因**：`feetY` 落在实心块内（玩家脚在墙里），起点不可达。
**fix已有**：`while Solid(pcx, feetY) feetY--`
**还可能发生**：玩家在空中时调plan，feetY算出来是空气格且下面没有ground

### 3. 跳跃落点偏差
**现象**：expected 2149，landed 2147，差2格
**原因**：ResimJump 在起跳时模拟，但实际起跳时机（posOk && vxOk）有 ±4px 误差，累积为 ±1 格偏差
**当前目标（MVP）**：mean 误差 < 0.5 格（裸玩家，无 buff）
**调试方法**：清空日志 → 跑15秒 → grep node_exit + landed 对比

### 4. bridge方向dx不对称
- 右：`dx=1, dy=1`（放脚前方1格右侧）
- 左：`dx=-2, dy=1`（放脚前方1格左侧）
原因：玩家宽2格，左向放置锚点偏移不同

### 5. Replan死循环
- 起点附近没有standable节点 → plan返回空 → Replan → 无限循环
- 表现：日志里反复出现 `[plan] no goal found` 或 `[plan] fallback→(pcx,feetY)`

### 6. stopAhead系数调试方法（自动化）
```bash
# 清空日志
> "$HOME/Library/Application Support/Terraria/tModLoader/TerraBlindLogs/jump_trace.log"
# 跑15秒
python -u scripts/exec_astar.py &
PID=$!
sleep 15
curl -s -X POST http://localhost:17878/nav_stop -d '{}'
kill $PID 2>/dev/null
# 统计误差
grep "jump landed" "$HOME/Library/Application Support/Terraria/tModLoader/TerraBlindLogs/jump_trace.log" | \
  python3 -c "
import sys, re
errs = []
for line in sys.stdin:
    m = re.search(r'landed \((\d+),\d+\) expected \((\d+),\d+\)', line)
    if m:
        errs.append(int(m.group(1)) - int(m.group(2)))
if errs:
    print(f'n={len(errs)} mean={sum(errs)/len(errs):.2f} min={min(errs)} max={max(errs)}')
"
```
mean接近0说明系数合适，mean<0说明偏短需要减小stopAhead，mean>0说明偏长需要增大。

---

## 物理参数参考（默认裸玩家）

| 参数 | 值 | 说明 |
|------|-----|------|
| `Player.jumpSpeed` | 5.01 | 起跳初速 px/frame |
| `Player.jumpHeight` | 15 | 按住jump的帧数 |
| `gravity` | 0.4 | 每帧重力加速度 |
| `maxRunSpeed` | 3.0 | 最大水平速度 px/frame |
| `accRunSpeed` | 0.08 | 水平加速度 |
| `runSlowdown` | 0.2 | 地面减速（松键每帧减0.2） |
| 稳定跳跃距离 | ~6-7格 | 用户实测 |

**注意**：空中没有runSlowdown，松手后水平速度几乎不变直到落地。

---

## 编译工作流

1. 改 `.cs` 文件
2. 游戏内 `/build TerraBlind`（或开发者菜单重新加载mod）
3. 用户确认 "1" = 编译加载完成
4. 清空日志，运行测试，读日志验证
5. 验证通过再commit
