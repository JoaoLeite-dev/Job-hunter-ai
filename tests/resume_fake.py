"""Synthetic OOXML fixture; no personal resume content is committed."""

from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
MAIN_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"


def make_resume(path):
    def run(text, properties=""):
        return f'<w:r>{properties}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'

    def paragraph(runs, style=""):
        properties = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
        return f"<w:p>{properties}{''.join(runs)}</w:p>"

    body = "".join(
        [
            paragraph([run("Example Person")], "Title"),
            paragraph([run("person@example.org")], "Contact"),
            paragraph([run("Resumo profissional")], "Heading1"),
            paragraph(
                [
                    run(
                        "Developer building tested web applications with Python",
                        "<w:rPr><w:b/></w:rPr>",
                    ),
                    run(
                        " and accessible interfaces using React components", "<w:rPr><w:i/></w:rPr>"
                    ),
                ]
            ),
            paragraph([run("Experiencia profissional")], "Heading1"),
            paragraph([run("Engineer | Example Company")]),
            paragraph([run("2022 to present")], "Dates"),
            paragraph(
                [run("Built responsive interfaces and tested backend integrations")], "ListBullet"
            ),
            paragraph([run("Mentored 10 engineers and improved processes")], "ListBullet"),
            paragraph([run("Projetos comerciais e proprios")], "Heading1"),
            paragraph(
                [
                    run("Project label", "<w:rPr><w:b/></w:rPr>"),
                    run("Built an inventory system for an example business"),
                ]
            ),
            "<w:tbl><w:tr><w:tc>"
            + paragraph([run("Nested table content must stay completely protected")])
            + "</w:tc></w:tr></w:tbl>",
            '<w:sectPr><w:pgMar w:top="720" w:bottom="720"/></w:sectPr>',
        ]
    )
    header = paragraph([run("Protected header")])
    parts = {
        "[Content_Types].xml": (
            f'<Types xmlns="{CT}"><Override '
            f'PartName="/word/document.xml" ContentType="{MAIN_TYPE}"/></Types>'
        ),
        "_rels/.rels": (
            f'<Relationships xmlns="{REL}"><Relationship Id="rId1" '
            f'Type="{OFFICE_REL}" Target="word/document.xml"/></Relationships>'
        ),
        "word/document.xml": f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>',
        "word/styles.xml": f'<w:styles xmlns:w="{W}"><w:style w:styleId="Title"/></w:styles>',
        "word/header1.xml": f'<w:hdr xmlns:w="{W}">{header}</w:hdr>',
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        for name, value in parts.items():
            archive.writestr(name, value)
    return path
