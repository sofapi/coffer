"""Coffer — lightweight invoice & expense tracking for small businesses."""

import csv
import io
import json
import os
import sqlite3
import tempfile
import threading
from datetime import datetime, date

import requests as http_requests
from flask import (
    Flask, request, jsonify, render_template, redirect, url_for, Response, send_file,
)

from db import get_db, init_db, next_invoice_number, get_settings, save_setting
from pdf_gen import generate_invoice_pdf

app = Flask(__name__)
init_db()

APP_NAME = "Coffer"


@app.context_processor
def inject_branding():
    """Make the product name and configured business name available to every
    template, so branding is driven by settings rather than hardcoded."""
    conn = get_db()
    try:
        business_name = get_settings(conn).get("business_name", "") or APP_NAME
    finally:
        conn.close()
    return {"app_name": APP_NAME, "business_name": business_name}


@app.route("/health")
def health():
    """Lightweight liveness probe for the container healthcheck."""
    return {"status": "ok", "app": APP_NAME}, 200

# ---------------------------------------------------------------------------
# Webhook helper
# ---------------------------------------------------------------------------

def fire_webhooks(event: str, payload: dict):
    """Send webhook notifications in background threads."""
    conn = get_db()
    hooks = conn.execute(
        "SELECT url FROM webhook_urls WHERE event = ? AND active = 1", (event,)
    ).fetchall()
    conn.close()
    for hook in hooks:
        def _send(url, data):
            try:
                http_requests.post(url, json=data, timeout=10)
            except Exception:
                pass
        threading.Thread(target=_send, args=(hook["url"], payload), daemon=True).start()


# ---------------------------------------------------------------------------
# Web UI routes
# ---------------------------------------------------------------------------

@app.route("/reports")
def reports():
    # UK tax year: 6 April to 5 April
    today = date.today()
    # Determine current tax year start year (e.g. 2025 for 2025/26)
    if today >= date(today.year, 4, 6):
        current_ty = today.year
    else:
        current_ty = today.year - 1

    selected_ty = request.args.get("ty", str(current_ty))
    selected_month = request.args.get("month", "")  # e.g. "2025-04" or "" for full year
    ty = int(selected_ty)
    ty_start = f"{ty}-04-06"
    ty_end = f"{ty + 1}-04-06"

    if selected_month:
        parts = selected_month.split("-")
        y, m = int(parts[0]), int(parts[1])
        # Month within tax year: 6th to 5th
        period_start = f"{y}-{m:02d}-06"
        if m == 12:
            period_end = f"{y + 1}-01-06"
        else:
            period_end = f"{y}-{m + 1:02d}-06"
        period_label = f"{date(y, m, 6).strftime('%B %Y')}"
    else:
        period_start = ty_start
        period_end = ty_end
        period_label = f"Full Year {ty}/{ty + 1}"

    conn = get_db()

    income_total = conn.execute(
        "SELECT COALESCE(SUM(amount),0) as t FROM income WHERE date >= ? AND date < ?",
        (period_start, period_end)
    ).fetchone()["t"]
    expenses_total = conn.execute(
        "SELECT COALESCE(SUM(amount),0) as t FROM expenses WHERE date >= ? AND date < ?",
        (period_start, period_end)
    ).fetchone()["t"]
    # Invoice income (paid invoices in the period)
    invoice_income = conn.execute(
        """SELECT COALESCE(SUM(il.amount),0) as t FROM invoice_lines il
           JOIN invoices i ON il.invoice_id=i.id
           WHERE i.status='paid' AND i.date >= ? AND i.date < ?""",
        (period_start, period_end)
    ).fetchone()["t"]
    # Unpaid invoices in the period
    unpaid = conn.execute(
        """SELECT COUNT(*) as c, COALESCE(SUM(il.amount),0) as t FROM invoice_lines il
           JOIN invoices i ON il.invoice_id=i.id
           WHERE i.status='unpaid' AND i.date >= ? AND i.date < ?""",
        (period_start, period_end)
    ).fetchone()

    total_income = income_total + invoice_income

    # Build month options for the tax year (Apr, May, ... Mar)
    months = []
    for i in range(12):
        m = ((4 + i - 1) % 12) + 1  # 4,5,6,...12,1,2,3
        y = ty if m >= 4 else ty + 1
        months.append({"value": f"{y}-{m:02d}", "label": date(y, m, 1).strftime("%b %Y")})

    # Tax year options: from earliest data year to current
    earliest = conn.execute(
        """SELECT MIN(d) as d FROM (
            SELECT MIN(date) as d FROM expenses
            UNION SELECT MIN(date) as d FROM income
            UNION SELECT MIN(date) as d FROM invoices)"""
    ).fetchone()["d"]
    conn.close()

    ty_options = []
    if earliest:
        ed = datetime.strptime(earliest, "%Y-%m-%d").date()
        start_ty = ed.year if ed >= date(ed.year, 4, 6) else ed.year - 1
    else:
        start_ty = current_ty
    for y in range(start_ty, current_ty + 1):
        ty_options.append({"value": str(y), "label": f"{y}/{y + 1}"})

    return render_template("reports.html",
        selected_ty=selected_ty, selected_month=selected_month,
        period_label=period_label,
        income_total=total_income, expenses_total=expenses_total,
        profit=total_income - expenses_total,
        unpaid_count=unpaid["c"], unpaid_total=unpaid["t"],
        months=months, ty_options=ty_options)


