"""Read-only DOCX inventory and conservative field manifest. Never rewrites the master."""

import hashlib
import io
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile
from zlib import error as ZlibError

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}
MAX_ARCHIVE = 20 * 1024 * 1024
MAX_EXPANDED = 64 * 1024 * 1024
PROTECTED_STYLES = {"title", "subtitle", "role", "contact", "dates"}
SECTIONS = {
    "resumo profissional": "summary",
    "experiencia profissional": "experience",
    "projetos comerciais e proprios": "projects",
}


class ResumeError(ValueError):
    """Safe error code; never includes the resume's text or filesystem paths."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def fold(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c)
    ).strip()


def load_package(path: Path) -> tuple[bytes, dict[str, bytes], ET.Element]:
    if path.suffix.lower() != ".docx" or path.is_symlink():
        raise ResumeError("unsupported_resume_file")
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_ARCHIVE + 1)
        if len(raw) > MAX_ARCHIVE:
            raise ResumeError("resume_too_large")
        with ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if len(entries) > 1000 or len(names) != len(set(names)):
                raise ResumeError("invalid_docx_archive")
            if sum(entry.file_size for entry in entries) > MAX_EXPANDED:
                raise ResumeError("expanded_resume_too_large")
            for entry in entries:
                name = PurePosixPath(entry.filename)
                if name.is_absolute() or ".." in name.parts or "\\" in entry.filename:
                    raise ResumeError("invalid_docx_archive")
                if "vba" in entry.filename.casefold() or entry.flag_bits & 1:
                    raise ResumeError("active_or_encrypted_document")
            parts = {entry.filename: archive.read(entry) for entry in entries}
        if not {"[Content_Types].xml", "_rels/.rels", "word/document.xml"} <= parts.keys():
            raise ResumeError("invalid_docx_package")
        for name, data in parts.items():
            if name.endswith((".xml", ".rels")) and re.search(
                rb"<!\s*(DOCTYPE|ENTITY)", data.replace(b"\x00", b""), re.I
            ):
                raise ResumeError("unsafe_xml")
        content_types = ET.fromstring(parts["[Content_Types].xml"])
        main_type = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
        )
        if not any(
            node.get("PartName") == "/word/document.xml" and node.get("ContentType") == main_type
            for node in content_types
        ):
            raise ResumeError("invalid_docx_content_type")
        relationships = ET.fromstring(parts["_rels/.rels"])
        rel_type = (
            "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
        )
        if not any(
            node.get("Type") == rel_type
            and node.get("Target") == "word/document.xml"
            and node.get("TargetMode") != "External"
            for node in relationships
        ):
            raise ResumeError("invalid_docx_relationship")
        root = ET.fromstring(parts["word/document.xml"])
        if root.tag != f"{{{W}}}document" or root.find("w:body", NS) is None:
            raise ResumeError("invalid_document_root")
    except (
        OSError,
        BadZipFile,
        ET.ParseError,
        RuntimeError,
        NotImplementedError,
        EOFError,
        ZlibError,
    ):
        raise ResumeError("unreadable_docx") from None
    return raw, parts, root


def inspect_template(path: Path) -> dict:
    raw, parts, root = load_package(path)
    paths = {}
    parents = {}

    stack = [(root, [])]
    while stack:
        node, node_path = stack.pop()
        if len(node_path) > 64 or len(paths) > 100_000:
            raise ResumeError("document_too_complex")
        paths[id(node)] = node_path
        for index, child in enumerate(node):
            parents[id(child)] = node
            stack.append((child, node_path + [index]))

    tracked = any(root.findall(f".//w:{tag}", NS) for tag in ["ins", "del", "moveFrom", "moveTo"])
    fields = []
    paragraphs = list(root.iter(f"{{{W}}}p"))
    section = "protected"
    for paragraph_index, paragraph in enumerate(paragraphs):
        style_node = paragraph.find("w:pPr/w:pStyle", NS)
        style = style_node.get(f"{{{W}}}val", "") if style_node is not None else ""
        text_nodes = list(paragraph.iter(f"{{{W}}}t"))
        text = "".join(node.text or "" for node in text_nodes)
        heading = fold(style).startswith("heading")
        if heading:
            section = SECTIONS.get(fold(text), "protected")
        ancestor = parents.get(id(paragraph))
        nested_container = False
        while ancestor is not None:
            if ancestor.tag in {
                f"{{{W}}}{tag}" for tag in ["tbl", "txbxContent", "sdt", "ins", "del"]
            }:
                nested_container = True
            ancestor = parents.get(id(ancestor))
        protected = heading or fold(style) in PROTECTED_STYLES or nested_container
        complex_paragraph = any(
            paragraph.findall(f".//w:{tag}", NS)
            for tag in ["hyperlink", "drawing", "fldChar", "instrText", "object"]
        )
        for text_index, node in enumerate(text_nodes):
            original = node.text or ""
            direct_run = parents.get(id(node))
            simple_run = (
                direct_run is not None
                and direct_run.tag == f"{{{W}}}r"
                and parents.get(id(direct_run)) is paragraph
                and len(list(direct_run.iter(f"{{{W}}}t"))) == 1
            )
            narrative = section == "summary" or (section == "experience" and style == "ListBullet")
            if section == "projects":
                narrative = len(text_nodes) > 1 and text_index == len(text_nodes) - 1
            candidate = (
                not protected
                and not tracked
                and not complex_paragraph
                and simple_run
                and narrative
                and len(original.split()) >= 5
                and not re.search(r"\d|https?://|[\w.+-]+@[\w.-]+", text)
            )
            fields.append(
                {
                    "field_id": f"p{paragraph_index:04d}_t{text_index:02d}",
                    "paragraph_index": paragraph_index,
                    "text_index": text_index,
                    "xml_path": paths[id(node)],
                    "section": section,
                    "style": style,
                    "original_text": original,
                    "original_sha256": digest(original.encode("utf-8")),
                    "max_characters": len(original),
                    "candidate": bool(candidate),
                    "protection_reason": ""
                    if candidate
                    else "protected_or_requires_manual_mapping",
                }
            )
    core = {
        "schema_version": 1,
        "template_sha256": digest(raw),
        "parts_sha256": {name: digest(data) for name, data in sorted(parts.items())},
        "paragraph_count": len(paragraphs),
        "table_count": len(list(root.iter(f"{{{W}}}tbl"))),
        "tracked_changes": tracked,
        "fields": fields,
        "validation": {"factual": "pending", "visual": "not_run", "pdf_ats": "not_run"},
    }
    return {**core, "manifest_hash": digest(canonical_json(core)), "approval": None}


def validate_manifest(path: Path, manifest: dict) -> dict:
    expected = inspect_template(path)
    provided = {key: value for key, value in manifest.items() if key != "approval"}
    baseline = {key: value for key, value in expected.items() if key != "approval"}
    if provided != baseline:
        raise ResumeError("manifest_template_mismatch")
    return expected


def approve_manifest(
    path: Path,
    manifest: dict,
    *,
    manifest_hash: str,
    field_ids: list[str],
    actor: str,
    approved_at: str,
) -> dict:
    validate_manifest(path, manifest)
    if manifest_hash != manifest["manifest_hash"]:
        raise ResumeError("manifest_hash_mismatch")
    if not field_ids or len(field_ids) != len(set(field_ids)) or not actor.strip():
        raise ResumeError("invalid_manifest_approval")
    candidates = {field["field_id"] for field in manifest["fields"] if field["candidate"]}
    if not set(field_ids) <= candidates:
        raise ResumeError("protected_field_selected")
    return {
        **manifest,
        "approval": {
            "manifest_hash": manifest_hash,
            "field_ids": sorted(field_ids),
            "actor": actor,
            "approved_at": approved_at,
        },
    }


def resolve_source(storage_root: Path, filename: str) -> Path:
    if (
        not filename
        or ":" in filename
        or "/" in filename
        or "\\" in filename
        or filename in {".", ".."}
    ):
        raise ResumeError("invalid_resume_filename")
    root = storage_root.resolve()
    source = root / filename
    if source.is_symlink() or not source.is_file() or source.resolve().parent != root:
        raise ResumeError("resume_source_not_found")
    return source


def store_template(storage_root: Path, source: Path) -> tuple[str, dict]:
    manifest = inspect_template(source)
    expected_hash = manifest["template_sha256"]
    root = storage_root.resolve()
    directory = root / "templates" / expected_hash
    if directory.is_symlink() or not directory.resolve().is_relative_to(root):
        raise ResumeError("invalid_storage_path")
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "master.docx"
    raw, _, _ = load_package(source)
    if digest(raw) != expected_hash:
        raise ResumeError("master_changed_during_import")
    if target.is_symlink():
        raise ResumeError("invalid_storage_path")
    try:
        with target.open("xb") as handle:
            handle.write(raw)
    except FileExistsError:
        if digest(target.read_bytes()) != expected_hash:
            raise ResumeError("stored_master_integrity_failure") from None
    draft_path = directory / "manifest.draft.json"
    if draft_path.is_symlink():
        raise ResumeError("invalid_storage_path")
    try:
        with draft_path.open("x", encoding="utf-8") as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2)
    except FileExistsError:
        try:
            existing = json.loads(draft_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ResumeError("draft_manifest_integrity_failure") from None
        if existing != manifest:
            raise ResumeError("draft_manifest_integrity_failure") from None
    review_path = directory / "manifest.review.md"
    if review_path.is_symlink():
        raise ResumeError("invalid_storage_path")
    review = [
        "# Resume field manifest for review",
        "",
        "Status: DRAFT. No fields have been authorized.",
        "",
        "Template SHA-256: " + expected_hash,
        "Manifest hash: " + manifest["manifest_hash"],
        "",
        "Only the candidate fields below can be selected through explicit authorization.",
        "All other text, dates, numbers, identity, contacts, styles "
        "and package parts stay protected.",
        "Factual verification, visual validation and PDF/ATS checks remain pending.",
        "",
    ]
    for field in manifest["fields"]:
        if field["candidate"]:
            review.extend(
                [
                    "## " + field["field_id"],
                    "",
                    "Section: " + field["section"],
                    "Maximum characters: " + str(field["max_characters"]),
                    "",
                    "Original text:",
                    "",
                ]
            )
            review.extend("> " + line for line in field["original_text"].splitlines())
            review.append("")
    try:
        with review_path.open("x", encoding="utf-8") as handle:
            handle.write("\n".join(review))
    except FileExistsError:
        pass
    if digest(source.read_bytes()) != expected_hash or digest(target.read_bytes()) != expected_hash:
        raise ResumeError("master_changed_during_import")
    return target.relative_to(root).as_posix(), manifest
