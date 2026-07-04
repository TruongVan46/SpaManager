import io
import logging
import os
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from utils.timezone_utils import local_now

logger = logging.getLogger(__name__)

PDF_FONT_REGULAR = "SpaUnicode"
PDF_FONT_BOLD = "SpaUnicode-Bold"
PDF_FALLBACK_REGULAR = "Helvetica"
PDF_FALLBACK_BOLD = "Helvetica-Bold"

_PDF_FONT_CONFIG = None
_PDF_FONT_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"


@dataclass(frozen=True)
class PdfFontConfig:
    regular: str
    bold: str
    regular_path: str | None = None
    bold_path: str | None = None
    fallback: bool = False


def _candidate_font_pairs():
    font_pairs = []

    bundled_fonts = [
        (_PDF_FONT_DIR / "NotoSans-Regular.ttf", _PDF_FONT_DIR / "NotoSans-Bold.ttf"),
        (_PDF_FONT_DIR / "DejaVuSans.ttf", _PDF_FONT_DIR / "DejaVuSans-Bold.ttf"),
    ]
    font_pairs.extend(bundled_fonts)

    windows_root = os.environ.get("WINDIR") or os.environ.get("SystemRoot")
    if windows_root:
        fonts_dir = Path(windows_root) / "Fonts"
        font_pairs.extend([
            (fonts_dir / "calibri.ttf", fonts_dir / "calibrib.ttf"),
            (fonts_dir / "arial.ttf", fonts_dir / "arialbd.ttf"),
            (fonts_dir / "segoeui.ttf", fonts_dir / "segoeuib.ttf"),
        ])

    font_pairs.extend([
        (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")),
        (Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"), Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf")),
        (Path("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"), Path("/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf")),
        (Path("/usr/share/fonts/truetype/freefont/FreeSans.ttf"), Path("/usr/share/fonts/truetype/freefont/FreeSansBold.ttf")),
    ])

    return font_pairs


def _ensure_registered_font(font_name, font_path):
    try:
        pdfmetrics.getFont(font_name)
        return
    except Exception:
        pass

    pdfmetrics.registerFont(TTFont(font_name, str(font_path)))


def get_pdf_font_config():
    global _PDF_FONT_CONFIG
    if _PDF_FONT_CONFIG is not None:
        return _PDF_FONT_CONFIG

    for regular_path, bold_path in _candidate_font_pairs():
        if not regular_path.exists() or not bold_path.exists():
            continue

        try:
            _ensure_registered_font(PDF_FONT_REGULAR, regular_path)
            _ensure_registered_font(PDF_FONT_BOLD, bold_path)
            _PDF_FONT_CONFIG = PdfFontConfig(
                regular=PDF_FONT_REGULAR,
                bold=PDF_FONT_BOLD,
                regular_path=str(regular_path),
                bold_path=str(bold_path),
                fallback=False,
            )
            return _PDF_FONT_CONFIG
        except Exception as exc:
            logger.warning(
                "Không đăng ký được font PDF từ %s / %s: %s",
                regular_path,
                bold_path,
                exc,
            )

    logger.warning(
        "Không tìm thấy font Unicode phù hợp cho PDF export; dùng %s/%s làm fallback.",
        PDF_FALLBACK_REGULAR,
        PDF_FALLBACK_BOLD,
    )
    _PDF_FONT_CONFIG = PdfFontConfig(
        regular=PDF_FALLBACK_REGULAR,
        bold=PDF_FALLBACK_BOLD,
        fallback=True,
    )
    return _PDF_FONT_CONFIG


def reset_pdf_font_config_cache():
    global _PDF_FONT_CONFIG
    _PDF_FONT_CONFIG = None


