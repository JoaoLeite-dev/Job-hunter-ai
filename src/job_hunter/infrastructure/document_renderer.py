"""Bounded, isolated LibreOffice conversion for the application runtime."""

import os
import re
import signal
import subprocess
import xml.etree.ElementTree as ET
from functools import cached_property
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from job_hunter.infrastructure.resumes import ResumeError, load_package


class RenderError(ResumeError):
    pass


def check_renderable(source: Path) -> bytes:
    raw, parts, _ = load_package(source)
    for name, content in parts.items():
        if name.startswith("word/embeddings/") or name.lower().endswith(".svg"):
            raise RenderError("unsupported_embedded_content")
        if name.endswith(".rels"):
            for relation in ET.fromstring(content):
                if relation.get("TargetMode", "").strip().casefold() == "external":
                    target = relation.get("Target", "")
                    if not relation.get("Type", "").endswith("/hyperlink") or urlsplit(
                        target
                    ).scheme.lower() not in {"https", "http", "mailto", "tel"}:
                        raise RenderError("external_document_resource_blocked")
        if name.endswith(".xml"):
            xml = ET.fromstring(content)
            for node in xml.iter():
                local = node.tag.split("}")[-1]
                if local == "object":
                    raise RenderError("unsupported_embedded_content")
                instruction = (node.text or "") if local == "instrText" else ""
                if local == "fldSimple":
                    instruction = " ".join(node.attrib.values())
                if re.search(
                    r"\b(DDEAUTO|DDE|INCLUDETEXT|INCLUDEPICTURE|LINK)\b", instruction, re.I
                ):
                    raise RenderError("external_document_field_blocked")
    return raw


def renderer_environment(home: str) -> dict:
    # The converter never needs database credentials, API tokens or OAuth secrets.
    allowed = {"PATH", "LANG", "LC_ALL", "TZ", "SYSTEMROOT", "WINDIR"}
    return {
        **{k: v for k, v in os.environ.items() if k in allowed},
        "HOME": home,
        "TMPDIR": home,
        "SAL_DISABLE_OPENCL": "1",
    }


class LibreOfficeRenderer:
    def __init__(self, binary: str = "/usr/bin/libreoffice", timeout: int = 45):
        self.binary = Path(binary)
        self.timeout = timeout
        if not self.binary.is_absolute() or not self.binary.is_file():
            raise RenderError("renderer_unavailable")

    @cached_property
    def version(self) -> str:
        try:
            with TemporaryDirectory(prefix="jobhunter_version_") as temporary:
                result = subprocess.run(
                    [str(self.binary), "--version"],
                    capture_output=True,
                    timeout=5,
                    check=False,
                    env=renderer_environment(temporary),
                )
        except (OSError, subprocess.TimeoutExpired):
            raise RenderError("renderer_version_unavailable") from None
        version = result.stdout.decode("utf-8", errors="replace").strip()
        if result.returncode or not version.startswith("LibreOffice"):
            raise RenderError("renderer_version_unavailable")
        return version[:200]

    def render(self, source: Path) -> bytes:
        raw = check_renderable(source)
        with TemporaryDirectory(prefix="jobhunter_render_") as temporary:
            directory = Path(temporary)
            input_path = directory / "document.docx"
            input_path.write_bytes(raw)
            output = directory / "output"
            output.mkdir()
            profile = directory / "profile"
            arguments = [
                str(self.binary),
                "--headless",
                "--nologo",
                "--nodefault",
                "--nofirststartwizard",
                "-env:UserInstallation=" + profile.as_uri(),
                "--convert-to",
                "pdf:writer_pdf_Export",
                "--outdir",
                str(output),
                str(input_path),
            ]
            environment = renderer_environment(temporary)
            try:
                process = subprocess.Popen(
                    arguments,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=environment,
                    start_new_session=os.name != "nt",
                )
                try:
                    process.communicate(timeout=self.timeout)
                except subprocess.TimeoutExpired:
                    if os.name != "nt":
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                    process.communicate()
                    raise RenderError("renderer_timeout") from None
            except OSError:
                raise RenderError("renderer_process_failed") from None
            pdf = output / "document.pdf"
            if process.returncode or not pdf.is_file():
                raise RenderError("pdf_conversion_failed")
            if not 0 < pdf.stat().st_size <= 32 * 1024 * 1024:
                raise RenderError("invalid_pdf_size")
            return pdf.read_bytes()
