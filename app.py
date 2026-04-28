import os
import io
import base64
import csv
from flask import Flask, render_template, request, jsonify, send_file
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, HRFlowable
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
import tempfile

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB max upload


# ── helpers ────────────────────────────────────────────────────────────────────

def get_grade(pct):
    if pct >= 90: return ('A+', '#1a7a4a')
    if pct >= 80: return ('A',  '#1d5c63')
    if pct >= 70: return ('B+', '#2e6da4')
    if pct >= 60: return ('B',  '#5b6dae')
    if pct >= 50: return ('C',  '#c9922a')
    if pct >= 40: return ('D',  '#d35400')
    return ('F', '#c0392b')

def bar_color(pct):
    if pct >= 75: return colors.HexColor('#1a7a4a')
    if pct >= 50: return colors.HexColor('#c9922a')
    return colors.HexColor('#c0392b')

def parse_csv(file_stream):
    """Parse uploaded CSV. First column = Name, rest = subjects."""
    content = file_stream.read().decode('utf-8-sig').strip()
    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)
    if not rows:
        return None, None
    headers = list(rows[0].keys())
    name_col = headers[0]
    subjects = headers[1:]
    students = []
    for row in rows:
        if not row.get(name_col, '').strip():
            continue
        scores = {}
        for sub in subjects:
            try:
                scores[sub] = float(row.get(sub, 0) or 0)
            except ValueError:
                scores[sub] = 0.0
        students.append({'name': row[name_col].strip(), 'scores': scores})
    return students, subjects

def enrich(students, subjects):
    """Add total, avg, pct, grade, rank to each student."""
    max_possible = len(subjects) * 100
    for s in students:
        s['total'] = sum(s['scores'].values())
        s['avg']   = s['total'] / len(subjects) if subjects else 0
        s['pct']   = (s['total'] / max_possible * 100) if max_possible else 0
        grade, color = get_grade(s['pct'])
        s['grade'] = grade
        s['grade_color'] = color

    ranked = sorted(students, key=lambda x: x['total'], reverse=True)
    for s in students:
        s['rank'] = next(i+1 for i, r in enumerate(ranked) if r['name'] == s['name'])

    return students


# ── PDF builder ────────────────────────────────────────────────────────────────

def build_pdf(students, subjects, org_name, logo_bytes=None):
    """Build a multi-page PDF — one page per student — and return bytes."""
    buf = io.BytesIO()
    W, H = A4

    c = canvas.Canvas(buf, pagesize=A4)
    total_students = len(students)

    for s in students:
        _draw_scorecard_page(c, s, subjects, org_name, logo_bytes, total_students, W, H)
        c.showPage()

    c.save()
    buf.seek(0)
    return buf

