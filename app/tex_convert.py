import io
import struct
from dataclasses import dataclass
from typing import Optional

from lz4.block import decompress as lz4_decompress
from PIL import Image, UnidentifiedImageError

from .models import Tex, TexMipmap

# 参考原始 RePKG 的 FreeImageFormat 枚举：
# 2=JPEG, 13=PNG, 24=DDS, 25=GIF, 35=MP4
FREEIMAGE_NAMES = {
    -1: "UNKNOWN",
    0: "BMP",
    1: "ICO",
    2: "JPEG",
    3: "JNG",
    6: "MNG",
    13: "PNG",
    17: "TARGA",
    18: "TIFF",
    24: "DDS",
    25: "GIF",
    35: "MP4",
}

FORMAT_TO_EXT = {
    "BMP": ".bmp",
    "ICO": ".ico",
    "JPEG": ".jpg",
    "JNG": ".jng",
    "MNG": ".mng",
    "PNG": ".png",
    "TARGA": ".tga",
    "TIFF": ".tiff",
    "DDS": ".dds",
    "GIF": ".gif",
    "MP4": ".mp4",
}

PNG_SIG = b"\x89PNG\r\n\x1a\n"
JPEG_SIG = b"\xff\xd8\xff"
BMP_SIG = b"BM"
GIF_SIG_1 = b"GIF87a"
GIF_SIG_2 = b"GIF89a"
DDS_SIG = b"DDS "
TIFF_SIG_1 = b"II*\x00"
TIFF_SIG_2 = b"MM\x00*"
ICO_SIG = b"\x00\x00\x01\x00"
MP4_MARKERS = (b"ftypisom", b"ftypmsnv", b"ftypmp42")


@dataclass
class ConvertedResult:
    kind: str  # image / bytes / skip
    ext: str
    image: Optional[Image.Image] = None
    data: Optional[bytes] = None
    reason: str = ""



def ensure_mipmap_decompressed(mipmap: TexMipmap) -> TexMipmap:
    if mipmap.is_lz4_compressed:
        mipmap.data = lz4_decompress(
            mipmap.data,
            uncompressed_size=mipmap.decompressed_bytes_count,
        )
        mipmap.is_lz4_compressed = False
    return mipmap



def convert_tex(tex: Tex, preserve_embedded_formats: bool = True) -> ConvertedResult:
    if not tex.images_container.images or not tex.images_container.images[0].mipmaps:
        raise ValueError("TEX 中没有可导出的图像数据")

    mipmap = tex.images_container.images[0].mipmaps[0]
    ensure_mipmap_decompressed(mipmap)

    data = mipmap.data
    width, height = mipmap.width, mipmap.height
    fmt = mipmap.format_name
    image_format_id = getattr(tex.images_container, "image_format", -1)
    freeimage_name = FREEIMAGE_NAMES.get(image_format_id, f"FREEIMAGE_{image_format_id}")

    # 先判断视频和动图
    if tex.is_video_texture or looks_like_mp4(data) or freeimage_name == "MP4":
        return ConvertedResult(kind="skip", ext="", reason="video")

    if tex.is_gif or freeimage_name == "GIF":
        return ConvertedResult(kind="skip", ext="", reason="gif")

    # 有些 TEX 里本身就是内嵌的 PNG/JPG/BMP/TIFF/... 图片字节
    embedded_ext = detect_embedded_ext(data, freeimage_name)
    if embedded_ext:
        if preserve_embedded_formats and embedded_ext in {".png", ".jpg", ".jpeg", ".bmp", ".ico", ".tga", ".tiff"}:
            return ConvertedResult(kind="bytes", ext=embedded_ext, data=data)

        # 其余内嵌图片尽量用 Pillow 解码后统一转成 PNG
        try:
            image = Image.open(io.BytesIO(data)).convert("RGBA")
            image = crop_image(image, tex)
            return ConvertedResult(kind="image", ext=".png", image=image)
        except UnidentifiedImageError:
            pass

    # 再处理 RePKG 的原始纹理路径
    if fmt == "RGBA8888":
        image = Image.frombytes("RGBA", (width, height), data)
        image = crop_image(image, tex)
        return ConvertedResult(kind="image", ext=".png", image=image)

    if fmt == "R8":
        image = Image.frombytes("L", (width, height), data)
        image = crop_image(image, tex)
        return ConvertedResult(kind="image", ext=".png", image=image)

    if fmt == "RG88":
        image = rg88_to_image(data, width, height)
        image = crop_image(image, tex)
        return ConvertedResult(kind="image", ext=".png", image=image)

    if fmt in ("DXT1", "DXT3", "DXT5"):
        image = dxt_to_image_via_dds(data, width, height, fmt)
        image = crop_image(image, tex)
        return ConvertedResult(kind="image", ext=".png", image=image)

    # 最后再兜底尝试：直接交给 Pillow 识别
    try:
        image = Image.open(io.BytesIO(data)).convert("RGBA")
        image = crop_image(image, tex)
        return ConvertedResult(kind="image", ext=".png", image=image)
    except Exception:
        raise ValueError(f"暂不支持的图片格式: {fmt}")



