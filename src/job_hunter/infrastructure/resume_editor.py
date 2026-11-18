"""Deterministic field edits backed by explicitly confirmed wording."""

import io
import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from xml.parsers import expat
from xml.sax.saxutils import escape
from zipfile import BadZipFile, ZipFile

from job_hunter.infrastructure.resumes import (
    ResumeError,
    W,
    canonical_json,
    digest,
    load_package,
    validate_manifest,
)


@dataclass(frozen=True)
class WordingFact:
    id: str
    category: str
    claim: str
    evidence_source: str
    verified: bool
    version: int


def wording_source(manifest: dict, field_id: str) -> str:
    return f"resume:{manifest['template_sha256']}:{field_id}"


def authorized_fields(master: Path, manifest: dict) -> dict:
    validate_manifest(master, manifest)
    approval = manifest.get("approval")
    if (
        not isinstance(approval, dict)
        or approval.get("manifest_hash") != manifest["manifest_hash"]
        or not approval.get("actor")
        or not approval.get("approved_at")
    ):
        raise ResumeError("manifest_not_authorized")
    allowed = approval.get("field_ids")
    candidates = {f["field_id"]: f for f in manifest["fields"] if f["candidate"]}
    if (
        not isinstance(allowed, list)
        or not allowed
        or any(not isinstance(x, str) for x in allowed)
        or len(allowed) != len(set(allowed))
        or not set(allowed) <= candidates.keys()
    ):
        raise ResumeError("invalid_field_authorization")
    return {field_id: candidates[field_id] for field_id in allowed}


def validate_wording(master: Path, manifest: dict, field_id: str, wording: str) -> dict:
    allowed = authorized_fields(master, manifest)
    if field_id not in allowed:
        raise ResumeError("field_not_authorized")
    field = allowed[field_id]
    if not isinstance(wording, str) or not wording.strip():
        raise ResumeError("invalid_wording")
    if len(wording) > field["max_characters"]:
        raise ResumeError("field_length_exceeded")
    if any(unicodedata.category(c) in {"Cc", "Cs", "Cf"} for c in wording):
        raise ResumeError("unsupported_text_characters")
    if re.search(r"\d|https?://|[\w.+-]+@[\w.-]+", wording):
        raise ResumeError("protected_data_in_wording")
    _, _, root = load_package(master)
    node = root
    for index in field["xml_path"]:
        node = node[index]
    if len(node) or node.tag != f"{{{W}}}t":
        raise ResumeError("complex_text_field")
    if (
        wording != wording.strip()
        and node.get("{http://www.w3.org/XML/1998/namespace}space") != "preserve"
    ):
        raise ResumeError("whitespace_would_change_layout")
    return field


def validate_edits(
    master: Path, manifest: dict, edits: list, facts: list[WordingFact]
) -> tuple[list, list]:
    if not isinstance(edits, list) or not 1 <= len(edits) <= 100:
        raise ResumeError("invalid_edit_plan")
    fact_map = {fact.id: fact for fact in facts}
    seen = set()
    normalized = []
    evidence = {}
    for edit in edits:
        keys = {"field_id", "original_text", "proposed_text", "supporting_fact_ids"}
        if (
            not isinstance(edit, dict)
            or set(edit) != keys
            or not all(isinstance(edit[k], str) for k in keys - {"supporting_fact_ids"})
        ):
            raise ResumeError("invalid_edit_schema")
        field_id = edit["field_id"]
        if field_id in seen:
            raise ResumeError("duplicate_edit_field")
        seen.add(field_id)
        field = validate_wording(master, manifest, field_id, edit["proposed_text"])
        if edit["original_text"] != field["original_text"]:
            raise ResumeError("original_text_mismatch")
        if edit["proposed_text"] == edit["original_text"]:
            raise ResumeError("empty_edit")
        ids = edit["supporting_fact_ids"]
        if (
            not isinstance(ids, list)
            or not ids
            or any(not isinstance(i, str) for i in ids)
            or len(ids) != len(set(ids))
        ):
            raise ResumeError("verified_wording_required")
        for fact_id in ids:
            fact = fact_map.get(fact_id)
            if (
                not fact
                or not fact.verified
                or fact.category != "resume_wording"
                or fact.claim != edit["proposed_text"]
                or fact.evidence_source != wording_source(manifest, field_id)
            ):
                raise ResumeError("verified_wording_required")
            evidence[fact_id] = {
                "id": fact.id,
                "version": fact.version,
                "claim_sha256": digest(fact.claim.encode("utf-8")),
                "evidence_source": fact.evidence_source,
            }
        normalized.append({**edit, "supporting_fact_ids": sorted(ids)})
    return sorted(normalized, key=lambda e: e["field_id"]), [evidence[k] for k in sorted(evidence)]


