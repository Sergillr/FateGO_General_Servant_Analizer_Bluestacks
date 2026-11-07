from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    Image,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from .models import ServantRecord
from .store import Roster

INK = colors.HexColor("#0f172a")
MUTED = colors.HexColor("#64748b")
GOLD = colors.HexColor("#b8892f")
LINE = colors.HexColor("#e2e8f0")
SOFT = colors.HexColor("#f8fafc")
GREEN = colors.HexColor("#16a34a")
AMBER = colors.HexColor("#d97706")
RED = colors.HexColor("#dc2626")

PAGE_W, PAGE_H = A4
MARGIN = 18 * mm


class ProgressBar(Flowable):
    def __init__(self, value: float | None, maximum: float, width: float = 70 * mm,
                 height: float = 3.4 * mm, color=GOLD):
        super().__init__()
        self.value = value
        self.maximum = maximum
        self.width = width
        self.height = height
        self.color = color

    def wrap(self, available_width, available_height):
        return self.width, self.height

    def draw(self):
        canvas = self.canv
        radius = self.height / 2
        canvas.setFillColor(LINE)
        canvas.roundRect(0, 0, self.width, self.height, radius, stroke=0, fill=1)
        if self.value is None or self.maximum <= 0:
            return
        fraction = max(0.0, min(1.0, self.value / self.maximum))
        if fraction <= 0:
            return
        canvas.setFillColor(self.color)
        canvas.roundRect(
            0, 0, max(self.height, self.width * fraction), self.height, radius, stroke=0, fill=1
        )


def _styles() -> dict[str, ParagraphStyle]:
    return {
        "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=30,
                                leading=34, textColor=INK),
        "subtitle": ParagraphStyle("subtitle", fontName="Helvetica-Bold", fontSize=16,
                                   leading=20, textColor=GOLD),
        "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=15,
                             leading=19, textColor=INK, spaceAfter=4),
        "h3": ParagraphStyle("h3", fontName="Helvetica-Bold", fontSize=9,
                             leading=12, textColor=MUTED, spaceBefore=6, spaceAfter=3),
        "body": ParagraphStyle("body", fontName="Helvetica", fontSize=9.5,
                               leading=13.5, textColor=INK),
        "small": ParagraphStyle("small", fontName="Helvetica", fontSize=8,
                                leading=11, textColor=MUTED),
        "name": ParagraphStyle("name", fontName="Helvetica-Bold", fontSize=22,
                               leading=25, textColor=INK),
        "label": ParagraphStyle("label", fontName="Helvetica-Bold", fontSize=8,
                                leading=11, textColor=MUTED),
        "value": ParagraphStyle("value", fontName="Helvetica", fontSize=9.5,
                                leading=12, textColor=INK),
    }


def _on_page(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN, 15 * mm, PAGE_W - MARGIN, 15 * mm)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(MARGIN, 10 * mm, "FGO Servant Analyzer")
    canvas.drawRightString(PAGE_W - MARGIN, 10 * mm, str(doc.page))
    canvas.restoreState()


def _stars(rarity: int | None) -> str:
    if not rarity:
        return ""
    return "*" * int(rarity)


def _fmt(value, fallback: str = "?") -> str:
    return str(value) if value not in (None, "", []) else fallback


def _status_paragraph(text: str, ok: bool | None) -> str:
    if ok is None:
        color = "#64748b"
        mark = "?"
    elif ok:
        color = "#16a34a"
        mark = "OK"
    else:
        color = "#d97706"
        mark = "PENDIENTE"
    return (
        f'<font size="7" color="{color}"><b>{mark}</b></font> '
        f'<font color="#0f172a">{text}</font>'
    )


