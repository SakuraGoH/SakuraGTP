# FoxGTP 逆向分析与 SakuraGTP 兼容性改造

> 目标：搞清楚野狐官方连线器 FoxGTP 2.9（`FoxGTP.exe`，2022-06-06，x86/MFC，765 KB）
> 到底做了什么，使它几乎能挂任何 GTP 引擎；然后把同样的机制（并且再放宽一点）
> 落到 SakuraGTP 的 GTP 层上。

本文所有结论都来自三份材料，互相印证：

1. **静态逆向**：PE 头 / 资源 / 字符串 / 反汇编（capstone），脚本在 `_re/`；
2. **官方文档**：《野狐围棋AI接入协议》1.05、《野狐围棋AI接入手册》2.01、
   《GTP2 规范》；文本提取在 `_re/pdf/`；
3. **真机验证**：改造后的桥接层直接驱动本机 KataGo 1.18.2（ONNX/OpenVINO 构建）
   走完整对局流程。

---

## 一、结论：FoxGTP 的兼容性来自 6 个决定

| # | 做法 | 证据 | 对兼容性的意义 |
|---|------|------|----------------|
| 1 | **只用 GTP v1 的 11 条核心命令**，一条扩展命令都不发 | 程序里只有下列格式串（`.rdata` 0x2997C–0x29B10）：`clear_board`、`boardsize %d`、`time_settings %d %d %d`、`komi %.1f`、`set_free_handicap %s`、`time_left %s %d %d`、`play %s %s`、`play %s pass`、`genmove %s`、`final_score`、`protocol_version`，外加 `quit`。**没有** `kata-*` / `lz-*` / `undo` / `list_commands` / `known_command` / `analyze` | 任何实现了 GTP 基本盘的引擎都能跑：KataGo、Leela Zero、GNU Go、Fuego、Pachi、SAI、AQ…… |
| 2 | **不用 `undo`，用「清盘 + 重放」恢复局面** | 同步函数 0x40C210：比较两份棋谱，前缀相同就只补差异；一旦分叉就 `clear_board` + 重设棋盘 + 整盘重放（设置批 0x40BDF0）。全程序没有 `undo` 字符串 | `undo` 是各家实现差异最大、最容易出错的命令。绕开它，断线重连、引擎重启、手数错乱都能恢复 |
| 3 | **野狐棋谱是唯一事实来源，引擎侧维护一份「已同步到第几手」** | 队列处理器 0x40C3A0 的 type=7（`play`）分支：`if (记录里的手数 > 引擎已同步手数) 才发送，否则直接丢弃` | 天然幂等：重复通知、回声、重连补发都不会重复落子；也避免「引擎算完一手后又被 play 一次」 |
| 4 | **开局只发一次时间设置，之后每手同步剩余时间** | 设置批里带 `time_settings`；手册 4.4 与更新日志 1.9「每步同步剩余读秒次数」 | 慢引擎也不会因为时间信息过期而乱用时间；同时把「野狐读秒 N 秒×M 次」翻译成引擎认的口径（加拿大读秒 vs 常用读秒） |
| 5 | **响应解析只看行首标记，正文按最宽松的方式理解** | 解析器 0x401500：`line[0]` 必须是 `=` 或 `?`；正文里的 `=`/`?` 不参与切分（更新日志 2.3 专门修过这个 bug） | 引擎一边算一边往 stdout 打日志/胜率时不会把响应切错 |
| 6 | **结果字符串做模糊识别** | 落子 0x4016E0：`strncmp(s,"pass",4)`、`strncmp(s,"resign",6)`，其余按 GTP 坐标解析（0x401A30：字母大小写都收、`atoi` 取行号、跳过 `I`）。点目 0x401770：找 `+`，用 `strstr` 在胜方字段里找 `w/white/b/black`，目数 ×100 | 各家 `final_score` 返回 `B+3.5`/`W+R`/`Draw`/`White wins by…` 都能收；`pass`/`PASS`/`passing` 也都能收 |

**一句话**：FoxGTP 的兼容性不是靠「适配每个引擎」，而是靠**把 GTP 用到最小公约数、
把状态恢复做成不需要引擎配合的重放、把输入输出都当成不可信文本来解析**。

### 但它有三处硬伤（我们的改造重点）

