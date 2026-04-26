from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class PackageEntry:
    full_path: str
    offset: int
    length: int
    data: Optional[bytes] = None


@dataclass
class Package:
    magic: str
    header_size: int
    entries: List[PackageEntry] = field(default_factory=list)


@dataclass
class TexHeader:
    format: int
    flags: int
    texture_width: int
    texture_height: int
    image_width: int
    image_height: int
    unk_int0: int


@dataclass
class TexMipmap:
    width: int
    height: int
    is_lz4_compressed: bool = False
    decompressed_bytes_count: int = 0
    data: bytes = b""
    format_name: str = ""


@dataclass
class TexImage:
    mipmaps: List[TexMipmap] = field(default_factory=list)


@dataclass
class TexImageContainer:
    magic: str
    image_count: int
    image_format: int = -1
    version: int = 1
    images: List[TexImage] = field(default_factory=list)


@dataclass
class Tex:
    magic1: str
    magic2: str
    header: TexHeader
    images_container: TexImageContainer

    @property
    def is_gif(self) -> bool:
        return (self.header.flags & 4) == 4

    @property
    def is_video_texture(self) -> bool:
        return (self.header.flags & 32) == 32
