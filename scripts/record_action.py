"""
录制+回放动作脚本。
用法：python scripts/record_action.py <output.json>
按 I 开始录制 | O 停止并保存 | P 回放 | Q 退出
录制在 mod 端 60fps 进行，不丢帧。
"""
import sys, os, time, json, threading
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from dotenv import load_dotenv
load_dotenv()

import urllib.request
from pynput import keyboard as kb

BASE = "http://127.0.0.1:17878"

SPECIAL_MAP = {
    kb.Key.space: 'jump',
}

def http_post(path, data=b""):
    req = urllib.request.Request(f"{BASE}{path}", data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.read().decode()

def expand_frames(frames):
    result = []
    for f in frames:
        n = f.get("repeat", 1)
        base = {k: v for k, v in f.items() if k != "repeat"}
        result.extend([base] * n)
    return result

def play_frames(frames):
    expanded = expand_frames(frames)
    print(f"回放 {len(expanded)} 帧 → mod 端执行...")
    payload = json.dumps(expanded).encode()
    result = http_post("/replay", payload)
    print(f"回放：{result}")

def compress_frames(frames):
    if not frames:
        return []
    result = []
    count = 1
    for i in range(1, len(frames)):
        if frames[i] == frames[i - 1]:
            count += 1
        else:
            entry = dict(frames[i - 1])
            if count > 1:
                entry["repeat"] = count
            result.append(entry)
            count = 1
    entry = dict(frames[-1])
    if count > 1:
        entry["repeat"] = count
    result.append(entry)
    return result

def load_skill(path):
    data = json.load(open(path))
    if isinstance(data, dict):
        return data.get("frames", [])
    return data

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    outfile = sys.argv[1]

    frames = load_skill(outfile) if os.path.exists(outfile) else []
    recording = False

    if frames:
        print(f"已加载 {len(frames)} 帧来自 {outfile}")
    print("按 I 开始录制 | O 停止 | P 回放 | L 退出")

    def on_press(key):
        global recording, frames
        try:
            c = key.char
            if c == 'i' and not recording:
                recording = True
                http_post("/record_start")
                print("● 录制中...")
            elif c == 'o' and recording:
                recording = False
                raw = http_post("/record_stop")
                frames = json.loads(raw)
                compressed = compress_frames(frames)
                skill = {"smart_cursor": False, "frames": compressed}
                with open(outfile, "w") as f:
                    json.dump(skill, f, indent=2)
                print(f"■ 停止，{len(frames)} 帧 → {len(compressed)} 条 → {outfile}")
            elif c == 'p':
                if frames:
                    threading.Thread(target=play_frames, args=(frames,), daemon=True).start()
                else:
                    print("没有录制内容")
            elif c == 'l':
                return False
        except AttributeError:
            pass

    with kb.Listener(on_press=on_press) as listener:
        listener.join()