@app.route("/")
def dashboard():
    conn = get_db()
    today = date.today()
    month_start = today.strftime("%Y-%m-01")
    if today.month == 12:
        next_month_start = f"{today.year + 1}-01-01"
    else:
        next_month_start = f"{today.year}-{today.month + 1:02d}-01"
    month = today.strftime("%Y-%m")

    expenses_total = conn.execute(
        "SELECT COALESCE(SUM(amount),0) as t FROM expenses WHERE date >= ? AND date < ?",
        (month_start, next_month_start)
    ).fetchone()["t"]
    income_total = conn.execute(
        "SELECT COALESCE(SUM(amount),0) as t FROM income WHERE date >= ? AND date < ?",
        (month_start, next_month_start)
    ).fetchone()["t"]
    invoice_income = conn.execute(
        """SELECT COALESCE(SUM(il.amount),0) as t FROM invoice_lines il
           JOIN invoices i ON il.invoice_id=i.id
           WHERE i.status='paid' AND i.date >= ? AND i.date < ?""",
        (month_start, next_month_start)
    ).fetchone()["t"]
    income_total += invoice_income
    unpaid = conn.execute(
        """SELECT COUNT(*) as c, COALESCE(SUM(il.amount),0) as t
           FROM invoices i LEFT JOIN invoice_lines il ON il.invoice_id = i.id
           WHERE i.status = 'unpaid'"""
    ).fetchone()
    invoices_unpaid = unpaid["c"]
    invoices_total = unpaid["t"]

    recent_expenses = conn.execute(
        "SELECT * FROM expenses ORDER BY date DESC LIMIT 5"
    ).fetchall()
    recent_income = conn.execute(
        "SELECT * FROM income ORDER BY date DESC LIMIT 5"
    ).fetchall()
    recent_invoices = conn.execute(
        """SELECT i.*, c.name as customer_name, COALESCE(SUM(il.amount),0) as total
           FROM invoices i
           JOIN customers c ON i.customer_id=c.id
           LEFT JOIN invoice_lines il ON il.invoice_id=i.id
           GROUP BY i.id
           ORDER BY i.date DESC LIMIT 5"""
    ).fetchall()

    conn.close()
    return render_template("dashboard.html",
        month=month, expenses_total=expenses_total, income_total=income_total,
        invoices_unpaid=invoices_unpaid, invoices_total=invoices_total,
        recent_expenses=recent_expenses, recent_income=recent_income,
        recent_invoices=recent_invoices)


# --- Expenses ---