def _gaps(record: ServantRecord) -> list[str]:
    lines: list[str] = []

    if record.level and record.max_level:
        ok = record.level >= record.max_level
        extra = "" if ok else f" (faltan {record.max_level - record.level})"
        lines.append(_status_paragraph(f"Nivel {record.level}/{record.max_level}{extra}", ok))

    if len(record.skills) == 3:
        total = sum(record.skills)
        ok = total >= 30
        lines.append(_status_paragraph(f"Skills {'/'.join(map(str, record.skills))} (total {total}/30)", ok))

    if len(record.append_skills) == 3:
        total = sum(record.append_skills)
        ok = total >= 30
        lines.append(_status_paragraph(
            f"Append {'/'.join(map(str, record.append_skills))} (total {total}/30)", ok))

    if record.np_level is not None:
        lines.append(_status_paragraph(f"NP {record.np_level}/5", record.np_level >= 5))

    if record.bond is not None:
        lines.append(_status_paragraph(f"Bond {record.bond}/10", record.bond >= 10))

    if record.fou_atk is not None or record.fou_hp is not None:
        ok = (record.fou_atk or 0) >= 1000 and (record.fou_hp or 0) >= 1000
        lines.append(_status_paragraph(
            f"Fou ATK {_fmt(record.fou_atk)}/1000 · HP {_fmt(record.fou_hp)}/1000", ok))

    return lines


def _portrait(record: ServantRecord, root: Path) -> Flowable:
    if record.portrait:
        path = root / record.portrait
        if path.exists():
            try:
                return Image(str(path), width=52 * mm, height=65 * mm)
            except Exception:  # noqa: BLE001
                pass
    placeholder = Table([[Paragraph("sin retrato", _styles()["small"])]], colWidths=[52 * mm],
                        rowHeights=[65 * mm])
    placeholder.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SOFT),
        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return placeholder


def _servant_block(record: ServantRecord, root: Path, styles: dict[str, ParagraphStyle]) -> list[Flowable]:
    header = Table(
        [[
            Paragraph(record.display_name, styles["name"]),
            Paragraph(
                f'<para align="right"><font color="#b8892f" size="14">{_stars(record.rarity)}</font><br/>'
                f'<font size="8" color="#64748b">{_fmt(record.class_name)}</font></para>',
                styles["body"],
            ),
        ]],
        colWidths=[110 * mm, 40 * mm],
    )
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -1), 1.2, GOLD),
    ]))

    rows: list[list] = []
    rows.append([Paragraph("NIVEL", styles["label"]),
                 Paragraph(f"{_fmt(record.level)}/{_fmt(record.max_level)}", styles["value"]),
                 ProgressBar(record.level, record.max_level or 100)])
    rows.append([Paragraph("NP", styles["label"]),
                 Paragraph(f"{_fmt(record.np_level)}/5", styles["value"]),
                 ProgressBar(record.np_level, 5)])
    rows.append([Paragraph("SKILLS", styles["label"]),
                 Paragraph("/".join(map(str, record.skills)) if record.skills else "?", styles["value"]),
                 ProgressBar(sum(record.skills) if record.skills else None, 30)])
    rows.append([Paragraph("APPEND", styles["label"]),
                 Paragraph("/".join(map(str, record.append_skills)) if record.append_skills else "?",
                           styles["value"]),
                 ProgressBar(sum(record.append_skills) if record.append_skills else None, 30)])
    rows.append([Paragraph("BOND", styles["label"]),
                 Paragraph(f"{_fmt(record.bond)}/10", styles["value"]),
                 ProgressBar(record.bond, 10)])
    rows.append([Paragraph("FOU", styles["label"]),
                 Paragraph(f"{_fmt(record.fou_atk)} / {_fmt(record.fou_hp)}", styles["value"]),
                 ProgressBar(min(record.fou_atk or 0, record.fou_hp or 0), 1000)])

    stats = Table(rows, colWidths=[16 * mm, 26 * mm, 70 * mm])
    stats.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, LINE),
    ]))

    body = Table([[ _portrait(record, root), stats ]], colWidths=[58 * mm, 92 * mm])
    body.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
    ]))

    flow: list[Flowable] = [header, body, Spacer(1, 5 * mm)]
    flow.append(Paragraph("ANALISIS", styles["h3"]))
    gaps = _gaps(record)
    flow.append(Paragraph("<br/>".join(gaps) if gaps else "Sin datos suficientes.", styles["body"]))

    atlas = record.atlas or {}
    if any(atlas.get(k) for k in ("atk_max", "hp_max", "np_name", "skill_names")):
        flow.append(Paragraph("DATOS DEL JUEGO (Atlas Academy)", styles["h3"]))
        info = []
        if atlas.get("atk_max"):
            info.append(f"ATK max: <b>{atlas['atk_max']}</b>")
        if atlas.get("hp_max"):
            info.append(f"HP max: <b>{atlas['hp_max']}</b>")
        if atlas.get("np_name"):
            rank = f" ({atlas['np_rank']})" if atlas.get("np_rank") else ""
            info.append(f"NP: <b>{atlas['np_name']}</b>{rank}")
        if info:
            flow.append(Paragraph(" · ".join(info), styles["body"]))
        if atlas.get("skill_names"):
            flow.append(Paragraph(
                "Skills: " + ", ".join(atlas["skill_names"]), styles["small"]))

    if record.ce:
        flow.append(Paragraph(f"CE equipada: <b>{record.ce}</b>", styles["small"]))

    return [KeepTogether(flow)]


