
# report_generator.py

import os
from datetime import datetime
from collections import defaultdict
import re
from reportlab.lib.pagesizes import A4
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Table, TableStyle,
    Image, Spacer, PageBreak
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# from classes.report_generator import _add_summary
from classes.database import (
    get_connection,
    get_current_shift_name
)
from path import LOGO_PATH,REPORT_PATH

# ==============================
# COMPANY / MILL INFO
# ==============================
MILL_NAME = "Armstrong textiles processing Pvt LTD"
MILL_ADDRESS = [ "Plot No:E10-G14",
                "Sipcot industrial Growth Center",
                "P.V Palayam (PO) Perundurai-638052 ",
                "GSTIN 33AABCJ3933D1Z1",
                "Mail ID :- atplindia@atpl-india.net",
]

COMPANY_NAME = "Texa Innovates"
COMPANY_EMAIL = "info@texainnovates.com"
COMPANY_LOCATION = "Coimbatore"



# ==============================
# PDF STYLES
# ==============================
styles = getSampleStyleSheet()

SECTION_STYLE = ParagraphStyle(
    "SectionStyle",
    parent=styles["Heading2"],
    fontSize=12
)

NORMAL_STYLE = styles["Normal"]

# ==============================
# HEADER / FOOTER DRAWING
# ==============================
def _draw_footer(canvas, doc):
    width, _ = A4
    footer_y = 35

    canvas.setLineWidth(0.5)
    canvas.line(30, footer_y + 10, width - 30, footer_y + 10)

    canvas.setFont("Helvetica", 8)
    canvas.drawCentredString(
        width / 2,
        footer_y,
        f"{COMPANY_NAME} | {COMPANY_EMAIL}"
    )

    canvas.drawRightString(
        width - 30,
        footer_y - 10,
        datetime.now().strftime("Generated on %d-%m-%Y %H:%M")
    )


def _draw_first_page(canvas, doc):
    canvas.saveState()
    width, height = A4

    left_x = 30
    right_x = width - 30
    top_y = height - 40
    gap = 12

    # ---- MILL NAME ----
    canvas.setFont("Helvetica-Bold", 11)
    canvas.drawString(left_x, top_y, MILL_NAME)

    # ---- MILL ADDRESS ----
    canvas.setFont("Helvetica", 9)
    y = top_y - gap
    for line in MILL_ADDRESS:
        canvas.drawString(left_x, y, line)
        y -= gap

    # ---- COMPANY LOGO ----
    if os.path.exists(LOGO_PATH):
        canvas.drawImage(
            str(LOGO_PATH),
            x=right_x - 90,
            y=top_y - 25,
            width=90,
            height=40,
            preserveAspectRatio=True,
            mask="auto"
        )

    # ---- HEADER SEPARATOR ----
    canvas.setLineWidth(0.6)
    canvas.line(30, y - 6, width - 30, y - 6)

    # ---- FOOTER ----
    _draw_footer(canvas, doc)

    canvas.restoreState()


def _draw_later_pages(canvas, doc):
    canvas.saveState()
    _draw_footer(canvas, doc)
    canvas.restoreState()

