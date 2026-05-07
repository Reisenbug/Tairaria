# CLAUDE.md

Claude Code 在本项目的行为准则。

---

## 犯错记录

历史踩坑见 `~/.claude/projects/-Users-lhy-Documents-Terraria-Agent/memory/feedback_lessons.md`。
新错误在本轮结束时追加，不要重复犯同类错。

## 代码要求
不要写多余的注释。
小心magic number。
用户同意后再commit push。
commit消息规范且尽可能分开。

## 1. 改动必须自己跑完闭环

改完代码不算完,要走完 **改→编译→跑→读日志→判断**。

- 改 `.cs`:输出 "请在游戏内 `/build TerraBlind`,完成回复 1",**等回复再继续**
- 改 Python:自己跑
- 跑完必须 `grep` 日志,不只看 stdout

## 2. 调试三步不可拆

```
清日志 → 跑 → 读日志
```

```bash
> "$HOME/Library/Application Support/Terraria/tModLoader/TerraBlindLogs/jump_trace.log"
```

## 3. 跑测试必须设超时和清理

```bash
> "$LOG"
python -u scripts/exec_astar.py &
PID=$!
sleep 15
curl -s -X POST http://localhost:17878/nav_stop -d '{}'
kill $PID 2>/dev/null
wait $PID 2>/dev/null
```

不带 `/nav_stop` 退出 = mod 还在动。

## 4. 用数据说话

调参问题给统计指标:

```
n=23 mean=-1.87 min=-4 max=0
```

n < 10 不算验证通过。禁止 "看起来差不多了"。

## 5. 二分定位,不猜原因

bug 出现按顺序:

1. 复现
2. 隔离(Python 端 / mod 端)
3. 缩小(`/plan_path` 对吗?`/jump` 单调对吗?)
4. 日志找最早异常 tick
5. **才**改代码

## 6. 一次一个变量

不要一把改三个参数。改一个 → 跑数据 → 记 → 下一个。

## 7. 改前先 grep

```bash
grep -rn "stopAhead" .
```

本项目有已弃用但未删除的文件(`terrain_astar2.py`、`terrain_nav.py`),容易改错。

## 8. 不确定先查文档

- **游戏知识**(物品 ID、boss 行为、地形规则等):https://terraria.wiki.gg/
- **tModLoader API**(类、Hook、生命周期等):http://docs.tmodloader.net/docs/stable/

不查就猜 = bug 来源。

## 9. 提交前自检

- [ ] 编译通过
- [ ] 跑了至少一次完整测试
- [ ] 日志无新增 WARN/ERROR
- [ ] 关键指标有数据
- [ ] 没改到已弃用文件
- [ ] `/nav_stop` 能停

## 10. 必须问的情况

- 改存档 / 角色配置
- kill 进程或改项目外文件
- 改 HTTP API 契约
- 改物理参数硬编码
- 大调 cost 权重

---

## 关键参考

**日志路径**
```
~/Library/Application Support/Terraria/tModLoader/TerraBlindLogs/jump_trace.log
```

**HTTP API**:端口 17878,详见 `PROJECT_OVERVIEW.md`

**物理参数(裸玩家)**

| 参数 | 值 |
|------|-----|
| jumpSpeed | 5.01 |
| jumpHeight | 15 |
| gravity | 0.4 |
| maxRunSpeed | 3.0 |
| accRunSpeed | 0.08 |
| runSlowdown | 0.2(仅地面) |

空中无水平摩擦,松手后 vx 几乎不变。
