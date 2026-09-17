"""快判层:把"判断"这个动作变得不用省着用。

大模型一次调用 6 秒 + 烧 RPM 配额,所以循环里不许有脑子,只能写死 if-else。
System One 模型(TypeSafe 的 Jev)70-500ms、输出免费,循环里第一次可以有判断。

这一层的存在理由是【后端可换】:业务代码只认 ask(),不认识 typesafe 这个名字。
Jev 没到手/没 key/挂了,自动退回 fallback(现在的大模型或硬编码),调用方不感知。

用法:
    from fastjudge import ask, Choice, Score, Noul
    r = ask("goal_clarity", goal_text)
    if r["intent"].confidence < CONF_ACT: ...
"""
import json
import os
import time

# ---- 后端 ----------------------------------------------------------------
# 装了 SDK 且有 key 才算可用。两者缺一就整层降级,不抛异常打断游戏。
try:
    from typesafe_sdk import Choice, Noul, Score, TypeSafeClient
    _SDK = True
except ImportError:                     # 还没轮到 waitlist,或没装
    _SDK = False

    class _Q:                           # 占位:让 QUESTIONS 表照样能写、能被 fallback 读
        def __init__(self, instructions, criteria=None):
            self.instructions = instructions
            self.criteria = criteria

    class Choice(_Q): kind = "choice"
    class Score(_Q): kind = "score"
    class Noul(_Q): kind = "noul"


def _read_key():
    """环境变量优先,否则读 ~/.typesafe_key(游戏进程继承不到终端的 export)"""
    k = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if k:
        return k
    try:
        with open(os.path.expanduser("~/.typesafe_key")) as f:
            return f.read().strip()
    except OSError:
        return ""


API_KEY = _read_key()
ENABLED = bool(_SDK and API_KEY)
# SDK 自己读环境变量,而 key 可能是从文件来的
if ENABLED and not os.environ.get("TYPESAFE_API_KEY"):
    os.environ["TYPESAFE_API_KEY"] = API_KEY
_client = TypeSafeClient() if ENABLED else None

# 判据阈值。抄官方 confidence-gated routing 的档位,按代价分级:
# 低于 ACT 就是真不确定 -- 别动,问玩家;高代价动作(挖一趟矿、拆地形)要到 SURE 才自动干。
CONF_ACT = 0.6          # 低于此:不行动,升级给大模型或问玩家
CONF_SURE = 0.85        # 高代价动作要过这条线才自动执行
NOUL_YES = 0.7          # Noul 返回的是概率不是 bool,自己定在哪儿算"是"

JUDGE_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fastjudge.jsonl")