@app.route("/expenses")
def expenses_list():
    conn = get_db()
    rows = conn.execute("SELECT * FROM expenses ORDER BY date DESC").fetchall()
    conn.close()
    return render_template("expenses.html", expenses=rows)


@app.route("/expenses/add", methods=["POST"])
def expenses_add():
    conn = get_db()
    conn.execute(
        "INSERT INTO expenses (amount, date, reference, category) VALUES (?,?,?,?)",
        (request.form["amount"], request.form["date"],
         request.form.get("reference", ""), request.form.get("category", ""))
    )
    conn.commit()
    conn.close()
    return redirect(url_for("expenses_list"))


@app.route("/expenses/<int:id>/delete", methods=["POST"])
def expenses_delete(id):
    conn = get_db()
    conn.execute("DELETE FROM expenses WHERE id=?", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for("expenses_list"))


# --- Income ---

@app.route("/income")
def income_list():
    conn = get_db()
    rows = conn.execute("SELECT * FROM income ORDER BY date DESC").fetchall()
    conn.close()
    return render_template("income.html", income=rows)


@app.route("/income/add", methods=["POST"])
def income_add():
    conn = get_db()
    conn.execute(
        "INSERT INTO income (amount, date, reference) VALUES (?,?,?)",
        (request.form["amount"], request.form["date"], request.form.get("reference", ""))
    )
    conn.commit()
    conn.close()
    return redirect(url_for("income_list"))


@app.route("/income/<int:id>/delete", methods=["POST"])
def income_delete(id):
    conn = get_db()
    conn.execute("DELETE FROM income WHERE id=?", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for("income_list"))


# --- Customers ---

@app.route("/customers")
def customers_list():
    conn = get_db()
    rows = conn.execute("SELECT * FROM customers ORDER BY name").fetchall()
    conn.close()
    return render_template("customers.html", customers=rows)


@app.route("/customers/add", methods=["POST"])
def customers_add():
    conn = get_db()
    conn.execute(
        "INSERT INTO customers (name, email, phone, address, notes) VALUES (?,?,?,?,?)",
        (request.form["name"], request.form.get("email", ""),
         request.form.get("phone", ""), request.form.get("address", ""),
         request.form.get("notes", ""))
    )
    conn.commit()
    conn.close()
    return redirect(url_for("customers_list"))


@app.route("/customers/<int:id>")
def customer_detail(id):
    conn = get_db()
    customer = conn.execute("SELECT * FROM customers WHERE id=?", (id,)).fetchone()
    invoices = conn.execute(
        """SELECT i.*,
           (SELECT COALESCE(SUM(amount),0) FROM invoice_lines WHERE invoice_id=i.id) as total
           FROM invoices i WHERE i.customer_id=? ORDER BY i.date DESC""", (id,)
    ).fetchall()
    conn.close()
    return render_template("customer_detail.html", customer=customer, invoices=invoices)


@app.route("/customers/<int:id>/edit", methods=["POST"])
def customers_edit(id):
    conn = get_db()
    conn.execute(
        "UPDATE customers SET name=?, email=?, phone=?, address=?, notes=? WHERE id=?",
        (request.form["name"], request.form.get("email", ""),
         request.form.get("phone", ""), request.form.get("address", ""),
         request.form.get("notes", ""), id)
    )
    conn.commit()
    conn.close()
    return redirect(url_for("customer_detail", id=id))


@app.route("/customers/<int:id>/delete", methods=["POST"])
def customers_delete(id):
    conn = get_db()
    conn.execute("DELETE FROM customers WHERE id=?", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for("customers_list"))


# --- Invoices ---

@app.route("/invoices")
def invoices_list():
    conn = get_db()
    rows = conn.execute(
        """SELECT i.*, c.name as customer_name,
           (SELECT COALESCE(SUM(amount),0) FROM invoice_lines WHERE invoice_id=i.id) as total
           FROM invoices i JOIN customers c ON i.customer_id=c.id
           ORDER BY i.date DESC"""
    ).fetchall()
    customers = conn.execute("SELECT id, name FROM customers ORDER BY name").fetchall()
    conn.close()
    return render_template("invoices.html", invoices=rows, customers=customers)