def _cover(roster: Roster, title: str, styles: dict[str, ParagraphStyle]) -> list[Flowable]:
    servants = roster.sorted()
    ssr = sum(1 for s in servants if (s.rarity or 0) == 5)
    sr = sum(1 for s in servants if (s.rarity or 0) == 4)
    maxed = sum(1 for s in servants if s.maxed_level)
    skills = sum(1 for s in servants if s.skills_maxed)
    np5 = sum(1 for s in servants if (s.np_level or 0) >= 5)
    bond10 = sum(1 for s in servants if (s.bond or 0) >= 10)

    metrics = [
        [Paragraph(f'<font size="20" color="#0f172a"><b>{len(servants)}</b></font><br/>'
                   f'<font size="8" color="#64748b">SERVANTS</font>', styles["body"]),
         Paragraph(f'<font size="20" color="#b8892f"><b>{ssr}</b></font><br/>'
                   f'<font size="8" color="#64748b">SSR</font>', styles["body"]),
         Paragraph(f'<font size="20" color="#0f172a"><b>{sr}</b></font><br/>'
                   f'<font size="8" color="#64748b">SR</font>', styles["body"])],
        [Paragraph(f'<font size="20" color="#16a34a"><b>{maxed}</b></font><br/>'
                   f'<font size="8" color="#64748b">NIVEL MAX</font>', styles["body"]),
         Paragraph(f'<font size="20" color="#16a34a"><b>{skills}</b></font><br/>'
                   f'<font size="8" color="#64748b">10/10/10</font>', styles["body"]),
         Paragraph(f'<font size="20" color="#0f172a"><b>{np5}</b></font><br/>'
                   f'<font size="8" color="#64748b">NP5</font>', styles["body"])],
    ]
    table = Table(metrics, colWidths=[50 * mm, 50 * mm, 50 * mm])
    table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE),
        ("BACKGROUND", (0, 0), (-1, -1), SOFT),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))

    return [
        Spacer(1, 45 * mm),
        Paragraph("Fate/Grand Order", styles["title"]),
        Paragraph(title.replace("Fate/Grand Order - ", ""), styles["subtitle"]),
        Spacer(1, 6 * mm),
        Paragraph(
            f"Generado el {datetime.now():%d/%m/%Y a las %H:%M} · "
            f"{bond10} servants en bond 10+",
            styles["small"],
        ),
        Spacer(1, 22 * mm),
        table,
        PageBreak(),
    ]


