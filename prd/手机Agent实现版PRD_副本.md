# 手机操作 Agent 实现版 PRD（MVP）

**文档版本**：v1.0（实现基线）
**创建日期**：2026-05-02
**作者**：Claude（CC 委托）
**文档定位**：本 PRD 是后续实际编码的唯一标准。`手机操作Agent系统PRD.md` 与 `手机操作Agent防炸机制PRD.md` 为参考资料；当本文与参考资料冲突时，以本文为准。

---

## 0. TL;DR（最重要的 12 行）

- **目标产品**：一个能聊天、有记忆、可调用技能去操作手机的本地 Agent。
- **运行环境**：**Windows 10/11**（开发 + 验证均在 Windows 上完成；本 PRD 文档可由其他系统维护，但所有代码与脚本以 Windows 为目标）。
- **MVP 验收**：在 USB 连接的安卓真机上，用户在聊天框说"按主题 X 发一条小红书文字笔记"，Agent 完成发布并在屏幕上看到"发布成功"四字 → MVP 通过。
- **设备**：1 台真安卓手机，USB 连 Windows PC，开发者模式 + USB 调试 + 厂商 USB 驱动。
- **大脑**：Kimi（Moonshot）API，模型名待第一步实测；走 OpenAI 兼容协议；带视觉。
- **手机控制**：`uiautomator2`（直接读 UI 树 → 拿元素 bounds → adb 注入触屏事件）。OCR + VLM 仅作兜底。
- **中文输入**：在手机上预装 `ADBKeyboard.apk`，运行时切为默认输入法。
- **Agent 编排**：`LangGraph`，状态机化的 plan → act → observe → verify → loop。
- **技能机制**：技能注册表；MVP 只实现 `publish_xhs_text_note(theme: str)`，其余动作（开 App / 回桌面 / 清后台 / 截图 / 找元素 / 点 / 输入）是底层 action 而非 skill。
- **记忆**：SQLite，4 张表：conversations、tasks、facts、skills。会话记忆 + 任务回放 + 用户事实 + 技能元数据。
- **对话界面**：Gradio Chatbot（左聊天，右实时手机截图），命令行模式作 fallback。
- **防炸机制**：原 PRD 的 10 条全部吸收，落到执行器层而非提示词层。
- **不做的事**：多设备并发、登录/验证码处理、图片/视频笔记、生产级部署、其他平台技能——全部留给 v2。

---

## 1. 范围与非范围

### 1.1 范围（MVP 必须做）
1. 安卓真机经 USB 连接到 Mac，能稳定执行触屏 / 截图 / 文字输入 / 启停 App。
2. 对话界面（Gradio）+ 一个 Kimi 驱动的 Agent，能理解"发一条小红书笔记，主题是 X"这类自然语言指令。
3. 技能注册机制 + 完整实现 `publish_xhs_text_note` 一个技能。
4. LLM 内容生成器：根据用户给定的主题方向，生成标题（≤20 字）+ 正文（200~500 字）+ 3~5 个标签。
5. 长期记忆：会话历史、用户偏好（如固定主题方向）、已发笔记记录、技能列表。
6. 防炸机制 10 条全部落地。
7. 用户取消（聊天框输入"停"或点 UI 上的停止键）能在 5 秒内停下手机操作并回桌面。

### 1.2 非范围（MVP 不做）
- 多台手机并发调度、设备池。
- 自动登录小红书（含短信 / 滑块 / 风控验证）。
- 图片笔记、视频笔记。
- iOS 设备。
- Windows 模拟器、云手机服务。
- 服务化部署、鉴权、多用户。
- 抖音 / 微信 / 通讯录等其他平台技能（保留扩展接口）。
- 反检测的拟人轨迹（MVP 用基本随机化即可，深度反检测留 v2）。

---

## 2. 成功标准

### 2.1 必须满足（缺一不可）
- ✅ 用户在聊天框输入"用主题 X 发一条小红书文字笔记"，Agent 在 ≤ 8 分钟内完成发布。
- ✅ 屏幕 OCR 截到"发布成功" / "已发布" / "成功" 任一关键词。
- ✅ 任务结束后手机当前前台包名为 launcher（小米/华为/原生等任一）。
- ✅ 任务过程中所有步骤的截图 + 操作日志可回放。
- ✅ 用户中途说"停"，5 秒内手机不再产生新触屏事件。

### 2.2 不该出现
- ❌ "假成功"：Agent 报告成功但屏幕没看到任何成功提示。
- ❌ "死循环"：同一坐标连续点击 ≥ 4 次而无页面变化。
- ❌ "正文被覆盖"：标签插入到正文中间。
- ❌ "锁泄漏"：任务异常退出后下一次任务无法启动。

