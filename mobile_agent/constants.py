"""
全局常量 —— 防炸机制的"硬约束"层。
本文件中的常量不可被 LLM 或上层 prompt 覆盖。
任何放宽这里数值的修改都必须经过人工 review。
"""

# ── 强制等待表(秒) PRD §6.3 ───────────────────
WAIT_AFTER_TAP = 1.0
WAIT_AFTER_TYPE = 0.5
WAIT_AFTER_SWIPE = 0.8
WAIT_AFTER_PAGE_CHANGE = 2.0
WAIT_AFTER_HASH_INPUT = 1.5     # 输 # 等推荐弹出
WAIT_AFTER_PUBLISH_TAP = 3.0    # 点"发布"后等服务器回包

# ── 重试上限 PRD §11.10 ───────────────────────
MAX_STEP_RETRY = 3              # 单步骤最多重试次数
MAX_TASK_RETRY = 1              # 单任务最多重试次数

# ── 设备互斥锁 PRD §6.5 ───────────────────────
DEVICE_LOCK_TIMEOUT_SEC = 600   # 10 分钟无心跳判超时
DEVICE_LOCK_HEARTBEAT_SEC = 30  # 每 30s 刷新锁时间戳

# ── LLM 调用 PRD §8.4 ─────────────────────────
LLM_TIMEOUT_SEC = 60
LLM_MAX_RETRIES = 3
LLM_TEMPERATURE_DEFAULT = 0.3
LLM_TEMPERATURE_ROUTER = 0.0    # 路由判断要确定性

# ── tap 随机延迟 PRD §6.1 ─────────────────────
TAP_DELAY_MIN_MS = 50
TAP_DELAY_MAX_MS = 150

# ── 取消响应 PRD §11.7 ────────────────────────
CANCEL_DEADLINE_SEC = 5

# ── 找元素三级查找重试间隔 PRD §6.2 ───────────
FIND_RETRY_WAIT_SEC = 1.5

# ── 启动器白名单(用于"是否回到桌面"的判定) ───
LAUNCHER_WHITELIST = frozenset({
    "com.miui.home",                          # 小米/红米
    "com.miui.launcher",
    "com.huawei.android.launcher",            # 华为/荣耀
    "com.hihonor.android.launcher",
    "com.sec.android.app.launcher",           # 三星
    "com.oppo.launcher",                      # OPPO
    "com.bbk.launcher2",                      # vivo
    "com.android.launcher",                   # 原生
    "com.android.launcher3",
    "com.google.android.apps.nexuslauncher",  # Pixel
})

# ── 业务相关 ──────────────────────────────────
XHS_PACKAGE = "com.xingin.xhs"
ADB_KEYBOARD_PACKAGE = "com.android.adbkeyboard"
ADB_KEYBOARD_IME = "com.android.adbkeyboard/.AdbIME"

# ── 发布"成功"关键词 PRD §2.1 ─────────────────
SUCCESS_KEYWORDS = ("发布成功", "已发布", "发布完成", "成功")