@app.route("/invoices/create", methods=["POST"])
def invoices_create():
    conn = get_db()
    inv_num = next_invoice_number(conn)
    conn.execute(
        "INSERT INTO invoices (invoice_number, customer_id, date, due_date, notes) VALUES (?,?,?,?,?)",
        (inv_num, request.form["customer_id"], request.form["date"],
         request.form.get("due_date", ""), request.form.get("notes", ""))
    )
    inv_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()

    # Fire webhook
    invoice = dict(conn.execute("SELECT * FROM invoices WHERE id=?", (inv_id,)).fetchone())
    fire_webhooks("invoice.created", {"event": "invoice.created", "invoice": invoice})

    conn.close()
    return redirect(url_for("invoice_detail", id=inv_id))


@app.route("/invoices/<int:id>")
def invoice_detail(id):
    conn = get_db()
    invoice = conn.execute("SELECT * FROM invoices WHERE id=?", (id,)).fetchone()
    customer = conn.execute("SELECT * FROM customers WHERE id=?", (invoice["customer_id"],)).fetchone()
    lines = conn.execute("SELECT * FROM invoice_lines WHERE invoice_id=? ORDER BY id", (id,)).fetchall()
    total = sum(l["amount"] for l in lines)
    conn.close()
    return render_template("invoice_detail.html", invoice=invoice, customer=customer, lines=lines, total=total)


@app.route("/invoices/<int:id>/add-line", methods=["POST"])
def invoice_add_line(id):
    hours = float(request.form.get("hours", 0) or 0)
    rate = float(request.form.get("rate", 0) or 0)
    amount = float(request.form.get("amount", 0) or 0)
    if hours and rate and not amount:
        amount = hours * rate

    conn = get_db()
    conn.execute(
        "INSERT INTO invoice_lines (invoice_id, description, date_attended, hours, rate, amount) VALUES (?,?,?,?,?,?)",
        (id, request.form["description"], request.form.get("date_attended", ""),
         hours, rate, amount)
    )
    conn.commit()
    conn.close()
    return redirect(url_for("invoice_detail", id=id))


@app.route("/invoices/<int:inv_id>/delete-line/<int:line_id>", methods=["POST"])
def invoice_delete_line(inv_id, line_id):
    conn = get_db()
    conn.execute("DELETE FROM invoice_lines WHERE id=? AND invoice_id=?", (line_id, inv_id))
    conn.commit()
    conn.close()
    return redirect(url_for("invoice_detail", id=inv_id))


@app.route("/invoices/<int:id>/status", methods=["POST"])
def invoice_status(id):
    conn = get_db()
    conn.execute("UPDATE invoices SET status=? WHERE id=?", (request.form["status"], id))
    conn.commit()
    conn.close()
    return redirect(url_for("invoice_detail", id=id))


@app.route("/invoices/<int:id>/edit", methods=["POST"])
def invoice_edit(id):
    conn = get_db()
    conn.execute(
        "UPDATE invoices SET date=?, due_date=?, notes=? WHERE id=?",
        (request.form["date"], request.form.get("due_date", ""),
         request.form.get("notes", ""), id)
    )
    conn.commit()
    conn.close()
    return redirect(url_for("invoice_detail", id=id))


@app.route("/invoices/<int:id>/delete", methods=["POST"])
def invoice_delete(id):
    conn = get_db()
    conn.execute("DELETE FROM invoice_lines WHERE invoice_id=?", (id,))
    conn.execute("DELETE FROM invoices WHERE id=?", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for("invoices_list"))


