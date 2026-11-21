# FoxGTP-Py

野狐围棋 AI 连线器 —— 官方 **FoxGTP 2.9** 的 Python 复刻实现，并在不牺牲兼容性的前提下
吸收了 SakuraGTP 的一些长处（现代界面、候选点/胜率、日志、自动恢复、自定义命令行）。

> 协议依据：《野狐围棋AI接入协议》1.05、《野狐围棋AI接入手册》2.01。

---

## 1. 它与 FoxGTP 一致的行为

| 行为 | 说明 |
|------|------|
| 核心 GTP 命令集 | 只依赖 `clear_board / boardsize / komi / time_settings / time_left / play / genmove / final_score / set_free_handicap / protocol_version`，扩展命令一律先探测再用 |
| 棋谱差异同步 | 野狐棋谱是唯一事实来源；引擎侧只记「已同步到第几手」。只需补差异；一旦分叉就 `clear_board` + 重设 + 整盘重放，**不依赖 `undo`** |
| 手数去重 | 野狐回显 AI 自己那手时不会重复 `play`；`play` 报错、手数跳变会触发重建 |
| 读秒换算 | 三种口径与 FoxGTP 一致：围棋常用读秒（N 秒 × M 次）/ 加拿大读秒（每周期 1 子）、扣除数据传输耗时、强制指定 AI 读秒时间 |
| 时间同步 | 开局 `time_settings` 一次，每手 `time_left` 一次 |
| 点目 | `final_score` → 模糊解析 → `$AFSCORE,W+350 / B+R / 0 / error` |
| 局末处理 | `$FARESULT` 后 `clear_board`，防止残局带入下一局 |
| 野狐协议 | 12 条命令全支持，含 `$AFSTATUS` 主动查询；校验和、单连接限制、断线自动重连 |

## 2. 它比 FoxGTP 多做的事（都不影响兼容性）

- **任意 GTP 命令/扩展命令**：启动时探测 `protocol_version / name / version / list_commands`
  （不支持 `list_commands` 就逐条 `known_command`），得到一个能力画像；
  `kata-*`、`lz-*`、`undo`、`stop` 等只在引擎声明支持时才会发送。
- **GTP Shell**：可以手动发送任何命令并看到完整多行响应（`kata-raw-nn` 这种也行）。
- **不回显命令号的引擎也能用**：id 匹配失败时按「先发先回」配对（FoxGTP 强制要求回显 id）。
- **候选点 / 胜率曲线**：KataGo 用 `kata-genmove_analyze` 流式读取；命令被拒绝时自动退回
  `genmove`。非 KataGo 引擎不显示（不会伪造数据）。
- **三种通信方式**：STDIO、TCP 客户端（连引擎）、TCP 服务端（等引擎连进来）。
- **自定义命令行**：可直接填 `ssh`/`plink`/`ikatago` 之类的命令（SakuraGTP 同款能力）。
- **自动恢复**：引擎异常退出/心跳超时后按固定间隔重连，重连成功后自动重建局面。
- **测试模式**：不接野狐也能在 AI 棋盘上左键落子、右键让引擎落子。
- **中英双语界面**（帮助菜单切换）。

## 3. 快速开始

```powershell
# 源码运行
python run.py
# 或者直接运行打包好的 exe
dist\FoxGTP-Py.exe
```

1. 「AI 引擎」区域选择通信方式，填引擎程序和参数，例如：

   ```
   katago.exe
   gtp -model model.bin.gz -config gtp.cfg
   ```

   点「连接」。日志里会打印识别结果：

   ```
   引擎能力: KataGo 1.13.0 [kata,kata-analyze,undo,final_score,free-handicap,time,rules,id]
   ```

2. 「野狐客户端」区域填监听端口（默认 6000），点「开始监听」。
3. 野狐客户端里填 `127.0.0.1` 和该端口，点「连接 AI」。
4. 对局开始后一切自动：同步棋谱、读秒、点目、断线恢复。

> KataGo 注意：它会在**工作目录**下创建 `gtp_logs` / `katago_ov_cache`。
> 如果程序放在不可写目录（如 Program Files），请把 `gtp.cfg` 里的 `logDir`、
> `onnxOpenVINOCacheDir` 改成绝对可写路径，或在设置里指定工作目录。

## 4. 设置项（与 FoxGTP 选项对应）