# ---- 问题表 --------------------------------------------------------------
# 一次调用里的问题【并行求值,多问不加延迟】(官方 speculative fan-out)。
# 所以按【调用时机】分组,不按用途分:该时机可能用到的全塞进去,用不上的让代码丢掉。
QUESTIONS = {

    # L3 触发器 -- 这一层唯一的【质变】。
    # 生成模型的训练目标就是补全,你没法求它承认自己不知道;校准过的置信度把"我不知道"变成一个数。
    # 注意 Noul 不带 confidence(概率本身就是信号),所以缺口判断必须用 Choice/Score。
    "goal_clarity": {
        "intent": Choice(
            instructions="玩家这条指令想让 AI 队友做什么",
            criteria={
                "gather": "采集/攒够某种材料(挖矿、砍树)",
                "craft": "合成物品或装备",
                "build": "用背包里的材料放置/建造",
                "goto": "去某个地方",
                "fight": "战斗或打 boss",
                "chat": "闲聊、问问题,不要求动作",
                # 【必须留】没有兜底选项,不着边际的话会被硬塞进最近的那一类
                "other": "以上都不是,或看不出想干什么",
            },
        ),
        # 下面三个是缺口。Score 而非 Noul:要 confidence 参与门控
        "quantity_clear": Score(
            instructions="要做多少这件事,指令里说清楚了吗",
            criteria=["完全没提数量", "能从目标倒推出数量", "明确给了数字"],
        ),
        "target_clear": Score(
            instructions="对哪个目标做,指令里说清楚了吗",
            criteria=["没说做什么材质/哪一个", "上下文能推断", "点名了具体目标"],
        ),
        "is_interrupt": Noul(
            instructions="这句话是在打断当前任务,而不是在下新任务或闲聊",
        ),
    },

    # 动作前置校验。拦一次省一趟 mod 往返 + 一轮大模型重试(约 6-7 秒)
    "action_sanity": {
        "will_work": Score(
            instructions="按当前状态,这个动作现在能成功吗",
            criteria=["肯定失败(缺物品/缺工具/位置不对)", "不好说", "条件都满足"],
        ),
        "blocker": Choice(
            instructions="如果做不成,最主要的原因是什么",
            criteria={
                "none": "没问题,能做",
                "no_item": "背包里没有要用的东西",
                "no_tool": "缺合适的工具(镐/斧)",
                "too_far": "目标太远,够不着",
                "bad_spot": "那个位置放不下/站不住",
                "unknown": "说不清",
            },
        ),
    },

    # compact_for_send 的逐条取舍。现在是位置启发式("旧的=没用的"),
    # 会把 track 立的台账和 mine_vein 的累计数误杀 -- 那些恰恰越旧越要留。
    "result_keep": {
        "worth": Score(
            instructions="这条工具返回对接下来完成目标还有没有用",
            criteria=["过期快照,丢掉不影响", "留个摘要就够", "必须原样留着(台账/累计数/坐标)"],
        ),
    },

    # 玩法1:循环里的判断。run_find_template / _mine_vein 之所以只能干写死的事,
    # 就是因为每轮问一次大模型不可能。
    "loop_step": {
        "done": Score(
            instructions="这个子目标已经完成了吗",
            criteria=["还差得远", "快了但没到", "已经达成"],
        ),
        "stuck": Noul(
            instructions="角色卡住了,再这样重复下去不会有进展",
        ),
        "next": Choice(
            instructions="下一步最该做什么",
            criteria={
                "continue": "接着做当前动作",
                "move": "先换个位置",
                "clear": "先挖掉挡路的东西",
                "retarget": "换一个目标",
                "escalate": "自己处理不了,交给大模型",
            },
        ),
    },

    # 路由:是不是"找东西"那个形状。以前这一问要烧一整次大模型调用(6.5s 限流)
    "find_shape": {
        "shape": Choice(
            instructions="玩家给 Terraria 里的 AI 队友下了一个目标。这个目标是不是"
                         "「世界上有个东西,找到它->走过去->对它做点什么->重复到够」这个形状?"
                         "是的话属于哪一种?",
            criteria={
                "find": "近处已经存在的方块,比如树/矿/箱子。走过去对它做点什么",
                "find_biome": "去某个生物群系(丛林/雪原/地牢),目标是到达那片区域",
                "find_descent": "去某群系通往地狱的主入口站定。玩家说主道/主入口/大洞口",
                "descend": "沿主道一路下到地狱。玩家说去地狱/去底层/速降",
                "build_replay": "回放录制好的建造。玩家说照录像盖房子/重现录制的结构",
                "not_find_class": "不是这个形状。用背包里的材料放置建造,或者合成装备、多步任务",
            },
        ),
    },

    # 计划执行中的取舍。以前每问一次就要唤醒一次大模型,所以循环里干脆不问
    "plan_step": {
        "on_track": Score(
            instructions="按这个计划走下去,还能达成目标吗",
            criteria=["已经跑偏了,该重新规划", "有点问题但能继续", "完全在正轨上"],
        ),
        "skip_step": Noul(
            instructions="这一步已经没必要做了(它要的结果现在已经满足)",
        ),
    },

    # 失败分诊。白名单只认得出"有问题",认不出"哪种问题"
    "op_failure": {
        "kind": Choice(
            instructions="Terraria 里一个自动玩家执行了一步操作,拿回这个结果。接下来该怎么办?",
            criteria={
                "retry_same": "同样的做法再试一次就行。临时被挡住、没抢到控制权、等一下就好",
                "replan": "这条路走不通,得换做法。目标不可达、材料不够、判据本身就错了",
                "not_a_failure": "其实不算失败。那个词是「稍后再试」或者中间状态",
            },
        ),
    },
}


