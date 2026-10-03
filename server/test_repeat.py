"""重复周期 repeat 的求解器测试（含暴力枚举对照）。

启用 repeat:[行周期, 列周期] 后，修补稿每格须与按行周期下移、
列周期右移后的格值分别相同（索引环绕）；周期与环向浮长 K、
锁定格、onesRange 同时生效；翻转数仍按实际改变的格数计算，
并列最优候选沿用按行展开字典序。
"""

import itertools
import random
import sys
import time

from solver import diagnose_unlocks, solve_repair, solve_repair_top
from weave import find_violations


def is_repeated(g, rows, cols, repeat):
    """网格 g 是否按 (行周期, 列周期) 环绕重复。"""
    rp, cp = repeat
    for r in range(rows):
        for c in range(cols):
            if g[r][c] != g[(r + rp) % rows][c]:
                return False
            if g[r][c] != g[r][(c + cp) % cols]:
                return False
    return True


def brute_top(rows, cols, k, grid, locks, ones_range=None, repeat=None,
              limit=3):
    """暴力枚举：浮长 + 锁定 + 区间 + 周期共同约束下的全局最少翻转，
    返回按行展开字典序前 limit 个 (翻转数, 展开序列)；无解返回 None。"""
    locked = set(map(tuple, locks))
    free = [(r, c) for r in range(rows) for c in range(cols)
            if (r, c) not in locked]
    sols = []
    for bits in itertools.product((0, 1), repeat=len(free)):
        g = [row[:] for row in grid]
        for (r, c), b in zip(free, bits):
            g[r][c] = b
        if find_violations(g, rows, cols, k):
            continue
        if repeat is not None and not is_repeated(g, rows, cols, repeat):
            continue
        ones = sum(v for row in g for v in row)
        if ones_range is not None and not (
                ones_range[0] <= ones <= ones_range[1]):
            continue
        flips = sum(b != grid[r][c] for (r, c), b in zip(free, bits))
        sols.append((flips, tuple(v for row in g for v in row)))
    if not sols:
        return None
    best = min(f for f, _ in sols)
    return sorted(((f, seq) for f, seq in sols if f == best),
                  key=lambda x: x[1])[:limit]


def check_top(rows, cols, k, grid, locks, ones_range, repeat, label,
              limit=3):
    expected = brute_top(rows, cols, k, grid, locks, ones_range, repeat,
                         limit)
    got = solve_repair_top(rows, cols, k, grid, locks, ones_range, repeat,
                           limit=limit)
    if expected is None:
        assert got is None, f"{label}: 应无解但解出 {got}"
        print(f"  [OK] {label}: 无可行修补（与暴力一致）")
        return
    assert got is not None, f"{label}: 应有解但报无解"
    assert got["flip_count"] == expected[0][0]
    assert len(got["candidates"]) == len(expected), (
        f"{label}: 候选数 {len(got['candidates'])} != {len(expected)}")
    seen = set()
    for cand, (ef, eseq) in zip(got["candidates"], expected):
        seq = tuple(v for row in cand["repaired"] for v in row)
        assert seq == eseq, f"{label}: 字典序错误"
        assert len(cand["flips"]) == ef == got["flip_count"]
        assert cand["onesCount"] == sum(seq)
        assert not find_violations(cand["repaired"], rows, cols, k)
        assert is_repeated(cand["repaired"], rows, cols, repeat), (
            f"{label}: 候选不满足重复周期 {repeat}")
        # 实际改变的格数即翻转数（周期等价类被整体翻转时逐格计数）
        assert len(cand["flips"]) == sum(
            v != grid[r][c]
            for r, row in enumerate(cand["repaired"])
            for c, v in enumerate(row))
        seen.add(seq)
    assert len(seen) == len(expected)
    for (r, c) in locks:
        for cand in got["candidates"]:
            assert cand["repaired"][r][c] == grid[r][c], (
                f"{label}: 锁定格 ({r},{c}) 被改变")
    if ones_range is not None:
        for cand in got["candidates"]:
            assert ones_range[0] <= cand["onesCount"] <= ones_range[1]
    print(f"  [OK] {label}: {len(expected)} 候选，各翻转 "
          f"{expected[0][0]} 格，满足周期 {repeat}")