def _build_pdf_styles():
    font_config = get_pdf_font_config()
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'PDFTitle',
        parent=styles['Normal'],
        fontName=font_config.bold,
        fontSize=18,
        leading=22,
        alignment=1,
        spaceAfter=15
    )

    meta_style = ParagraphStyle(
        'PDFMeta',
        parent=styles['Normal'],
        fontName=font_config.regular,
        fontSize=10,
        leading=14,
        spaceAfter=4
    )

    heading2_style = ParagraphStyle(
        'PDFHeading2',
        parent=styles['Normal'],
        fontName=font_config.bold,
        fontSize=13,
        leading=16,
        spaceBefore=14,
        spaceAfter=8
    )

    cell_style = ParagraphStyle(
        'TableCell',
        parent=styles['Normal'],
        fontName=font_config.regular,
        fontSize=9,
        leading=12
    )

    cell_center = ParagraphStyle(
        'TableCellCenter',
        parent=cell_style,
        alignment=1
    )

    cell_right = ParagraphStyle(
        'TableCellRight',
        parent=cell_style,
        alignment=2
    )

    cell_bold = ParagraphStyle(
        'TableCellBold',
        parent=cell_style,
        fontName=font_config.bold
    )

    cell_bold_center = ParagraphStyle(
        'TableCellBoldCenter',
        parent=cell_center,
        fontName=font_config.bold
    )

    return font_config, {
        'title_style': title_style,
        'meta_style': meta_style,
        'heading2_style': heading2_style,
        'cell_style': cell_style,
        'cell_center': cell_center,
        'cell_right': cell_right,
        'cell_bold': cell_bold,
        'cell_bold_center': cell_bold_center,
    }

