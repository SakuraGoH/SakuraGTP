# SakuraGTP HTTP API 文档

版本：1.2.0
协议：HTTP + JSON
默认地址：`http://127.0.0.1:8765`
编码：UTF-8

---

## 一、概述

SakuraGTP 提供本地 HTTP API，让用户无需修改源码即可二次开发。

- 只监听 `127.0.0.1`，本机访问。
- 无认证，任何本机程序可调。
- CORS 允许所有来源，网页可直接调。
- 所有响应为 JSON。

启动方式：SakuraGTP 界面 → 「HTTP API」组 → 点「启动 API」。

---

## 二、端点列表

### GET

| 路径            | 说明                  |
| ------------- | ------------------- |
| `/`           | API 信息与端点列表         |
| `/status`     | 引擎、野狐、AI 颜色、盘面尺寸等状态 |
| `/board`      | 当前盘面落子              |
| `/candidates` | 当前引擎候选选点            |
| `/winrate`    | 胜率曲线数据              |
| `/score`      | 目差曲线数据              |
| `/match`      | 好手率统计               |
| `/engine`     | 引擎信息                |

### POST

| 路径              | Body                       | 说明        |
| --------------- | -------------------------- | --------- |
| `/gtp`          | `{"command": "genmove B"}` | 发送 GTP 命令 |
| `/engine/start` | 无                          | 启动引擎      |
| `/engine/stop`  | 无                          | 停止引擎      |
| `/fox/start`    | 无                          | 开始监听野狐    |
| `/fox/stop`     | 无                          | 停止监听野狐    |
| `/rules`        | `{"rule": "japanese"}`     | 切换规则      |

---

## 三、GET 端点详解

### 1. `GET /`

返回 API 信息和端点列表。

**响应示例**：

```json
{
  "name": "SakuraGTP API",
  "version": "1.0",
  "endpoints": [
    "GET /status",
    "GET /board",
    "GET /candidates",
    "GET /winrate",
    "GET /score",
    "GET /match",
    "GET /engine",
    "POST /gtp",
    "POST /engine/start",
    "POST /engine/stop",
    "POST /fox/start",
    "POST /fox/stop",
    "POST /rules"
  ]
}
```

---

### 2. `GET /status`

返回当前状态。

**响应示例**：

```json
{
  "engine_running": true,
  "fox_listening": true,
  "api_running": true,
  "ai_color": "W",
  "board_size": 19,
  "komi": 7.5,
  "last_move_number": 12,
  "live_winrate": false
}
```

**字段说明**：

| 字段                 | 类型     | 说明                |
| ------------------ | ------ | ----------------- |
| `engine_running`   | bool   | 引擎是否运行            |
| `fox_listening`    | bool   | 野狐是否连接            |
| `api_running`      | bool   | API 是否运行          |
| `ai_color`         | string | AI 所执颜色，`B` 或 `W` |
| `board_size`       | int    | 棋盘尺寸              |
| `komi`             | float  | 贴目                |
| `last_move_number` | int    | 最后一手手数            |
| `live_winrate`     | bool   | 是否启用实时胜率模式        |

---

### 3. `GET /board`

返回当前盘面落子。

**响应示例**：

```json
{
  "board_size": 19,
  "komi": 7.5,
  "stones": [
    {"move_number": 1, "color": "B", "vertex": "Q16", "x": 15, "y": 3},
    {"move_number": 2, "color": "W", "vertex": "D4", "x": 3, "y": 15}
  ]
}
```

**字段说明**：

| 字段            | 类型     | 说明                |
| ------------- | ------ | ----------------- |
| `move_number` | int    | 手数，从 1 开始         |
| `color`       | string | `B` 或 `W`         |
| `vertex`      | string | GTP 坐标，如 `Q16`    |
| `x`           | int    | 野狐 X 坐标，0~18，从左到右 |
| `y`           | int    | 野狐 Y 坐标，0~18，从上到下 |

---

### 4. `GET /candidates`

返回当前引擎候选选点。

**响应示例**：

