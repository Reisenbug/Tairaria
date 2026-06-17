# 物理引擎复刻审计（PhysicsSimulator ↔ 原版 Player.Update）

**目的**：PhysicsSimulator 不是原版代码的"子集"，而是把原版 `Player.Update` 里**逐行交织的物理算术**摘出来、剥掉副作用（dust/sound/全局依赖）、重写成**可空跑、无副作用、依赖最小**的物理核——供 A* 规划器对假想状态空跑数千次。

本文档 = 一次完整通读 `Player.Update`（L23881–L27716）裸玩家全路径的结果，外加**非裸玩家扩展时照着补的地图**。

源码：`/Users/lhy/Documents/terraria-source/1.4.5.4/split/Player.cs`（按类拆分）、`Collision.cs`。
我们的实现：`~/Library/Application Support/Terraria/tModLoader/ModSources/TerraBlind/PhysicsSimulator.cs`。

---

## 0. 为什么是"摘+重写"而不是"搬整段"

原版 Update 里物理与非物理**逐行交织**，共用同一控制流与局部变量。例：出水段 L27262-27356——

```
wet = false;                          // 物理
if (jump > jumpHeight/5) jump=...;    // ★物理: hold cap
for (50次) Dust.NewDust(...);          // 特效
PlaySound(19, ...);                    // 音效
velocity.Y /= 2;                       // ★物理: 入水减速
```

物理行（★）夹在 dust/sound 中间。整段文本搬过来 → 编译器要求 `mount.CanFly`/`grappling[]`/`Dust.NewDust` 等符号全部存在 → 拖进整个 Player 类 + mount/wing/buff 子系统 = 半个 Terraria。

且规划器需要的是**对假想状态空跑、无副作用、可回滚、每秒数千次**——原版 Update 只能对真实玩家跑真实一帧、带满副作用、依赖 Main 全局，**结构上无法用于规划**。

**所以重写是结构必然**。能直接调原版的（纯函数、依赖少）就直接调——碰撞几何全部直接 call `Collision.*`，一行没重写。只有加速/跳/重力/水参这几段标量算术，因在原版里与几百字段缠绕，必须摘出重写。

---

## 1. 裸玩家单帧物理：原版调度顺序（Player.Update）

裸玩家 = 无坐骑/翅膀/钩爪/冲刺/buff/绳索。一帧按此顺序（其余分支条件全 false 跳过）：

| 顺序 | 原版行 | 物理 |
|---|---|---|
| 设默认参数 | L23895-23902 | maxFall=10, grav=defaultGrav, jh=15, js=5.01, maxRun=3, runAccel=0.08, runSlowdown=0.2, accRun=maxRun |
| 介质重力覆写 | L23932-23962 | wet 改**竖直**参数（见 §2） |
| moveSpeed 乘入 | L25491-25492 | `runAccel *= moveSpeed; maxRun *= moveSpeed`（裸=1） |
| UpdateJumpHeight | L25493 | 跳跃饰品改 jh/js（裸=15/5.01） |
| 裸玩家主块入口 | **L25975** `else if (grappling[0]==-1 && !tongued)` | ← 不在绳/无钩才进 |
| run 参数修正层 | L25977-26100 | 装备/地形/buff 改 run（裸全跳，除冰面 §4） |
| **HorizontalMovement** | **L26163** | 水平加速/摩擦（§3） |
| gravDir | L26209-26211 | 裸 = 1 |
| UpdateControlHolds | L26217 | 维护 releaseJump 等边缘标志 |
| **JumpMovement** | **L26219** | 跳跃 hold/起跳（§3） |
| 重力大分支入口 | L26274 `if(frozen/webbed/stoned)` → **L26288 else** | 裸走 else |
| **重力施加** | **L26830** `velocity.Y += gravity` | 每帧（含 hold 帧） |
| **maxFall 截顶** | **L26841** `if(vy>maxFall) vy=maxFall` | 每帧 |
| wet 衔接 | L27262-27356 | 入水/出水（§2） |
| **SlopeDownMovement** | **L27536**（调 WalkDownSlope L22948） | move 前下坡贴地 |
| **StepDown** | **L27546** | move 前下台阶 |
| **StepUp** | **L27552/27557** | move 前上台阶 |
| **position += velocity** | **L27664** | 真正移动 |
| **SlopingCollision** | **L27716**（调 SlopeCollision L23212） | move 后斜坡抬升 |