# ==============================
# MAIN ENTRY FUNCTION
# ==============================
def generate_defect_report_pdf(
    report_type,
    start_time,
    end_time,
    roll_id=None,
    shift_name=None,
    exclude_defect_ids=None
):
    # os.makedirs(output_dir, exist_ok=True)

    if exclude_defect_ids is None:
        exclude_defect_ids = []

    start_db = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d %H:%M:%S")
    end_db = datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d %H:%M:%S")

    if report_type == "roll":
        filename = f"roll_{roll_id}_{start_db}_to_{end_db}.pdf".replace(":", "-")
        rolls_data = _fetch_roll_data(start_db, end_db, roll_id, exclude_defect_ids)

    elif report_type == "day":
        filename = f"day_{start_db}_to_{end_db}.pdf".replace(":", "-")
        rolls_data = _fetch_roll_data(start_db, end_db, None, exclude_defect_ids)

    else:
        raise ValueError("Invalid report type")

    # if not rolls_data:
        # raise ValueError("No data found for report")
    if not rolls_data:
        file_path = REPORT_PATH / filename

        doc = SimpleDocTemplate(
            str(file_path),
            pagesize=A4,
            leftMargin=30,
            rightMargin=30,
            topMargin=100,
            bottomMargin=60
        )

        elements = []

        elements.append(Spacer(1, 20))
        elements.append(
            Paragraph(
                "Defect Report",
                SECTION_STYLE
            )
        )

        elements.append(Spacer(1, 20))

        elements.append(
            Paragraph(
                f"Roll ID: {roll_id}",
                NORMAL_STYLE
            )
        )

        elements.append(Spacer(1, 10))

        elements.append(
            Paragraph(
                f"Start Time: {_format_datetime(start_db)}",
                NORMAL_STYLE
            )
        )

        elements.append(
            Paragraph(
                f"End Time: {_format_datetime(end_db)}",
                NORMAL_STYLE
            )
        )

        elements.append(Spacer(1, 30))

        elements.append(
            Paragraph(
                "<b>No defect data found for this roll.</b>",
                NORMAL_STYLE
            )
        )

        doc.build(
            elements,
            onFirstPage=_draw_first_page,
            onLaterPages=_draw_later_pages
        )

        print(
            f"✅ Empty report created for roll {roll_id}: "
            f"{file_path}"
        )

        return str(file_path)

    file_path = REPORT_PATH / filename

    doc = SimpleDocTemplate(
        str(file_path),
        pagesize=A4,
        leftMargin=30,
        rightMargin=30,
        topMargin=100,
        bottomMargin=60
    )

    elements = []
    date_range = f"{start_db} to {end_db}"

    for idx, (roll_id, defects) in enumerate(rolls_data.items()):
        if idx > 0:
            elements.append(PageBreak())

        elements.append(Spacer(1, 20))
        elements.append(Paragraph("Defect Report", SECTION_STYLE))
        elements.append(Spacer(1, 12))

        _add_summary(elements, roll_id, date_range, shift_name, defects)
        elements.append(Spacer(1, 14))

        _add_defect_table(elements, defects)
        _add_defect_images(elements, defects)

    doc.build(
        elements,
        onFirstPage=_draw_first_page,
        onLaterPages=_draw_later_pages
    )

    return str(file_path)
# ==============================
# DATA FETCHING
# ==============================
# def _fetch_roll_data(start_db, end_db, roll_id=None, exclude_defect_ids=None):
#     conn = get_connection()
#     cur = conn.cursor()

#     if exclude_defect_ids is None:
#         exclude_defect_ids = []

#     sql = """
#         SELECT id, timestamp, roll_id, machine_number,
#                program_number, defect_type,
#                defect_code, target_rotation, image_path,x,y
#         FROM defect_logs
#         WHERE datetime(timestamp) >= datetime(?)
#           AND datetime(timestamp) <= datetime(?)
#     """
#     params = [start_db, end_db]

#     if roll_id is not None:
#         sql += " AND CAST(roll_id AS INTEGER) = ?"
#         params.append(int(roll_id))

#     if exclude_defect_ids:
#         placeholders = ",".join(["?"] * len(exclude_defect_ids))
#         sql += f" AND id NOT IN ({placeholders})"
#         params.extend(exclude_defect_ids)

#     sql += " ORDER BY datetime(timestamp) ASC"

#     print("SQL:", sql)
#     print("PARAMS:", params)

#     cur.execute(sql, params)
#     rows = cur.fetchall()

#     print("ROWS FOUND:", len(rows))
#     print("ROW IDS:", [r[0] for r in rows])

#     conn.close()

#     grouped = defaultdict(list)
#     for r in rows:
#         grouped[str(r[2])].append(r)

#     return grouped

