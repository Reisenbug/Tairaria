# Terraria Agent — 规划/执行矛盾缓解任务

## 背景

项目当前状态：
- mod 端 PathPlanner (A*) 在规划阶段对玩家物理状态做了静态假设
- 执行阶段（NavCoordinator + JumpCoordinator + ReplaySystem）在真实 60fps 物理下不可避免偏离假设
- stopAhead 系数已调好,系统性偏差消除,但结构性矛盾仍在

详细架构见 PROJECT_OVERVIEW.md。本次任务**不改变架构**,只在现有状态机内补强容错。

## 物理参数(裸玩家,MVP前提)

jumpSpeed=5.01, jumpHeight=15, gravity=0.4
maxRunSpeed=3.0, accRunSpeed=0.08, runSlowdown=0.2 (地面)
空中无水平减速。

## 工作流约束

1. 改 .cs 文件后必须 `/build TerraBlind`,等用户确认 "1" 才算编译完成
2. 每个任务完成后:清空 jump_trace.log → 运行 exec_astar.py 15秒 → grep 日志验证 → 用户确认通过再 commit
3. 日志路径:`~/Library/Application Support/Terraria/tModLoader/TerraBlindLogs/jump_trace.log`
4. 停止 mod 必须 `curl -X POST http://localhost:17878/nav_stop -d '{}'`,kill Python 不够
5. 按下面的任务顺序执行,**完成一个、验证一个、commit 一个**,不要并行

---

## 任务1: Replan 起点保护(修死循环 bug)

### 问题

NavCoordinator 触发 Replan 时直接调 PathPlanner.Plan(sign),但当前 (pcx, feetY) 可能不是 standable:
- 玩家在空中(jump/fall 中途被 Replan)
- 玩家脚陷在实心块边缘
- 玩家站在已被改动的 bridge 残片上

PathPlanner 此时返回空路径或 fallback 到 (pcx, feetY) 自身,触发再次 Replan,形成死循环。
表现:日志反复出现 `[plan] no goal found` 或 `[plan] fallback→(pcx,feetY)`。

### 改动范围

- `NavCoordinator.cs`:在 Replan 入口前增加 RecoverToStandable 阶段
- 新增状态:`Recover`(在 Idle 与 Plan 调用之间)

### 实现

1. NavCoordinator 状态机增加 `Recover` 状态
2. 触发 Replan 时,先检查当前 (pcx, feetY):
   - 用 PathPlanner 已有的 standable 判定逻辑(是否需要把它抽成 public static helper,你判断)
   - 是 standable → 直接进 Plan(走原流程)
   - 不是 → 进 Recover 状态
3. Recover 状态的恢复策略(按优先级尝试):
   a. 玩家在空中(velocity.Y != 0 或脚下非 Solid):什么都不按,等落地。落地后重新检查
   b. 玩家脚陷墙(Solid(pcx, feetY) == true):向上扫描第一个非实心格(`while Solid(pcx, feetY) feetY--`),如果扫到的位置脚下有 Solid 且头顶空,就视为 standable;否则按 d
   c. 玩家在窄缝/单格平台:向左/右各试一格,谁先到达 standable 就走谁
   d. 60 帧内仍未恢复 → 进 Failed,reason="recover_timeout"
4. Recover 成功 → 进 Plan;Recover 失败 → 进 Failed
5. **不允许 Recover 内部直接调用 PathPlanner**(避免递归)

### 日志要求

新增日志 tag `[recover]`,格式:
```
[recover] start (pcx,feetY) reason=in_air|in_wall|narrow|other
[recover] attempt strategy=wait_landing|scan_up|step_left|step_right
[recover] done -> standable (pcx,feetY) after N frames
[recover] fail reason=...
```

### 验证