def _summary(roster: Roster, styles: dict[str, ParagraphStyle]) -> list[Flowable]:
    servants = roster.sorted()
    classes: dict[str, list[ServantRecord]] = {}
    for servant in servants:
        classes.setdefault(servant.class_name or "Sin clase", []).append(servant)

    rows = [[
        Paragraph("<b>Clase</b>", styles["small"]),
        Paragraph("<b>Total</b>", styles["small"]),
        Paragraph("<b>SSR</b>", styles["small"]),
        Paragraph("<b>Nivel max</b>", styles["small"]),
        Paragraph("<b>10/10/10</b>", styles["small"]),
    ]]
    for class_name in sorted(classes):
        group = classes[class_name]
        rows.append([
            Paragraph(class_name, styles["body"]),
            Paragraph(str(len(group)), styles["body"]),
            Paragraph(str(sum(1 for s in group if (s.rarity or 0) == 5)), styles["body"]),
            Paragraph(str(sum(1 for s in group if s.maxed_level)), styles["body"]),
            Paragraph(str(sum(1 for s in group if s.skills_maxed)), styles["body"]),
        ])

    class_table = Table(rows, colWidths=[50 * mm, 22 * mm, 22 * mm, 30 * mm, 30 * mm], repeatRows=1)
    class_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), SOFT),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, GOLD),
        ("LINEBELOW", (0, 1), (-1, -1), 0.3, LINE),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))

    detail_rows = [[
        Paragraph("<b>Servant</b>", styles["small"]),
        Paragraph("<b>Clase</b>", styles["small"]),
        Paragraph("<b>Rareza</b>", styles["small"]),
        Paragraph("<b>Nivel</b>", styles["small"]),
        Paragraph("<b>NP</b>", styles["small"]),
        Paragraph("<b>Skills</b>", styles["small"]),
        Paragraph("<b>Bond</b>", styles["small"]),
    ]]
    for servant in servants:
        detail_rows.append([
            Paragraph(servant.display_name, styles["body"]),
            Paragraph(_fmt(servant.class_name, "-"), styles["small"]),
            Paragraph(_stars(servant.rarity) or "-", styles["small"]),
            Paragraph(f"{_fmt(servant.level)}/{_fmt(servant.max_level)}", styles["small"]),
            Paragraph(_fmt(servant.np_level, "-"), styles["small"]),
            Paragraph("/".join(map(str, servant.skills)) if servant.skills else "-", styles["small"]),
            Paragraph(_fmt(servant.bond, "-"), styles["small"]),
        ])

    detail = Table(detail_rows, colWidths=[62 * mm, 26 * mm, 20 * mm, 22 * mm, 14 * mm, 28 * mm, 16 * mm],
                   repeatRows=1)
    detail.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), SOFT),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, GOLD),
        ("LINEBELOW", (0, 1), (-1, -1), 0.3, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))

    return [
        Paragraph("Resumen de cuenta", styles["h2"]),
        Paragraph(
            f"{len(servants)} servants registrados. "
            "Los datos de progreso se leen de la pantalla; los stats vienen de Atlas Academy.",
            styles["small"],
        ),
        Spacer(1, 5 * mm),
        class_table,
        Spacer(1, 8 * mm),
        Paragraph("Inventario", styles["h2"]),
        Spacer(1, 2 * mm),
        detail,
        PageBreak(),
    ]


def build_report(
    roster: Roster,
    out_path: Path,
    title: str = "Fate/Grand Order - Servant Report",
    author: str = "FGO Servant Analyzer",
    root: Path | None = None,
) -> Path:
    root = root or Path.cwd()
    styles = _styles()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    doc = BaseDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=16 * mm,
        bottomMargin=20 * mm,
        title=title,
        author=author,
    )
    frame = Frame(MARGIN, 20 * mm, PAGE_W - 2 * MARGIN, PAGE_H - 36 * mm, id="main")
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=_on_page)])

    story: list[Flowable] = []
    story += _cover(roster, title, styles)
    if roster.servants:
        story += _summary(roster, styles)
        for servant in roster.sorted():
            story += _servant_block(servant, root, styles)
            story.append(PageBreak())
    else:
        story.append(Paragraph("No hay servants en el roster todavia.", styles["body"]))

    doc.build(story)
    return out_path