```json
{
  "candidates": [
    {"vertex": "D16", "x": 3, "y": 3, "visits": 1009, "winrate": 0.6347, "score": 1.2, "order": 0},
    {"vertex": "Q4", "x": 15, "y": 15, "visits": 800, "winrate": 0.62, "score": 1.0, "order": 1}
  ]
}
```

**字段说明**：

| 字段        | 类型     | 说明        |
| --------- | ------ | --------- |
| `vertex`  | string | GTP 坐标    |
| `x`       | int    | 野狐 X 坐标   |
| `y`       | int    | 野狐 Y 坐标   |
| `visits`  | int    | 计算量       |
| `winrate` | float  | 胜率，0~1    |
| `score`   | float  | 目差        |
| `order`   | int    | 排名，0 是第一选 |

**注意**：只在引擎思考时才有数据，平时为空。

---

### 5. `GET /winrate`

返回胜率曲线数据。

**响应示例**：

```json
{
  "data": [
    {"move": 1, "black_winrate": 0.52},
    {"move": 2, "black_winrate": 0.48}
  ],
  "stdev": 13.4
}
```

**字段说明**：

| 字段              | 类型    | 说明                       |
| --------------- | ----- | ------------------------ |
| `move`          | int   | 手数                       |
| `black_winrate` | float | 黑棋胜率，0~1                 |
| `stdev`         | float | 不确定度 ScoreStdev，可能为 null |

---

### 6. `GET /score`

返回目差曲线数据。

**响应示例**：

```json
{
  "data": [
    {"move": 1, "own_score_lead": 1.2},
    {"move": 2, "own_score_lead": 0.8}
  ]
}
```

**字段说明**：

| 字段               | 类型    | 说明            |
| ---------------- | ----- | ------------- |
| `move`           | int   | 手数            |
| `own_score_lead` | float | 己方目差，正数表示己方领先 |

---

### 7. `GET /match`

返回好手率统计。

**响应示例**：

```json
{
  "total": 10,
  "good_moves": 7,
  "threshold": 3.0
}
```

**字段说明**：

| 字段           | 类型    | 说明            |
| ------------ | ----- | ------------- |
| `total`      | int   | 对手总手数         |
| `good_moves` | int   | 好手手数          |
| `threshold`  | float | 好手阈值（胜率下降百分比） |

**好手率 = good_moves / total × 100%**。

---

### 8. `GET /engine`

返回引擎信息。

**响应示例**：

```json
{
  "running": true,
  "remote_mode": false,
  "path": "C:\\KataGo\\katago.exe",
  "weight": "C:\\KataGo\\model.bin.gz",
  "config": "C:\\KataGo\\gtp.cfg",
  "remote_cmd": ""
}
```

**字段说明**：

| 字段            | 类型     | 说明     |
| ------------- | ------ | ------ |
| `running`     | bool   | 是否运行   |
| `remote_mode` | bool   | 是否远程模式 |
| `path`        | string | 引擎路径   |
| `weight`      | string | 权重路径   |
| `config`      | string | 配置路径   |
| `remote_cmd`  | string | 远程命令行  |

---

## 四、POST 端点详解

### 1. `POST /gtp`

发送 GTP 命令给引擎。

**请求体**：

```json
{"command": "genmove B"}
```

**响应**：

```json
{"ok": true}
```

**失败**：

```json
{"ok": false}
```

**注意**：引擎未运行时返回 `{"ok": false}`。

**支持的命令**：任何 GTP 命令，如 `genmove B`、`play B D4`、`kata-set-param maxTime 5` 等。

---

### 2. `POST /engine/start`

启动引擎。

**请求体**：无。

**响应**：

```json
{"ok": true, "message": "已尝试启动引擎"}
```

---

### 3. `POST /engine/stop`

停止引擎。

**响应**：

```json
{"ok": true, "message": "引擎已停止"}
```

---

### 4. `POST /fox/start`

开始监听野狐。

**响应**：

```json
{"ok": true, "message": "已尝试开始监听"}
```

---

