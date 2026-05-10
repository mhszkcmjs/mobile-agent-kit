# 手机操作 Agent

一个能聊天、有记忆、可调用技能操作真实安卓手机的本地 Agent。

**目前已交付能力（MVP）**

| 能力 | 入口 | 说明 |
|---|---|---|
| 闲聊 + 记忆 | `python -m mobile_agent.app` | 自动抽取用户偏好,跨会话记得 |
| 发小红书笔记 | 聊天："发一条 XX 主题的小红书笔记" | VLM 自主完成发布 |
| 浏览小红书 | 聊天："刷两条小红书的推送把内容给我" | VLM 阅读笔记并汇总要点 |
| 应急操作 | UI 右下角三个按钮 | 🛑 停止 / 🏠 回桌面 / 🧹 清后台 |

- 详细架构与设计契约：[`prd/手机Agent实现版PRD_副本.md`](prd/手机Agent实现版PRD_副本.md)
- 我对这个项目最终决定不再投入的复盘（第一人称、有真实细节）：[`docs/postmortem.md`](docs/postmortem.md)

---

## 一、首次部署（全新机器、全新手机）

### 1. PC 端环境（Windows 10/11）

```powershell
# Python 3.10+(python.org 装,勾选 Add to PATH)
python --version

# 装 adb(任选其一)
# A. Scoop(推荐)
irm get.scoop.sh | iex
scoop install adb
# B. 手动:从 https://dl.google.com/android/repository/platform-tools-latest-windows.zip 解压到 C:\platform-tools\,加 PATH

adb version    # 验证
```

### 2. 手机端

打开开发者模式 + USB 调试 + 安装授权:

1. 设置 → 关于本机 → 连点【版本号】7 次 → 进入【开发者选项】
2. 开发者选项里全部打开:
   - **USB 调试**
   - **USB 调试(安全设置)** ← 装 atx-agent 必须
   - **通过 USB 安装应用** ← 装 ADBKeyboard 必须
   - **指针位置**(可选,debug 时方便观察)
3. USB 数据线连 PC(原装数据线,光充电的线不行)
4. 手机弹窗"允许 USB 调试吗" → 勾选**始终允许此计算机** → 允许

### 3. 项目初始化

```powershell
# 进项目根（你 clone 后的实际目录）
cd path\to\mobile-agent

# 创建并激活 venv
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 装依赖(一次,以后开新终端只激活 venv 即可)
pip install -r requirements.txt
pip install langgraph langchain-core
```

> 如果 `Activate.ps1` 报"无法加载脚本",先执行:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

### 4. 配置 API Key（密钥放在项目目录之外）

为了让密钥永远不可能被误推到 GitHub，**推荐把 `.env` 放到用户目录下**：

```powershell
# Windows: 拷贝模板到 %USERPROFILE%\.config\mobile-agent\.env
$cfg = "$env:USERPROFILE\.config\mobile-agent"
New-Item -ItemType Directory -Force -Path $cfg | Out-Null
Copy-Item .env.example "$cfg\.env"
notepad "$cfg\.env"
```

```bash
# macOS / Linux:
mkdir -p ~/.config/mobile-agent
cp .env.example ~/.config/mobile-agent/.env
$EDITOR ~/.config/mobile-agent/.env
```

填好 `MOONSHOT_API_KEY`，模型 ID 先留默认，下一步会实测。

> 也可以通过环境变量 `MOBILE_AGENT_ENV_FILE` 指向任意位置的密钥文件；
> 或者旧用法：直接在项目根放 `.env`（已被 `.gitignore` 忽略，但不推荐，万一某天 .gitignore 被误改就泄漏）。

### 5. 验证 Kimi 模型 + 把可用模型写回 .env

```powershell
python scripts\verify_kimi_model.py
```

把脚本最后输出的"推荐写入 .env"两行（如 `MODEL_NAME=moonshot-v1-32k`、`VISION_MODEL_NAME=moonshot-v1-32k-vision-preview`）覆盖到 `.env`。

### 6. 推 atx-agent 到手机

```powershell
python -m uiautomator2 init
```

跑完最后一行没报错就 OK。

### 7. 装中文输入法 APK（ADBKeyboard）

```powershell
.\scripts\install_adbkeyboard.ps1
```