| 设置 | 对应 FoxGTP | 说明 |
|------|-------------|------|
| 使用围棋常用读秒 | UseGoByoYomi | 勾选：`time_settings s` = 读秒次数；不勾：s=1（加拿大读秒） |
| 指定数据传输耗时 | UseDataTransferTime / DataTransferTime | 从读秒时间里扣除，防止野狐超时 |
| 指定 AI 引擎读秒时间 | AICalTime | 强制指定引擎读秒，与野狐读秒无关 |
| 心跳 | UseHeartbeat / HeartbeatSeconds | `protocol_version` 保活，超时判定假死并恢复 |
| 自动重连 | 自动恢复机制 | 引擎断开后按间隔重连并重放局面 |
| maxTime / maxVisits / maxPlayouts | —（新增） | 仅 KataGo：`kata-set-param`；非 KataGo 时 maxTime 用于给读秒封顶 |
| 分析/候选点 | —（新增） | 支持 `kata-genmove_analyze` 时启用 |
| 让子方式 | —（新增） | 自动 / 自由摆放 / 固定让子 / 逐子落子 |

## 5. 代码结构

```
FoxGTP-Py/
├── run.py                    启动入口
├── app/                      GUI（PyQt5）
│   ├── main.py               应用入口（含 --selftest 打包自检）
│   ├── ui_main.py            主窗口：连接面板、通信日志、菜单、子窗口
│   ├── ui_dialogs.py         设置对话框、GTP Shell、棋盘窗口、帮助
│   ├── board_widget.py       棋盘绘制（坐标/星位/棋子/最后一手/候选点）
│   ├── winrate_widget.py     胜率曲线
│   ├── theme.py              深色主题
│   └── i18n.py               中英文案
├── foxgtp/                   与界面无关的核心
│   ├── fox_protocol.py       $FA/$AF 包：校验和、打包、解析、落子字段
│   ├── fox_server.py         TCP 服务端（等野狐连进来）
│   ├── gtp_protocol.py       GTP 行分类、坐标、结果模糊解析
│   ├── gtp_session.py        命令编号、响应匹配、多行/流式/游离响应
│   ├── transports.py         STDIO / TCP 客户端 / TCP 服务端
│   ├── engine_profile.py     能力探测
│   ├── dialect.py            命令翻译（时间/让子/规则/落子/点目）
│   ├── game_state.py         两套棋谱 + 差异同步计划
│   ├── controller.py         总控：野狐↔GTP、看门狗、心跳、恢复
│   ├── logbook.py            通信日志（时间戳、按天写文件）
│   └── config.py             配置读写（便携式 config.json）
├── tests/                    61 项单元/集成测试 + 真引擎端到端脚本
├── tools/make_icon.py        生成图标与样式箭头
└── FoxGTP-Py.spec / build.ps1  打包
```

数据流：

```
野狐客户端 --TCP--> FoxServer --$FAxxx--> Controller --GTP--> GtpSession --> Transport --> AI 引擎
                                       <--$AFxxx--           <--响应--
```

## 6. 兼容性对照

| 场景 | FoxGTP | FoxGTP-Py |
|------|--------|-----------|
| KataGo | ✅ | ✅（候选点/胜率） |
| Leela Zero / GNU Go / Fuego / Pachi | ✅ | ✅ |
| 不回显命令号的引擎 | ❌ | ✅ |
| 任意扩展命令（kata-*/lz-*） | ❌ | ✅（探测后使用） |
| 手动发任意 GTP 命令 | ✅（Shell） | ✅ |
| 非 19 路棋盘 | ✅ | ✅ |
| 断线/手数错乱恢复 | ✅（重放） | ✅（重放 + 跳变检测） |
| 引擎不支持 `final_score` | ✅ 回 error | ✅ 回 error |
| 引擎崩溃自动恢复 | ✅ | ✅ |
| 测试模式 | ✅ | ✅ |

## 7. 测试

```powershell
python -m unittest discover -s tests -v      # 61 项，秒级完成
```

真引擎端到端（需要 KataGo/Leela）：

```powershell
$env:KATAGO_EXE="C:\KataGo\katago.exe"
$env:KATAGO_MODEL="C:\KataGo\model.onnx"
$env:KATAGO_CFG="C:\KataGo\gtp.cfg"
python tests\manual_katago_e2e.py
```

它会用真实 TCP 野狐客户端驱动整个链路：`$FARULE` → `$FAMOVE` → `$AFPLAY` →
`$FASCORE` → `$AFSCORE` → `$FASKIP`，并打印引擎画像。

## 8. 打包

```powershell
.\build.ps1          # 先跑测试，再生成 dist\FoxGTP-Py.exe
```

`dist\FoxGTP-Py.exe` 是单文件、无控制台窗口，图标/箭头等资源已内嵌；
`--selftest` 参数会启动→截图→退出，用于验证打包产物。

## 9. 许可与声明

本程序与北京野狐世纪技术有限公司无隶属关系；野狐协议、GTP 协议归各自所有者。
