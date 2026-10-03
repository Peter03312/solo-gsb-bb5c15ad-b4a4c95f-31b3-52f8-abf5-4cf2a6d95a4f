"""设计稿（尺寸、格值、锁定格、K）的合法性校验。"""

MAX_ROWS = 16
MAX_COLS = 8


class ValidationError(ValueError):
    """输入不合法，携带面向用户的中文错误信息。"""


def _is_int(v):
    # JSON 里 bool 是 int 的子类，需排除；不接受浮点/字符串
    return isinstance(v, int) and not isinstance(v, bool)


def validate_design(payload):
    """校验并规范化设计稿，返回 (rows, cols, grid, locks, k, ones_range, repeat)。

    ones_range 为 None（未填写区间）或 (下限, 上限)：填写时两端都必填，
    且满足 0 <= 下限 <= 上限 <= 行数×列数。
    repeat 为 None（不限制）或 (行周期, 列周期)：填写时两端都必填，
    且为 1 <= 行周期 <= 行数、1 <= 列周期 <= 列数 的正整数。
    不合法时抛出 ValidationError。
    """
    if not isinstance(payload, dict):
        raise ValidationError("请求体必须是 JSON 对象")

    rows, cols, k = payload.get("rows"), payload.get("cols"), payload.get("k")
    if not _is_int(rows) or not 1 <= rows <= MAX_ROWS:
        raise ValidationError(f"行数必须是 1~{MAX_ROWS} 的整数")
    if not _is_int(cols) or not 1 <= cols <= MAX_COLS:
        raise ValidationError(f"列数必须是 1~{MAX_COLS} 的整数")
    if not _is_int(k) or k < 1:
        raise ValidationError("最大浮长 K 必须是正整数")

    grid = payload.get("grid")
    if (not isinstance(grid, list) or len(grid) != rows
            or any(not isinstance(row, list) or len(row) != cols
                   for row in grid)):
        raise ValidationError("交织格必须是与尺寸一致的矩形数组")
    for r in range(rows):
        for c in range(cols):
            v = grid[r][c]
            if not _is_int(v) or v not in (0, 1):
                raise ValidationError(f"格值只能为 0 或 1（第 {r + 1} 行第 {c + 1} 列不合法）")

    locks = payload.get("locks")
    if not isinstance(locks, list):
        raise ValidationError("锁定格必须是坐标数组")
    norm_locks = set()
    for item in locks:
        if (not isinstance(item, list) or len(item) != 2
                or not _is_int(item[0]) or not _is_int(item[1])):
            raise ValidationError("锁定格坐标必须是 [行, 列] 整数对")
        r, c = item
        if not (0 <= r < rows and 0 <= c < cols):
            raise ValidationError(f"锁定格 ({r + 1}, {c + 1}) 越界")
        norm_locks.add((r, c))

    # 格值 1 总数区间：未填（键缺失或 null）沿用现有修补规则；
    # 填写时必须是 [下限, 上限] 两元素数组，两端都必填，
    # 且 0 <= 下限 <= 上限 <= 行数×列数（不悄悄截断）。
    total = rows * cols
    raw_range = payload.get("onesRange", None)
    if raw_range is None:
        ones_range = None
    elif (isinstance(raw_range, list) and len(raw_range) == 2
          and _is_int(raw_range[0]) and _is_int(raw_range[1])):
        lower, upper = raw_range
        if lower < 0 or upper < 0:
            raise ValidationError("格值1总数区间端点不得为负数")
        if lower > upper:
            raise ValidationError("格值1总数区间下限不得大于上限")
        if upper > total:
            raise ValidationError(
                f"格值1总数区间上限 {upper} 超出当前尺寸总格数 {total}"
                f"（{rows}×{cols}），请调整区间或尺寸")
        ones_range = (lower, upper)
    else:
        raise ValidationError(
            "格值1总数区间须为 [下限, 上限]，填写时两端都必填"
            "（0 ≤ 下限 ≤ 上限 ≤ 行数×列数）；不填时请传 null 或省略")

    # 重复周期：省略或 null 表示不限制；填写时必须是 [行周期, 列周期]
    # 两元素数组，两端都必填，且为不超过当前行/列数的正整数。
    # 尺寸变化导致周期越界只提示调整，绝不悄悄截断。
    raw_repeat = payload.get("repeat", None)
    if raw_repeat is None:
        repeat = None
    elif (isinstance(raw_repeat, list) and len(raw_repeat) == 2
          and _is_int(raw_repeat[0]) and _is_int(raw_repeat[1])):
        row_period, col_period = raw_repeat
        if row_period < 1 or col_period < 1:
            raise ValidationError("重复周期必须是正整数（行周期、列周期均 ≥ 1）")
        if row_period > rows:
            raise ValidationError(
                f"行周期 {row_period} 超出当前行数 {rows}"
                f"（{rows}×{cols}），请调整周期或尺寸，不会自动截断")
        if col_period > cols:
            raise ValidationError(
                f"列周期 {col_period} 超出当前列数 {cols}"
                f"（{rows}×{cols}），请调整周期或尺寸，不会自动截断")
        repeat = (row_period, col_period)
    else:
        raise ValidationError(
            "重复周期须为 [行周期, 列周期]，填写时两端都必填"
            "（1 ≤ 行周期 ≤ 行数、1 ≤ 列周期 ≤ 列数）；不填时请传 null 或省略")

    grid = [[int(v) for v in row] for row in grid]
    locks = sorted(norm_locks)
    return rows, cols, grid, locks, k, ones_range, repeat


def canonical(rows, cols, grid, locks, k, ones_range=None, repeat=None):
    """规范化后的可哈希表示，用于预览一致性比对。"""
    return {
        "rows": rows,
        "cols": cols,
        "grid": [list(row) for row in grid],
        "locks": [list(p) for p in sorted(map(tuple, locks))],
        "k": k,
        "onesRange": None if ones_range is None
        else [ones_range[0], ones_range[1]],
        "repeat": None if repeat is None
        else [repeat[0], repeat[1]],
    }