| 硬伤 | 证据 | 后果 |
|------|------|------|
| **强制要求引擎回显命令号** | 解析器 0x401500 要求 `=` 后紧跟数字，`= Q16` 直接判为非法；手册 4.1 明文要求「AI 引擎必须支持带有 id 格式的 GTP 命令且返回数据中必须携带命令 id」 | 不回显 id 的引擎（部分 GNU Go 构建、老版 Pachi/Aya/Many Faces、各种自研引擎）直接不工作 |
| **状态是全局单例 + 单线程假设** | 全局变量 0x437F34/0x437F58/0x437ED4 等，命令队列按 id 严格匹配，匹配不上就丢弃 | 一旦 id 对不上（引擎漏回、异步输出）就永久错位，只能重连 |
| **点目只认 `final_score`** | 没有 `final_score` 就按协议回 `error` | 对不实现 `final_score` 的引擎，野狐「申请点目」永远失败 |

---

## 二、逆向过程与关键证据

### 2.1 二进制概况

```
FoxGTP.exe  PE32 i386, 5 sections, MFC 100 (动态链接 mfc100u.dll / msvcr100.dll)
.rsrc 522 KB：PNG 图标 + 对话框 + 字符串表（UI 中英双语）
PDB: D:\FOXCODE_ZWF(20141008)\client\SlnOther\Release\FoxGTP.pdb
导入：WS2_32（socket）、CreateProcessW/CreatePipe（STDIO 挂引擎）、
      RegQueryValueW（配置存注册表 HKCU\…\FoxGTP）、gdiplus（棋盘绘制）
```

注册表配置键（字符串表 `.rdata` 0x2854–0x29CC）：
`WorkMode`、`AIChannel`、`AIEngineExePath`、`AIEngineExeCmdLine`、`AIEngineIP`、
`AIEnginePort`、`FoxGTPPort`、`FoxAIPort`、`UseHeartbeat`、`HeartbeatSeconds`、
`UseGoByoYomi`、`UseDataTransferTime`、`DataTransferTime`、`AICalTime`。

### 2.2 GTP 客户端：命令、编号、发送

发送函数族 0x4028E0–0x4031FF，每个函数都是同一个模板：

```c
n = snprintf(buf, 0x80, id > 0 ? "%d boardsize %d" : "boardsize %d", id, size);
send(buf, strlen(buf));          // 0x4027A0：日志 → 写管道/socket → 入命令队列
```

对应关系（枚举值在队列处理器 0x40C3A0 的跳转表里）：

| type | 命令 | 格式串 |
|------|------|--------|
| 1 | clear_board | `%d clear_board` |
| 2 | boardsize | `%d boardsize %d` |
| 3 | time_settings | `%d time_settings %d %d %d` |
| 4 | komi | `%d komi %.1f` |
| 5 | set_free_handicap | `%d set_free_handicap %s` |
| 6 | time_left | `%d time_left %s %d %d` |
| 7 | play | `%d play %s %s` |
| 8 | play pass | `%d play %s pass` |
| 9 | genmove | `%d genmove %s` |
| 10 | final_score | `%d final_score` |
| 11 | protocol_version | `%d protocol_version` |
| — | quit | `quit`（不带 id） |

注意 `komi %.1f`：FoxGTP 只保留一位小数，`6.75` 会被降级成 `6.8`。我们没照抄这一条。

### 2.3 响应解析器（0x401500）

反汇编还原出的判定顺序：

1. 长度必须 > 1，首字符必须是 `=` 或 `?`；
2. **第二个字符不能是空格**、不能是换行，必须是 `0`–`9`（即 `=1 xxx`）；
3. 用 `atoi` 取 id；正文 = 第一个空格之后的部分；
4. 没有 id 的 `= Q16` 直接被判非法，整行丢弃。

这就是它「只能挂会回显 id 的引擎」的根源，也是我们第一个要放宽的地方。

### 2.4 落子/点目的模糊解析

* 0x4016E0：`strncmp(s,"pass",4)==0` → pass；`strncmp(s,"resign",6)==0` → resign；
  否则走 0x401A30 解析坐标。
* 0x401A30：首字母 `a-z` → 转大写；`atoi(&s[1])` 取行号；列号 `c>='J' ? c-'B' : c-'A'`
  （即跳过字母 `I`）；行号 `y = boardSize - row`。
