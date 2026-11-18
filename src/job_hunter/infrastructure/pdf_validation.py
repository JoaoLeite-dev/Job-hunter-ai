"""PDF text, reading order and conservative layout checks against the same-engine baseline."""

import re
import unicodedata

import pymupdf

from job_hunter.infrastructure.document_renderer import RenderError


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text).replace("\u00ad", "")).strip()


def open_pdf(data: bytes):
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except (RuntimeError, ValueError):
        raise RenderError("invalid_rendered_pdf") from None
    if document.needs_pass or not 1 <= document.page_count <= 20:
        document.close()
        raise RenderError("unsupported_pdf_document")
    return document


def _locations(document, text: str) -> list:
    return [
        (index, tuple(rect))
        for index, page in enumerate(document)
        for rect in page.search_for(text)
    ]


def _same_locations(left: list, right: list, tolerance: float) -> bool:
    return len(left) == len(right) and all(
        a[0] == b[0] and max(abs(x - y) for x, y in zip(a[1], b[1], strict=True)) <= tolerance
        for a, b in zip(left, right, strict=True)
    )


def _contains(box, words, tolerance):
    return all(words[i] >= box[i] - tolerance for i in [0, 1]) and all(
        words[i] <= box[i] + tolerance for i in [2, 3]
    )


def compare_pdfs(
    original: bytes, variant: bytes, manifest: dict, edits: list, *, tolerance: float = 1.5
) -> dict:
    if not 0 <= tolerance <= 3:
        raise ValueError("Invalid layout tolerance")
    with open_pdf(original) as before, open_pdf(variant) as after:
        flags = pymupdf.TEXTFLAGS_TEXT | pymupdf.TEXT_DEHYPHENATE
        original_text = normalize(" ".join(p.get_text("text", flags=flags) for p in before))
        variant_text = normalize(" ".join(p.get_text("text", flags=flags) for p in after))
        if "\ufffd" in original_text or "\ufffd" in variant_text:
            raise RenderError("unreadable_pdf_glyphs")
        if not original_text or not variant_text:
            raise RenderError("pdf_text_missing")
        replacements = {e["field_id"]: e["proposed_text"] for e in edits}
        missing = []
        expected_pdf_replacements = []
        out_of_order = []
        cursor_before = cursor_after = 0
        for field in manifest["fields"]:
            original_value = normalize(field["original_text"])
            expected = normalize(replacements.get(field["field_id"], field["original_text"]))
            if not original_value:
                continue
            start_before = original_text.find(original_value, cursor_before)
            start_after = variant_text.find(expected, cursor_after)
            if original_value not in original_text or expected not in variant_text:
                missing.append(field["field_id"])
            elif start_before < 0 or start_after < 0:
                out_of_order.append(field["field_id"])
            else:
                if field["field_id"] in replacements:
                    expected_pdf_replacements.append(
                        (start_before, start_before + len(original_value), expected)
                    )
                cursor_before = start_before + len(original_value)
                cursor_after = start_after + len(expected)
        expected_pdf_text = original_text
        for start, end, value in sorted(expected_pdf_replacements, reverse=True):
            expected_pdf_text = expected_pdf_text[:start] + value + expected_pdf_text[end:]
        unexpected_text = expected_pdf_text != variant_text
        ats = {
            "status": "passed"
            if not missing and not out_of_order and not unexpected_text
            else "failed",
            "method": "literal_text_and_reading_order",
            "missing_field_ids": missing,
            "out_of_order_field_ids": out_of_order,
            "unexpected_text": unexpected_text,
        }
        issues = []
        checked = 0
        if before.page_count != after.page_count:
            issues.append("page_count_changed")
        else:
            for old_page, new_page in zip(before, after, strict=True):
                if any(
                    abs(a - b) > tolerance
                    for a, b in zip(old_page.rect, new_page.rect, strict=True)
                ):
                    issues.append("page_dimensions_changed")
                for page in [old_page, new_page]:
                    if any(
                        not _contains(tuple(page.rect), w[:4], tolerance)
                        for w in page.get_text("words")
                    ):
                        issues.append("text_outside_page")
                old_images = [
                    (tuple(i["bbox"]), i.get("digest"))
                    for i in old_page.get_image_info(hashes=True)
                ]
                new_images = [
                    (tuple(i["bbox"]), i.get("digest"))
                    for i in new_page.get_image_info(hashes=True)
                ]
                if len(old_images) != len(new_images) or any(
                    a[1] != b[1]
                    or max(abs(x - y) for x, y in zip(a[0], b[0], strict=True)) > tolerance
                    for a, b in zip(old_images, new_images, strict=True)
                ):
                    issues.append("image_layout_changed")
                old_shapes = [(d["type"], tuple(d["rect"])) for d in old_page.get_drawings()]
                new_shapes = [(d["type"], tuple(d["rect"])) for d in new_page.get_drawings()]
                if len(old_shapes) != len(new_shapes) or any(
                    a[0] != b[0]
                    or max(abs(x - y) for x, y in zip(a[1], b[1], strict=True)) > tolerance
                    for a, b in zip(old_shapes, new_shapes, strict=True)
                ):
                    issues.append("vector_layout_changed")
            for field in manifest["fields"]:
                value = normalize(field["original_text"])
                if len(value) < 3:
                    continue
                left = _locations(before, value)
                if field["field_id"] in replacements:
                    right = _locations(after, normalize(replacements[field["field_id"]]))
                    # Changed text must remain inside the original text's line container.
                    if not left or not right or {p for p, _ in left} != {p for p, _ in right}:
                        issues.append("edited_text_position_unknown")
                        continue
                    for page_index in {p for p, _ in left}:
                        old_rect = pymupdf.Rect()
                        new_rect = pymupdf.Rect()
                        for p, box in left:
                            if p == page_index:
                                old_rect |= pymupdf.Rect(box)
                        for p, box in right:
                            if p == page_index:
                                new_rect |= pymupdf.Rect(box)
                        if (
                            abs(old_rect.x0 - new_rect.x0) > tolerance
                            or abs(old_rect.y0 - new_rect.y0) > tolerance
                            or not _contains(tuple(old_rect), tuple(new_rect), tolerance)
                        ):
                            issues.append("edited_text_exceeds_original_bounds")
                else:
                    right = _locations(after, value)
                    if not left or not _same_locations(left, right, tolerance):
                        issues.append("protected_text_moved")
                    else:
                        checked += 1
            if not checked:
                issues.append("no_protected_anchors_verified")
        return {
            "visual": {
                "status": "passed" if not issues else "failed",
                "method": "text_anchors_images_vectors",
                "tolerance_points": tolerance,
                "original_pages": before.page_count,
                "variant_pages": after.page_count,
                "protected_anchors_checked": checked,
                "issues": sorted(set(issues)),
            },
            "pdf_ats": ats,
        }