def _text_spans(xml: bytes) -> dict:
    # Expat reports byte offsets. Never serialize the XML tree: namespace prefixes,
    # unsupported OOXML extensions, whitespace and attributes stay byte-for-byte intact.
    try:
        xml.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ResumeError("unsupported_document_encoding") from None
    declaration = re.match(rb"(?:\xef\xbb\xbf)?<\?xml[^>]*\?>", xml)
    if declaration:
        encoding = re.search(rb'encoding\s*=\s*["\x27]([^"\x27]+)', declaration.group(), re.I)
        if encoding and encoding.group(1).lower().replace(b"-", b"") != b"utf8":
            raise ResumeError("unsupported_document_encoding")
    parser = expat.ParserCreate(namespace_separator="}")
    stack = []
    spans = {}

    def start(name, attributes):
        if stack:
            path = stack[-1]["path"] + (stack[-1]["children"],)
            stack[-1]["children"] += 1
        else:
            path = ()
        entry = {"path": path, "children": 0}
        if name == W + "}t":
            index = parser.CurrentByteIndex
            quote = None
            while index < len(xml):
                char = xml[index]
                if quote:
                    if char == quote:
                        quote = None
                elif char in (34, 39):
                    quote = char
                elif char == 62:
                    break
                index += 1
            entry["start"] = index + 1
        stack.append(entry)

    def end(name):
        entry = stack.pop()
        if name == W + "}t" and "start" in entry:
            spans[entry["path"]] = (entry["start"], parser.CurrentByteIndex)

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    try:
        parser.Parse(xml, True)
    except expat.ExpatError:
        raise ResumeError("unreadable_document_xml") from None
    return spans


def patch_xml(xml: bytes, manifest: dict, edits: list) -> bytes:
    spans = _text_spans(xml)
    fields = {field["field_id"]: field for field in manifest["fields"]}
    replacements = []
    for edit in edits:
        field = fields[edit["field_id"]]
        span = spans.get(tuple(field["xml_path"]))
        if not span or span[0] > span[1]:
            raise ResumeError("text_anchor_not_found")
        replacements.append((*span, escape(edit["proposed_text"]).encode("utf-8")))
    result = xml
    for start, end, value in sorted(replacements, reverse=True):
        result = result[:start] + value + result[end:]
    try:
        ET.fromstring(result)
    except ET.ParseError:
        raise ResumeError("invalid_edited_xml") from None
    return result


def build_docx(
    master: Path, manifest: dict, edits: list, facts: list[WordingFact]
) -> tuple[bytes, dict]:
    edits, evidence = validate_edits(master, manifest, edits, facts)
    raw, parts, _ = load_package(master)
    edited = patch_xml(parts["word/document.xml"], manifest, edits)
    output = io.BytesIO()
    with ZipFile(io.BytesIO(raw)) as source, ZipFile(output, "w") as destination:
        for entry in source.infolist():
            content = edited if entry.filename == "word/document.xml" else parts[entry.filename]
            destination.writestr(entry, content)
    result = output.getvalue()
    validate_structure(master, result, manifest, edits)
    plan_hash = digest(
        canonical_json(
            {
                "manifest_hash": manifest["manifest_hash"],
                "approval": manifest["approval"],
                "edits": edits,
                "evidence": evidence,
            }
        )
    )
    return result, {
        "plan_hash": plan_hash,
        "edits": edits,
        "evidence": evidence,
        "factual": {"status": "passed", "method": "exact_confirmed_wording"},
        "structural": {"status": "passed"},
        "docx_ats": {"status": "passed", "method": "ordered_xml_text"},
        "visual": {"status": "not_run"},
        "pdf_ats": {"status": "not_run"},
        "state": "validation_pending",
    }


def validate_structure(master: Path, output: bytes, manifest: dict, edits: list) -> None:
    validate_manifest(master, manifest)
    _, parts, _ = load_package(master)
    expected = patch_xml(parts["word/document.xml"], manifest, edits)
    try:
        with ZipFile(io.BytesIO(output)) as archive:
            if archive.namelist() != list(parts):
                raise ResumeError("document_parts_changed")
            for name, content in parts.items():
                if archive.read(name) != (expected if name == "word/document.xml" else content):
                    raise ResumeError("protected_document_content_changed")
            edited_root = ET.fromstring(archive.read("word/document.xml"))
    except (OSError, BadZipFile, ET.ParseError):
        raise ResumeError("invalid_variant_document") from None
    expected_root = ET.fromstring(expected)
    expected_text = [node.text or "" for node in expected_root.iter(f"{{{W}}}t")]
    edited_text = [node.text or "" for node in edited_root.iter(f"{{{W}}}t")]
    if edited_text != expected_text:
        raise ResumeError("document_text_order_changed")
    if digest(master.read_bytes()) != manifest["template_sha256"]:
        raise ResumeError("master_integrity_failure")