* 0x401990（反向）：`%c%d`，`x>7` 时字母 `+0x42`（跳 `I`），行号 `size - y`。
* 0x401770（`final_score`）：`find('+')`，胜方 = 前半段 `strstr` 里找 `w/white/b/black`，
  目数 = `atof(后半段) * 100`，转成野狐的 `W+350` 口径。

### 2.5 同步算法（0x40C210 —— 整套兼容性的核心）

```
sync(foxMoves):
    if 引擎未就绪: return
    r = compare(engineMoves, foxMoves)
    if r == 1:  return                       # 完全一致
    if r == 0:                               # 分叉
        resetBoard()                         # 清空引擎侧棋谱 & 队列
        setupBatch()                         # clear_board/boardsize/komi/time_settings/让子
        for m in foxMoves: play(m)           # 整盘重放
    if r == 2:                               # 引擎是野狐的前缀
        for m in foxMoves[len(engineMoves):]: play(m)   # 只补差异
```

`setupBatch()`（0x40BDF0）的顺序固定：
`clear_board → boardsize → komi → time_settings → set_free_handicap`。

队列处理器里对 `play` 还有一道保险：记录里带手数，**手数 ≤ 引擎已同步手数就跳过**，
所以重复通知和回声不会造成重复落子。

### 2.6 野狐协议侧

* 12 条命令的字符串表在 0x43060C–0x430680，类型 1–12，分发器 0x41AAB0：
  `$FARULE`(1) / `$FASTATUS`(2) / `$FATIMELEFT`(3) / `$FAMOVE`(4) / `$FASKIP`(5) /
  `$FARESULT`(6) / `$FASCORE`(7) / `$AFPLAY`(8) / `$AFSTATUS`(9) / `$AFSKIP`(10) /
  `$AFGIVEUP`(11) / `$AFSCORE`(12)。
* `$FARULE` 处理（0x41ADA0）只做记录：棋盘、保留时间、读秒时间、读秒次数、贴目(×100)、
  让子坐标列表，**不立即下发命令**；真正下发发生在随后的 `$FASTATUS`/`$FAMOVE` 触发同步时。
* `$FAMOVE`（0x41B830）只做两件事：记 AI 颜色、把手数/坐标/颜色追加进野狐棋谱。
* 打包函数 0x427C50 生成 `$CMD,item,…*hh\r\n`（异或校验，不含 `$` 和 `*`），
  与《野狐围棋AI接入协议》3.1 节完全一致。

### 2.7 更新日志（`.rdata` 0x42CA–0x5382）里自己写下的兼容性补丁

| 版本 | 原文 | 含义 |
|------|------|------|
| 1.7 | Use protocol_version command as a heartbeat packet | TCP 保活 |
| 1.8/1.9 | Add the Byo yomi rules commonly used in Go, not Canadian…；Each step synchronizes the remaining byo yomi times | 读秒口径换算 + 每手同步 |
| 2.1 | Increase the processing of returning prefix characters. For example, LeelaZero returns the prefix `Leela:` | 响应前缀剥离 |
| 2.2 | Increase the specified data transmission time option… | 从读秒里扣除传输耗时，防野狐超时 |
| 2.3 | Modify the problem that the unpacking error is caused by the calculation process data containing `=` or `?` | 解析只看行首标记 |
| 2.6 | At the end of the game, send the command clear_board | 局末清盘，防止残局带入下一局 |
| 2.8 | Modify the problem that final_score returns a draw parsing error | 和棋解析 |

---

## 三、SakuraGTP 原来的问题

改造前的 `gtp_bridge.py` 是**按 KataGo 写死**的：

1. 一步到位的 `kata-genmove_analyze`：非 KataGo 引擎直接报 `unknown command`，
   然后这次 `genmove` 就永远没有结果（野狐只能等超时）。
2. `kata-set-param maxTime/maxVisits/maxPlayouts`：非 KataGo 引擎报错；
   `set_rules` 也是无条件发 `kata-set-rules`。
3. 落子同步是「只发增量、从不校验」：断线重连、手数跳变、引擎重启后必然错位，
   而且没有恢复手段（不发 `clear_board`、不重放）。