---

## 3. 技术选型（含理由）

| 模块 | 选型 | 理由 | 备选 |
|---|---|---|---|
| 语言 | Python 3.10+ | LangGraph、uiautomator2 都是 Python；用户指定 | — |
| 手机控制 | `uiautomator2`（pip 装；手机端跑 atx-agent） | 直接拿系统 UI 树，元素定位远比 OCR 可靠；轻量、Python 原生 | Appium（重）；纯 adb shell（弱） |
| 中文输入 | `ADBKeyboard.apk` | `adb shell input text` 不支持中文。ADBKeyboard 通过广播注入 Unicode | 剪贴板粘贴（部分 App 阻断粘贴） |
| OCR 兜底 | `PaddleOCR`（中文优） | 开源、中文准确率高；离线 | EasyOCR、Tesseract（中文差） |
| VLM 兜底 | Kimi 视觉模型 | 用户已配 API；UI 树 + OCR 都失效时让模型直接看截图找元素 | — |
| Agent 编排 | `LangGraph` | 状态机适合"plan→act→verify→retry"循环；显式可控 | LangChain AgentExecutor（黑盒） |
| LLM | Kimi（Moonshot OpenAI 兼容） | 用户提供 | — |
| 对话 UI | `Gradio` Chatbot | 50 行起一个像样的 Web UI，原生支持图片消息（直接显示截图） | Streamlit、CLI |
| 长期记忆 | SQLite + 文件 | 单进程 demo 够用；文件存截图 | Chroma 向量库（v2） |
| 截图存储 | 本地 `runs/<task_id>/step_NN.png` | 简单、可回放 | — |

### 3.1 关于 Kimi 模型 ID（待验证）
**M0 第一件事**：写一个 30 行的脚本，依次试 `kimi-m2.6`、`kimi-latest`、`moonshot-v1-128k-vision-preview`、`kimi-k2-0711-preview`，记录哪个能通且支持视觉。后续所有代码读 `MODEL_NAME` 环境变量，不写死。
- API base：`https://api.moonshot.cn/v1`（OpenAI 兼容）
- 鉴权：`Authorization: Bearer <key>`
- key 通过 `.env` 注入，不进 git。

---

## 4. 系统架构

### 4.1 五层架构（替代原 PRD 的四层）
```
┌──────────────────────────────────────────────────────┐
│ L5  对话层  Gradio Chatbot（用户↔Agent，带截图渲染）  │
└──────────────────────────────────────────────────────┘
                       ↕ (text + image)
┌──────────────────────────────────────────────────────┐
│ L4  Agent 层  LangGraph 状态机                        │
│      Plan → Select Skill → Run → Verify → Memory     │
└──────────────────────────────────────────────────────┘
                       ↕
┌──────────────────────────────────────────────────────┐
│ L3  技能层  SkillRegistry                             │
│      skills/publish_xhs_text_note.py（唯一 MVP 技能）│
└──────────────────────────────────────────────────────┘
                       ↕
┌──────────────────────────────────────────────────────┐
│ L2  动作层  Device API（无 LLM 参与，纯执行）         │
│      tap / swipe / type / find / wait / verify       │
│      互斥锁、超时、重试、强制等待都在这层             │
└──────────────────────────────────────────────────────┘
                       ↕ (adb / atx-agent)
┌──────────────────────────────────────────────────────┐
│ L1  设备层  Android 真机（uiautomator2 server）       │
└──────────────────────────────────────────────────────┘
```

横切：**记忆层**（SQLite）和 **日志/截图层**（文件系统）服务于 L2~L5。

### 4.2 一次任务的数据流
```
用户："按'独居老人陪伴'主题，发一条小红书文字笔记"
  ↓
[L5] 入消息队列，渲染到聊天框
  ↓
[L4] Agent 收到消息：
     - 读取近 N 轮会话 + 用户事实 + 可用技能列表，注入 system prompt
     - 让 Kimi 输出：意图 = call_skill, skill = publish_xhs_text_note, args = {theme: "独居老人陪伴"}
  ↓
[L4] 路由到技能层
  ↓
[L3] publish_xhs_text_note(theme):
     - 子步骤 1: generate_content(theme) → {title, body, tags}（调 Kimi 文本）
     - 子步骤 2: 拿设备锁
     - 子步骤 3: 按写死的 12 步模板调用 L2
  ↓
[L2] 每一步：截图 → 找元素（UI 树→OCR→VLM 三级）→ 触屏 → 强制等待 → 截图验证
     失败累计 ≥ 3 → 抛 StepFailed → L3 触发清理 → 释放锁 → 上报失败
  ↓
[L4] 完成验证（业务 + 环境 + 系统三步）→ 写记忆 → 回消息给 L5
  ↓
[L5] 显示"已发布，标题 = ...，耗时 ... 分钟"，附最后一张截图
```