def _fetch_roll_data(
    start_db,
    end_db,
    roll_id=None,
    exclude_defect_ids=None
):
    conn = get_connection()
    cur = conn.cursor()

    if exclude_defect_ids is None:
        exclude_defect_ids = []

    sql = """
        SELECT
            id,
            job_id,
            result,
            defect_meter,
            roll_id,
            machine_number,
            defect_code,
            defect_type,
            x,
            y,
            timestamp,
            image_path
        FROM defect_report_table
        WHERE datetime(timestamp) >= datetime(?)
          AND datetime(timestamp) <= datetime(?)
    """

    params = [start_db, end_db]

    if roll_id is not None:
        sql += " AND CAST(roll_id AS INTEGER) = ?"
        params.append(int(roll_id))

    if exclude_defect_ids:
        placeholders = ",".join(
            ["?"] * len(exclude_defect_ids)
        )

        sql += f" AND id NOT IN ({placeholders})"
        params.extend(exclude_defect_ids)

    sql += " ORDER BY datetime(timestamp) ASC"

    print("SQL:", sql)
    print("PARAMS:", params)

    cur.execute(sql, params)
    rows = cur.fetchall()

    print("ROWS FOUND:", len(rows))
    print("ROW IDS:", [row[0] for row in rows])

    conn.close()

    grouped = defaultdict(list)

    for row in rows:
        # row[4] = roll_id
        grouped[str(row[4])].append(row)

    return grouped