4. 坐标换算写死 19 路（`_xy_to_gtp` 里 `19 - y`）。
5. `time_settings` 只在开局发一次，`time_left` 发固定 `999999 0`；
   野狐的读秒次数被当石头数发出去。
6. `final_score` 失败时没有按协议回 `error`，而是把引擎的报错文本当结果发回去。
7. 响应解析只认 `=id`、`= `、裸 `play X` 三种正则，前缀、多行、`?` 错误都没有统一处理。

---

## 四、改造方案

新增两个模块，`gtp_bridge.py` 重写：

```
gtp_session.py   会话层：命令编号、响应匹配（id / FIFO 双模）、多行累积、
                 analyze 流的 ack 与裸落子行、游离响应丢弃
gtp_dialect.py   方言层：能力探测（protocol_version/name/list_commands/known_command）
                 + 命令翻译（时间、让子、规则、genmove、点目）
gtp_bridge.py    业务层：野狐协议 ↔ GTP，两套棋谱 + 差异同步 + 看门狗
```

### 4.1 会话层：把「不可信文本」吃干净

* 三种响应风格都认：

  | 形态 | 例子 | 来源 |
  |------|------|------|
  | 带 id | `=7 Q16` | GTP 规范 / KataGo / GNU Go |
  | 不带 id | `= Q16` | Leela Zero、部分老引擎 |
  | 裸行 | `play Q16` | KataGo 的 analyze 类命令最终行 |

* 引擎不回显 id 时按「先发先回」匹配（FoxGTP 做不到）；
* 数字正文与命令号的歧义处理：只有当「数字后面还有内容」或「该命令本来就返回空正文」
  时才认作 id（否则 `protocol_version` 返回的 `2` 会被误认为 id=2）；
* 引擎名前缀剥离：`Leela: Q16` → `Q16`（FoxGTP 2.1 的补丁，我们做了通用化）；
* `info …` / `play …` 等中间行单独走流处理，不会把 `=`/`?` 切错；
* 放弃的命令（如思考中开新局）记账，后续没有 id 的游离响应直接丢弃，
  避免 FIFO 错配。

### 4.2 方言层：探测后再决定发什么

```
protocol_version → name → list_commands → (失败则 known_command 逐条问)
```

得到 `EngineProfile`：`family`（katago/leela/gnugo/fuego/pachi/unknown）、
`echoes_id`、`kata`、`kata_analyze`、`undo`、`final_score`、`set_free_handicap`、
`time_settings`、`stop`……

命令翻译规则：

| 需求 | KataGo | 其他引擎 | 再退一步 |
|------|--------|----------|----------|
| 规则 | `kata-set-rules chinese` | 不发（记日志） | — |
| 让子 | `set_free_handicap D16 Q4 D4` | 同左 | `play B D16` 逐子 |
| 读秒 | `time_settings`/`time_left` | 同左 | 不发 |
| 落子 | `kata-genmove_analyze B interval 50 maxmoves 12` | `genmove B` | 命令报错后自动退回 `genmove` |
| 点目 | `final_score` | 同左 | 回 `$AFSCORE,…,error`（协议允许） |

读秒换算（对齐 FoxGTP 手册 4.4.1 / 4.4.2）：

```
byo = 指定 AI 读秒时间            (勾选 specify_ai_byoyomi 时)
    | 野狐读秒 - 数据传输耗时      (勾选 use_data_transfer_time 时)
    | 野狐读秒
stones = 读秒次数   (勾选 use_common_byo_yomi，围棋常用读秒)
       | 1          (默认，折算成加拿大读秒)
非 KataGo 且设置了 maxTime 时：byo = min(byo, ceil(maxTime))   # 防超时
```

### 4.3 业务层：照抄 FoxGTP 的同步模型并补强

* 维护两份棋谱：`_events`（野狐）与 `_engine_events`（引擎），元素是 `(颜色, 顶点)`，
  pass 也进序列；
* `_sync_engine()`：公共前缀 → 只补差异；分叉 → `clear_board` + 完整设置 + 整盘重放；
  任何 `play` 报错、手数跳变 → 标记 dirty，下次同步自动重建；
* **genmove 结果同时记入两份棋谱**：引擎 `genmove` 已经把这一手落在自己盘面上了，
  所以野狐回声回来时不能再 `play` 一次（这是 FoxGTP 队列里「手数 ≤ 已同步就跳过」的同款逻辑）；