---

## 5. L1 设备层：环境准备（Windows）

### 5.1 Windows PC 端

#### 5.1.1 安装 ADB（platform-tools）
任选其一：
- **方案 A（推荐，Scoop）**：
  ```powershell
  # 先装 Scoop（如果没有）
  Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
  irm get.scoop.sh | iex
  scoop install adb
  ```
- **方案 B（手动）**：
  1. 从 Google 官网下载 `platform-tools-latest-windows.zip`
  2. 解压到 `C:\platform-tools\`
  3. 把 `C:\platform-tools\` 加入系统环境变量 `Path`
  4. 重开 PowerShell 验证

验证：`adb version` → 输出版本号（≥ 34.x）

#### 5.1.2 安装 USB 驱动（Windows 专属，Mac/Linux 不需要）
没装驱动 → `adb devices` 会显示 `unauthorized` 或干脆看不到设备。按你手机品牌选：
| 品牌 | 驱动 |
|---|---|
| 小米/红米 | Mi USB Driver（小米官方） |
| 华为/荣耀 | HiSuite 自带，或单独装 HiSuite USB Driver |
| 三星 | Samsung USB Driver for Mobile Phones |
| OPPO/vivo/realme | 各自官方助手自带 |
| 通用兜底 | Google USB Driver（Android Studio 自带）/ Universal ADB Driver |

装完插上手机，`adb devices` 应输出类似：
```
List of devices attached
abc1234567        device
```

#### 5.1.3 安装 Python 3.10+
- 从 python.org 下载 Windows 安装包
- **安装时务必勾选 "Add python.exe to PATH"**
- 验证：`python --version` 输出 3.10 或更高

#### 5.1.4 字符编码与终端
- PowerShell 默认是 GBK，处理中文打印/日志会乱。两种处理：
  - 临时：每次开终端先跑 `chcp 65001`
  - 永久：在 `.env` 中设 `PYTHONUTF8=1`，并在 PowerShell 配置文件里加 `[Console]::OutputEncoding = [System.Text.Encoding]::UTF8`
- **推荐使用 Windows Terminal**（微软商店），原生 UTF-8 支持更好

#### 5.1.5 杀软白名单
- Windows Defender / 360 / 火绒 偶尔会拦 `adb.exe` 或截图传输
- 项目根目录加入白名单，避免任务跑一半被杀进程

### 5.2 手机端（CC 你需要做的操作）
1. 进【设置】→【关于本机】→ 连点【版本号】7 次，开启开发者模式。
2. 进【设置】→【开发者选项】，打开：
   - USB 调试
   - USB 调试（安全设置）
   - 通过 USB 安装应用
   - 指针位置（debug 期可视化用，可选）
3. USB 连 Windows PC，弹窗"允许 USB 调试吗"勾选"始终允许"→ 允许。
   - 第一次连接弹窗可能在手机锁屏后才出现，留意通知栏
4. 在 Windows PowerShell 跑 `adb devices`，应能看到设备 ID（不是 `unauthorized`）。
5. **预装两个 APK**（开发者会指引）：
   - 小红书（你自己已装并登录好账号）
   - `ADBKeyboard.apk`（中文输入注入用，开源，仓库会带 `.\scripts\install_adbkeyboard.ps1` 一键装）
6. 进【设置】→【系统】→【语言和输入法】→【管理键盘】，启用 ADBKeyboard 并设为默认输入法（运行时脚本会自动切，但首次需手动启用权限）。

### 5.3 一键初始化（PowerShell）
```powershell
# 在项目根目录
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

python -m uiautomator2 init        # 自动给手机推 atx-agent
.\scripts\install_adbkeyboard.ps1  # 安装中文输入法 APK
python scripts\check_device.py     # 自检：adb 可见、UI 树可读、ADBKeyboard 已启用、能截图
```

> 如果 `Activate.ps1` 报"无法加载，因为在此系统上禁止运行脚本"，先执行：
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

---

## 6. L2 动作层：Device API 设计

### 6.1 接口契约（核心 12 个）
```python
class Device:
    def screenshot(self) -> Path                       # 截图，返回本地文件路径
    def dump_ui(self) -> UIElement                     # 解析 uiautomator dump
    def find(self, **criteria) -> Optional[UIElement]  # 三级查找（见 6.2）
    def tap(self, x: int, y: int) -> None              # 带 50~150ms 随机延迟
    def tap_element(self, el: UIElement) -> None       # 自动取 bounds 中心
    def swipe(self, x1, y1, x2, y2, duration_ms=300) -> None
    def type_text(self, text: str) -> None             # 走 ADBKeyboard，支持中文
    def press_key(self, key: Literal["HOME","BACK","RECENT"]) -> None
    def current_package(self) -> str                   # 当前前台包名
    def is_on_launcher(self) -> bool                   # 包名是否在 LAUNCHER_WHITELIST
    def launch_app(self, package: str) -> None
    def clear_recent_apps(self) -> None                # 见 6.4 的清后台子流程
