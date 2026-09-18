"""Generate the Finance Paymob project handbook PDF from its Markdown source."""

from __future__ import annotations

import argparse
import html
import re
from pathlib import Path

from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    HRFlowable,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
)
from reportlab.platypus.tableofcontents import TableOfContents


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "docs" / "FINANCE_PAYMOB_PROJECT_DOCUMENTATION.md"
DEFAULT_OUTPUT = ROOT / "Finance Paymob - Project Documentation.pdf"

NAVY = colors.HexColor("#102A43")
BLUE = colors.HexColor("#0E7490")
CYAN = colors.HexColor("#22D3EE")
PALE = colors.HexColor("#ECFEFF")
INK = colors.HexColor("#243B53")
MUTED = colors.HexColor("#627D98")
LINE = colors.HexColor("#D9E2EC")
GREEN = colors.HexColor("#15803D")
ORANGE = colors.HexColor("#C2410C")


def register_fonts() -> tuple[str, str, str]:
    candidates = [
        (
            Path("C:/Windows/Fonts/arial.ttf"),
            Path("C:/Windows/Fonts/arialbd.ttf"),
            Path("C:/Windows/Fonts/consola.ttf"),
        ),
        (
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"),
        ),
    ]
    for regular, bold, mono in candidates:
        if regular.exists() and bold.exists() and mono.exists():
            pdfmetrics.registerFont(TTFont("DocBody", str(regular)))
            pdfmetrics.registerFont(TTFont("DocBold", str(bold)))
            pdfmetrics.registerFont(TTFont("DocMono", str(mono)))
            pdfmetrics.registerFontFamily(
                "DocBody", normal="DocBody", bold="DocBold"
            )
            return "DocBody", "DocBold", "DocMono"
    return "Helvetica", "Helvetica-Bold", "Courier"


BODY_FONT, BOLD_FONT, MONO_FONT = register_fonts()


class HandbookDocTemplate(BaseDocTemplate):
    def __init__(self, filename: str, **kwargs):
        self.running_title = kwargs.pop(
            "running_title", "Technical & Operations Handbook"
        )
        super().__init__(filename, **kwargs)
        content_frame = Frame(
            self.leftMargin,
            self.bottomMargin,
            self.width,
            self.height,
            id="content",
        )
        self.addPageTemplates(
            [
                PageTemplate(id="Handbook", frames=[content_frame], onPage=page_decor),
            ]
        )

    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph):
            level = getattr(flowable, "_toc_level", None)
            if level is not None:
                text = flowable.getPlainText()
                key = f"section-{self.seq.nextf('section')}"
                self.canv.bookmarkPage(key)
                self.canv.addOutlineEntry(text, key, level=level, closed=False)
                self.notify("TOCEntry", (level, text, self.page, key))


