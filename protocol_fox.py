def calc_checksum(data: bytes) -> int:
    """异或校验和：不包含第一个字符 $"""
    if not data:
        return 0
    if data[0:1] == b"$":
        data = data[1:]
    chk = 0
    for b in data:
        chk ^= b
    return chk & 0xFF

def build_packet(command: str, *items) -> bytes:
    """
    构建野狐协议包：$ABXXXX,ddd,...,ddd*hh\r\n
    """
    body = "$" + command
    for it in items:
        body += "," + str(it)
    raw = body.encode("utf-8")
    chk = calc_checksum(raw)
    packet = raw + f"*{chk:02X}\r\n".encode("ascii")
    return packet

def parse_packet(line: str):
    """
    解析一行野狐协议包，返回 (command, items) 或 None
    """
    line = line.strip()
    if not line.startswith("$"):
        return None
    if "*" in line:
        line = line.split("*", 1)[0]
    parts = line[1:].split(",")
    if not parts:
        return None
    return parts[0], parts[1:]