```

### 6.2 元素查找三级策略
```python
def find(self, text=None, resource_id=None, content_desc=None,
         class_name=None, text_contains=None, position=None,
         vlm_hint=None, screenshot=None) -> Optional[UIElement]:
    # 第一级：UI 树精确匹配（uiautomator2 selector）
    el = self._find_in_ui_tree(...)
    if el: return el

    # 第二级：OCR（PaddleOCR 中文）
    if text or text_contains:
        el = self._find_by_ocr(text or text_contains)
        if el: return el

    # 第三级：VLM 兜底（Kimi 视觉）
    if vlm_hint:
        el = self._find_by_vlm(vlm_hint)   # "底部正中那个红色加号"
        if el: return el

    return None
```
**重要**：每升一级前必须重新截图 + 等 1.5 秒，绝不在同一截图上跨级重试。

### 6.3 强制等待表（写死，不可被上层覆盖）
| 动作后 | 强制等待 |
|---|---|
| tap | 1.0s |
| type_text | 0.5s |
| swipe | 0.8s |
| 切页面（包名变化） | 2.0s |
| 输入 `#` 等推荐 | 1.5s |
| 点"发布"按钮后 | 3.0s |

### 6.4 清后台子流程（写死的固定步骤）
1. press_key RECENT
2. 等待 1.5s 截图
3. 在屏幕左侧（x=屏宽×0.2, y=屏高×0.5）按住 → 滑到右侧（x=屏宽×0.8）
4. 找到"全部清除" / "清除全部"文字 → tap
5. 再 press_key RECENT 一次，验证截到"近期没有任何内容"或类似提示
6. press_key HOME
7. 验证 `is_on_launcher() == True`，否则抛异常

### 6.5 设备互斥锁
```python
class DeviceLock:
    LOCK_TIMEOUT = 600  # 10 分钟
    def acquire(self, device_id, task_id) -> bool: ...
    def release(self, device_id) -> None: ...
    def force_release_if_expired(self, device_id) -> None: ...
```
- 进程内单例（MVP 单进程不需要 redis）
- 任务开始前 acquire，finally release
- 心跳：任务每 30s 刷新锁时间戳；超 10 分钟无心跳判超时

---

## 7. L3 技能层

### 7.1 SkillRegistry 接口
```python
class Skill(Protocol):
    name: str
    description: str           # 给 LLM 看的描述
    args_schema: type[BaseModel]
    def run(self, args: BaseModel, ctx: RunContext) -> SkillResult: ...
```
- `RunContext` 持有 `device`、`memory`、`logger`、`cancel_token`。
- `SkillResult { ok: bool, summary: str, artifacts: list[Path] }`
- 注册：扫描 `skills/` 目录自动收集。

### 7.2 唯一 MVP 技能：`publish_xhs_text_note`

**args**：
```python
class PublishXhsArgs(BaseModel):
    theme: str                 # 用户给的方向
    title: str | None = None   # 可选，None 则 LLM 生成
    body: str | None = None
    tags: list[str] | None = None
```

**子步骤**：

#### 步骤 0：内容生成（不操作手机）
- 若 title/body/tags 任一为空 → 调 Kimi 文本模型生成。
- Prompt 模板写在 `skills/prompts/xhs_content.md`，输出强制 JSON：
  ```json
  {"title":"≤20字","body":"200~500字纯文本，不带#","tags":["3~5个","不带#"]}
  ```
- 用 `pydantic` 校验，校验失败重试 1 次。

