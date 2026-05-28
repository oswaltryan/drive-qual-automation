from __future__ import annotations

import io
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from drive_qual.reports.constants import (
    CFB_END_OF_CHAIN,
    CFB_FAT_SECTOR,
    CFB_FREE_SECTOR,
    CFB_MINI_SECTOR_SIZE,
    CFB_MINI_STREAM_CUTOFF,
    CFB_NO_STREAM,
    CFB_SECTOR_SIZE,
    OLE_MARKER_BYTES,
    PACKAGE_CLSID,
)

ASCII_CONTROL_CHAR_LIMIT = 32


def _add_embedded_package_to_paragraph(paragraph: Any, artifact: Path, *, width: Any) -> None:
    object_r_id = _relate_to_embedded_package(paragraph.part, artifact)
    icon_r_id = _relate_to_object_icon(paragraph.part, artifact)
    shape_id = f"_x0000_i{1000 + _relationship_number(object_r_id)}"
    object_id = f"_{zlib.crc32(f'{artifact.name}:{object_r_id}'.encode()) % 2_000_000_000}"
    run = paragraph.add_run()
    run_element = run._r
    run_element.append(
        _embedded_package_xml(
            object_r_id=object_r_id,
            icon_r_id=icon_r_id,
            shape_id=shape_id,
            object_id=object_id,
            width_pt=_points(width),
        )
    )


def _relationship_number(r_id: str) -> int:
    suffix = r_id.removeprefix("rId")
    return int(suffix) if suffix.isdecimal() else 0


def _relate_to_embedded_package(part: Any, artifact: Path) -> str:
    from docx.opc.constants import CONTENT_TYPE as CT
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.opc.packuri import PackURI
    from docx.opc.part import Part

    package = part.package
    partname = package.next_partname("/word/embeddings/oleObject%d.bin")
    embedded_filename = _embedded_package_filename(artifact)
    ole_part = Part(
        PackURI(str(partname)),
        CT.OFC_OLE_OBJECT,
        _ole_package_blob(
            label=embedded_filename,
            filename=embedded_filename,
            payload=_embedded_package_payload(artifact),
        ),
        package,
    )
    return cast(str, part.relate_to(ole_part, RT.OLE_OBJECT))


def _embedded_package_filename(artifact: Path) -> str:
    parent_label = _embedded_package_parent_label(artifact)
    filename = _safe_package_filename(artifact.name)
    if parent_label is None:
        return filename
    return _safe_package_filename(f"{parent_label} - {filename}")


def _embedded_package_payload(artifact: Path) -> bytes:
    if artifact.suffix.casefold() == ".png":
        normalized = _normalized_png_payload(artifact)
        if normalized is not None:
            return normalized
    return artifact.read_bytes()


def _normalized_png_payload(artifact: Path) -> bytes | None:
    from PIL import Image

    try:
        with Image.open(artifact) as image:
            loaded = image.copy()
    except Exception:
        return None

    stream = io.BytesIO()
    loaded.save(stream, format="PNG")
    return stream.getvalue()


def _embedded_package_parent_label(artifact: Path) -> str | None:
    parts = list(artifact.parts[:-1])
    for index, part in enumerate(parts):
        token = _normalized_token(part)
        if "inrush" in token:
            return _join_package_label_parts("In Rush", _rail_label_parts(parts[index:]))
        if "maxio" in token:
            return _join_package_label_parts("Max IO", _rail_label_parts(parts[index:]))
    return None


def _rail_label_parts(parts: list[str]) -> list[str]:
    labels: list[str] = []
    for part in parts:
        token = _normalized_token(part)
        if "5v" in token:
            labels.append("5V")
        elif "12v" in token:
            labels.append("12V")
    return labels[:1]


def _join_package_label_parts(category: str, labels: list[str]) -> str:
    return " ".join([category, *labels])


def _safe_package_filename(value: str) -> str:
    sanitized = "".join(
        "_" if character in '<>:"/\\|?*' or ord(character) < ASCII_CONTROL_CHAR_LIMIT else character
        for character in value
    )
    return sanitized.strip(" .") or "embedded-image.png"