class NumberedCanvas(canvas.Canvas):
    """Custom canvas to compute total page count and draw page numbers in footer."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_number(num_pages)
            super().showPage()
        super().save()

    def draw_page_number(self, page_count):
        self.saveState()
        font_config = get_pdf_font_config()
        try:
            self.setFont(font_config.regular, 9)
        except Exception:
            self.setFont(PDF_FALLBACK_REGULAR, 9)
            
        page_text = f"Trang {self._pageNumber} / {page_count}"
        self.drawRightString(self._pagesize[0] - 36, 30, page_text)
        self.restoreState()

def format_money(val):
    if val is None:
        val = 0
    return f"{val:,.0f}".replace(",", ".") + " đ"


def _payment_method_display_label(payment_method):
    normalized = (payment_method or "").strip().lower()
    labels = {
        "cash": "Tiền mặt",
        "card": "Thẻ",
        "transfer": "Chuyển khoản",
        "bank_transfer": "Chuyển khoản",
        "momo": "MoMo",
        "vnpay": "VNPay",
        "paid": "Đã thanh toán",
        "unpaid": "Chưa thanh toán",
        "partial": "Thanh toán một phần",
        "pending": "Chờ xử lý",
        "cancelled": "Đã hủy",
        "canceled": "Đã hủy",
        "refunded": "Đã hoàn tiền",
    }
    if not normalized or normalized == "none":
        return "Không rõ"
    return labels.get(normalized, payment_method if payment_method else "Không rõ")

def generate_invoice_pdf(invoices, summary, keyword=None, from_date=None, to_date=None, payment_method=None):
    buffer = io.BytesIO()
    
    # Page setup (margins: 36pt, printable width: 523.27)
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=54
    )
    
    _, styles = _build_pdf_styles()
    title_style = styles['title_style']
    meta_style = styles['meta_style']
    heading2_style = styles['heading2_style']
    cell_style = styles['cell_style']
    cell_center = styles['cell_center']
    cell_right = styles['cell_right']
    cell_bold = styles['cell_bold']
    cell_bold_center = styles['cell_bold_center']
    
    story = []
    
    # 1. Document Title
    story.append(Paragraph("DANH SÁCH HÓA ĐƠN", title_style))
    story.append(Spacer(1, 10))
    
    # 2. Metadata Section (Điều kiện lọc)
    has_filters = False
    filter_lines = []
    
    if from_date:
        if isinstance(from_date, str):
            from_date_str = datetime.strptime(from_date.strip(), "%Y-%m-%d").strftime('%d/%m/%Y')
        else:
            from_date_str = from_date.strftime('%d/%m/%Y')
        filter_lines.append(f"<b>Từ ngày:</b> {from_date_str}")
        has_filters = True
    if to_date:
        if isinstance(to_date, str):
            to_date_str = datetime.strptime(to_date.strip(), "%Y-%m-%d").strftime('%d/%m/%Y')
        else:
            to_date_str = to_date.strftime('%d/%m/%Y')
        filter_lines.append(f"<b>Đến ngày:</b> {to_date_str}")
        has_filters = True
    if payment_method and payment_method != "Tất cả":
        filter_lines.append(f"<b>Phương thức thanh toán:</b> {_payment_method_display_label(payment_method)}")
        has_filters = True
    if keyword:
        filter_lines.append(f"<b>Từ khóa:</b> {keyword}")
        has_filters = True
        
    story.append(Paragraph("<b>ĐIỀU KIỆN LỌC</b>", heading2_style))
    if has_filters:
        for line in filter_lines:
            story.append(Paragraph(line, meta_style))
    else:
        story.append(Paragraph("Không áp dụng bộ lọc (Hiển thị tất cả)", meta_style))
        
    now_str = local_now().strftime('%d/%m/%Y %H:%M:%S')
    story.append(Paragraph(f"<b>Ngày xuất báo cáo:</b> {now_str}", meta_style))
    story.append(Spacer(1, 12))
    
    # 3. Invoice Table
    story.append(Paragraph("DANH SÁCH CHI TIẾT", heading2_style))
    
    table_data = [
        [
            Paragraph("STT", cell_bold_center),
            Paragraph("Mã HĐ", cell_bold_center),
            Paragraph("Ngày", cell_bold_center),
            Paragraph("Khách hàng", cell_bold_center),
            Paragraph("Tổng tiền", cell_bold_center),
            Paragraph("Thanh toán", cell_bold_center)
        ]
    ]
    
    for idx, inv in enumerate(invoices, start=1):
        date_str = inv.invoice_date.strftime('%d/%m/%Y') if inv.invoice_date else 'N/A'
        table_data.append([
            Paragraph(str(idx), cell_center),
            Paragraph(f"HD{inv.id}", cell_center),
            Paragraph(date_str, cell_center),
            Paragraph(inv.customer.name if inv.customer else '', cell_style),
            Paragraph(format_money(inv.total_amount), cell_right),
            Paragraph(getattr(inv, 'display_payment_method', None) or inv.payment_method or 'Không rõ', cell_center)
        ])
        
    # Column widths setup: STT (35), Mã HĐ (50), Ngày (75), Khách hàng (160), Tổng tiền (103.27), Thanh toán (100)
    # Total printable width: 523.27
    inv_table = Table(table_data, colWidths=[35, 50, 75, 160, 103.27, 100])
    inv_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#F2F2F2')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#D9D9D9')),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(inv_table)
    story.append(Spacer(1, 15))
    
    # 4. Bottom Summary
    story.append(Paragraph("TỔNG CỘNG", heading2_style))
    summary_data = [
        [
            Paragraph("<b>Tổng hóa đơn:</b>", cell_style),
            Paragraph(str(summary.get("invoice_count", 0)), cell_style)
        ],
        [
            Paragraph("<b>Tổng doanh thu:</b>", cell_style),
            Paragraph(format_money(summary.get("total_revenue", 0)), cell_bold)
        ],
        [
            Paragraph("<b>Tổng giảm giá:</b>", cell_style),
            Paragraph(format_money(summary.get("total_discount", 0)), cell_style)
        ]
    ]
    
    summary_table = Table(summary_data, colWidths=[120, 200])
    summary_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
    ]))
    story.append(summary_table)
    
    doc.build(story, canvasmaker=NumberedCanvas)
    buffer.seek(0)
    return buffer


def generate_statistics_pdf(summary, customer_stats, service_stats, from_date=None, to_date=None):
    buffer = io.BytesIO()
    
    # Page setup
    # Margins: 36pt (0.5 inch). Printable width: 595.27 - 72 = 523.27
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=54
    )
    
    _, styles = _build_pdf_styles()
    title_style = styles['title_style']
    meta_style = styles['meta_style']
    heading2_style = styles['heading2_style']
    cell_style = styles['cell_style']
    cell_center = styles['cell_center']
    cell_right = styles['cell_right']
    cell_bold = styles['cell_bold']
    cell_bold_center = styles['cell_bold_center']

    story = []
    
    # 1. Document Title
    story.append(Paragraph("BÁO CÁO THỐNG KÊ SPA", title_style))
    story.append(Spacer(1, 10))
    
    # 2. Metadata Section
    date_range_str = "Tất cả thời gian"
    if from_date and to_date:
        date_range_str = f"{from_date.strftime('%d/%m/%Y')} - {to_date.strftime('%d/%m/%Y')}"
    elif from_date:
        date_range_str = f"Từ ngày {from_date.strftime('%d/%m/%Y')}"
    elif to_date:
        date_range_str = f"Đến ngày {to_date.strftime('%d/%m/%Y')}"
        
    now_str = local_now().strftime('%d/%m/%Y %H:%M:%S')
    
    story.append(Paragraph(f"<b>Khoảng thời gian:</b> {date_range_str}", meta_style))
    story.append(Paragraph(f"<b>Ngày xuất báo cáo:</b> {now_str}", meta_style))
    story.append(Spacer(1, 12))
    
    # 3. Overview Statistics
    story.append(Paragraph("I. THÔNG TIN TỔNG QUAN", heading2_style))
    
    overview_data = [
        [
            Paragraph("<b>Tổng doanh thu:</b>", cell_style),
            Paragraph(format_money(summary.get("revenue", 0)), cell_bold)
        ],
        [
            Paragraph("<b>Tổng hóa đơn:</b>", cell_style),
            Paragraph(f"{summary.get('invoice_count', 0):,}".replace(",", "."), cell_style)
        ],
        [
            Paragraph("<b>Tổng khách hàng:</b>", cell_style),
            Paragraph(f"{summary.get('customer_count', 0):,}".replace(",", "."), cell_style)
        ],
        [
            Paragraph("<b>Tổng lịch hẹn:</b>", cell_style),
            Paragraph(f"{summary.get('appointment_count', 0):,}".replace(",", "."), cell_style)
        ]
    ]
    
    # Clean two-column table for overview stats, aligned to the left
    overview_table = Table(overview_data, colWidths=[120, 200])
    overview_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
    ]))
    story.append(overview_table)
    story.append(Spacer(1, 15))
    
    # 4. Customer Statistics Table
    story.append(Paragraph("II. THỐNG KÊ KHÁCH HÀNG", heading2_style))
    
    cust_table_data = [
        [
            Paragraph("STT", cell_bold_center),
            Paragraph("Khách hàng", cell_bold_center),
            Paragraph("SĐT", cell_bold_center),
            Paragraph("Số hóa đơn", cell_bold_center),
            Paragraph("Tổng tiền đã chi", cell_bold_center)
        ]
    ]
    
    for idx, cust in enumerate(customer_stats, start=1):
        cust_table_data.append([
            Paragraph(str(idx), cell_center),
            Paragraph(cust.get("name", ""), cell_style),
            Paragraph(cust.get("phone") or "", cell_center),
            Paragraph(f"{cust.get('invoice_count', 0):,}".replace(",", "."), cell_right),
            Paragraph(format_money(cust.get("total_spent", 0)), cell_right)
        ])
        
    # Standard margins: 36 left and right. Printable width: 523.27
    # Column widths setup: STT (40), Khách hàng (150), SĐT (100), Số hóa đơn (90), Tổng tiền đã chi (143.27)
    cust_table = Table(cust_table_data, colWidths=[40, 150, 100, 90, 143.27])
    cust_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#F2F2F2')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#D9D9D9')),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(cust_table)
    story.append(Spacer(1, 15))
    
    # 5. Service Statistics Table
    story.append(Paragraph("III. THỐNG KÊ DỊCH VỤ", heading2_style))
    
    svc_table_data = [
        [
            Paragraph("STT", cell_bold_center),
            Paragraph("Tên dịch vụ", cell_bold_center),
            Paragraph("Số lượt sử dụng", cell_bold_center),
            Paragraph("Doanh thu", cell_bold_center)
        ]
    ]
    
    for idx, svc in enumerate(service_stats, start=1):
        svc_table_data.append([
            Paragraph(str(idx), cell_center),
            Paragraph(svc.get("service_name", ""), cell_style),
            Paragraph(f"{svc.get('quantity_sold', 0):,}".replace(",", "."), cell_right),
            Paragraph(format_money(svc.get("revenue", 0)), cell_right)
        ])
        
    # Printable width: 523.27
    # Column widths setup: STT (40), Tên dịch vụ (200), Số lượt sử dụng (120), Doanh thu (163.27)
    svc_table = Table(svc_table_data, colWidths=[40, 200, 120, 163.27])
    svc_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#F2F2F2')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#D9D9D9')),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(svc_table)
    
    # Build Document using NumberedCanvas
    doc.build(story, canvasmaker=NumberedCanvas)
    
    buffer.seek(0)
    return buffer