#### 步骤 1~12：写死的发布流程（参考原 PRD 5.2，重新落到代码动作）
```
1. device.launch_app("com.xingin.xhs")
   verify: current_package == "com.xingin.xhs"

2. find(text="+", position="bottom_center", vlm_hint="底部红色加号")
   tap_element
   verify: find(text="写文字") 不为 None

3. tap_element(find(text="写文字"))
   verify: 进入文字编辑页（找到"标题"占位符）

4. find(text_contains="标题") → tap_element → type_text(title)
   find(text="下一步") → tap_element
   wait 2s

5. find(text="下一步") → tap_element  # 默认模板，跳过模板选择

6. # 进入正文编辑页
   find(text_contains="标题") → tap_element → type_text(title) （二次输入，原模板要求）
   find(text_contains="正文") → tap_element → type_text(body)

7. # 加标签——关键风险点
   # 7.1 强制把光标移到正文末尾：再次 tap 正文区域 + 按 END 键 + 输入 "\n"
   # 7.2 循环 len(tags) 次：
   #     type_text("#")
   #     wait 1.5s
   #     找弹出的推荐列表里第一个 → tap_element
   #     ⚠️ 严禁直接 type_text(tag_name)，会被识别为普通文字而非话题

8. find(text="发布") → tap_element
   wait 3s

9. # 业务验证
   ocr_screen() 包含 ["发布成功","已发布","成功"] 任一 → True

10. device.clear_recent_apps()  # 见 6.4
11. device.press_key("HOME")
12. assert device.is_on_launcher()
```

#### 完成标准（写死在 skill 里，不可被 prompt 改）
```python
def verify_done(self, device) -> bool:
    return all([
        self.business_verified,         # 步骤 9 已确认
        self.recent_cleared,            # 步骤 10 内部已确认
        device.is_on_launcher(),        # 步骤 12 再确认
    ])
```

---

## 8. L4 Agent 层（LangGraph）

### 8.1 状态
```python
class AgentState(TypedDict):
    messages: list[BaseMessage]        # 会话历史（短期）
    user_facts: dict                   # 从记忆层加载
    intent: Literal["chat","call_skill","cancel"] | None
    skill_call: dict | None            # {name, args}
    skill_result: SkillResult | None
    cancel_requested: bool
```

### 8.2 节点
1. `load_context`：从 SQLite 拿近 20 轮会话 + user_facts + skill_descriptions。
2. `route`：调 Kimi，输出 JSON `{intent, skill_call?}`。
3. `chat_reply`：纯聊天分支，直接回复。
4. `run_skill`：执行技能，期间每步把截图 push 到 UI（通过队列）。
5. `summarize`：把结果写回 messages + 写 tasks 表。
6. `cancel_handler`：监听到 cancel_requested，向 device 发 cancel token，等清理完成再回。

### 8.3 边
```
START → load_context → route
        route --intent=chat--> chat_reply → summarize → END
        route --intent=call_skill--> run_skill → summarize → END
        route --intent=cancel--> cancel_handler → END
```

### 8.4 LLM 接入
- 单一 client 类 `KimiClient`，封装：
  - `chat(messages, json_mode=False) -> str`
  - `chat_with_image(messages, image_path) -> str`（VLM 兜底用）
- 重试：`tenacity`，最多 3 次，指数退避，不重试 4xx。
- 超时：单次 60s。
- 全部带 `temperature=0.3`，路由判断用 `temperature=0`。

---

## 9. L5 对话层（Gradio）

### 9.1 界面布局
```
┌─────────────────────────────┬─────────────────────────┐
│                             │                         │
│  Chatbot（消息流）           │  当前手机截图（实时）    │
│                             │                         │
│  - 用户消息                  │  ┌───────────────────┐ │
│  - Agent 回复                │  │                   │ │
│  - 带 thumbnail 的截图       │  │   step_07.png    │ │
│                             │  │                   │ │
│  ┌───────────────────────┐  │  └───────────────────┘ │
│  │ 输入框…              │  │                         │
│  └───────────────────────┘  │  [停止] [清后台] [回桌面]│
│  [发送]                     │                         │
└─────────────────────────────┴─────────────────────────┘
```

### 9.2 关键交互
- 流式：技能执行的每步把"步骤 k：xxx"以 system 消息形式插入聊天流。
- 截图：技能执行时通过 `gr.Image` 组件 + queue 推流，每步刷新右侧。
- 取消：右下角红色【停止】按钮 → 设置 cancel_token → Agent 走 cancel 路径。
- 应急按钮：【清后台】【回桌面】绕过 Agent 直接调 L2，给用户兜底。

### 9.3 启动
```powershell
.\.venv\Scripts\Activate.ps1
python -m mobile_agent.app   # 默认 http://localhost:7860
```

---

## 10. 记忆层（SQLite）