@app.route("/invoices/<int:id>/pdf")
def invoice_pdf(id):
    conn = get_db()
    invoice = dict(conn.execute("SELECT * FROM invoices WHERE id=?", (id,)).fetchone())
    customer = dict(conn.execute("SELECT * FROM customers WHERE id=?", (invoice["customer_id"],)).fetchone())
    lines = [dict(r) for r in conn.execute("SELECT * FROM invoice_lines WHERE invoice_id=? ORDER BY id", (id,)).fetchall()]
    settings = get_settings(conn)
    conn.close()

    pdf_bytes = bytes(generate_invoice_pdf(invoice, customer, lines, settings))
    disposition = "attachment" if request.args.get("download") else "inline"
    filename = f"{invoice['invoice_number']}.pdf"
    return Response(pdf_bytes, mimetype="application/pdf",
                    headers={"Content-Disposition": f'{disposition}; filename="{filename}"'})


# --- Webhooks management ---

@app.route("/webhooks")
def webhooks_list():
    conn = get_db()
    hooks = conn.execute("SELECT * FROM webhook_urls ORDER BY id").fetchall()
    conn.close()
    return render_template("webhooks.html", webhooks=hooks)


@app.route("/webhooks/add", methods=["POST"])
def webhooks_add():
    conn = get_db()
    conn.execute(
        "INSERT INTO webhook_urls (url, event) VALUES (?,?)",
        (request.form["url"], request.form.get("event", "invoice.created"))
    )
    conn.commit()
    conn.close()
    return redirect(url_for("webhooks_list"))


@app.route("/webhooks/<int:id>/delete", methods=["POST"])
def webhooks_delete(id):
    conn = get_db()
    conn.execute("DELETE FROM webhook_urls WHERE id=?", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for("webhooks_list"))


# --- Invoice Settings ---

LOGO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


@app.route("/invoice-settings")
def invoice_settings():
    conn = get_db()
    settings = get_settings(conn)
    conn.close()
    return render_template("invoice_settings.html", settings=settings)


@app.route("/invoice-settings/save", methods=["POST"])
def invoice_settings_save():
    conn = get_db()
    save_setting(conn, "business_name", request.form.get("business_name", ""))
    save_setting(conn, "logo_x", request.form.get("logo_x", "10"))
    save_setting(conn, "logo_y", request.form.get("logo_y", "8"))
    save_setting(conn, "logo_w", request.form.get("logo_w", "40"))
    save_setting(conn, "logo_h", request.form.get("logo_h", "0"))
    save_setting(conn, "invoice_footer", request.form.get("invoice_footer", ""))

    # Handle logo upload
    logo = request.files.get("logo")
    if logo and logo.filename:
        ext = os.path.splitext(logo.filename)[1].lower()
        if ext in (".jpg", ".jpeg", ".png"):
            logo_path = os.path.join(LOGO_DIR, f"invoice_logo{ext}")
            logo.save(logo_path)
            save_setting(conn, "logo_path", logo_path)

    conn.close()
    return redirect(url_for("invoice_settings"))


@app.route("/invoice-settings/remove-logo", methods=["POST"])
def invoice_settings_remove_logo():
    conn = get_db()
    settings = get_settings(conn)
    logo_path = settings.get("logo_path", "")
    if logo_path and os.path.exists(logo_path):
        os.remove(logo_path)
    save_setting(conn, "logo_path", "")
    conn.close()
    return redirect(url_for("invoice_settings"))


@app.route("/invoice-settings/preview-pdf")
def invoice_settings_preview():
    """Generate a sample invoice PDF using current settings."""
    conn = get_db()
    settings = get_settings(conn)
    conn.close()

    sample_invoice = {
        "invoice_number": "INV-PREVIEW",
        "date": date.today().isoformat(),
        "due_date": "",
        "status": "unpaid",
        "notes": "This is a preview invoice to check your settings.",
    }
    sample_customer = {
        "name": "Sample Customer",
        "email": "sample@example.com",
        "phone": "07700 900000",
        "address": "123 Example Street\nLeeds LS1 1AA",
    }
    sample_lines = [
        {"description": "Lawn mowing", "date_attended": date.today().isoformat(),
         "hours": 2, "rate": 35, "amount": 70},
        {"description": "Hedge trimming", "date_attended": date.today().isoformat(),
         "hours": 1.5, "rate": 40, "amount": 60},
    ]

    pdf_bytes = bytes(generate_invoice_pdf(sample_invoice, sample_customer, sample_lines, settings))
    return Response(pdf_bytes, mimetype="application/pdf",
                    headers={"Content-Disposition": "inline; filename=preview.pdf"})