### 5. `POST /fox/stop`

停止监听野狐。

**响应**：

```json
{"ok": true, "message": "野狐监听已停止"}
```

---

### 6. `POST /rules`

切换规则。

**请求体**：

```json
{"rule": "japanese"}
```

**支持的规则**：

- `chinese`：中国规则
- `japanese`：日本规则
- `korean`：韩国规则
- `aga`：AGA 规则
- `new-zealand`：新西兰规则

**响应**：

```json
{"ok": true}
```

---

## 五、调用示例

### Python（requests）

```python
import requests

BASE = "http://127.0.0.1:8765"

# 查状态
r = requests.get(f"{BASE}/status")
print(r.json())

# 查盘面
r = requests.get(f"{BASE}/board")
for s in r.json()["stones"]:
    print(s["move_number"], s["color"], s["vertex"])

# 查选点
r = requests.get(f"{BASE}/candidates")
for c in r.json()["candidates"]:
    print(c["order"], c["vertex"], c["winrate"], c["visits"])

# 发 GTP 命令
r = requests.post(f"{BASE}/gtp", json={"command": "genmove B"})
print(r.json())

# 切换规则
r = requests.post(f"{BASE}/rules", json={"rule": "japanese"})
print(r.json())
```

### Python（标准库）

```python
import urllib.request
import json

BASE = "http://127.0.0.1:8765"

with urllib.request.urlopen(f"{BASE}/status") as resp:
    data = json.loads(resp.read().decode("utf-8"))
    print(data)

req = urllib.request.Request(
    f"{BASE}/gtp",
    data=json.dumps({"command": "genmove B"}).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST"
)
with urllib.request.urlopen(req) as resp:
    print(json.loads(resp.read().decode("utf-8")))
```

### curl

```bash
curl http://127.0.0.1:8765/status
curl http://127.0.0.1:8765/board
curl http://127.0.0.1:8765/candidates

curl -X POST http://127.0.0.1:8765/gtp \
     -H "Content-Type: application/json" \
     -d "{\"command\": \"genmove B\"}"

curl -X POST http://127.0.0.1:8765/rules \
     -H "Content-Type: application/json" \
     -d "{\"rule\": \"japanese\"}"
```

### JavaScript

```javascript
const BASE = "http://127.0.0.1:8765";

fetch(`${BASE}/status`)
  .then(r => r.json())
  .then(data => console.log(data));

fetch(`${BASE}/gtp`, {
  method: "POST",
  headers: {"Content-Type": "application/json"},
  body: JSON.stringify({command: "genmove B"})
})
  .then(r => r.json())
  .then(data => console.log(data));
```

### C#

```csharp
using System;
using System.Net.Http;
using System.Text;
using System.Threading.Tasks;

class Program
{
    static async Task Main()
    {
        var client = new HttpClient();
        var baseUrl = "http://127.0.0.1:8765";

        var status = await client.GetStringAsync($"{baseUrl}/status");
        Console.WriteLine(status);

        var json = "{\"command\": \"genmove B\"}";
        var content = new StringContent(json, Encoding.UTF8, "application/json");
        var resp = await client.PostAsync($"{baseUrl}/gtp", content);
        Console.WriteLine(await resp.Content.ReadAsStringAsync());
    }
}
```

### Java

```java
import java.net.http.*;
import java.net.URI;

public class Main {
    public static void main(String[] args) throws Exception {
        HttpClient client = HttpClient.newHttpClient();
        String base = "http://127.0.0.1:8765";

        HttpRequest getReq = HttpRequest.newBuilder()
            .uri(URI.create(base + "/status"))
            .GET()
            .build();
        HttpResponse<String> getResp = client.send(getReq, HttpResponse.BodyHandlers.ofString());
        System.out.println(getResp.body());

        String json = "{\"command\": \"genmove B\"}";
        HttpRequest postReq = HttpRequest.newBuilder()
            .uri(URI.create(base + "/gtp"))
            .header("Content-Type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(json))
            .build();
        HttpResponse<String> postResp = client.send(postReq, HttpResponse.BodyHandlers.ofString());
        System.out.println(postResp.body());
    }
}
```