底层碰撞几何在 `Collision.cs`：WetCollision L1577 / WalkDownSlope L1693 / SlopeCollision L1798 / TileCollision L2301 / StepDown L3601 / StepUp L3665。**全部直接 call，未重写。**

### ★ 判据层核查表（2026-06-17 逐字对齐 commit e411b1e）
> 上面是「结构层」(哪步/行号/顺序)。bug 全藏在**判据层**(条件/阈值/参数)——当初 md 只记结构层，没防住自造判据(自创 Grounded、StepUp 2px探测)。**改 physim 判据必须先看这表 + 原版行，逐字抄，禁止自造等价**。see memory `feedback_verbatim_physics`。

| 步骤 | 原版裸玩家判据(条件/参数) | 原版行 | physim | 状态 |
|---|---|---|---|---|
| 左/右 全力加速 | `controlX && vx (>/<)∓maxRun && dashDelay>=0` | L19379/19437 | `input.X && vx (</>)±MaxRun` | ✓ dashDelay 裸恒真 |
| 左/右 弱加速 | 外 `vx (>/<)∓accRun && !slow && !burned`;内 `velocity.Y==0\|\|wingsLogic>0\|\|CanFly` | L19495/19525,内19527 | 外 `vx∓AccRunSpeed`;内 `vy==0f` | ✓ 内层用帧首vy(重力前) |
| 地面摩擦 | `velocity.Y == 0f` | L19591 | `vy == 0f` | ✓ (曾误用 Grounded) |
| 空中摩擦 | `!PortalPhysicsEnabled`,量 `runSlowdown*0.5` | L19606 | else,`RunSlowdown*0.5` | ✓ |
| JumpMovement 续跳 | `if(jump>0){ if(velocity.Y==0)jump=0; else vy=-jumpSpeed,jump-- }` | L20204-20223 | jumpHStart>0 分支:`vy==0→jfl=0` else 顶 | ✓ (曾漏落地清零) |
| JumpMovement 点火 | `velocity.Y==0 → vy=-jumpSpeed; jump=jumpHeight` | L20316-20323 | jumpHStart==0 分支(SimulateSegment 给 jfl 启动) | ✓ 用 jumpHStart 区分点火/续跳 |
| 重力施加 | `velocity.Y += gravity*gravDir` | L26830 | `vy += ph.Gravity` | ✓ gravDir=1 |
| maxFall 截顶 | `if(velocity.Y>maxFallSpeed)=maxFallSpeed` | L26841 | `min(.., MaxFall)` | ✓ |
| WalkDownSlope | 调 `(pos,vel,w,h, gravity*gravDir)` | L22948 | 传 `ph.Gravity` | ✓ gravDir=1 |
| StepDown | `velocity.Y == gravity`(无 !controlDown);参 `gravDir, waterWalk\|\|waterWalk2` | L27544/27546 | `vel.Y == ph.Gravity`;默认参 | ✓ (曾误加 !ft) |
| StepUp | `(velocity.Y >= gravity) && !controlDown`;参 `gravDir, controlUp` | L27555/27557 | `vel.Y >= ph.Gravity && !ft`;默认参(controlUp=false) | ✓ (曾自造 vx!=0+Grounded+2px) |
| position += velocity | dry: `DryCollision`全速;wet: `WetCollision(.., 0.5)` 位移×0.5,夹轴全速 | L27664/27683 | dry 全速; wet 每轴未夹×0.5 | ✓ |
| SlopingCollision | 调 `(pos,vel,w,h,gravity, stairFall)`,`stairFall=controlDown\|...` | L23212 | 传 `ph.Gravity, ft` | ✓ 裸 stairFall=controlDown=ft |
| TileCollision 参数 | `(pos,vel,w,h, fallThrough, ignorePlats, gravDir, ..., hoik=!flag)` | L23129 | `(pos,vel,W,H, ft, ft, 1)`,hoik 默认 | ⚠️ fallThrough/ignorePlats 都传 ft;hoik 默认 true。裸大体等价,待真验 |

**State.Grounded**：原版**没有**这个量。physim 保留它**仅**用于 SimulateJump/SimulateFall 的「边何时结束」边界判定,**绝不用作物理判据**(物理判据一律用 velocity.Y)。

---

## 2. 介质参数（水）

L23956-23962 普通水（裸玩家，非 honey/merman/trident）：
```
gravity = 0.2f; maxFallSpeed = 5f; jumpHeight = 30; jumpSpeed = 6.01f;
```
水只改**竖直**参数。水平 run 参数在 Update 主体不被 wet 改动。
> 我们 BuildWet 含 ×0.5 约定（已与用户确认，勿质疑，见 memory `water_params_locked`）。