def _normalized_token(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _relate_to_object_icon(part: Any, artifact: Path) -> str:
    from docx.opc.constants import RELATIONSHIP_TYPE as RT

    package = part.package
    icon_part = package.get_or_add_image_part(_object_preview_stream(artifact))
    return cast(str, part.relate_to(icon_part, RT.IMAGE))


def _object_preview_stream(artifact: Path) -> io.BytesIO:
    from PIL import Image

    stream = io.BytesIO()
    image = Image.open(artifact)
    image.thumbnail((96, 96))
    image.save(stream, format="PNG")
    stream.seek(0)
    cast(Any, stream).name = f"{artifact.stem}-preview.png"
    return stream


def _embedded_package_xml(*, object_r_id: str, icon_r_id: str, shape_id: str, object_id: str, width_pt: float) -> Any:
    from docx.oxml import parse_xml

    height_pt = width_pt
    return parse_xml(
        f"""
        <w:object
            xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
            xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
            xmlns:v="urn:schemas-microsoft-com:vml"
            xmlns:o="urn:schemas-microsoft-com:office:office"
            w:dxaOrig="{int(width_pt * 20)}"
            w:dyaOrig="{int(height_pt * 20)}">
            <v:shapetype id="_x0000_t75" coordsize="21600,21600" o:spt="75"
                o:preferrelative="t" path="m@4@5l@4@11@9@11@9@5xe" filled="f" stroked="f">
                <v:stroke joinstyle="miter"/>
                <v:formulas>
                    <v:f eqn="if lineDrawn pixelLineWidth 0"/>
                    <v:f eqn="sum @0 1 0"/>
                    <v:f eqn="sum 0 0 @1"/>
                    <v:f eqn="prod @2 1 2"/>
                    <v:f eqn="prod @3 21600 pixelWidth"/>
                    <v:f eqn="prod @3 21600 pixelHeight"/>
                    <v:f eqn="sum @0 0 1"/>
                    <v:f eqn="prod @6 1 2"/>
                    <v:f eqn="prod @7 21600 pixelWidth"/>
                    <v:f eqn="sum @8 21600 0"/>
                    <v:f eqn="prod @7 21600 pixelHeight"/>
                    <v:f eqn="sum @10 21600 0"/>
                </v:formulas>
                <v:path o:extrusionok="f" gradientshapeok="t" o:connecttype="rect"/>
                <o:lock v:ext="edit" aspectratio="t"/>
            </v:shapetype>
            <v:shape id="{shape_id}" type="#_x0000_t75"
                style="width:{width_pt:.2f}pt;height:{height_pt:.2f}pt" o:ole="">
                <v:imagedata r:id="{icon_r_id}" o:title=""/>
            </v:shape>
            <o:OLEObject Type="Embed" ProgID="Package" ShapeID="{shape_id}"
                DrawAspect="Icon" ObjectID="{object_id}" r:id="{object_r_id}"/>
        </w:object>
        """
    )


def _points(width: Any) -> float:
    return int(width) / 12700.0


def _ole_package_blob(*, label: str, filename: str, payload: bytes) -> bytes:
    streams = [
        _CfbStream("\x01Ole", OLE_MARKER_BYTES),
        _CfbStream("\x01Ole10Native", _ole10_native_stream(label=label, filename=filename, payload=payload)),
    ]
    return _write_cfb(streams)


def _ole10_native_stream(*, label: str, filename: str, payload: bytes) -> bytes:
    label_bytes = _asciiz(label)
    filename_bytes = _asciiz(filename)
    command_bytes = _asciiz(filename)
    body = b"".join(
        [
            struct.pack("<H", 2),
            label_bytes,
            filename_bytes,
            struct.pack("<H", 0),
            struct.pack("<H", 3),
            struct.pack("<I", len(command_bytes)),
            command_bytes,
            struct.pack("<I", len(payload)),
            payload,
        ]
    )
    return struct.pack("<I", len(body)) + body


def _asciiz(value: str) -> bytes:
    return value.encode("utf-8", errors="replace") + b"\x00"


@dataclass
class _CfbStream:
    name: str
    data: bytes
    start: int = CFB_END_OF_CHAIN

    @property
    def size(self) -> int:
        return len(self.data)

    @property
    def mini(self) -> bool:
        return len(self.data) < CFB_MINI_STREAM_CUTOFF


@dataclass(frozen=True)
class _DirectoryEntry:
    name: str
    entry_type: int
    right: int = CFB_NO_STREAM
    child: int = CFB_NO_STREAM
    start: int = CFB_END_OF_CHAIN
    size: int = 0
    clsid: bytes = b"\x00" * 16


@dataclass(frozen=True)
class _FatLayout:
    sector_count: int
    fat_sector_count: int
    minifat_start: int
    minifat_sector_count: int
    directory_start: int
    root_start: int
    root_sector_count: int
    regular_streams: list[_CfbStream]


def _write_cfb(streams: list[_CfbStream]) -> bytes:
    mini_stream, mini_fat = _build_mini_stream(streams)
    regular_streams = [stream for stream in streams if not stream.mini]
    minifat_stream = _pack_fat(mini_fat)
    minifat_sector_count = _sector_count(minifat_stream)
    root_sector_count = _sector_count(mini_stream)
    regular_sector_count = sum(_sector_count(stream.data) for stream in regular_streams)
    nonfat_sector_count = minifat_sector_count + 1 + root_sector_count + regular_sector_count
    fat_sector_count = _fat_sector_count(nonfat_sector_count)
    first_minifat_sector = fat_sector_count if mini_fat else CFB_END_OF_CHAIN
    first_directory_sector = fat_sector_count + minifat_sector_count
    current_sector = first_directory_sector + 1
    root_start = current_sector if mini_stream else CFB_END_OF_CHAIN
    current_sector += root_sector_count
    for stream in regular_streams:
        stream.start = current_sector
        current_sector += _sector_count(stream.data)
    directory_stream = _build_directory_stream(streams, root_start=root_start, root_size=len(mini_stream))
    sector_payloads = [b""] * fat_sector_count
    sector_payloads.extend(_chunk_sectors(minifat_stream))
    sector_payloads.extend(_chunk_sectors(directory_stream))
    sector_payloads.extend(_chunk_sectors(mini_stream))
    for stream in regular_streams:
        sector_payloads.extend(_chunk_sectors(stream.data))
    fat = _build_fat(
        _FatLayout(
            sector_count=len(sector_payloads),
            fat_sector_count=fat_sector_count,
            minifat_start=first_minifat_sector,
            minifat_sector_count=minifat_sector_count,
            directory_start=first_directory_sector,
            root_start=root_start,
            root_sector_count=root_sector_count,
            regular_streams=regular_streams,
        )
    )
    fat_sectors = _chunk_sectors(_pack_fat(fat))
    sector_payloads[:fat_sector_count] = fat_sectors
    header = _cfb_header(fat_sector_count, first_directory_sector, first_minifat_sector, minifat_sector_count)
    return header + b"".join(_pad(payload, CFB_SECTOR_SIZE) for payload in sector_payloads)


def _build_mini_stream(streams: list[_CfbStream]) -> tuple[bytes, list[int]]:
    mini_sectors: list[bytes] = []
    mini_fat: list[int] = []
    for stream in streams:
        if not stream.mini:
            continue
        stream.start = len(mini_sectors)
        chunks = _chunk_units(stream.data, CFB_MINI_SECTOR_SIZE)
        mini_sectors.extend(chunks)
        for offset in range(len(chunks)):
            mini_fat.append(stream.start + offset + 1 if offset < len(chunks) - 1 else CFB_END_OF_CHAIN)
    return b"".join(mini_sectors), mini_fat


def _build_directory_stream(streams: list[_CfbStream], *, root_start: int, root_size: int) -> bytes:
    entries = [
        _directory_entry(
            _DirectoryEntry(
                "Root Entry",
                5,
                child=1 if streams else CFB_NO_STREAM,
                start=root_start,
                size=root_size,
                clsid=PACKAGE_CLSID,
            )
        )
    ]
    for index, stream in enumerate(streams, start=1):
        right = index + 1 if index < len(streams) else CFB_NO_STREAM
        entries.append(
            _directory_entry(_DirectoryEntry(stream.name, 2, right=right, start=stream.start, size=stream.size))
        )
    return _pad(b"".join(entries), CFB_SECTOR_SIZE)


def _directory_entry(spec: _DirectoryEntry) -> bytes:
    name_bytes = spec.name.encode("utf-16le") + b"\x00\x00"
    entry = bytearray(128)
    entry[: len(name_bytes)] = name_bytes
    struct.pack_into("<H", entry, 64, len(name_bytes))
    entry[66] = spec.entry_type
    entry[67] = 1
    struct.pack_into("<iii", entry, 68, CFB_NO_STREAM, spec.right, spec.child)
    entry[80:96] = spec.clsid
    struct.pack_into("<i", entry, 116, spec.start)
    struct.pack_into("<Q", entry, 120, spec.size)
    return bytes(entry)


def _build_fat(layout: _FatLayout) -> list[int]:
    fat: list[int] = [CFB_FREE_SECTOR] * layout.sector_count
    for index in range(layout.fat_sector_count):
        fat[index] = CFB_FAT_SECTOR
    _mark_fat_chain(fat, layout.minifat_start, layout.minifat_sector_count)
    _mark_fat_chain(fat, layout.directory_start, 1)
    _mark_fat_chain(fat, layout.root_start, layout.root_sector_count)
    for stream in layout.regular_streams:
        _mark_fat_chain(fat, stream.start, _sector_count(stream.data))
    return fat


def _mark_fat_chain(fat: list[int], start: int, count: int) -> None:
    if start < 0 or count == 0:
        return
    for offset in range(count):
        fat[start + offset] = start + offset + 1 if offset < count - 1 else CFB_END_OF_CHAIN


def _cfb_header(
    fat_sector_count: int,
    first_directory_sector: int,
    first_minifat_sector: int,
    minifat_sector_count: int,
) -> bytes:
    header = bytearray(CFB_SECTOR_SIZE)
    header[:8] = bytes.fromhex("d0cf11e0a1b11ae1")
    struct.pack_into("<HHHHH", header, 24, 0x003E, 0x0003, 0xFFFE, 9, 6)
    struct.pack_into(
        "<IIiIIi",
        header,
        40,
        0,
        fat_sector_count,
        first_directory_sector,
        0,
        CFB_MINI_STREAM_CUTOFF,
        first_minifat_sector,
    )
    struct.pack_into("<Ii", header, 64, minifat_sector_count, CFB_END_OF_CHAIN)
    struct.pack_into("<I", header, 72, 0)
    for index in range(109):
        value = index if index < fat_sector_count else CFB_FREE_SECTOR
        struct.pack_into("<i", header, 76 + index * 4, value)
    return bytes(header)


def _pack_fat(fat: list[int]) -> bytes:
    if not fat:
        return b""
    padding = (_sector_count(struct.pack(f"<{len(fat)}i", *fat)) * 128) - len(fat)
    padded = fat + ([CFB_FREE_SECTOR] * padding)
    return struct.pack(f"<{len(padded)}i", *padded)


def _fat_sector_count(payload_sector_count: int) -> int:
    fat_sector_count = 1
    while fat_sector_count * 128 < payload_sector_count + fat_sector_count:
        fat_sector_count += 1
    return fat_sector_count


def _chunk_sectors(data: bytes) -> list[bytes]:
    return _chunk_units(data, CFB_SECTOR_SIZE)


def _chunk_units(data: bytes, unit_size: int) -> list[bytes]:
    if not data:
        return []
    return [data[index : index + unit_size] for index in range(0, len(data), unit_size)]


def _sector_count(data: bytes) -> int:
    return (len(data) + CFB_SECTOR_SIZE - 1) // CFB_SECTOR_SIZE


def _pad(data: bytes, size: int) -> bytes:
    remainder = len(data) % size
    return data if remainder == 0 else data + (b"\x00" * (size - remainder))