def _draw_scorecard_page(c, s, subjects, org_name, logo_bytes, total_students, W, H):
    """Draw one student scorecard onto the canvas."""
    INK   = colors.HexColor('#0f1117')
    CREAM = colors.HexColor('#faf8f3')
    GOLD  = colors.HexColor('#c9922a')
    GOLD_LIGHT = colors.HexColor('#f9f0dc')
    TEAL  = colors.HexColor('#1d5c63')
    BORDER= colors.HexColor('#e2d9c6')
    WHITE = colors.white

    margin = 14*mm

    # ── HEADER BLOCK ──────────────────────────────────────────────────────────
    header_h = 38*mm
    c.setFillColor(INK)
    c.rect(0, H - header_h, W, header_h, fill=1, stroke=0)

    # Logo
    logo_x = margin
    logo_y = H - header_h + 6*mm
    logo_size = 26*mm
    if logo_bytes:
        try:
            logo_reader = ImageReader(io.BytesIO(logo_bytes))
            c.drawImage(logo_reader, logo_x, logo_y, width=logo_size, height=logo_size,
                        preserveAspectRatio=True, mask='auto')
        except Exception:
            _draw_placeholder_logo(c, logo_x, logo_y, logo_size, GOLD)
    else:
        _draw_placeholder_logo(c, logo_x, logo_y, logo_size, GOLD)

    # Name + org
    text_x = logo_x + logo_size + 8*mm
    c.setFillColor(CREAM)
    c.setFont('Helvetica-Bold', 20)
    c.drawString(text_x, H - 16*mm, s['name'])
    c.setFillColor(colors.HexColor('#e8c56d'))
    c.setFont('Helvetica', 9)
    c.drawString(text_x, H - 23*mm, org_name)

    # ── BADGE STRIP ───────────────────────────────────────────────────────────
    badge_h = 11*mm
    strip_y = H - header_h - badge_h
    c.setFillColor(GOLD_LIGHT)
    c.rect(0, strip_y, W, badge_h, fill=1, stroke=0)

    # thin gold line
    c.setStrokeColor(BORDER)
    c.setLineWidth(0.5)
    c.line(0, strip_y, W, strip_y)

    badges = [
        (f"Total: {int(s['total'])}",    INK,                    CREAM),
        (f"Average: {s['avg']:.1f}",     TEAL,                   CREAM),
        (f"Grade: {s['grade']}",         colors.HexColor(s['grade_color']), CREAM),
        (f"Rank: #{s['rank']} of {total_students}", colors.HexColor('#888888'), CREAM),
    ]
    bx = margin
    for text, bg, fg in badges:
        c.setFont('Helvetica-Bold', 7.5)
        tw = c.stringWidth(text, 'Helvetica-Bold', 7.5)
        pad = 4*mm
        bw = tw + pad*2
        bh = 6*mm
        by = strip_y + (badge_h - bh)/2
        # rounded rect via bezier approximation
        _rounded_rect(c, bx, by, bw, bh, 2*mm, bg)
        c.setFillColor(fg)
        c.drawString(bx + pad, by + 1.8*mm, text)
        bx += bw + 4*mm

    # ── SUBJECT TABLE ─────────────────────────────────────────────────────────
    table_top = strip_y - 8*mm
    row_h = 11*mm
    col_subject_w = 60*mm
    col_bar_w     = W - 2*margin - col_subject_w - 22*mm
    col_score_w   = 22*mm

    # Header row
    c.setFillColor(colors.HexColor('#f0ece4'))
    c.rect(margin, table_top - 8*mm, W - 2*margin, 8*mm, fill=1, stroke=0)
    c.setFillColor(colors.HexColor('#888888'))
    c.setFont('Helvetica-Bold', 7)
    c.drawString(margin + 2*mm,                              table_top - 5.5*mm, 'SUBJECT')
    c.drawString(margin + col_subject_w + 2*mm,              table_top - 5.5*mm, 'PERFORMANCE')
    c.drawString(W - margin - col_score_w + 4*mm,            table_top - 5.5*mm, 'SCORE')

    cy = table_top - 8*mm

    for i, sub in enumerate(subjects):
        val = s['scores'].get(sub, 0)
        pct = min(100, val)  # assumes /100
        bcolor = bar_color(pct)
        row_bg = WHITE if i % 2 == 0 else colors.HexColor('#fdfcfa')

        c.setFillColor(row_bg)
        c.rect(margin, cy - row_h, W - 2*margin, row_h, fill=1, stroke=0)

        # separator line
        c.setStrokeColor(colors.HexColor('#f0ece4'))
        c.setLineWidth(0.4)
        c.line(margin, cy - row_h, W - margin, cy - row_h)

        # Subject name
        c.setFillColor(INK)
        c.setFont('Helvetica', 9)
        c.drawString(margin + 2*mm, cy - row_h + 3.5*mm, sub)

        # Bar background
        bar_x = margin + col_subject_w
        bar_y = cy - row_h + 4*mm
        bar_full_w = col_bar_w - 6*mm
        bar_h_px = 3.5*mm

        c.setFillColor(colors.HexColor('#eeeeee'))
        _rounded_rect(c, bar_x, bar_y, bar_full_w, bar_h_px, 1.5*mm, colors.HexColor('#eeeeee'))

        # Bar fill
        filled_w = (pct / 100) * bar_full_w
        if filled_w > 0:
            _rounded_rect(c, bar_x, bar_y, filled_w, bar_h_px, 1.5*mm, bcolor)

        # Score
        c.setFillColor(bcolor)
        c.setFont('Helvetica-Bold', 9)
        c.drawRightString(W - margin - 2*mm, cy - row_h + 3.5*mm, str(int(val)))

        cy -= row_h

    # ── FOOTER STRIP ──────────────────────────────────────────────────────────
    footer_h = 14*mm
    c.setFillColor(INK)
    c.rect(0, 0, W, footer_h, fill=1, stroke=0)

    col_w = W / 3
    footer_items = [
        ('OVERALL PERCENTAGE', f"{s['pct']:.1f}%"),
        ('CLASS RANK',         f"#{s['rank']} of {total_students}"),
        ('GENERATED',          __import__('datetime').date.today().strftime('%d %b %Y')),
    ]
    for i, (label, value) in enumerate(footer_items):
        fx = i * col_w + margin/2
        c.setFillColor(colors.HexColor('#888888'))
        c.setFont('Helvetica', 6.5)
        c.drawString(fx, footer_h - 5*mm, label)
        c.setFillColor(CREAM)
        c.setFont('Helvetica-Bold', 9)
        c.drawString(fx, footer_h - 10*mm, value)