* 时间：开局 `time_settings`，每手 `time_left`（含读秒口径换算）；
* 点目：`final_score` → 模糊解析 → `$AFSCORE,对手?,W+1350`；
* 看门狗：`maxTime + 25s` 没回 → `stop`（引擎支持时）→ 重试用最保守的 `genmove`
  → 仍失败才 `$AFSKIP`（停一手总比野狐超时判负好）；
* 局末：`$FARESULT` 后 `clear_board`（FoxGTP 2.6 的做法）；
* 引擎重启/开新局：重置会话，清掉可能还在引擎肚子里的旧命令。

### 4.4 兼容性对照

| 场景 | 改造前 | FoxGTP | 改造后 |
|------|--------|--------|--------|
| KataGo | ✅ | ✅ | ✅（保留候选点/胜率） |
| Leela Zero | ❌ unknown command | ✅ | ✅（不回显 id 也行） |
| GNU Go / Fuego / Pachi | ❌ | ✅ | ✅ |
| 不回显 id 的引擎 | ❌ | ❌ | ✅ |
| 非 19 路棋盘 | ❌ 坐标写死 | ✅ | ✅ |
| 断线重连 / 手数错乱 | ❌ 无法恢复 | ✅ 重放 | ✅ 重放（并检测跳变） |
| 引擎 think 中途开新局 | ❌ 命令错位 | ⚠️ | ✅ 丢弃游离响应 |
| `final_score` 不支持 | ❌ 回垃圾 | ✅ 回 error | ✅ 回 error |
| `kata-*` 报错的引擎 | ❌ 卡死 | ✅ | ✅ 自动退回 `genmove` |
| genmove 无响应 | ❌ 永远等 | ⚠️ 依赖野狐重连 | ✅ stop + 重试 + 停一手 |
| 6.75 贴目 | ✅ | ❌ 变 6.8 | ✅ 原样 |

---

## 五、验证

### 5.1 单元测试（26 项全绿）

```powershell
python -m unittest discover -s tests -v
```

`tests/mock_engine.py` 模拟三种方言：KataGo（回显 id、analyze 先 ack 再流式）、
Leela Zero（不回显 id、带 `Leela:` 前缀、无 `final_score`）、GNU Go（回显 id、
只有核心 GTP）。覆盖：

* 开局命令与贴目格式、两种读秒口径；
* 让子：`set_free_handicap` 之后 `$FASTATUS` 里的让子不能被重复 `play`；
* 行棋：对手落子 → `play` + `genmove`；AI 落子 → `$AFPLAY`（手数/坐标）；
* 回声去重（AI 自己那手不能被重复下）；
* pass / resign；
* `kata-genmove_analyze` 被拒绝 → 自动退回 `genmove`；
* 两次 genmove 失败 → `$AFSKIP`；
* 点目翻译（`B+3.5` → `B+350`）、不支持的引擎回 `error`；
* 断线重连：分叉 → 整盘重建；仅落后 → 只补差异；**全程不发 `undo`**；
* 9 路坐标往返；
* 候选点解析（KataGo 0–1 与 Leela 1/10000 两种胜率口径）；
* 纯解析单测（`parse_genmove` / `parse_score` / `komi` 格式）。

### 5.2 真机冒烟（KataGo 1.18.2 ONNX/OpenVINO，CPU provider）

```
[probe] ready = True | KataGo 2(katago) [kata,kata-analyze,lz-analyze,undo,
                                     final_score,free-handicap,time,id回显]
GTP发送: 5 clear_board / 6 boardsize 19 / 7 komi 6.5 / 8 time_settings 60 30 1
GTP发送: 9 play W D16
GTP发送: 10 time_left B 60 30 / 11 kata-set-param maxTime 5.00 / 13 kata-genmove_analyze B …
[genmove] 7.3s [('AFPLAY', ('B', '2^15^15^B'))]
[candidates] 7 ['Q4','Q16','D4','R4','Q3','R16']
[candidate sample] {'vertex': 'Q4', 'visits': 5, 'winrate': 0.011, 'score': -12.81}
GTP发送: 19 final_score → 点目结果: 'W+13.5' -> W+1350
[rebuild] events = [('W','Q4'),('B','D16'),('W','Q16')] | engine 同步一致
```

