from .binary import BinaryReader
from .models import Tex, TexHeader, TexImageContainer, TexImage, TexMipmap


TEX_FORMAT_MAP = {
    0: "RGBA8888",
    4: "DXT5",
    6: "DXT3",
    7: "DXT1",
    8: "RG88",
    9: "R8",
}


def get_mipmap_format_name(image_format: int, tex_format: int) -> str:
    if image_format != -1:
        return f"FREEIMAGE_{image_format}"
    return TEX_FORMAT_MAP.get(tex_format, f"UNKNOWN_{tex_format}")


def read_tex(data: bytes) -> Tex:
    r = BinaryReader(data)

    magic1 = r.read_nstring(max_length=16)
    if magic1 != "TEXV0005":
        raise ValueError(f"不是受支持的 TEX 文件，magic1={magic1!r}")

    magic2 = r.read_nstring(max_length=16)
    if magic2 != "TEXI0001":
        raise ValueError(f"不是受支持的 TEX 文件，magic2={magic2!r}")

    header = TexHeader(
        format=r.read_i32(),
        flags=r.read_i32(),
        texture_width=r.read_i32(),
        texture_height=r.read_i32(),
        image_width=r.read_i32(),
        image_height=r.read_i32(),
        unk_int0=r.read_u32(),
    )

    images_container = read_image_container(r, header.format)
    return Tex(
        magic1=magic1,
        magic2=magic2,
        header=header,
        images_container=images_container,
    )


def read_image_container(r: BinaryReader, tex_format: int) -> TexImageContainer:
    magic = r.read_nstring(max_length=16)
    image_count = r.read_i32()

    image_format = -1
    if magic in ("TEXB0001", "TEXB0002"):
        pass
    elif magic == "TEXB0003":
        image_format = r.read_i32()
    elif magic == "TEXB0004":
        fmt = r.read_i32()
        is_video_mp4 = r.read_i32() == 1
        if fmt == -1 and is_video_mp4:
            fmt = 35
        image_format = fmt
    else:
        raise ValueError(f"未知的图像容器 magic: {magic}")

    version = int(magic[4:])
    if version == 4 and image_format != 35:
        version = 3

    container = TexImageContainer(
        magic=magic,
        image_count=image_count,
        image_format=image_format,
        version=version,
        images=[],
    )

    for _ in range(image_count):
        container.images.append(read_image(r, container.version, image_format, tex_format))

    return container


def read_image(r: BinaryReader, version: int, image_format: int, tex_format: int) -> TexImage:
    mipmap_count = r.read_i32()
    image = TexImage()

    for _ in range(mipmap_count):
        if version == 1:
            mipmap = TexMipmap(
                width=r.read_i32(),
                height=r.read_i32(),
                data=read_blob(r),
            )
        elif version in (2, 3):
            mipmap = TexMipmap(
                width=r.read_i32(),
                height=r.read_i32(),
                is_lz4_compressed=(r.read_i32() == 1),
                decompressed_bytes_count=r.read_i32(),
                data=read_blob(r),
            )
        elif version == 4:
            param1 = r.read_i32()
            param2 = r.read_i32()
            _condition_json = r.read_nstring()
            param3 = r.read_i32()
            if param1 != 1 or param2 != 2 or param3 != 1:
                raise ValueError(f"不支持的 TEXB0004 参数: {param1}, {param2}, {param3}")
            mipmap = TexMipmap(
                width=r.read_i32(),
                height=r.read_i32(),
                is_lz4_compressed=(r.read_i32() == 1),
                decompressed_bytes_count=r.read_i32(),
                data=read_blob(r),
            )
        else:
            raise ValueError(f"不支持的图像容器版本: {version}")

        mipmap.format_name = get_mipmap_format_name(image_format, tex_format)
        image.mipmaps.append(mipmap)

    return image


def read_blob(r: BinaryReader) -> bytes:
    size = r.read_i32()
    if size < 0:
        raise ValueError(f"数据块大小异常: {size}")
    return r.read(size)