---

## 六、常见用例

### 1. 实时胜率监控

```python
import requests
import time

BASE = "http://127.0.0.1:8765"

while True:
    r = requests.get(f"{BASE}/winrate", timeout=2)
    data = r.json()
    if data["data"]:
        latest = data["data"][-1]
        print(f"第{latest['move']}手，黑棋胜率{latest['black_winrate']*100:.1f}%")
    time.sleep(1)
```

### 2. 自动认输

```python
import requests
import time

BASE = "http://127.0.0.1:8765"
THRESHOLD = 0.05

while True:
    status = requests.get(f"{BASE}/status").json()
    ai_color = status["ai_color"]

    wr = requests.get(f"{BASE}/winrate").json()
    if wr["data"]:
        latest = wr["data"][-1]
        black_wr = latest["black_winrate"]
        ai_wr = black_wr if ai_color == "B" else 1.0 - black_wr
        if ai_wr < THRESHOLD:
            print(f"AI 胜率 {ai_wr*100:.1f}%，自动认输")
            requests.post(f"{BASE}/gtp", json={"command": "kata-set-param resignThreshold 1.0"})
            break
    time.sleep(1)
```

### 3. 对局记录

```python
import requests
import json
import time
import os

BASE = "http://127.0.0.1:8765"
OUT_DIR = "games"

os.makedirs(OUT_DIR, exist_ok=True)
timestamp = time.strftime("%Y%m%d_%H%M%S")

record = {
    "timestamp": timestamp,
    "board": requests.get(f"{BASE}/board").json(),
    "winrate": requests.get(f"{BASE}/winrate").json(),
    "score": requests.get(f"{BASE}/score").json(),
    "match": requests.get(f"{BASE}/match").json(),
}

with open(os.path.join(OUT_DIR, f"{timestamp}.json"), "w", encoding="utf-8") as f:
    json.dump(record, f, ensure_ascii=False, indent=2)
```

---

## 七、错误处理

### 常见错误

| 错误                   | 原因       | 解决              |
| -------------------- | -------- | --------------- |
| `Connection refused` | API 未启动  | 点「启动 API」       |
| `404 not found`      | 路径错误     | 用 `GET /` 看端点列表 |
| `500`                | API 内部异常 | 看 SakuraGTP 日志  |
| 超时                   | API 卡住   | 重启 SakuraGTP    |

### Python 错误处理示例

```python
import requests

BASE = "http://127.0.0.1:8765"

try:
    r = requests.get(f"{BASE}/status", timeout=2)
    r.raise_for_status()
    print(r.json())
except requests.ConnectionError:
    print("API 未启动")
except requests.Timeout:
    print("API 超时")
except requests.HTTPError as e:
    print(f"HTTP 错误: {e}")
except Exception as e:
    print(f"其他错误: {e}")
```

---

## 八、注意事项

1. **API 默认只监听 127.0.0.1**，本机访问。
2. **无认证**，任何本机程序可调。
3. **CORS 允许所有来源**，网页可直接调。
4. **端口冲突**：默认 8765，可改。
5. **`/candidates` 只在引擎思考时有数据**。
6. **`/gtp` 需要引擎运行**，否则返回 `{"ok": false}`。
7. **JSON 编码为 UTF-8**，中文正常。

---

## 九、常见问题

**Q：API 启动后，浏览器访问 `http://127.0.0.1:8765/` 没反应？**

A：检查端口是否被占用，换端口。

**Q：能局域网访问吗？**

A：默认不能。如需局域网，把 `api_server.py` 里的 `host="127.0.0.1"` 改成 `host="0.0.0.0"`，注意安全。

**Q：能加 WebSocket 吗？**

A：可以，但要换框架。当前用 HTTP 轮询。

---

## 十、版本

| 版本    | 日期         | 说明   |
| ----- | ---------- | ---- |
| 1.2.0 | 2026-10-06 | 初始版本 |

---