（该机器无 Intel GPU/NPU，配置里的 OpenVINO GPU/NPU 会卡死，冒烟时用
`-override-config onnxProvider=cpu` 强制 CPU，所以 `final_score` 用了 34.7 秒；
这属于硬件与权重规模问题，不是协议层问题。）

---

## 六、使用与配置

新增/生效的配置项都在 `sakura_config.json`（与 FoxGTP 的选项一一对应）：

| 键 | 默认 | 说明 |
|----|------|------|
| `use_common_byo_yomi` | `false` | `true` = 读秒按「N 秒 × M 次」（围棋常用）；`false` = 折算成加拿大读秒（每周期 1 子） |
| `data_transfer_time` | `1` | >0 时从引擎读秒里扣除该秒数，防止传输耗时导致野狐超时 |
| `specify_ai_byoyomi` | `false` | `true` = 强制使用 `ai_byo_yomi_time` 作为引擎读秒 |
| `ai_byo_yomi_time` | `5` | 上项的秒数 |
| `max_time` / `max_visits` / `max_playouts` | 5 / 0 / 0 | KataGo 走 `kata-set-param`；非 KataGo 时 `max_time` 用来给读秒时间封顶 |

UI 行为：

* 引擎启动后自动探测，通信日志里会打印一行
  `引擎识别: KataGo 1.13.0(katago) [kata,kata-analyze,undo,final_score,…]`；
* `GET /engine` 多了 `dialect` 字段（见 API 文档）；
* 规则按钮只对支持 `kata-set-rules` 的引擎生效，其余引擎只记日志，不再发无效命令。

---

## 七、已知限制

1. **没有 `final_score` 的引擎**（如部分 Leela Zero 版本）点目只能回 `error`；
   野狐侧建议把「申请点目」设为「同意对手申请和 AI 获胜结果」，不要依赖 AI 点目。
2. **analyze 命令的两种协议形态**都实现了（`= play X` 与裸 `play X`），但极端情况下
   某引擎既不回 ack 也不回裸行，只能靠看门狗兜底（stop → 重试 → 停一手）。
3. 非 KataGo 引擎没有候选点/实时胜率（协议层没这个能力，不硬造）。
4. `komi` 支持到两位小数；个别只吃整数的老引擎可能报错（会记日志，不影响后续）。
5. 反向验证：FoxGTP 本身没在本机跑起来做黑盒对照（它的对话框需要人工点按，
   且 2022 版 PDB 指向内部路径），结论以静态反汇编 + 官方文档 + 真引擎验证为准。

### 实测环境里踩到的一个坑（可能对用户有用）

KataGo 的 ONNX/OpenVINO 版本启动时会**在当前工作目录**下创建 `gtp_logs`（配置里的
`logDir`）和 `katago_ov_cache`。如果 SakuraGTP 放在 Program Files 之类不可写的位置，
KataGo 会直接抛 `Uncaught exception: Error creating directory: Access is denied.` 然后退出，
表现为「引擎启动成功但一条命令都不回」。解决办法二选一：

* 把 SakuraGTP（或它的工作目录）放到可写位置；或
* 在 KataGo 的 cfg 里把 `logDir` / `onnxOpenVINOCacheDir` 改成绝对可写路径。

---

## 八、文件清单

| 文件 | 说明 |
|------|------|
| `gtp_session.py` | 新增：GTP 会话层（编号、匹配、多行、流、游离响应） |
| `gtp_dialect.py` | 新增：能力探测 + 命令翻译 + 结果解析 |
| `gtp_bridge.py` | 重写：野狐 ↔ GTP 状态机、两套棋谱、时间管理、看门狗 |
| `ui_main.py` | 启动/停止引擎时通知桥接层；把读秒选项接进桥接层；`/engine` 增加方言信息 |
| `tests/mock_engine.py`、`tests/test_compat.py` | 新增：三种方言的假引擎 + 26 项回归测试 |
| `_re/` | 逆向脚本（PE 解析、资源、字符串、反汇编、PDF 提取）与提取文本 |
| `SakuraGTP HTTP API 文档.md` | `/engine` 增加 `dialect` 字段说明 |