构造测试场景(用户帮忙在游戏里复现):
1. 玩家从悬崖跳下,在空中调 /nav_start → 应该看到 wait_landing,落地后正常 plan
2. 用 /jump 把玩家送进墙里 → 应该看到 scan_up 或 step_*,然后正常 plan
3. 跑常规 15秒导航测试 → 不应有 `[plan] fallback→(pcx,feetY)` 死循环

### Commit message

```
nav: add Recover state before Replan to prevent infinite loop

When Replan is triggered while player is in invalid position
(in air, in wall, on bridge debris), PathPlanner used to fail
and trigger another Replan immediately. Now we recover the player
to a standable tile first, then plan.
```

---

## 任务2: 持续闭环监控(预警偏差,提前 Replan)

### 问题

当前 Replan 触发条件:
- path 空
- Stall(60帧×4次 pcx 不变)= 240帧才触发
- Deviate(feetY > segStartY + 10)

Stall 240帧 ≈ 4秒,Deviate 10格,都太宽容。等到触发时偏差已经累积很大。

### 思路

每个 path 节点在创建时携带:
- `expected_arrival_tick`(从段开始算的预期帧数)
- `expected_pos`(节点目标 wx,wy)

每帧检查实际进度,如果**偏差速率**异常就提前 Replan。

### 改动范围

- `PathPlanner.cs`:输出的 path 节点结构体增加 `expectedFrames` 字段(在 Plan 时算出)
- `NavCoordinator.cs`:每帧在 Move/Jump/Bridge/Pillar 状态内调用 CheckProgress()

### 实现

1. PathPlanner 在生成每条边时记录预期帧数:
   - move 边:`Math.Abs(dx) * 16f / MaxRun`(粗略,假设全速)
   - fall 边:用 PhysicsSimulator 算落地帧数
   - jump 边:已经在 BuildJumpEdges 里算过 hold,加上落地帧
   - bridge 边:`col * 16f / MaxRun + col * placeFrames`
   - pillar 边:`rise * placeFrames + 一次跳跃`(用现有常量)

2. NavCoordinator 在进入每个节点时记录 `_segStartTick = Main.GameUpdateCount`

3. 每帧 CheckProgress():
   ```
   elapsed = currentTick - _segStartTick
   expected = currentNode.expectedFrames
   if elapsed < expected * 0.5: return  // 太早不判
   if elapsed > expected * 2.0:
       Log("[progress] timeout node[i] elapsed={elapsed} expected={expected}")
       Replan("progress_timeout"); return
   ```

4. 额外的偏差速率检查(只在 Move 状态):
   ```
   actualProgress = (pcx - _segStartPcx) / Math.Sign(targetX - _segStartPcx)  // 朝目标方向的进度
   expectedProgress = elapsed / expected * abs(targetX - _segStartPcx)
   if actualProgress < expectedProgress * 0.3 and elapsed > 60:
       Replan("progress_too_slow"); return
   ```

5. **保留**现有的 Stall 检测,但阈值降到 60帧×2次(共120帧),作为兜底

### 日志要求

```
[progress] node[i] elapsed=N expected=M ratio=X.XX
[progress] timeout/slow node[i] -> replan
```

只在触发 Replan 时打,正常进度不打(避免日志爆炸)。

### 验证

1. 跑 15秒常规测试 → 比较 Replan 触发次数是否合理(不应频繁触发,但 Stall 应该几乎不出现了)
2. 人为让玩家被怪物击退 → 应该在 1-2 秒内触发 progress Replan,而不是等 4 秒 Stall
3. grep `[progress]` 日志,统计 timeout vs slow 比例

### Commit message

```
nav: add progress monitoring for early Replan

Stall detection (240 frames) is too lax. Now each path node
carries expectedFrames; if elapsed exceeds 2x expected or
forward progress falls below 30% of expected after 60 frames,
trigger Replan immediately instead of waiting for Stall.
```

---

## 任务3: Jump 边鲁棒性评分

### 问题