入水 L27343：`if(ShouldFloatInWater) { velocity.Y /= 2; if(vy>3) vy=3; }` —— BuildWet 已含。
出水 L27354：`if(jump > jumpHeight/5) jump = jumpHeight/5;` —— jumpHeight 是**空气**值(15)，cap=3。已复刻（PhysicsSimulator L118）。

honey L23936(grav0.1/maxFall3) / merman L23941 / trident L23944 / shimmer L23918 —— 未复刻，用到再补。

---

## 3. 两段核心算术（HorizontalMovement / JumpMovement）

### HorizontalMovement L19303-19730（裸玩家 6 分支）
| 原版行 | 情形 | 公式 |
|---|---|---|
| L19437 | 右、vx<maxRun | `if(vx<-slow)vx+=slow; vx+=accel` 全力 |
| L19525 | 右、maxRun≤vx<accRun，**且 vy==0** | `vx += accel*0.2` 弱加速（★地面专属） |
| L19379 | 左、vx>-maxRun | 对称全力 |
| L19495 | 左、超速，**且 vy==0** | 对称弱加速 |
| L19591 | 无键、vy==0 | 地面摩擦 `runSlowdown`(0.2) |
| L19606 | 无键、空中 | 空中摩擦 `runSlowdown*0.5`(0.1) |

**关键**：弱加速段 L19527 有 `velocity.Y==0f` 门槛 → 空中无水平加速（裸）。巡航锯齿 = 全力加速(+0.08) vs 摩擦交替；空中摩擦半量(0.1<0.2)，故空中锯齿平均速度略高。

### JumpMovement L20072-（裸玩家 2 点）
- hold 段 L20204-20224：`if(jump>0){ if(vy==0)jump=0; else{ vy=-jumpSpeed; jump--; } }`
- 起跳点火 L20226 → L20316-20323：`if(velocity.Y==0f && releaseJump){ vy=-jumpSpeed; jump=jumpHeight; }`
- **"落地一帧才能再跳"** = L20226 的 `velocity.Y==0f`（落地帧 vy 常有残留，需下一帧清零）+ `releaseJump` 边缘触发。

原版 hold 与重力是**两个独立步骤**：JumpMovement 设 `vy=-jumpSpeed` → 重力段 L26830 `vy+=gravity`（hold 帧也走）→ L26841 截顶。净值 hold 帧 = `-jumpSpeed+gravity`。**勿折叠成常数**（已修，见 §6）。

---

## 4. ⚠️ 裸玩家会触发但未复刻（真缺口）

| 原版行 | 物理 | 触发条件 | 优先级 |
|---|---|---|---|
| **L26031-26052** slippy/slippy2 | 冰面打滑：`runSlowdown→0`、`accel*0.6/0.7`，iceSkate 再 ×3.5 | **踩冰块/雪原地面** | 高（洞穴/雪原必碰） |
| L25438-25464 | debuff：slow÷2 / dazed÷3 / chilled×0.75 改 moveSpeed；slowOgreSpit/shieldRaised 额外 `vx/=2` | 中相应 debuff | 中（战斗才有） |

---

## 5. ⏭️ 非裸玩家扩展地图（用到再补）

**原则**：饰品/buff 的"效果值"由原版 `UpdateEquips`/`UpdateBuffs`/`UpdateArmorSets` 每帧算成 Player 字段（如 `wingsLogic`/`moveSpeed`/`jumpSpeedBoost`）。**我们永不搬这些遍历逻辑**——只在 `Params.FromPlayer` 那一刻**读字段成品快照**；移动"行为逻辑"（怎么飞/怎么冲）才需把对应子系统算术复刻进 Step。

### 5.1 移速/跳跃类饰品（只读字段，最易）
| 字段 | 原版改写点 | 我们补在哪 |
|---|---|---|
| `moveSpeed` | L25491 乘入 | BuildDry 已读 ✅ |
| `jumpSpeedBoost`/`jumpHeight`/`jumpSpeed` | UpdateJumpHeight L19123（jumpBoost/frogLeg/moonLord/wereWolf/empressBrooch/sticky/dazed） | FromPlayer 读 p.jumpHeight/p.jumpSpeed 替换硬编（#2） |
| `runAccel/maxRun/accRun` 倍率 | L25981-26097（empressBrooch/magilum/shadowArmor/powerrun/sandBoots/sandstorm…） | 读对应字段或乘成品 |