def crop_image(image: Image.Image, tex: Tex) -> Image.Image:
    target_width = max(1, tex.header.image_width)
    target_height = max(1, tex.header.image_height)
    if image.size != (target_width, target_height):
        return image.crop((0, 0, target_width, target_height))
    return image



def detect_embedded_ext(data: bytes, freeimage_name: str = "") -> Optional[str]:
    if not data:
        return None

    if data.startswith(PNG_SIG):
        return ".png"
    if data.startswith(JPEG_SIG):
        return ".jpg"
    if data.startswith(BMP_SIG):
        return ".bmp"
    if data.startswith(GIF_SIG_1) or data.startswith(GIF_SIG_2):
        return ".gif"
    if data.startswith(DDS_SIG):
        return ".dds"
    if data.startswith(TIFF_SIG_1) or data.startswith(TIFF_SIG_2):
        return ".tiff"
    if data.startswith(ICO_SIG):
        return ".ico"

    ext = FORMAT_TO_EXT.get(freeimage_name)
    if ext:
        return ext
    return None



def looks_like_mp4(data: bytes) -> bool:
    if len(data) < 12:
        return False
    marker = data[4:12]
    return marker in MP4_MARKERS



def rg88_to_image(data: bytes, width: int, height: int) -> Image.Image:
    # 参考 RePKG 的 RG88 像素定义：Color => Rgba32(G, G, G, R)
    out = bytearray()
    for i in range(0, len(data), 2):
        r = data[i]
        g = data[i + 1]
        out.extend([g, g, g, r])
    return Image.frombytes("RGBA", (width, height), bytes(out))



def dxt_to_image_via_dds(data: bytes, width: int, height: int, fmt: str) -> Image.Image:
    dds_bytes = build_dds(width, height, fmt, data)
    return Image.open(io.BytesIO(dds_bytes)).convert("RGBA")



def build_dds(width: int, height: int, fmt: str, payload: bytes) -> bytes:
    fourcc = {
        "DXT1": b"DXT1",
        "DXT3": b"DXT3",
        "DXT5": b"DXT5",
    }[fmt]

    header = bytearray()
    header.extend(b"DDS ")
    header.extend(struct.pack("<I", 124))
    header.extend(struct.pack("<I", 0x0002100F))
    header.extend(struct.pack("<I", height))
    header.extend(struct.pack("<I", width))
    header.extend(struct.pack("<I", len(payload)))
    header.extend(struct.pack("<I", 0))
    header.extend(struct.pack("<I", 1))
    header.extend(b"\x00" * 44)

    header.extend(struct.pack("<I", 32))
    header.extend(struct.pack("<I", 0x00000004))
    header.extend(fourcc)
    header.extend(struct.pack("<I", 0))
    header.extend(struct.pack("<I", 0))
    header.extend(struct.pack("<I", 0))
    header.extend(struct.pack("<I", 0))
    header.extend(struct.pack("<I", 0))

    header.extend(struct.pack("<I", 0x1000))
    header.extend(struct.pack("<I", 0))
    header.extend(struct.pack("<I", 0))
    header.extend(struct.pack("<I", 0))
    header.extend(struct.pack("<I", 0))

    return bytes(header) + payload