最后一行如果显示 `[WARN] set IME manually:...`,去手机:
> 设置 → 系统 → 语言和输入法 → 管理键盘 → 启用 ADBKeyboard

(发笔记时项目会自动切到 ADBKeyboard,任务结束自动切回。)

### 8. 五项自检

```powershell
python scripts\check_device.py
```

期望全 `[ OK ]`,允许两条 `[WARN]`(ADBKeyboard 未启用为 IME / 锁屏读不到包名)。
有 `[FAIL]` 不要往下走,先排查。

---

## 二、日常启动（之前连过的手机）

新开一个 PowerShell 后:

```powershell
# 1. 确认 adb 在 PATH 里。如果不在,按你机器上 platform-tools 的实际路径补一下:
#    $env:Path += ";C:\platform-tools"
# 装系统 PATH 永久生效更省事。

# 2. 激活 venv
.\.venv\Scripts\Activate.ps1

# 3. 确认设备在线
adb devices            # 应看到 xxxxxxxxx  device

# 4. 启动 Agent UI
python -m mobile_agent.app
```

浏览器自动打开 http://127.0.0.1:7860。

### 设备状态异常处理

| 现象 | 处理 |
|---|---|
| `adb devices` 没列出设备 | 拔线重插,留意手机弹窗"允许 USB 调试" |
| `unauthorized` | 手机弹窗里勾"始终允许" → 允许 |
| `offline` | `adb kill-server; adb start-server`,然后拔线重插 |
| 仍 `offline` | 手机【开发者选项 → 撤销 USB 调试授权】后重插,重新授权 |

---

## 三、UI 界面使用

启动 `python -m mobile_agent.app` 后,浏览器打开 http://127.0.0.1:7860,会看到双栏布局:

```
┌──────────────────────────────┬──────────────────────────────┐
│                              │                              │
│   左:对话                    │   右:当前手机截图(实时刷新) │
│   - 用户消息                 │                              │
│   - Agent 回复               │   ┌──────────────────┐       │
│   - "正在执行..."进度提示    │   │   step_NN.png    │       │
│                              │   │                  │       │
│  ┌────────────────────────┐  │   └──────────────────┘       │
│  │ 输入框                 │  │                              │
│  └────────────────────────┘  │  [🛑 停止] [🏠 回桌面] [🧹 清后台] │
│  [发送]    [清空对话]        │                              │
└──────────────────────────────┴──────────────────────────────┘
```

### 左栏:聊天

直接说自然语言,Agent 自动判断意图、选技能、调用。示例:

- 闲聊
  > 你好

- 触发发布技能
  > 用"独居老人陪伴"主题发一条小红书文字笔记

- 触发浏览技能
  > 帮我刷两条小红书的推送,把有用信息汇总给我

- 设定长期偏好(自动写入记忆)
  > 我以后发笔记都用温暖、口语化的风格

- 取消(任务进行中)
  > 停

### 右栏:实时手机截图

任务执行时,每一步操作完会自动刷新右侧。看模型在做什么、卡在哪一步,一目了然。

### 应急按钮(绕过 Agent 直接操作 Device)

| 按钮 | 作用 |
|---|---|
| 🛑 停止 | 设置 cancel_token,等待当前 action 结束后停止后续操作 |
| 🏠 回桌面 | 直接 press_key HOME,无视当前任务 |
| 🧹 清后台 | 走清后台流程(进多任务页 → 清除全部 → 回桌面) |

---

## 四、命令行入口（不开 UI）

| 入口 | 用途 |
|---|---|
| `python -m mobile_agent.agent.cli` | CLI 聊天模式(无截图,无应急按钮) |
| `python -m mobile_agent.skills.publish_xhs_text_note --theme=独居老人陪伴` | 跳过 Agent 直接调技能 |
| `python -m mobile_agent.skills.browse_xhs_posts --count=2` | 直接调浏览技能 |
| `python scripts\manual_repl.py` | 交互式 Device 调试(截图/点击/输入中文) |
| `python scripts\check_device.py` | 设备五项自检 |
| `python scripts\check_memory.py` | 查看 SQLite 内的会话/任务/事实/技能 |
| `python scripts\cleanup_stale_tasks.py` | 清理因中断停留在 running 状态的僵尸任务 |

---

## 五、目录结构