def _fallback(name, state, why):
    """后端不可用时的返回。Choice/Score 标 confidence=0 -- 低于 CONF_ACT,
    调用方的门控自然走"别自作主张"那条路,不用到处写 if ENABLED。
    Noul 照样给 None:它本来就没有 confidence,这里造一个假的会让调用方走错门。"""
    out = {"_ok": False, "_why": why}
    for q, spec in QUESTIONS.get(name, {}).items():
        out[q] = _Answer(None, None if isinstance(spec, Noul) else 0.0)
    return out


class _Answer:
    """统一 Choice/Score/Noul 三种答案的读法,省得调用方分别记 .choice/.score/.noul。

    confidence=None 是 Noul:它没有这个量。要判是不是,拿 .value 和 NOUL_YES 比。"""
    __slots__ = ("value", "confidence", "raw")

    def __init__(self, value, confidence, raw=None):
        self.value = value
        self.confidence = confidence
        self.raw = raw

    def sure(self, bar=CONF_ACT):
        """够不够确信到可以照着动。Noul 没有 confidence,一律 False -- 走 .value 那条路。"""
        return self.confidence is not None and self.confidence >= bar

    def spread(self):
        """概率分布,没有就是空。低 confidence 有两种:几个选项【都行】(摊开但无所谓),
        和几种解释【互斥】(摊开才是真缺口)。只看 confidence 这一个标量分不出来,
        要看形状 -- 所以原样透出去。"""
        return getattr(self.raw, "probabilities", None) or {}

    def __repr__(self):
        c = "n/a" if self.confidence is None else f"{self.confidence:.2f}"
        return f"<{self.value} c={c}>"


def _unwrap(a):
    v = getattr(a, "choice", None)
    if v is None:
        v = getattr(a, "score", None)
    if v is None:
        v = getattr(a, "noul", None)
    # Noul 【没有】confidence,概率本身就是答案。0.5 的意思是"是和否各一半",
    # 不是"中等程度" -- 所以不许把 |p-0.5| 当确信度去和 CONF_* 比。
    # 这里给 None,逼调用方拿 .value 和 NOUL_YES 比,别走错门。
    return _Answer(v, getattr(a, "confidence", None), a)


def ask(name, state, timeout=None):
    """问一组判断。name 是 QUESTIONS 里的组名,state 可以是 str/dict/list。

    官方建议用 dict:字段名模型看得见,是重要上下文。
    返回 {问题名: _Answer}。后端不可用时全部 confidence=0,不抛异常。"""
    qs = QUESTIONS.get(name)
    if qs is None:
        raise KeyError(f"没有这组判断:{name}")
    if not ENABLED:
        return _fallback(name, state, "no_sdk" if not _SDK else "no_key")

    t0 = time.monotonic()
    try:
        kw = {"timeout": timeout} if timeout else {}
        resp = _client.system_one(state=state, questions=qs, **kw)
        out = {k: _unwrap(v) for k, v in resp.answers.items()}
        out["_ok"] = True
        _log(name, state, out, time.monotonic() - t0)
        return out
    except Exception as e:
        # 判断层挂了不该让游戏停。退回去,调用方按低置信度处理
        print(f"[fastjudge] {name} 失败,降级:{type(e).__name__} {e}")
        return _fallback(name, state, type(e).__name__)


def _log(name, state, out, dt):
    """每次调用记一行。Jev 到手后要验它的置信度是不是真校准的 --
    ground truth 得现在开始攒,不然到时候没有对照数据。"""
    try:
        row = {"t": time.time(), "name": name, "dt": round(dt, 3),
               "state": str(state)[:500],
               "ans": {k: [v.value, round(v.confidence, 3)]
                       for k, v in out.items() if isinstance(v, _Answer)}}
        with open(JUDGE_LOG, "a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass


if __name__ == "__main__":
    print(f"fastjudge: sdk={_SDK} key={'有' if API_KEY else '无'} enabled={ENABLED}")
    for n, qs in QUESTIONS.items():
        print(f"  {n}: {', '.join(qs)}")
    r = ask("goal_clarity", "帮我弄点铁")
    print(f"  试调用 -> {r}")