### 10.1 表结构
```sql
-- 1. 会话历史
CREATE TABLE conversations (
  id INTEGER PRIMARY KEY,
  ts DATETIME DEFAULT CURRENT_TIMESTAMP,
  role TEXT,           -- user/assistant/system
  content TEXT,
  task_id TEXT NULL    -- 关联到具体任务
);

-- 2. 任务记录
CREATE TABLE tasks (
  id TEXT PRIMARY KEY,         -- uuid
  ts_start DATETIME,
  ts_end DATETIME NULL,
  skill TEXT,
  args_json TEXT,
  status TEXT,                 -- running/success/failed/cancelled
  summary TEXT NULL,
  artifacts_dir TEXT           -- runs/<task_id>/
);

-- 3. 用户事实（长期偏好、固定主题方向等）
CREATE TABLE facts (
  id INTEGER PRIMARY KEY,
  ts DATETIME DEFAULT CURRENT_TIMESTAMP,
  key TEXT UNIQUE,             -- "default_theme" / "post_style" / "account_id"
  value TEXT,
  source TEXT                  -- "user_explicit" / "agent_inferred"
);

-- 4. 技能元数据（启动时同步）
CREATE TABLE skills (
  name TEXT PRIMARY KEY,
  description TEXT,
  args_schema_json TEXT,
  enabled INTEGER DEFAULT 1
);
```

### 10.2 记忆使用规则
- **短期**：每轮对话取最近 20 条 conversations 注入 prompt。
- **事实抽取**：每次对话结束后，让 LLM 用一段固定 prompt 判断"是否有可写入 facts 的稳定事实"，有则 upsert。
- **任务回溯**：用户问"上一条发的什么"，从 tasks 表查最近一条 success 的，把 summary + 末尾截图返回。
- **不存敏感数据**：API key、登录凭证等绝不进数据库。

---

## 11. 防炸机制落地清单（对齐原 PRD 10 条）

| # | 原机制 | 本系统落点 | 强制级 |
|---|---|---|---|
| 1 | 标准指令模板 | `skills/publish_xhs_text_note.py` 的 12 步写死在代码里，**不暴露给 LLM 修改** | P0 |
| 2 | OCR 失败重试 | `Device.find` 三级策略，每级失败 wait 1.5~2s 重新截图 | P1 |
| 3 | 强制等待 | `Device` 内部装饰器 `@enforce_wait(...)`，常量在 `constants.py`，禁止覆盖 | P1 |
| 4 | 三步完成验证 | `publish_xhs_text_note.verify_done()` | P0 |
| 5 | 单设备互斥锁 | `DeviceLock` 进程内单例 + 10 分钟超时 | P0 |
| 6 | 原子任务拆解 | "5 条笔记"在 Agent 层拆成 5 次 skill 调用串行，前一个 success 才发下一个 | P0 |
| 7 | 双向取消 | `cancel_token` 透传到 `Device`；每个动作执行前检查 `if token.cancelled: cleanup(); raise Cancelled` | P1 |
| 8 | 精确字符串编辑 | 不适用（这是开发工具问题，不是手机操作问题）。仅作为开发规范写入 README | — |
| 9 | 大文件分页 | 不适用 | — |
| 10 | 失败终止兜底 | `MAX_STEP_RETRY=3` / `MAX_TASK_RETRY=1`，写在 `constants.py`；超限 → cleanup → raise → Agent 层捕获 → 写 failed 任务 → UI 报失败 | P0 |

---

## 12. 项目结构

```
agent-moible/
├── prd/
│   ├── 手机操作Agent系统PRD.md            （参考）
│   ├── 手机操作Agent防炸机制PRD.md        （参考）
│   └── 手机Agent实现版PRD.md              （本文档，唯一标准）
├── mobile_agent/
│   ├── __init__.py
│   ├── app.py                  # Gradio 入口
│   ├── constants.py            # 等待时间/重试上限/超时（写死）
│   ├── config.py               # 读 .env
│   ├── llm/
│   │   ├── kimi_client.py
│   │   └── prompts/
│   │       ├── router.md
│   │       ├── xhs_content.md
│   │       └── fact_extract.md
│   ├── device/
│   │   ├── device.py           # Device 主类
│   │   ├── ocr.py              # PaddleOCR 封装
│   │   ├── vlm_finder.py       # VLM 兜底
│   │   ├── adb_keyboard.py     # 中文输入
│   │   ├── lock.py             # DeviceLock
│   │   └── ui_tree.py          # uiautomator2 selector wrapper
│   ├── skills/
│   │   ├── __init__.py         # SkillRegistry
│   │   ├── base.py
│   │   └── publish_xhs_text_note.py
│   ├── agent/
│   │   ├── graph.py            # LangGraph
│   │   ├── state.py
│   │   └── nodes.py
│   ├── memory/
│   │   ├── db.py               # SQLite
│   │   └── facts.py
│   └── utils/
│       ├── logger.py
│       └── cancel.py
├── scripts/
│   ├── check_device.py         # 环境自检
│   ├── verify_kimi_model.py    # M0 必跑：确认 Kimi 模型 ID
│   ├── install_adbkeyboard.ps1 # Windows PowerShell（主用）
│   ├── install_adbkeyboard.sh  # Mac/Linux 备用（开发者本机调试用）
│   └── manual_repl.py          # 不走 Agent，直接命令行调 Device 调试
├── runs/                       # 任务截图与日志（.gitignore）
├── data/
│   └── memory.db               # SQLite（.gitignore）
├── tests/
│   ├── test_device_smoke.py    # 真机冒烟
│   └── test_skill_xhs.py
├── .env.example
├── requirements.txt
├── README.md
└── .gitignore
```