```
mobile_agent/
├── app.py            # L5 Gradio UI 入口
├── constants.py      # 等待时间/重试上限/包名等硬约束
├── config.py         # 读 .env
├── device/           # L2 动作层(uiautomator2 封装)
│   ├── device.py     #   Device 主类
│   ├── vlm_loop.py   #   VLM 自主动作循环(语义动作集)
│   ├── ocr.py        #   OCR 兜底(可选)
│   ├── vlm_finder.py #   VLM 坐标兜底
│   ├── adb_keyboard.py
│   ├── lock.py       #   设备互斥锁
│   └── ui_tree.py
├── skills/           # L3 技能层
│   ├── base.py
│   ├── publish_xhs_text_note.py   # 发小红书文字笔记
│   └── browse_xhs_posts.py        # 浏览小红书并汇总
├── agent/            # L4 LangGraph 编排
│   ├── graph.py
│   ├── nodes.py      #   load_context / route / chat / run_skill / cancel / summarize
│   └── cli.py
├── memory/           # SQLite 记忆
│   ├── db.py         #   conversations / tasks / facts / skills 4 张表
│   └── facts.py      #   长期事实自动抽取
├── llm/
│   ├── kimi_client.py
│   └── prompts/      #   router / xhs_content / fact_extract
└── utils/
    ├── logger.py
    └── cancel.py     #   CancelToken

scripts/              # 运维与调试脚本
runs/                 # 任务截图与日志(.gitignore)
data/                 # SQLite + 下载的 APK(.gitignore)
prd/                  # 设计文档
```

---

## 六、扩展新技能

只要在 `mobile_agent/skills/` 加一个 `.py` 文件,按下面骨架填:

```python
from pydantic import BaseModel, Field
from mobile_agent.skills.base import RunContext, SkillResult


class MyArgs(BaseModel):
    foo: str = Field(...)


class _MySkill:
    name = "my_skill"
    description = "给 Agent 路由器看的一句话简介"
    args_schema = MyArgs

    def run(self, args: MyArgs, ctx: RunContext) -> SkillResult:
        # 用 ctx.device 操作手机
        # 用 mobile_agent.device.vlm_loop.run_vlm_loop 让 VLM 自主操作
        return SkillResult(ok=True, summary="...", artifacts=[])


SKILL = _MySkill()
```

启动时 `autoload()` 会自动发现注册,Agent 路由器立刻能选到新技能,无需改任何其他代码。

---

## 七、常见问题

| 现象 | 处理 |
|---|---|
| `adb devices` 没列设备 | 数据线只供电不传数据,换原装线 |
| PowerShell 中文乱码 | `.env` 里 `PYTHONUTF8=1`,或用 Windows Terminal |
| 路径含中文/空格 → 偶发异常 | 把项目挪到 `C:\dev\agent-mobile\` 等纯英文短路径 |
| ADBKeyboard 装上但 `ime list -s` 不出现 | 手机【设置→语言和输入法→管理键盘】手动启用 |
| OPPO 手机安装 APK 失败 [-99] | 设置 → 安全 → 关闭"安装应用前验证";或登录 OPPO 账号 |
| 任务被 Ctrl+C 中断后 DB 里有 `running` 残留 | `python scripts\cleanup_stale_tasks.py` |
| Agent 路由总是回 chat 不调技能 | 用更明确的指令,比如"调用 publish_xhs_text_note 发..." |
| VLM 偶尔陷入死循环 | UI 上点 🛑 停止,把日志贴出来分析模型为什么困住 |

---

## 八、当前已知限制（v2 路线）

- **VLM 收敛性**:模型偶尔在发布成功后忘记任务结束,会重复操作。需要更严格的 done 判定。
- **取消延迟**:Gradio 停止按钮目前等当前 HTTP 请求完才能生效。改异步执行后可做到秒级响应。
- **多设备并发**:目前进程内一锁一设备,多设备需要 Redis。
- **登录/验证码**:不支持自动登录,小红书账号需提前在手机上登好。
- **图片/视频笔记**:只支持文字笔记。

---

更详细的设计契约、防炸机制清单、阶段化交付标准,请阅读 [`prd/手机Agent实现版PRD_副本.md`](prd/手机Agent实现版PRD_副本.md) 和 [`prd/手机操作Agent防炸机制PRD.md`](prd/手机操作Agent防炸机制PRD.md)。