### 5.2 翅膀（搬 WingMovement 算术 + 字段）
- 定义 `WingMovement()` L21549；Update 调用/重力分支 L26257-26293、悬停 L26881。
- 关键字段：`wingsLogic`(类型)、`wingTime`/`wingTimeMax`、`canRocket`、`flag19`(本帧在飞)。
- 行为：HorizontalMovement L19497/19527 的 `wingsLogic>0` 让**空中也能加速**（且 L19534 翅膀加速翻倍）；重力分支 L26280/26508 用 `gravity/3` 缓降。
- **补法**：把 WingMovement 的 vy 缓降公式 + HorizontalMovement 的 `wingsLogic>0` 空中加速分支复刻进 Step；wingsLogic/wingTime 从字段读。

### 5.3 二段跳（云朵瓶/沙暴/暴雪/独角兽/恶魔之心…）
- JumpMovement L20245-20580 的 `flag5~flag13` + `canJumpAgain_*` 字段。
- `RefreshDoubleJumps()` L20313 落地刷新。
- **补法**：起跳分支增加"空中且 canJumpAgain_X 为真"的二段点火；各变体 jump 帧数/初速不同（如沙暴 `jump=jumpHeight*3` L20350）。**注意**：二段跳会让寻路节点空间膨胀，需配合规划侧处理。

### 5.4 冲刺 DashMovement
- 定义 L20589；Update 调 L26232。字段 `dashDelay`/`dashDir`/`DashType`。冲刺给瞬时大 vx。

### 5.5 钩爪 GrappleMovement
- 定义 L22141；Update 调 L27136。`grappling[]` 非 -1 时裸玩家主块 L25975 **整个不走**，改走钩爪物理（朝钩点加速）。

### 5.6 坐骑 mount
- run 参数 L26120-26133（覆写/减半）、跳跃 UpdateJumpHeight L19126、各种 mount.Type 特判遍布。最复杂，需要时单列。

### 5.7 绳索 pulley
- L25602 FindPulley、L25782 pulley 主块（特殊重力 `vy -= gravity` 上爬、L25767 绳上跳）。`controlUp/controlDown` 攀爬。

---

## 6. 已修复的复刻偏差（校准记录）

| 偏差 | 根因 | 修复 | commit |
|---|---|---|---|
| 跳跃 hold 折叠成 `-(js-grav)` 常数 | 把原版"设-js"+"+grav"两独立步并成一步 → 跨介质/截顶/未来修正失真 | 拆回两段：step1 `vy=-js`，step2 `vy=min(vy+grav,maxFall)` 每帧 | 225df13 |
| 出水 hold cap 自创 `airCap-used` | 反推公式错 | 原版 `jfl=min(jfl, jumpHeight/5)` | 225df13 |
| 弱加速段漏判地面 | L19527 `vy==0` 门槛没复刻 → 空中多加 0.016/帧累积 | 弱加速分支加门槛 | e915b35 |
| 水物理用压速度上限模拟 | 应是 velocity全速+位移×0.5(L22960),旧 BuildWet 压 MaxRun=1.5 → 出水交界 vx 累积 dpx→28 | BuildWet 水平回裸值,Step wet 位移×0.5(夹轴全速) | 814a06b |
| **自造判据(Grounded/StepUp/落地清零)** | 多处判据自己发明非逐字抄原版 → 系统性接缝噪声(水边 dpy 恒-1.2) | 全部逐字对齐原版 velocity.Y 判据,见§1判据层表 | e411b1e |

验证：逐字对齐后 dpx 74%<0.5px、dpy 84%<0.5px(原~50% / 水边-1.2恒定)。残差集中在深处 jumpPlace 反复失败(执行层,非物理)。

---

## 7. 验证方法（守则）

- 改 .cs → `/build TerraBlind` → 用户回 1。**build 前先清日志。**
- per-run 日志：`TerraBlindLogs/runs/<sx>_<sy>__<gx>_<gy>.log`，逐帧 `ss-cmp` 给 plan vs exec 的 px/py/vx/vy 与 d(...)。
- **用数据说话**：偏差看 d(...) 是否单调累积（系统性）还是恒定/锯齿（浮点相位）。n≥10 才算验证。
- 二分定位：先确认 plan 还是 exec 偏；先看哪个量（vx 先偏→水平逻辑；vy 先偏→跳/重力/介质）最早分叉的帧。
