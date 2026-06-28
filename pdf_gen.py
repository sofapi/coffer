"""Lightweight PDF invoice generation using fpdf2."""

import os
from fpdf import FPDF


class InvoicePDF(FPDF):
    def header(self):
        self.set_font("Helvetica", "B", 20)
        self.cell(0, 10, "INVOICE", align="R", new_x="LMARGIN", new_y="NEXT")
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")


def generate_invoice_pdf(invoice, customer, lines, settings=None):
    if settings is None:
        settings = {}

    pdf = InvoicePDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=20)

    # Logo
    logo_path = settings.get("logo_path", "")
    logo_bottom = pdf.get_y()
    if logo_path and os.path.exists(logo_path):
        try:
            lx = float(settings.get("logo_x", 10))
            ly = float(settings.get("logo_y", 8))
            lw = float(settings.get("logo_w", 40))
            lh = float(settings.get("logo_h", 0))  # 0 = auto aspect ratio
            info = pdf.image(logo_path, x=lx, y=ly, w=lw, h=lh)
            # Move cursor below the logo so nothing overlaps
            logo_bottom = ly + info["rendered_height"]
        except Exception:
            pass

    # Business info — start below the logo
    pdf.set_y(logo_bottom + 2)
    business_name = settings.get("business_name", "Your Business")
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 6, business_name, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.ln(5)

    # Invoice details
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(95, 6, "Bill To:", new_x="RIGHT")
    pdf.cell(95, 6, "Invoice Details:", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 10)
    pdf.cell(95, 5, customer["name"], new_x="RIGHT")
    pdf.cell(95, 5, f"Invoice #: {invoice['invoice_number']}", new_x="LMARGIN", new_y="NEXT")

    if customer["address"]:
        for line in customer["address"].split("\n"):
            pdf.cell(95, 5, line.strip(), new_x="RIGHT")
            pdf.cell(95, 5, "", new_x="LMARGIN", new_y="NEXT")

    pdf.cell(95, 5, customer.get("email", ""), new_x="RIGHT")
    pdf.cell(95, 5, f"Date: {invoice['date']}", new_x="LMARGIN", new_y="NEXT")

    pdf.cell(95, 5, customer.get("phone", ""), new_x="RIGHT")
    due = invoice.get("due_date", "")
    pdf.cell(95, 5, f"Due: {due}" if due else "", new_x="LMARGIN", new_y="NEXT")

    pdf.cell(95, 5, "", new_x="RIGHT")
    pdf.cell(95, 5, f"Status: {invoice['status'].upper()}", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(10)

    # Table header
    pdf.set_fill_color(60, 120, 60)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(65, 8, " Description", fill=True, new_x="RIGHT")
    pdf.cell(30, 8, "Date", align="C", fill=True, new_x="RIGHT")
    pdf.cell(25, 8, "Hours", align="C", fill=True, new_x="RIGHT")
    pdf.cell(30, 8, "Rate", align="C", fill=True, new_x="RIGHT")
    pdf.cell(40, 8, "Amount", align="R", fill=True, new_x="LMARGIN", new_y="NEXT")

    # Table rows
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 9)
    total = 0.0
    for i, line in enumerate(lines):
        bg = i % 2 == 0
        if bg:
            pdf.set_fill_color(240, 245, 240)

        pdf.cell(65, 7, f" {line['description'][:40]}", fill=bg, new_x="RIGHT")
        pdf.cell(30, 7, line.get("date_attended", ""), align="C", fill=bg, new_x="RIGHT")
        hours = line.get("hours", 0) or 0
        rate = line.get("rate", 0) or 0
        pdf.cell(25, 7, f"{hours:.1f}" if hours else "", align="C", fill=bg, new_x="RIGHT")
        pdf.cell(30, 7, f"{rate:.2f}" if rate else "", align="C", fill=bg, new_x="RIGHT")
        pdf.cell(40, 7, f"{line['amount']:.2f}", align="R", fill=bg, new_x="LMARGIN", new_y="NEXT")
        total += line["amount"]

    # Total
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(150, 8, "TOTAL:", align="R", new_x="RIGHT")
    pdf.cell(40, 8, f"  {total:.2f}", align="R", new_x="LMARGIN", new_y="NEXT")

    # Notes
    if invoice.get("notes"):
        pdf.ln(10)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 6, "Notes:", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(0, 5, invoice["notes"])

    # Footer message (centred at bottom of last page)
    footer_text = settings.get("invoice_footer", "").strip()
    if footer_text:
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(100, 100, 100)
        # Position above the page number footer (which sits at -15mm)
        pdf.set_y(-30)
        for line in footer_text.split("\n"):
            pdf.cell(0, 4, line.strip(), align="C", new_x="LMARGIN", new_y="NEXT")

    return pdf.output()