PathPlanner.BuildJumpEdges 当前对每条 jump 边只测试一次"假设 vx 和 launchX",选最优 hold。但执行时 vx 有 ±0.3 随机偏差,launchX 有 ±4px 触发误差。规划层对此一无所知,可能选了一条"理论可达但容错为零"的边。

### 思路

每条候选 jump 边在 BuildJumpEdges 阶段做 9 点扰动测试(vx 域 3 点 × launchX 域 3 点),统计有多少落点仍落在 target 的 standable 邻域。鲁棒性纳入 cost。

### 改动范围

- `PathPlanner.cs::BuildJumpEdges`
- 不改其他文件

### 实现

1. 对每条候选 (launchNode, targetNode, hold):
   ```
   vxBase = sign * MaxRun  (或 0 for pillar)
   launchXBase = launchNode.Wx * 16 + 8
   
   robustHits = 0
   for vxDelta in [-0.3, 0, +0.3]:
       for xDelta in [-4, 0, +4]:
           landing = PhysicsSimulator.Simulate(vxBase+vxDelta, launchXBase+xDelta, hold)
           if Math.Abs(landing.tileX - targetNode.Wx) <= 1 and IsStandable(landing.tileX, landing.tileY):
               robustHits += 1
   ```

2. 鲁棒性纳入 cost:
   ```
   baseCost = max(col + overhead - rise_bonus, 1)
   if robustHits >= 8: finalCost = baseCost          // 鲁棒
   elif robustHits >= 5: finalCost = baseCost * 1.3
   elif robustHits >= 3: finalCost = baseCost * 2.0
   else: continue  // 跳过这条边,太脆弱
   ```

3. 当 launchNode 是 pillar 出口时,vxDelta 域改成 [-0.1, 0, +0.1](pillar 起跳 vx 接近严格 0)

4. 性能预算:扰动测试每条边多 8 次 PhysicsSimulator.Simulate 调用。如果 BuildJumpEdges 耗时 > 50ms 影响实时性,在 PathPlanner 内加耗时日志,先看实际开销再决定是否优化(比如把扰动测试做成并行,或者只对 col >= 4 的长跳边测试)。

### 日志要求

```
[plan] jump edge (a,b)->(c,d) hold=H robustHits=N/9 cost=C
```

只在 verbose 模式打(NavCoordinator 已有 verbose 开关?如无,加一个)。

### 验证

1. 跑 15秒常规测试 → 跳跃落点 std deviation 应该下降(对比改动前后的 grep "jump landed" 统计)
2. 找一段地形多跳跃的区域 → 改动后选的路径应该偏向"短跳+宽落点",而不是"长跳+窄落点"
3. PathPlanner 单次调用耗时不超过原来的 3 倍(给 verbose 打耗时)

### Commit message

```
plan: add robustness scoring to jump edges

Each jump edge is now tested with vx ± 0.3 and launchX ± 4px
perturbations. Edges with < 3/9 robust landings are pruned;
others have cost scaled by robustness. This makes the planner
naturally avoid fragile long jumps to narrow platforms.
```

---

## 完成标准

三个任务全部 commit 后,做一次综合验证:
1. 清日志,跑常规 30 秒导航
2. grep 关键 tag:`[recover]`、`[progress]`、`[plan] jump edge`(verbose)
3. 统计:
   - jump landed 误差均值和方差(对比改动前的 baseline)
   - Replan 触发次数(应该比之前少,因为 progress 监控提前介入,但 recover 把无效 Replan 去掉了)
   - 是否还有死循环征兆(`[plan] fallback` 连续出现)

把上述统计写在最终 PR 描述里。

## 不在本次任务范围

以下事项明确**不做**,避免 scope creep:
- 重构 ResimJump / hold 选择函数化
- 段内重规划(jump 落点偏差时的局部修正)
- 长程+短程两层规划
- 任何 LLM 接入

这些是 jungle 阶段之前再考虑的事。