# ---------------------------------------------------------------------------
# CSV Export
# ---------------------------------------------------------------------------

@app.route("/export")
def export_page():
    return render_template("export.html")


@app.route("/export/incoming.csv")
def export_incoming_csv():
    date_from = request.args.get("from", "")
    date_to = request.args.get("to", "")

    conn = get_db()

    # Income entries
    income_q = "SELECT amount, date, reference, 'income' as source FROM income"
    params = []
    clauses = []
    if date_from:
        clauses.append("date >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("date <= ?")
        params.append(date_to)
    if clauses:
        income_q += " WHERE " + " AND ".join(clauses)

    # Paid invoices with customer name and line-item total
    invoice_q = """
        SELECT COALESCE(SUM(il.amount),0) as amount, i.date,
               i.invoice_number || ' - ' || c.name as reference,
               'invoice' as source
        FROM invoices i
        JOIN customers c ON i.customer_id = c.id
        LEFT JOIN invoice_lines il ON il.invoice_id = i.id
        WHERE i.status = 'paid'
    """
    inv_params = []
    if date_from:
        invoice_q += " AND i.date >= ?"
        inv_params.append(date_from)
    if date_to:
        invoice_q += " AND i.date <= ?"
        inv_params.append(date_to)
    invoice_q += " GROUP BY i.id"

    income_rows = conn.execute(income_q, params).fetchall()
    invoice_rows = conn.execute(invoice_q, inv_params).fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Amount", "Reference", "Source"])

    all_rows = sorted(
        [dict(r) for r in income_rows] + [dict(r) for r in invoice_rows],
        key=lambda r: r["date"]
    )
    for row in all_rows:
        writer.writerow([row["date"], f"{row['amount']:.2f}", row["reference"], row["source"]])

    csv_data = output.getvalue()
    filename = "incoming"
    if date_from:
        filename += f"_from_{date_from}"
    if date_to:
        filename += f"_to_{date_to}"
    filename += ".csv"

    return Response(csv_data, mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})


@app.route("/export/outgoing.csv")
def export_outgoing_csv():
    date_from = request.args.get("from", "")
    date_to = request.args.get("to", "")

    conn = get_db()
    q = "SELECT amount, date, reference, category FROM expenses"
    params = []
    clauses = []
    if date_from:
        clauses.append("date >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("date <= ?")
        params.append(date_to)
    if clauses:
        q += " WHERE " + " AND ".join(clauses)
    q += " ORDER BY date"

    rows = conn.execute(q, params).fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Amount", "Reference", "Category"])
    for row in rows:
        writer.writerow([row["date"], f"{row['amount']:.2f}", row["reference"], row["category"]])

    csv_data = output.getvalue()
    filename = "outgoing"
    if date_from:
        filename += f"_from_{date_from}"
    if date_to:
        filename += f"_to_{date_to}"
    filename += ".csv"

    return Response(csv_data, mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})


# ---------------------------------------------------------------------------
# REST API
# ---------------------------------------------------------------------------

@app.route("/api/expenses", methods=["GET", "POST"])
def api_expenses():
    conn = get_db()
    if request.method == "POST":
        data = request.json
        conn.execute(
            "INSERT INTO expenses (amount, date, reference, category) VALUES (?,?,?,?)",
            (data["amount"], data["date"], data.get("reference", ""), data.get("category", ""))
        )
        conn.commit()
        eid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        row = dict(conn.execute("SELECT * FROM expenses WHERE id=?", (eid,)).fetchone())
        conn.close()
        return jsonify(row), 201
    else:
        rows = [dict(r) for r in conn.execute("SELECT * FROM expenses ORDER BY date DESC").fetchall()]
        conn.close()
        return jsonify(rows)