def _fetch_shift_data(start_db, end_db, shift_name):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT shift_start_time, shift_end_time
        FROM shift_table
        WHERE shift = ?
    """, (shift_name,))
    row = cur.fetchone()

    if not row:
        return {}

    start, end = row

    cur.execute("""
        SELECT timestamp, roll_id, machine_number,
               program_number, defect_type,
               defect_code, target_rotation, image_path,x,y
        FROM defect_logs
        WHERE timestamp BETWEEN ? AND ?
        ORDER BY timestamp ASC
    """, (start, end))

    rows = cur.fetchall()
    conn.close()

    grouped = defaultdict(list)
    for r in rows:
        grouped[str(r[1])].append(r)

    return grouped

# ==============================
# PDF CONTENT SECTIONS
# ==============================
def _format_datetime(dt_value):
    try:
        return datetime.strptime(
            str(dt_value),
            "%Y-%m-%d %H:%M:%S"
        ).strftime("%d-%m-%Y %H:%M:%S")
    except Exception:
        return str(dt_value)
    

def _merge_defect_mm(defect_text):

    if not defect_text:
        return ""

    totals = {}

    pattern = r"([A-Za-z_]+)\s*([0-9]+(?:\.[0-9]+)?)\s*mm"

    for name, value in re.findall(pattern, str(defect_text)):
        totals[name] = totals.get(name, 0.0) + float(value)

    if not totals:
        return defect_text

    return ", ".join(
        f"{name} {total:.1f} mm"
        for name, total in totals.items()
    )

# def _add_summary(elements, roll_id, date_db, shift_name, defects):

#     first = defects[0]
#     last = defects[-1]

#     report_date = datetime.strptime(
#         first[1],
#         "%Y-%m-%d %H:%M:%S"
#     ).strftime("%d-%m-%Y")

#     data = [
#         ["Date", report_date],
#         ["Roll ID", roll_id],
#         ["MC", first[3]],
#         ["Start Time", _format_datetime(first[1])],
#         ["End Time", _format_datetime(last[1])],
#         ["Shift", shift_name or get_current_shift_name()],
#         ["Total Defect", len(defects)],
#     ]

#     table = Table(data, colWidths=[150, 300])

#     table.setStyle(TableStyle([
#         ("GRID", (0,0), (-1,-1), 1.0, colors.black),
#         ("BACKGROUND", (0,0), (0,-1), colors.whitesmoke)
#     ]))

#     elements.append(table)

def _add_summary(
    elements,
    roll_id,
    date_db,
    shift_name,
    defects
):
    first = defects[0]
    last = defects[-1]

    # first[10] = timestamp
    report_date = datetime.strptime(
        first[10],
        "%Y-%m-%d %H:%M:%S"
    ).strftime("%d-%m-%Y")

    data = [
        ["Date", report_date],
        ["Roll ID", roll_id],

        # first[5] = machine_number
        ["MC", first[5]],

        # timestamp
        ["Start Time", _format_datetime(first[10])],
        ["End Time", _format_datetime(last[10])],

        ["Shift", shift_name or get_current_shift_name()],
        ["Total Defect", len(defects)],
    ]

    table = Table(
        data,
        colWidths=[150, 300]
    )

    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 1.0, colors.black),
        ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke)
    ]))

    elements.append(table)

# def _add_defect_table(elements, defects):

#     elements.append(Paragraph("Defect Details", SECTION_STYLE))
#     elements.append(Spacer(1, 8))

#     table_data = [[
#         "S.No",
#         "Meter",
#         "Defect Type / Meter of Defect",
#         "X", 
#         "Y",
#         "Time"
#     ]]

#     for i, d in enumerate(defects, 1):

#         table_data.append([
#             i,
#             f"{float(d[7]) / 1000:.3f} m",
#             _merge_defect_mm(d[5]),
#             d[9] if d[9] is not None else "",
#             d[10] if d[10] is not None else "",
#             _format_datetime(d[1])
#         ])

#     table = Table(
#         table_data,
#         colWidths=[35, 60, 210, 45, 45, 120],
#         repeatRows=1
#     )

#     table.setStyle(TableStyle([
#         ("GRID", (0,0), (-1,-1), 1.0, colors.black),
#         ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
#         ("VALIGN", (0,0), (-1,-1), "TOP")
#     ]))

#     elements.append(table)

def _add_defect_table(elements, defects):

    elements.append(
        Paragraph(
            "Defect Details",
            SECTION_STYLE
        )
    )

    elements.append(Spacer(1, 8))

    table_data = [[
        "S.No",
        "Meter",
        "Defect Type",
        "X",
        "Y",
        "Time"
    ]]

    for i, d in enumerate(defects, 1):

        # Column mapping:
        #
        # d[0]  = id
        # d[1]  = job_id
        # d[2]  = result
        # d[3]  = defect_meter
        # d[4]  = roll_id
        # d[5]  = machine_number
        # d[6]  = defect_code
        # d[7]  = defect_type
        # d[8]  = x
        # d[9]  = y
        # d[10] = timestamp
        # d[11] = image_path

        try:
            meter = float(d[3] or 0)
            meter_text = f"{meter:.3f} m"
        except Exception:
            meter_text = str(d[3] or "")

        table_data.append([
            i,
            meter_text,
            str(d[7] or ""),
            d[8] if d[8] is not None else "",
            d[9] if d[9] is not None else "",
            _format_datetime(d[10])
        ])

    table = Table(
        table_data,
        colWidths=[35, 60, 210, 45, 45, 120],
        repeatRows=1
    )

    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 1.0, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("VALIGN", (0, 0), (-1, -1), "TOP")
    ]))

    elements.append(table)

def _add_defect_images(elements, defects):

    from PIL import Image as PILImage
    from reportlab.platypus.flowables import KeepTogether

    elements.append(PageBreak())

    elements.append(Paragraph("Defect Images", SECTION_STYLE))
    elements.append(Spacer(1, 12))

    PAGE_WIDTH = 520
    IMG_HEIGHT = 160

    valid_count = 0

    for idx, d in enumerate(defects, 1):

        try:

            img_path = d[11]

            print("IMAGE PATH:", img_path)

            si = Paragraph(
                f"<b>SI No : {idx}</b>",
                NORMAL_STYLE
            )

            if not img_path:
                continue

            if not os.path.exists(img_path):
                print("MISSING:", img_path)
                continue

            # VERIFY IMAGE
            with PILImage.open(img_path) as test_img:
                test_img.verify()

            # REOPEN AFTER VERIFY
            img = Image(
                img_path,
                width=PAGE_WIDTH,
                height=IMG_HEIGHT,
                kind="proportional"
            )

            box = Table(
                [[si], [img]],
                colWidths=[PAGE_WIDTH]
            )

            box.setStyle(TableStyle([
                ("BOX", (0, 0), (-1, -1), 0.75, colors.grey),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]))

            elements.append(KeepTogether(box))
            elements.append(Spacer(1, 16))

            valid_count += 1

        except Exception as e:

            print("SKIPPED IMAGE:", e)

            continue

    print("VALID IMAGES:", valid_count)

# if __name__ == "__main__":

#     print("Report generation started...")

#     path = generate_defect_report_pdf(
#         report_type="roll",
#         start_time="2026-04-14 16:10:22",
#         end_time="2026-04-14 16:44:44",
#         roll_id=1009,
#         exclude_defect_ids=[]
#     )

#     print("Report created:", path)