def brute_diagnose(rows, cols, k, grid, locks, ones_range=None, repeat=None,
                   limit=3):
    """暴力求最少解锁集合（短字典序前 limit 个）及各自最优修补。

    None 表示结构性无解。
    """
    locked = sorted(map(tuple, locks))

    def best_repair(unlockset):
        remaining = set(locked) - set(unlockset)
        best = None
        for bits in itertools.product((0, 1), repeat=rows * cols):
            g = [list(bits[r * cols:(r + 1) * cols]) for r in range(rows)]
            if any(g[r][c] != grid[r][c] for (r, c) in remaining):
                continue
            if find_violations(g, rows, cols, k):
                continue
            if repeat is not None and not is_repeated(g, rows, cols, repeat):
                continue
            ones = sum(bits)
            if ones_range is not None and not (
                    ones_range[0] <= ones <= ones_range[1]):
                continue
            flips = tuple((r, c) for r in range(rows)
                          for c in range(cols) if g[r][c] != grid[r][c])
            if best is None or (len(flips), bits) < (
                    len(best[0]), best[1]):
                best = (flips, bits)
        return best

    feasible = []
    for size in range(len(locked) + 1):
        for comb in itertools.combinations(range(len(locked)), size):
            unlockset = [locked[i] for i in comb]
            sol = best_repair(unlockset)
            if sol is not None:
                feasible.append((unlockset, sol))
        if feasible:
            break
    if not feasible:
        return None
    feasible.sort(key=lambda x: [list(p) for p in x[0]])
    return [(s, len(sol[0]), sol[1]) for s, sol in feasible[:limit]]


def check_diagnose(rows, cols, k, grid, locks, ones_range, repeat, label):
    got = diagnose_unlocks(rows, cols, k, grid, locks, ones_range, repeat,
                           limit=3)
    expected = brute_diagnose(rows, cols, k, grid, locks, ones_range, repeat)
    locked = set(map(tuple, locks))
    if expected is None:
        assert got["structural"] is True, f"{label}: 应结构性无解"
        assert "options" not in got
        print(f"  [OK] {label}: 结构性无解（与暴力一致）")
        return
    assert got.get("structural") is False
    assert got["unlock_count"] == len(expected[0][0]), (
        f"{label}: 最少解锁数不一致")
    assert len(got["options"]) == len(expected)
    for opt, (exp_unlocks, exp_flips, exp_seq) in zip(got["options"],
                                                       expected):
        unlocks = [tuple(p) for p in opt["unlocks"]]
        assert unlocks == exp_unlocks
        ex = opt["example"]
        seq = tuple(v for row in ex["repaired"] for v in row)
        assert seq == exp_seq
        assert len(ex["flips"]) == exp_flips
        assert is_repeated(ex["repaired"], rows, cols, repeat)
        for (r, c) in locked - set(unlocks):
            assert ex["repaired"][r][c] == grid[r][c], (
                f"{label}: 未解锁格被改变")
    print(f"  [OK] {label}: 最少解锁 {got['unlock_count']} 格，"
          f"{len(expected)} 集合（与暴力一致）")


