"""重复周期 repeat 的接口端到端验证（Flask test client）。

覆盖：
- preview：周期回显、候选全部满足周期与浮长、周期+区间+锁定同时生效、
  周期导致无解时 solvable=false 且无 token；
- 非法周期（类型/越界/只填一端/0/负数/布尔）-> 400；
- confirm：周期随原稿持久化、确认体缺/改周期 -> 409 mismatch、
  无字段/ null 请求与旧响应字段保持兼容；
- diagnose：周期下区分锁定阻碍与结构性无解、示例满足周期、只读无 token；
- 尺寸变化使周期越界 -> 400 且错误信息提示调整（不截断）。
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DB_PATH"] = _tmp.name

import app as server  # noqa: E402
from weave import find_violations  # noqa: E402

client = server.app.test_client()
FAILS = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}{(' :: ' + detail) if detail else ''}")
    if not cond:
        FAILS.append(name)


def is_repeated(g, rows, cols, repeat):
    rp, cp = repeat
    for r in range(rows):
        for c in range(cols):
            if g[r][c] != g[(r + rp) % rows][c]:
                return False
            if g[r][c] != g[r][(c + cp) % cols]:
                return False
    return True


def make_draft(grid, locks=None, k=2, ones_range=None, repeat=None):
    d = {"rows": len(grid), "cols": len(grid[0]), "grid": grid,
         "locks": locks or [], "k": k}
    if ones_range is not None:
        d["onesRange"] = ones_range
    if repeat is not None:
        d["repeat"] = repeat
    return d


def confirm(token, draft, candidate=None):
    body = {"token": token, **draft}
    if candidate is not None:
        body["candidate"] = candidate
    return client.post("/api/confirm", json=body)


before = client.get("/api/state").get_json()
check("初始版本为 1 且带 repeat 字段（旧库迁移）",
      before["version"] == 1 and before.get("repeat") is None,
      json.dumps(before)[:200])

# --- 非法周期 -> 400，错误信息提示调整，不截断 ---
z4 = [[0] * 4 for _ in range(4)]
bad_repeats = [[], [2], [2, None], [0, 2], [2, 0], [-1, 2], [5, 2],
               [2, 5], "x", [1.0, 2], [True, 2], [2, False]]
for bad in bad_repeats:
    r = client.post("/api/preview", json=make_draft(z4, repeat=bad))
    check(f"非法周期 {json.dumps(bad)} -> 400", r.status_code == 400,
          r.get_json().get("error", "") if r.is_json else "")

# 越界信息须明确提示“请调整…不自动截断”
r = client.post("/api/preview", json=make_draft(z4, repeat=[5, 2]))
check("行周期越界提示调整尺寸/周期",
      r.status_code == 400 and "行周期" in r.get_json()["error"]
      and "5" in r.get_json()["error"])
r = client.post("/api/preview", json=make_draft(z4, repeat=[2, 5]))
check("列周期越界提示调整尺寸/周期",
      r.status_code == 400 and "列周期" in r.get_json()["error"])
check("非法周期不改变版本",
      client.get("/api/state").get_json()["version"] == 1)

# 尺寸变小使既存周期越界：服务端不截断，直接 400
body = make_draft([[0] * 3 for _ in range(3)], repeat=[2, 4])
r = client.post("/api/preview", json=body)
check("尺寸与周期不匹配 -> 400（不自动截断）", r.status_code == 400
      and "列周期" in r.get_json()["error"])

# --- 周期可解：4x4 全0 K=2 repeat[2,2]，两个棋盘方向 ---
r = client.post("/api/preview", json=make_draft(z4, repeat=[2, 2]))
b = r.get_json()
check("周期预览可解并带令牌", r.status_code == 200 and b["solvable"]
      and bool(b["token"]), json.dumps(b)[:200])
check("响应回显 repeat 与 input.repeat",
      b["repeat"] == [2, 2] and b["input"]["repeat"] == [2, 2])
check("candidateCount=2 且候选互异",
      b["candidateCount"] == 2 and len(b["candidates"]) == 2
      and b["candidates"][0]["repaired"] != b["candidates"][1]["repaired"])
for i, cand in enumerate(b["candidates"]):
    check(f"候选{i}满足周期[2,2]与浮长K=2",
          is_repeated(cand["repaired"], 4, 4, [2, 2])
          and not find_violations(cand["repaired"], 4, 4, 2))
    check(f"候选{i}各翻转 {len(cand['flips'])} 格（实际改变计数）",
          len(cand["flips"]) == sum(
              v != z4[rr][cc] for rr, row in enumerate(cand["repaired"])
              for cc, v in enumerate(row)) == 8)
check("旧字段 repaired 指向首候选",
      b["repaired"] == b["candidates"][0]["repaired"])
token = b["token"]

# --- 周期 + 区间 + 锁定同时生效 ---
r = client.post("/api/preview",
                json=make_draft(z4, locks=[[0, 0]], k=2,
                                ones_range=[8, 8], repeat=[2, 2]))
b2 = r.get_json()
check("周期+区间+锁定 可解", b2["solvable"] and bool(b2["token"]))
check("首候选锁定格不变、周期达标、区间达标",
      b2["candidates"][0]["repaired"][0][0] == 0
      and is_repeated(b2["candidates"][0]["repaired"], 4, 4, [2, 2])
      and b2["candidates"][0]["onesCount"] == 8)

# 周期与锁定冲突 -> 无令牌
conflict_grid = [row[:] for row in z4]
conflict_grid[0][2] = 1
r = client.post("/api/preview",
                json=make_draft(conflict_grid,
                                locks=[[0, 0], [0, 2]], repeat=[2, 2]))
b3 = r.get_json()
check("周期同类锁定冲突 -> solvable=false 无令牌",
      r.status_code == 200 and b3["solvable"] is False
      and "token" not in b3 and b3["repeat"] == [2, 2])

# 周期本身结构性无解（列周期 1 => 每行全同）
r = client.post("/api/preview", json=make_draft(z4, repeat=[2, 1]))
check("周期[2,1] 无解无令牌",
      r.get_json()["solvable"] is False and "token" not in r.get_json())

# --- 确认：周期随原稿持久化，缺/改周期 -> 409 mismatch ---
draft_rep = make_draft(z4, repeat=[2, 2])
r = client.post("/api/confirm",
                json={"token": token, **make_draft(z4)})
check("确认体缺周期 -> 409 mismatch", r.status_code == 409
      and "mismatch" not in r.get_json()["error"])  # 错误文案不含英文码
check("mismatch 后原稿版本/周期不变",
      client.get("/api/state").get_json()["version"] == 1)

r = client.post("/api/confirm",
                json={"token": token, **make_draft(z4, repeat=[4, 4])})
check("确认体周期被改 -> 409 mismatch", r.status_code == 409)

r = client.post("/api/confirm",
                json={"token": token, **make_draft(z4, repeat=None)})
check("确认体显式 null 周期 vs 预览 [2,2] -> 409 mismatch",
      r.status_code == 409)

r = client.post("/api/confirm", json={"token": token, **draft_rep})
check("周期一致确认成功 200", r.status_code == 200)
st = r.get_json()["state"]
check("确认后周期持久化、版本 +1、网格满足周期",
      st["version"] == 2 and st["repeat"] == [2, 2]
      and is_repeated(st["grid"], 4, 4, [2, 2])
      and not find_violations(st["grid"], 4, 4, 2))

# 令牌已消费
r = client.post("/api/confirm", json={"token": token, **draft_rep})
check("周期令牌重复确认 -> 409", r.status_code == 409)

# 第 2 个候选也带周期
r = client.post("/api/preview", json=make_draft(z4, repeat=[2, 2]))
b4 = r.get_json()
r = client.post("/api/confirm",
                json={"token": b4["token"], "candidate": 1,
                      **make_draft(z4, repeat=[2, 2])})
check("周期下选择候选1确认成功", r.status_code == 200
      and is_repeated(r.get_json()["state"]["grid"], 4, 4, [2, 2])
      and r.get_json()["state"]["grid"]
      == b4["candidates"][1]["repaired"])

# 新预览/确认 null 周期：清除周期持久化，且无字段请求体与 null 等价
cur = client.get("/api/state").get_json()
base = {"rows": cur["rows"], "cols": cur["cols"], "grid": cur["grid"],
        "locks": cur["locks"], "k": cur["k"]}
pv = client.post("/api/preview", json={**base, "repeat": None}).get_json()
check("无周期预览 repeat=null 且可解",
      pv["solvable"] and pv["repeat"] is None)
r = client.post("/api/confirm", json={"token": pv["token"], **base})
check("无字段确认体与 null 周期预览兼容", r.status_code == 200)
check("确认后周期为 null", r.get_json()["state"]["repeat"] is None)

# --- 诊断：周期下区分锁定阻碍与结构性无解，示例满足周期 ---
# 锁定阻碍
r = client.post("/api/diagnose",
                json=make_draft(conflict_grid,
                                locks=[[0, 0], [0, 2]], k=2, repeat=[2, 2]))
d = r.get_json()
check("周期下锁定阻碍诊断 200", r.status_code == 200
      and d["structurallyUnsolvable"] is False
      and d["unlockCount"] == 1, json.dumps(d)[:200])
check("诊断回显 repeat", d["repeat"] == [2, 2])
for opt in d["options"]:
    ex = opt["example"]
    check("诊断示例满足周期与浮长",
          is_repeated(ex["repaired"], 4, 4, [2, 2])
          and not find_violations(ex["repaired"], 4, 4, 2))
    kept = {(0, 0), (0, 2)} - {tuple(p) for p in opt["unlocks"]}
    check("诊断示例未解锁格不变",
          all(ex["repaired"][rr][cc] == conflict_grid[rr][cc]
              for rr, cc in kept))
check("诊断无 token", "token" not in d)

# 结构性：周期[1,1] 全格相等
r = client.post("/api/diagnose", json=make_draft(z4, repeat=[1, 1]))
d2 = r.get_json()
check("周期[1,1] -> 结构性无解且无 options",
      d2["structurallyUnsolvable"] is True and "options" not in d2
      and "token" not in d2)

# 结构性：周期 + 区间联合不可达（周期[2,2] 下总数恒为 8）
r = client.post("/api/diagnose",
                json=make_draft(z4, ones_range=[9, 9], repeat=[2, 2]))
d3 = r.get_json()
check("周期[2,2]+区间[9,9] -> 结构性无解",
      d3["structurallyUnsolvable"] is True and "options" not in d3)

# 可解草稿诊断：unlockCount=0、空集合、示例满足周期
r = client.post("/api/diagnose", json=make_draft(z4, repeat=[2, 2]))
d4 = r.get_json()
check("可解周期草稿诊断 best=0",
      d4["structurallyUnsolvable"] is False and d4["unlockCount"] == 0
      and d4["options"][0]["unlocks"] == []
      and is_repeated(d4["options"][0]["example"]["repaired"], 4, 4, [2, 2]))

# 诊断只读：版本不变
check("诊断后版本不变",
      client.get("/api/state").get_json()["version"]
      == cur["version"] + 1)

# 非法周期诊断同样 400
r = client.post("/api/diagnose", json=make_draft(z4, repeat=[0, 2]))
check("诊断非法周期 -> 400", r.status_code == 400)

# --- 旧请求/响应兼容：不带 repeat 的完整闭环 ---
legacy = make_draft([[0, 1], [0, 1]], k=2)
before_v = client.get("/api/state").get_json()["version"]
p = client.post("/api/preview", json=legacy).get_json()
check("旧请求（无 repeat）预览正常",
      p["solvable"] and p["repeat"] is None and p["token"])
cr = confirm(p["token"], legacy)
check("旧请求确认成功、版本递增",
      cr.status_code == 200
      and cr.get_json()["state"]["version"] == before_v + 1)
check("旧响应字段保持不变（无 repeat 必填依赖）",
      set(["solvable", "token", "repaired", "flips", "flipCount",
           "candidates", "candidateCount"]).issubset(p.keys()))

print()
if FAILS:
    print(f"{len(FAILS)} 项失败：{FAILS}")
    sys.exit(1)
print("全部通过。")
