import io
import struct


class BinaryReader:
    def __init__(self, data: bytes):
        self.buf = io.BytesIO(data)

    def tell(self) -> int:
        return self.buf.tell()

    def seek(self, offset: int, whence: int = 0) -> None:
        self.buf.seek(offset, whence)

    def read(self, n: int) -> bytes:
        data = self.buf.read(n)
        if len(data) != n:
            raise EOFError(f"需要读取 {n} 字节，但实际只读到 {len(data)} 字节")
        return data

    def read_i32(self) -> int:
        return struct.unpack("<i", self.read(4))[0]

    def read_u32(self) -> int:
        return struct.unpack("<I", self.read(4))[0]

    def read_f32(self) -> float:
        return struct.unpack("<f", self.read(4))[0]

    def read_nstring(self, max_length: int = 1024) -> str:
        parts = []
        for _ in range(max_length):
            ch = self.read(1)
            if ch == b"\x00":
                break
            parts.append(ch)
        return b"".join(parts).decode("utf-8", errors="replace")

    def read_string_i32_size(self, max_length: int = 4096) -> str:
        size = self.read_i32()
        if size < 0 or size > max_length:
            raise ValueError(f"字符串长度异常: {size}")
        return self.read(size).decode("utf-8", errors="replace")