def main():
    print("== 固定周期用例（暴力对照） ==")
    # 4x4 全0 K=2 + 周期[2,2]：恰剩两个棋盘格方向，各翻转 8 格
    z4 = [[0] * 4 for _ in range(4)]
    check_top(4, 4, 2, z4, [], None, (2, 2), "4x4 K=2 周期[2,2] 两候选")
    # 周期 [4,4] 等于不限制
    check_top(4, 4, 2, z4, [], None, (4, 4), "4x4 周期[4,4] 等价无限制")
    # 列周期 1：整行恒同 -> 行无限浮长，无解
    check_top(4, 4, 2, z4, [], None, (2, 1), "4x4 周期列1 无解")
    # 行周期 1：整列恒同 -> 无解
    check_top(4, 4, 2, z4, [], None, (1, 2), "4x4 周期行1 无解")
    # 2x2 周期 [1,1]：全格相等，结构性无解
    check_top(2, 2, 2, [[0, 0], [0, 0]], [], None, (1, 1),
              "2x2 周期[1,1] 无解")
    # 周期与锁定冲突：周期 [2,2] 下 (0,0) 与 (0,2) 同类须相等，
    # 原稿一锁 0 一锁 1 -> 锁定状态下无解
    conflict_grid = [row[:] for row in z4]
    conflict_grid[0][2] = 1
    check_top(4, 4, 2, conflict_grid, [(0, 0), (0, 2)], None, (2, 2),
              "4x4 周期同类锁定冲突 无解")
    # 周期与 onesRange 同时生效
    check_top(4, 4, 2, z4, [], (8, 8), (2, 2),
              "4x4 周期[2,2] 区间[8,8]")
    check_top(4, 4, 2, z4, [], (0, 0), (2, 2),
              "4x4 周期[2,2] 区间[0,0] 无解")
    # 非整除周期：6 列、列周期 4 等价列周期 2；3 行、行周期 3 不限制
    z64 = [[0] * 6 for _ in range(3)]
    got = solve_repair_top(3, 6, 2, z64, [], None, (3, 4), limit=1)
    assert got is not None
    g = got["candidates"][0]["repaired"]
    assert is_repeated(g, 3, 6, (3, 4))
    assert not find_violations(g, 3, 6, 2)
    print("  [OK] 3x6 K=2 周期[3,4]（非整除，等价列周期2）可解且满足周期")

    # 已合法的周期原稿：0 翻转
    periodic = [[0, 1, 0, 1], [1, 0, 1, 0],
                [0, 1, 0, 1], [1, 0, 1, 0]]
    check_top(4, 4, 1, periodic, [], None, (2, 2),
              "4x4 棋盘格本合法且周期[2,2] 0翻转")

    print("== 周期随机小网格对照暴力 ==")
    rng = random.Random(7071)
    for i in range(80):
        rows = rng.randint(2, 4)
        cols = rng.randint(2, 4)
        k = rng.randint(1, 3)
        grid = [[rng.randint(0, 1) for _ in range(cols)] for _ in range(rows)]
        locks = [[r, c] for r in range(rows) for c in range(cols)
                 if rng.random() < 0.3]
        rp = rng.randint(1, rows)
        cp = rng.randint(1, cols)
        orng = None
        if rng.random() < 0.4:
            lo = rng.randint(0, rows * cols)
            orng = (lo, rng.randint(lo, rows * cols))
        check_top(rows, cols, k, grid, locks, orng, (rp, cp),
                  f"随机#{i} {rows}x{cols} K={k} 周期[{rp},{cp}]"
                  f"{' 区间' + str(orng) if orng else ''}")

    print("== 周期下的解锁诊断（暴力对照） ==")
    # 同类锁定冲突：原稿 (0,0)=0、(0,2)=1 均锁定，周期 [2,2] 要求同类相等，
    # 解除其中 1 格即可
    check_diagnose(4, 4, 2, conflict_grid, [(0, 0), (0, 2)], None, (2, 2),
                   "4x4 周期同类锁冲突 需解1")
    # 周期本身使无锁也无解 -> 结构性
    check_diagnose(4, 4, 2, z4, [(0, 0)], None, (1, 1),
                   "4x4 周期[1,1] 结构性无解")
    # 全锁 + 周期：需解除 2 格构成棋盘方向；与暴力一致
    check_diagnose(2, 2, 2, [[0, 0], [0, 0]],
                   [[r, c] for r in range(2) for c in range(2)],
                   None, (2, 2), "2x2 全锁 周期[2,2] 需解2")
    drng = random.Random(7072)
    for i in range(40):
        rows = drng.randint(2, 4)
        cols = drng.randint(2, 4)
        k = drng.randint(1, 3)
        grid = [[drng.randint(0, 1) for _ in range(cols)] for _ in range(rows)]
        locks = [[r, c] for r in range(rows) for c in range(cols)
                 if drng.random() < 0.45]
        rp = drng.randint(1, rows)
        cp = drng.randint(1, cols)
        orng = None
        if drng.random() < 0.4:
            lo = drng.randint(0, rows * cols)
            orng = (lo, drng.randint(lo, rows * cols))
        check_diagnose(rows, cols, k, grid, locks, orng, (rp, cp),
                       f"诊断随机#{i} {rows}x{cols} K={k} 周期[{rp},{cp}]")

    print("== 大网格性能（16x8 + 周期） ==")
    prng = random.Random(7073)
    for k, rp, cp in ((1, 8, 4), (2, 8, 4), (2, 2, 2), (3, 4, 2), (2, 16, 8)):
        grid = [[prng.randint(0, 1) for _ in range(8)] for _ in range(16)]
        t0 = time.time()
        got = solve_repair_top(16, 8, k, grid, [], None, (rp, cp), limit=3)
        dt = time.time() - t0
        if got is not None:
            for cand in got["candidates"]:
                assert not find_violations(cand["repaired"], 16, 8, k)
                assert is_repeated(cand["repaired"], 16, 8, (rp, cp))
            print(f"  [OK] 16x8 K={k} 周期[{rp},{cp}]: "
                  f"{len(got['candidates'])} 候选, 各翻转 "
                  f"{got['flip_count']} 格, {dt:.2f}s")
        else:
            print(f"  [OK] 16x8 K={k} 周期[{rp},{cp}]: 无解, {dt:.2f}s")
        assert dt < 15, "周期求解超时"

    # 周期 + 区间 + 大网格
    grid = [[prng.randint(0, 1) for _ in range(8)] for _ in range(16)]
    t0 = time.time()
    got = solve_repair_top(16, 8, 2, grid, [], (40, 80), (8, 4), limit=1)
    dt = time.time() - t0
    assert got is not None
    cand = got["candidates"][0]
    assert 40 <= cand["onesCount"] <= 80
    assert is_repeated(cand["repaired"], 16, 8, (8, 4))
    print(f"  [OK] 16x8 K=2 周期[8,4] 区间[40,80]: "
          f"{cand['onesCount']} 个1, {dt:.2f}s")
    assert dt < 15

    print("\n全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