---

## 13. 阶段化交付（5 个 milestone）

每个 milestone 都有"完成 = 可演示"的标准。

### M0：环境验证（0.5 天，Windows）
- [ ] Windows 装好 platform-tools，`adb` 在 PATH 中，`adb version` 输出版本号
- [ ] 装好对应品牌 USB 驱动，`adb devices` 看到真机且非 unauthorized
- [ ] Python 3.10+ 已装且 `python --version` 正常
- [ ] `python -m venv .venv` + `.\.venv\Scripts\Activate.ps1` 可用
- [ ] 手机装好 ADBKeyboard 并启用
- [ ] `python -m uiautomator2 init` 通过
- [ ] `python scripts\verify_kimi_model.py` 跑通，确认可用模型 ID + 视觉是否可用
- **演示**：`python scripts\check_device.py` 全绿 + Kimi 文本/视觉各回一句话

### M1：Device 层打通（1.5 天）
- [ ] Device 12 个接口实现完毕
- [ ] `manual_repl.py` 能交互式：截图、找元素、点击、输入中文
- [ ] 清后台流程在你的手机型号上跑通（可能需要按机型微调坐标比例）
- [ ] 设备锁单元测试通过
- **演示**：在 REPL 里一行行执行打开小红书 → 点 + 号 → 回桌面，全过程稳定

### M2：小红书技能（2 天）
- [ ] 内容生成：Kimi 输出合规 JSON 的成功率 ≥ 95%
- [ ] 12 步发布流程串通，**先用预填的 title/body/tags 跑**
- [ ] 标签步骤的"光标定位 + # 触发推荐 + 选第一个"能稳定不覆盖正文
- [ ] 三步完成验证生效
- **演示**：`python -m mobile_agent.skills.publish_xhs_text_note --title=xx --body=xx --tags=a,b,c` 直接发出去

### M3：Agent 编排（1 天）
- [ ] LangGraph 5 节点连通
- [ ] 路由准确率：10 条样本（5 闲聊 + 5 发笔记）≥ 9/10
- [ ] cancel 5s 内停下
- **演示**：CLI 模式 `python -m mobile_agent.agent.cli`，自然语言驱动一次完整发布

### M4：对话 UI（1 天）
- [ ] Gradio 双栏布局
- [ ] 截图实时刷新
- [ ] 停止 / 清后台 / 回桌面 三个应急按钮工作
- **演示**：浏览器打开 7860，全流程鼠标操作完成发布

### M5：记忆 + 收尾（1 天）
- [ ] 4 张 SQLite 表 + 读写
- [ ] 用户事实抽取至少能记住"默认主题方向"
- [ ] 任务表能查"上一条发了什么"
- [ ] README 写完、`.env.example` 给齐
- **演示**：第二天打开重新跑，Agent 仍能记得你上次设的主题方向

**总计 ≈ 6 天**（不含真机调试中遇到的机型适配抖动；预留 +30%）。

---

## 14. 验收用例（用户体验级）

### UC-1：首次跑通
```
用户：你好
Agent：你好 CC，我是手机操作助理。我现在能帮你在小红书发文字笔记。
       要发的话，告诉我主题方向就行。

用户：用"独居老人陪伴"主题发一条
Agent：好。我来生成内容并发布，过程大约 3~5 分钟。
       [系统消息] 步骤 1/12：打开小红书... [截图]
       [系统消息] 步骤 2/12：点击 + 号... [截图]
       ...
       [系统消息] 步骤 9/12：检测到"发布成功"... [截图]
       [系统消息] 已清理后台、返回桌面
Agent：✅ 已发布。
       标题：《独居的妈妈，需要的不只是一日三餐》
       正文：...（前 50 字）
       标签：#独居老人 #银发关怀 #陪伴
       耗时：3 分 42 秒
```

### UC-2：中途取消
```
用户：再发一条，主题"老人助听器选购"
Agent：好的，开始...
       [步骤 3/12 进行中]
用户：停
Agent：[5s 内] 已停止。手机已清理后台并返回桌面。
       本次任务标记为 cancelled。
```