@app.route("/api/income", methods=["GET", "POST"])
def api_income():
    conn = get_db()
    if request.method == "POST":
        data = request.json
        conn.execute(
            "INSERT INTO income (amount, date, reference) VALUES (?,?,?)",
            (data["amount"], data["date"], data.get("reference", ""))
        )
        conn.commit()
        eid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        row = dict(conn.execute("SELECT * FROM income WHERE id=?", (eid,)).fetchone())
        conn.close()
        return jsonify(row), 201
    else:
        rows = [dict(r) for r in conn.execute("SELECT * FROM income ORDER BY date DESC").fetchall()]
        conn.close()
        return jsonify(rows)


@app.route("/api/invoices", methods=["GET", "POST"])
def api_invoices():
    conn = get_db()
    if request.method == "POST":
        data = request.json
        inv_num = next_invoice_number(conn)
        conn.execute(
            "INSERT INTO invoices (invoice_number, customer_id, date, due_date, notes) VALUES (?,?,?,?,?)",
            (inv_num, data["customer_id"], data["date"],
             data.get("due_date", ""), data.get("notes", ""))
        )
        inv_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        for line in data.get("lines", []):
            hours = float(line.get("hours", 0) or 0)
            rate = float(line.get("rate", 0) or 0)
            amount = float(line.get("amount", 0) or 0)
            if hours and rate and not amount:
                amount = hours * rate
            conn.execute(
                "INSERT INTO invoice_lines (invoice_id, description, date_attended, hours, rate, amount) VALUES (?,?,?,?,?,?)",
                (inv_id, line["description"], line.get("date_attended", ""), hours, rate, amount)
            )
        conn.commit()

        invoice = dict(conn.execute("SELECT * FROM invoices WHERE id=?", (inv_id,)).fetchone())
        fire_webhooks("invoice.created", {"event": "invoice.created", "invoice": invoice})
        conn.close()
        return jsonify(invoice), 201
    else:
        rows = [dict(r) for r in conn.execute(
            """SELECT i.*, c.name as customer_name,
               (SELECT COALESCE(SUM(amount),0) FROM invoice_lines WHERE invoice_id=i.id) as total
               FROM invoices i JOIN customers c ON i.customer_id=c.id ORDER BY i.date DESC"""
        ).fetchall()]
        conn.close()
        return jsonify(rows)


@app.route("/api/invoices/<int:id>")
def api_invoice_detail(id):
    conn = get_db()
    invoice = dict(conn.execute("SELECT * FROM invoices WHERE id=?", (id,)).fetchone())
    invoice["lines"] = [dict(r) for r in conn.execute(
        "SELECT * FROM invoice_lines WHERE invoice_id=? ORDER BY id", (id,)
    ).fetchall()]
    invoice["total"] = sum(l["amount"] for l in invoice["lines"])
    conn.close()
    return jsonify(invoice)


@app.route("/api/customers", methods=["GET"])
def api_customers():
    conn = get_db()
    rows = [dict(r) for r in conn.execute("SELECT * FROM customers ORDER BY name").fetchall()]
    conn.close()
    return jsonify(rows)


