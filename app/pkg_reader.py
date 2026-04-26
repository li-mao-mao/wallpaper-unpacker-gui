from .binary import BinaryReader
from .models import Package, PackageEntry


def read_pkg(data: bytes, read_entry_bytes: bool = True) -> Package:
    r = BinaryReader(data)
    package_start = r.tell()

    magic = r.read_string_i32_size(max_length=32)
    entry_count = r.read_i32()

    entries = []
    for _ in range(entry_count):
        full_path = r.read_string_i32_size(max_length=1024)
        offset = r.read_i32()
        length = r.read_i32()
        entries.append(PackageEntry(full_path=full_path, offset=offset, length=length))

    data_start = r.tell()
    header_size = data_start - package_start
    pkg = Package(magic=magic, header_size=header_size, entries=entries)

    if read_entry_bytes:
        for entry in pkg.entries:
            r.seek(data_start + entry.offset)
            entry.data = r.read(entry.length)

    return pkg