### UC-3：失败兜底
```
（小红书弹了个版本更新弹窗，找不到 + 号）
Agent：[步骤 2/12 重试 3 次失败]
       任务失败：未找到底部"+"按钮（可能是版本更新弹窗遮挡）。
       已清理后台并返回桌面。建议你手动检查后再让我重试。
```

### UC-4：记忆生效
```
（第二天）
用户：再发一条
Agent：用上次的"独居老人陪伴"方向吗？还是换一个？
用户：用上次的
Agent：好，开始...
```

---

## 15. 风险与未尽事项

### 15.1 已知风险
| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| Kimi `kimi-m2.6` 不存在或不带视觉 | 中 | 高 | M0 第一步验证；准备 fallback 模型名 |
| 小红书版本更新导致 UI 树变化 | 高 | 高 | 元素查找用文本/content-desc 而非 resource-id；OCR + VLM 兜底 |
| 小红书反自动化检测触发限流 | 中 | 高 | 注入随机延迟、随机滑动微抖；MVP 不追求拟人，封号自负（用户已确认） |
| 标签推荐不弹出 | 中 | 中 | 单个标签最多重试 2 次；2 次失败则跳过该标签继续 |
| 手机型号差异（清后台手势） | 高 | 中 | 把清后台拆成"原生 Android" / "MIUI" / "EMUI" 三套，启动时让用户选 |
| ADBKeyboard 在某些定制 ROM 输入异常 | 中 | 中 | 兜底走剪贴板粘贴 |
| atx-agent 在长任务中崩溃 | 低 | 中 | Device 层装心跳，断了自动重连一次 |
| 用户取消时手机正在长按 | 低 | 低 | cancel 检查粒度=每个 action 之前 |
| **Windows USB 驱动缺失/不兼容** | 高 | 高 | M0 第一项就装好；准备 Universal ADB Driver 兜底 |
| **PowerShell 中文乱码** | 中 | 低 | `.env` 设 PYTHONUTF8=1；推荐 Windows Terminal |
| **Windows 路径含中文/空格** | 中 | 中 | 项目放在 `C:\dev\agent-moible\` 这类纯英文短路径下 |
| **PaddleOCR 在 Windows 安装失败** | 中 | 中 | 需要 VC++ 运行库；失败则降级到 EasyOCR；或第一版纯靠 UI 树 + VLM 不开 OCR |
| **杀软拦截 adb.exe / 截图传输** | 中 | 中 | 项目根目录加白名单 |
| **USB 线只供电不传数据** | 中 | 高 | 提示 CC 换原装数据线或确保线材支持数据传输 |

### 15.2 v2 路线（不在本次范围）
- 多设备并发 + 设备池 + redis 锁
- 抖音 / 微信 / 浏览器技能扩展
- 拟人轨迹与反检测
- 自动登录（接打码平台）
- 向量化记忆（Chroma）+ 跨任务复用
- Web 版手机控制（adb over WiFi 暴露在内网）
- 任务编排 DAG（"先发小红书再转抖音"）

---

## 16. 给 CC 的开工清单（Windows）

实施前你只要做这几件事：

1. **Windows PC 就绪**：Windows 10/11，留 ≥ 5GB 空间，建议装 Windows Terminal。
2. **数据线 + 安卓手机**：原装 USB 数据线（充电线常常只供电，不传数据，会让 `adb devices` 看不到设备）。
3. **USB 驱动**：按手机品牌装好（小米/华为/三星 等都有自己的官方驱动）。
4. **小红书**：手机上小红书已登录、个人主页能正常打开。
5. **Python**：装 Python 3.10+，安装时勾选"Add to PATH"。
6. **项目目录**：建议放在 `C:\dev\agent-moible\`（纯英文、短路径、无空格）。
7. **Kimi**：把 API key 放在项目根的 `.env`：
   ```
   MOONSHOT_API_KEY=sk-your-moonshot-api-key-here
   MOONSHOT_BASE_URL=https://api.moonshot.cn/v1
   MODEL_NAME=kimi-m2.6   # M0 步骤 1 会验证并自动改这里
   PYTHONUTF8=1
   ```
8. **手机操作授权**：第一次连 USB 时弹的"始终允许此电脑调试"勾上。

之后所有事我（开发执行者）按本 PRD 的 milestone 顺序推。每个 milestone 结束跟你 demo 一次，确认后进下一个。

> **协作模式说明**：本 PRD 文档目前位于 Mac 上的 `~/Desktop/agent-moible/prd/`，仅作为设计契约维护。实际代码工程将在 Windows 机器上从零搭建（推荐路径 `C:\dev\agent-moible\`），通过 git 或文件传输保持 PRD 同步。

---

**文档结束**

*本 PRD 是后续编码的契约。任何对架构、技术选型、技能流程的变更都需要先更新本文档，再改代码。*
