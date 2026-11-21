# `_re/` —— FoxGTP 逆向分析脚本

对 `野狐围棋AI接入程序和使用手册(Fox Go AI Program And Manual)20220606\FoxGTP\FoxGTP.exe`
做静态分析时用到的脚本。依赖：`capstone`（反汇编）、`pypdf`（手册文本提取）。

| 脚本 | 作用 |
|------|------|
| `pe.py` | 极简 PE 解析：节表、数据目录、资源树、调试目录（拿到 PDB 路径） |
| `imports.py` | 导出导入表 + 全节 ASCII 字符串（`imports.txt`） |
| `res.py` | 资源里的 UTF-16 字符串、字符串表、对话框（`res.txt`） |
| `disasm.py` | 线性反汇编 `.text`，把字符串/导入地址标注到每条指令上（`listing.txt`） |
| `show.py` | 按地址区间打印反汇编（`python show.py 401500 4016e0`） |
| `iat.py` | 打印 IAT 地址 → 函数名 |
| `thunks.py` | 解析 `.rdata` 里的二级跳转表 |
| `foxrefs.py` | 找野狐协议命令字符串（`$FARULE` 等）在代码里的引用 |
| `gtp_strings.py` | 过滤 GTP 相关字符串 |
| `hexdump.py` | 关键字符串区的十六进制视图 |
| `pdf.py` | 把 5 份官方 PDF 提取成文本（`pdf/*.txt`） |

`listing.txt`（约 2 MB，56288 条指令）可用 `disasm.py` 重新生成。

关键地址速查：

| 地址 | 内容 |
|------|------|
| 0x401500 | GTP 响应解析（要求 `=<数字>`） |
| 0x4016E0 / 0x401A30 / 0x401990 | 落子解析 / 坐标解析 / 坐标生成 |
| 0x401770 / 0x401900 | `final_score` 解析 / 胜方识别 |
| 0x4028E0–0x4031FF | 11 条 GTP 命令的发送函数 |
| 0x40C3A0 | 命令队列处理器（11 种 type 的分发 + play 去重） |
| 0x40C210 | 棋谱比较与同步（补差异 / 整盘重放） |
| 0x40BDF0 | 开局设置批：clear_board→boardsize→komi→time_settings→让子 |
| 0x40EFB0 / 0x40F0A0 | 引擎响应分发（genmove/final_score/play 错误） |
| 0x41A930 / 0x41AAB0 | 野狐命令名查找 / 12 条命令分发 |
| 0x41ADA0 / 0x41B830 | `$FARULE` / `$FAMOVE` 处理 |
| 0x427C50 | 野狐协议打包（`$CMD,…*hh\r\n`） |