@app.route("/api/summary/monthly")
def api_monthly_summary():
    month = request.args.get("month", date.today().strftime("%Y-%m"))
    month_start = f"{month}-01"
    parts = month.split("-")
    y, m = int(parts[0]), int(parts[1])
    if m == 12:
        next_month_start = f"{y + 1}-01-01"
    else:
        next_month_start = f"{y}-{m + 1:02d}-01"
    conn = get_db()

    expenses = conn.execute(
        "SELECT COALESCE(SUM(amount),0) as total, COUNT(*) as count FROM expenses WHERE date >= ? AND date < ?",
        (month_start, next_month_start)
    ).fetchone()
    income = conn.execute(
        "SELECT COALESCE(SUM(amount),0) as total, COUNT(*) as count FROM income WHERE date >= ? AND date < ?",
        (month_start, next_month_start)
    ).fetchone()
    invoices = conn.execute(
        """SELECT COUNT(*) as count,
           SUM(CASE WHEN status='paid' THEN 1 ELSE 0 END) as paid_count,
           SUM(CASE WHEN status='unpaid' THEN 1 ELSE 0 END) as unpaid_count
           FROM invoices WHERE date >= ? AND date < ?""",
        (month_start, next_month_start)
    ).fetchone()
    invoice_total = conn.execute(
        """SELECT COALESCE(SUM(il.amount),0) as total FROM invoice_lines il
           JOIN invoices i ON il.invoice_id=i.id WHERE i.date >= ? AND i.date < ?""",
        (month_start, next_month_start)
    ).fetchone()

    expense_categories = [dict(r) for r in conn.execute(
        """SELECT COALESCE(category,'Uncategorised') as category, SUM(amount) as total, COUNT(*) as count
           FROM expenses WHERE date >= ? AND date < ? GROUP BY category ORDER BY total DESC""",
        (month_start, next_month_start)
    ).fetchall()]

    conn.close()
    return jsonify({
        "month": month,
        "expenses": {"total": expenses["total"], "count": expenses["count"]},
        "income": {"total": income["total"], "count": income["count"]},
        "invoices": {
            "count": invoices["count"],
            "paid": invoices["paid_count"] or 0,
            "unpaid": invoices["unpaid_count"] or 0,
            "total_value": invoice_total["total"],
        },
        "profit": income["total"] - expenses["total"],
        "expense_categories": expense_categories,
    })


# ---------------------------------------------------------------------------
# Backup & restore (browser)
# ---------------------------------------------------------------------------
# Everything Coffer stores lives in one SQLite file, so backup is a single
# consistent snapshot of that file, and restore is uploading one back.

REQUIRED_TABLES = {
    "customers", "expenses", "income", "invoices", "invoice_lines", "settings",
}


@app.route("/backup")
def backup_page():
    return render_template(
        "backup.html",
        message=request.args.get("message"),
        error=request.args.get("error"),
    )


@app.route("/backup/download")
def backup_download():
    """Stream a consistent SQLite snapshot as a download. `VACUUM INTO` writes a
    clean copy (WAL fully applied), so the file is valid even while the app runs."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    os.unlink(tmp.name)  # VACUUM INTO requires the destination not to exist
    conn = get_db()
    try:
        conn.execute("VACUUM INTO ?", (tmp.name,))
    finally:
        conn.close()
    with open(tmp.name, "rb") as f:
        data = f.read()
    os.unlink(tmp.name)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return send_file(
        io.BytesIO(data),
        mimetype="application/x-sqlite3",
        as_attachment=True,
        download_name=f"coffer-backup-{stamp}.db",
    )


@app.route("/backup/restore", methods=["POST"])
def backup_restore():
    """Replace all data with an uploaded Coffer backup, after validating it is a
    sound SQLite database with the expected schema. Overwrites in place via the
    SQLite backup API, so existing connections stay valid."""
    upload = request.files.get("backup")
    if not upload or not upload.filename:
        return redirect(url_for("backup_page", error="Choose a backup file to restore."))

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    try:
        upload.save(tmp.name)
        tmp.close()
        src = sqlite3.connect(tmp.name)
        try:
            integrity = src.execute("PRAGMA integrity_check").fetchone()[0]
            tables = {
                r[0] for r in src.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if integrity != "ok" or not REQUIRED_TABLES.issubset(tables):
                return redirect(url_for(
                    "backup_page",
                    error="That file is not a valid Coffer backup.",
                ))
            dst = get_db()
            try:
                src.backup(dst)  # copy uploaded DB over the live one
            finally:
                dst.close()
        finally:
            src.close()
    except sqlite3.DatabaseError:
        return redirect(url_for(
            "backup_page", error="That file is not a valid SQLite database."))
    finally:
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)

    return redirect(url_for("backup_page", message="Backup restored successfully."))


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=False)