def page_decor(canvas, doc):
    canvas.saveState()
    width, height = A4
    if doc.page > 1:
        canvas.setFillColor(NAVY)
        canvas.rect(0, height - 14 * mm, width, 14 * mm, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont(BOLD_FONT, 8)
        canvas.drawString(18 * mm, height - 9 * mm, "FINANCE PAYMOB")
        canvas.setFont(BODY_FONT, 8)
        canvas.drawRightString(
            width - 18 * mm, height - 9 * mm, doc.running_title
        )
        canvas.setStrokeColor(LINE)
        canvas.line(18 * mm, 14 * mm, width - 18 * mm, 14 * mm)
        canvas.setFillColor(MUTED)
        canvas.setFont(BODY_FONT, 7.5)
        canvas.drawString(18 * mm, 9 * mm, "Internal use | Version 1.0")
        canvas.drawRightString(width - 18 * mm, 9 * mm, f"Page {doc.page}")
    canvas.restoreState()


class CoverPage(Flowable):
    def __init__(
        self,
        *,
        title: str,
        subtitle: str,
        baseline: str,
        classification: str,
    ):
        super().__init__()
        self.width, self.height = A4
        self.title = title
        self.subtitle = subtitle
        self.baseline = baseline
        self.classification = classification

    def wrap(self, avail_width, avail_height):
        return avail_width, avail_height

    def draw(self):
        c = self.canv
        w, h = self.width, self.height
        c.setFillColor(NAVY)
        c.rect(-18 * mm, -20 * mm, w + 40 * mm, h + 40 * mm, fill=1, stroke=0)
        c.setFillColor(BLUE)
        c.circle(w - 25 * mm, h - 28 * mm, 55 * mm, fill=1, stroke=0)
        c.setFillColor(CYAN)
        c.circle(w - 12 * mm, h - 15 * mm, 14 * mm, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont(BOLD_FONT, 11)
        c.drawString(4 * mm, h - 45 * mm, "LEARNERS POINT")
        c.setFillColor(CYAN)
        c.rect(4 * mm, h - 60 * mm, 22 * mm, 2 * mm, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont(BOLD_FONT, 30)
        title_lines = (
            ["Finance Paymob", "Project Documentation"]
            if self.title == "Finance Paymob Project Documentation"
            else (
                ["Finance Paymob", "User Guide"]
                if self.title == "Finance Paymob User Guide"
                else [self.title]
            )
        )
        for line_number, line in enumerate(title_lines):
            c.drawString(4 * mm, h - (92 + line_number * 14) * mm, line)
        c.setFont(BODY_FONT, 14)
        c.setFillColor(colors.HexColor("#BAE6FD"))
        c.drawString(4 * mm, h - 122 * mm, self.subtitle)
        c.setFillColor(colors.white)
        c.setFont(BODY_FONT, 10)
        c.drawString(4 * mm, 52 * mm, "Version 1.0  |  17 September 2026")
        if self.baseline:
            c.drawString(4 * mm, 44 * mm, self.baseline)
        c.setFillColor(colors.HexColor("#94A3B8"))
        c.drawString(4 * mm, 28 * mm, f"Classification: {self.classification}")


class DiagramFlowable(Flowable):
    def __init__(self, kind: str):
        super().__init__()
        self.kind = kind
        self.width = 170 * mm
        self.height = 70 * mm if kind == "architecture" else 58 * mm

    def wrap(self, avail_width, avail_height):
        self.width = min(self.width, avail_width)
        return self.width, self.height

    @staticmethod
    def _box(d, x, y, w, h, title, subtitle="", fill=PALE):
        d.add(Rect(x, y, w, h, 5, 5, fillColor=fill, strokeColor=BLUE))
        d.add(
            String(
                x + w / 2,
                y + h / 2 + 4,
                title,
                fontName=BOLD_FONT,
                fontSize=8,
                textAnchor="middle",
                fillColor=NAVY,
            )
        )
        if subtitle:
            d.add(
                String(
                    x + w / 2,
                    y + h / 2 - 7,
                    subtitle,
                    fontName=BODY_FONT,
                    fontSize=6.5,
                    textAnchor="middle",
                    fillColor=MUTED,
                )
            )

    @staticmethod
    def _arrow(d, x1, y1, x2, y2, color=BLUE):
        d.add(Line(x1, y1, x2, y2, strokeColor=color, strokeWidth=1.5))
        angle = 4
        d.add(
            Polygon(
                [x2, y2, x2 - angle, y2 + angle / 2, x2 - angle, y2 - angle / 2],
                fillColor=color,
                strokeColor=color,
            )
        )

    def draw(self):
        d = Drawing(self.width, self.height)
        if self.kind == "architecture":
            self._box(d, 5, 110, 100, 35, "Bitrix24", "CRM + automation")
            self._box(d, 125, 110, 100, 35, "Customer UI", "Payment + terms")
            self._box(d, 245, 110, 100, 35, "Cash Desk", "Employee + manager")
            self._box(d, 125, 55, 100, 38, "Backend API", "FastAPI orchestration", colors.white)
            self._box(d, 5, 5, 100, 35, "Paymob", "Online payments")
            self._box(d, 125, 5, 100, 35, "PostgreSQL", "Authoritative ledger")
            self._box(d, 245, 5, 100, 35, "Zoho + Email", "Invoice + delivery")
            self._arrow(d, 105, 127, 125, 80)
            self._arrow(d, 175, 110, 175, 93)
            self._arrow(d, 245, 127, 225, 80)
            self._arrow(d, 125, 70, 105, 22)
            self._arrow(d, 175, 55, 175, 40)
            self._arrow(d, 225, 70, 245, 22)
        elif self.kind == "payment-flow":
            labels = [
                ("Lead stage", "Bitrix"),
                ("Payment link", "Backend"),
                ("Terms + method", "Customer"),
                ("Verified payment", "Provider/Staff"),
                ("Invoice + CRM", "Zoho/Bitrix"),
            ]
            x = 3
            for index, (title, sub) in enumerate(labels):
                self._box(d, x, 42, 64, 42, title, sub)
                if index < len(labels) - 1:
                    self._arrow(d, x + 64, 63, x + 73, 63)
                x += 73
        elif self.kind == "id-mapping":
            self._box(d, 5, 45, 80, 42, "Lead", "Lead ID")
            self._box(d, 105, 45, 80, 42, "Sales deal", "native LEAD_ID")
            self._box(d, 205, 45, 80, 42, "Finance deal", "Original Deal ID")
            self._box(d, 305, 45, 60, 42, "Workflow", "stored IDs")
            self._arrow(d, 85, 66, 105, 66)
            self._arrow(d, 185, 66, 205, 66)
            self._arrow(d, 285, 66, 305, 66)
        else:
            self._box(d, 3, 45, 72, 42, "Finance created", "Partial status")
            self._box(d, 94, 45, 72, 42, "Pause", "Due date - 1 day")
            self._box(d, 185, 45, 72, 42, "Due webhook", "Installment N")
            self._box(d, 276, 45, 72, 42, "Payment page", "Method + terms")
            self._arrow(d, 75, 66, 94, 66)
            self._arrow(d, 166, 66, 185, 66)
            self._arrow(d, 257, 66, 276, 66)
            d.add(
                String(
                    175,
                    18,
                    "Fully Paid branch ends without reminder",
                    fontName=BOLD_FONT,
                    fontSize=7,
                    textAnchor="middle",
                    fillColor=GREEN,
                )
            )
        d.drawOn(self.canv, 0, 0)


def make_styles():
    base = getSampleStyleSheet()
    styles = {
        "body": ParagraphStyle(
            "Body",
            parent=base["BodyText"],
            fontName=BODY_FONT,
            fontSize=9,
            leading=13,
            textColor=INK,
            spaceAfter=4,
        ),
        "h1": ParagraphStyle(
            "H1",
            parent=base["Heading1"],
            fontName=BOLD_FONT,
            fontSize=18,
            leading=22,
            textColor=NAVY,
            spaceBefore=14,
            spaceAfter=8,
            keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "H2",
            parent=base["Heading2"],
            fontName=BOLD_FONT,
            fontSize=13,
            leading=16,
            textColor=BLUE,
            spaceBefore=11,
            spaceAfter=5,
            keepWithNext=True,
        ),
        "h3": ParagraphStyle(
            "H3",
            parent=base["Heading3"],
            fontName=BOLD_FONT,
            fontSize=10.5,
            leading=14,
            textColor=NAVY,
            spaceBefore=8,
            spaceAfter=3,
            keepWithNext=True,
        ),
        "bullet": ParagraphStyle(
            "Bullet",
            parent=base["BodyText"],
            fontName=BODY_FONT,
            fontSize=8.7,
            leading=12,
            leftIndent=14,
            firstLineIndent=-8,
            bulletIndent=5,
            textColor=INK,
            spaceAfter=2,
        ),
        "quote": ParagraphStyle(
            "Quote",
            parent=base["BodyText"],
            fontName=BODY_FONT,
            fontSize=9.2,
            leading=14,
            leftIndent=12,
            rightIndent=8,
            borderColor=CYAN,
            borderWidth=2,
            borderPadding=8,
            backColor=PALE,
            textColor=NAVY,
            spaceBefore=6,
            spaceAfter=8,
        ),
        "code": ParagraphStyle(
            "Code",
            parent=base["Code"],
            fontName=MONO_FONT,
            fontSize=7.5,
            leading=10,
            leftIndent=8,
            rightIndent=8,
            borderColor=LINE,
            borderWidth=0.5,
            borderPadding=7,
            backColor=colors.HexColor("#F5F7FA"),
            textColor=NAVY,
            spaceBefore=4,
            spaceAfter=7,
        ),
        "tocTitle": ParagraphStyle(
            "TOCTitle",
            fontName=BOLD_FONT,
            fontSize=22,
            leading=26,
            textColor=NAVY,
            spaceAfter=12,
        ),
        "small": ParagraphStyle(
            "Small",
            fontName=BODY_FONT,
            fontSize=7.5,
            leading=10,
            textColor=MUTED,
        ),
    }
    return styles


def inline_markup(text: str) -> str:
    value = html.escape(text)
    value = re.sub(r"`([^`]+)`", rf'<font name="{MONO_FONT}">\1</font>', value)
    value = re.sub(r"\*\*([^*]+)\*\*", rf'<font name="{BOLD_FONT}">\1</font>', value)
    return value


def markdown_story(
    source: str,
    styles: dict,
    *,
    title: str,
    subtitle: str,
    baseline: str,
    classification: str,
) -> list:
    story: list = [
        CoverPage(
            title=title,
            subtitle=subtitle,
            baseline=baseline,
            classification=classification,
        ),
        PageBreak(),
    ]
    story.append(Paragraph("Contents", styles["tocTitle"]))
    toc = TableOfContents()
    toc.levelStyles = [
        ParagraphStyle(
            "TOC1",
            fontName=BOLD_FONT,
            fontSize=9,
            leading=14,
            leftIndent=0,
            firstLineIndent=0,
            textColor=NAVY,
            spaceBefore=2,
        ),
        ParagraphStyle(
            "TOC2",
            fontName=BODY_FONT,
            fontSize=8,
            leading=11,
            leftIndent=12,
            firstLineIndent=0,
            textColor=INK,
        ),
    ]
    story.extend([toc, PageBreak()])

    lines = source.splitlines()
    index = 0
    in_code = False
    code_lines: list[str] = []
    paragraph_lines: list[str] = []

    def flush_paragraph():
        if paragraph_lines:
            text = " ".join(part.strip() for part in paragraph_lines)
            story.append(Paragraph(inline_markup(text), styles["body"]))
            paragraph_lines.clear()

    while index < len(lines):
        raw = lines[index]
        stripped = raw.strip()
        if stripped.startswith("```"):
            flush_paragraph()
            if in_code:
                code = "<br/>".join(html.escape(line) for line in code_lines)
                story.append(Paragraph(code or " ", styles["code"]))
                code_lines.clear()
                in_code = False
            else:
                in_code = True
            index += 1
            continue
        if in_code:
            code_lines.append(raw)
            index += 1
            continue
        diagram = re.match(r"<!--\s*DIAGRAM:([\w-]+)\s*-->", stripped)
        if diagram:
            flush_paragraph()
            story.extend(
                [
                    Spacer(1, 4 * mm),
                    KeepTogether([DiagramFlowable(diagram.group(1)), Spacer(1, 3 * mm)]),
                ]
            )
        elif stripped.startswith("# "):
            # The cover already presents the document title.
            flush_paragraph()
        elif stripped.startswith("## "):
            flush_paragraph()
            p = Paragraph(inline_markup(stripped[3:]), styles["h1"])
            p._toc_level = 0
            story.append(p)
        elif stripped.startswith("### "):
            flush_paragraph()
            p = Paragraph(inline_markup(stripped[4:]), styles["h2"])
            p._toc_level = 1
            story.append(p)
        elif stripped.startswith("#### "):
            flush_paragraph()
            story.append(Paragraph(inline_markup(stripped[5:]), styles["h3"]))
        elif stripped.startswith("> "):
            flush_paragraph()
            story.append(Paragraph(inline_markup(stripped[2:]), styles["quote"]))
        elif re.match(r"^[-*]\s+", stripped):
            flush_paragraph()
            text = re.sub(r"^[-*]\s+", "", stripped)
            story.append(
                Paragraph(inline_markup(text), styles["bullet"], bulletText="•")
            )
        elif re.match(r"^\d+\.\s+", stripped):
            flush_paragraph()
            match = re.match(r"^(\d+)\.\s+(.*)", stripped)
            story.append(
                Paragraph(
                    inline_markup(match.group(2)),
                    styles["bullet"],
                    bulletText=f"{match.group(1)}.",
                )
            )
        elif stripped == "---":
            flush_paragraph()
            story.append(
                HRFlowable(
                    width="100%",
                    thickness=0.6,
                    color=LINE,
                    spaceBefore=5,
                    spaceAfter=7,
                )
            )
        elif not stripped:
            flush_paragraph()
        else:
            paragraph_lines.append(stripped)
        index += 1
    flush_paragraph()
    return story


def build_pdf(
    source_path: Path,
    output_path: Path,
    *,
    title: str = "Finance Paymob Project Documentation",
    subtitle: str = "Technical & Operations Handbook",
    baseline: str = "Implementation baseline: v5 / 39c2462",
    classification: str = "Internal use",
) -> None:
    markdown = source_path.read_text(encoding="utf-8")
    styles = make_styles()
    doc = HandbookDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=21 * mm,
        bottomMargin=18 * mm,
        title=title,
        author="Learners Point",
        subject="Internal technical and operations handbook",
        running_title=subtitle,
    )
    doc.multiBuild(
        markdown_story(
            markdown,
            styles,
            title=title,
            subtitle=subtitle,
            baseline=baseline,
            classification=classification,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--title", default="Finance Paymob Project Documentation")
    parser.add_argument("--subtitle", default="Technical & Operations Handbook")
    parser.add_argument(
        "--baseline", default="Implementation baseline: v5 / 39c2462"
    )
    parser.add_argument("--classification", default="Internal use")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    build_pdf(
        args.source.resolve(),
        args.output.resolve(),
        title=args.title,
        subtitle=args.subtitle,
        baseline=args.baseline,
        classification=args.classification,
    )
    print(f"Generated {args.output.resolve()}")


if __name__ == "__main__":
    main()