def _draw_placeholder_logo(c, x, y, size, color):
    c.setFillColor(color)
    c.roundRect(x, y, size, size, 3*mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont('Helvetica-Bold', 14)
    c.drawCentredString(x + size/2, y + size/2 - 5, '🏫')

def _rounded_rect(c, x, y, w, h, r, fill_color):
    c.setFillColor(fill_color)
    c.roundRect(x, y, w, h, r, fill=1, stroke=0)


# ── ROUTES ─────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/parse', methods=['POST'])
def api_parse():
    """Parse uploaded CSV and return structured student data as JSON."""
    if 'csv' not in request.files:
        return jsonify({'error': 'No CSV file uploaded'}), 400

    csv_file = request.files['csv']
    students, subjects = parse_csv(csv_file.stream)
    if not students:
        return jsonify({'error': 'Could not parse CSV. Check the format.'}), 400

    enriched = enrich(students, subjects)

    return jsonify({
        'students': enriched,
        'subjects': subjects,
        'summary': {
            'count':   len(enriched),
            'avg':     round(sum(s['avg'] for s in enriched) / len(enriched), 1),
            'top':     max(enriched, key=lambda x: x['total'])['name'],
            'subjects': len(subjects),
        }
    })


@app.route('/api/pdf', methods=['POST'])
def api_pdf():
    """Generate PDF for one or all students. Returns PDF file."""
    data       = request.form
    students   = __import__('json').loads(data.get('students', '[]'))
    subjects   = __import__('json').loads(data.get('subjects', '[]'))
    org_name   = data.get('org_name', 'Student Report Card')
    target     = data.get('target', 'all')   # 'all' or student name
    logo_bytes = None

    if 'logo' in request.files:
        logo_bytes = request.files['logo'].read()

    if target != 'all':
        students = [s for s in students if s['name'] == target]
        if not students:
            return jsonify({'error': 'Student not found'}), 404

    pdf_buf = build_pdf(students, subjects, org_name, logo_bytes)
    fname = f"ScoreCard_{target.replace(' ','_')}.pdf" if target != 'all' else 'All_ScoreCards.pdf'

    return send_file(
        pdf_buf,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=fname
    )


if __name__ == '__main__':
    app.run(debug=True, port=5000)
