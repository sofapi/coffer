"""Route-level behaviour: theme persistence, palette application, the dashboard
payload, and that the existing pages still render."""

import json
import re
from datetime import date

import pytest

import finance
import theme
from tests.test_finance import add_customer, add_expense, add_income, add_invoice

# --------------------------------------------------------------------------
# theme persistence
# --------------------------------------------------------------------------

def test_default_palette_is_applied_before_any_choice_is_made(client):
    html = client.get("/").get_data(as_text=True)
    assert 'data-palette="coffer-classic"' in html


def test_saving_a_palette_persists_it_across_requests(client):
    res = client.post("/appearance/save", data={"palette": "midnight"})
    assert res.status_code == 302

    html = client.get("/").get_data(as_text=True)
    assert 'data-palette="midnight"' in html
    # ...and on every other page, not just the one that set it.
    for path in ("/invoices", "/expenses", "/reports", "/appearance", "/backup"):
        assert 'data-palette="midnight"' in client.get(path).get_data(as_text=True), path


def test_saved_palette_survives_a_fresh_app_context(client, db_path):
    client.post("/appearance/save", data={"palette": "ocean"})
    import db as db_module
    conn = db_module.get_db()
    try:
        stored = db_module.get_settings(conn)[theme.PALETTE_SETTING_KEY]
    finally:
        conn.close()
    assert stored == "ocean"


def test_an_unknown_palette_is_rejected_and_changes_nothing(client):
    client.post("/appearance/save", data={"palette": "plum"})
    res = client.post("/appearance/save", data={"palette": "not-a-palette"})
    assert res.status_code == 302
    assert "saved=invalid" in res.headers["Location"]
    assert 'data-palette="plum"' in client.get("/").get_data(as_text=True)


def test_a_corrupt_stored_palette_degrades_to_the_default(client):
    import db as db_module
    conn = db_module.get_db()
    db_module.save_setting(conn, theme.PALETTE_SETTING_KEY, "deleted-palette")
    conn.close()
    html = client.get("/").get_data(as_text=True)
    assert 'data-palette="coffer-classic"' in html
    assert html.count("data-palette=") >= 1


def test_theme_setting_is_backfilled_into_an_existing_database(db_path):
    """Upgrading an install that predates the setting must not need a migration."""
    import db as db_module
    conn = db_module.get_db()
    conn.execute("DELETE FROM settings WHERE key = ?", (theme.PALETTE_SETTING_KEY,))
    conn.commit()
    conn.close()

    db_module.init_db()

    conn = db_module.get_db()
    try:
        assert db_module.get_settings(conn)[theme.PALETTE_SETTING_KEY] == "coffer-classic"
    finally:
        conn.close()


def test_backfill_never_overwrites_a_users_choice(db_path):
    import db as db_module
    conn = db_module.get_db()
    db_module.save_setting(conn, theme.PALETTE_SETTING_KEY, "sand")
    conn.close()

    db_module.init_db()

    conn = db_module.get_db()
    try:
        assert db_module.get_settings(conn)[theme.PALETTE_SETTING_KEY] == "sand"
    finally:
        conn.close()


# --------------------------------------------------------------------------
# palette application
# --------------------------------------------------------------------------

def test_palette_tokens_are_inlined_so_nothing_flashes(client):
    client.post("/appearance/save", data={"palette": "midnight"})
    html = client.get("/").get_data(as_text=True)
    head = html.split("</head>", 1)[0]
    # The tokens must arrive inline, ahead of the stylesheet request.
    assert "--bg:#0e1524" in head
    assert head.index("<style>") < head.index('href="/static/style.css"')


def test_only_the_appearance_page_loads_the_full_palette_stylesheet(client):
    assert "/palettes.css" not in client.get("/").get_data(as_text=True)
    assert "/palettes.css" in client.get("/appearance").get_data(as_text=True)


def test_palettes_css_is_generated_and_complete(client):
    res = client.get("/palettes.css")
    assert res.status_code == 200
    assert res.mimetype == "text/css"
    css = res.get_data(as_text=True)
    for p in theme.PALETTES:
        assert f'html[data-palette="{p.id}"]' in css


def test_appearance_page_lists_every_palette_with_a_visual_swatch(client):
    html = client.get("/appearance").get_data(as_text=True)
    for p in theme.PALETTES:
        assert f'value="{p.id}"' in html
        assert p.name in html
        # The swatch paints the palette's own colours, not just a label.
        assert p.resolved()["brand"] in html
        assert p.resolved()["chart-revenue"] in html


def test_appearance_page_marks_the_current_palette(client):
    client.post("/appearance/save", data={"palette": "forest"})
    html = client.get("/appearance").get_data(as_text=True)
    assert re.search(r'value="forest"[^>]*checked', html)
    assert "Current" in html


def test_no_hardcoded_colours_remain_in_the_stylesheet():
    """Every colour must be a token, or a palette cannot repaint the app."""
    with open("static/style.css") as fh:
        css = fh.read()
    literals = re.findall(r"#[0-9a-fA-F]{3,8}\b", css)
    assert literals == [], f"hard-coded colours in style.css: {set(literals)}"


# --------------------------------------------------------------------------
# dashboard
# --------------------------------------------------------------------------

def test_dashboard_renders_with_an_empty_database(client):
    res = client.get("/")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "Financial performance" in html
    assert "No invoices yet" in html


def test_has_data_distinguishes_a_new_install_from_a_quiet_period(client, conn):
    """The chart's empty-state copy branches on this: telling a brand new user
    to 'try a wider period' is useless advice."""
    assert client.get("/api/dashboard/performance").get_json()["has_data"] is False

    cid = add_customer(conn)
    add_invoice(conn, cid, "2019-03-01", [100.0], status="paid")
    payload = client.get("/api/dashboard/performance?period=6m").get_json()
    assert payload["has_data"] is True
    assert all(p["revenue"] == 0 for p in payload["series"])


def test_dashboard_embeds_the_chart_payload_for_first_paint(client, conn):
    cid = add_customer(conn)
    add_invoice(conn, cid, "2026-08-01", [500.0], status="paid")

    html = client.get("/?period=6m").get_data(as_text=True)
    blob = re.search(
        r'<script type="application/json" id="performance-data">(.*?)</script>',
        html, re.S)
    assert blob, "chart data must be embedded so the chart paints without a round trip"
    data = json.loads(blob.group(1))
    assert len(data["series"]) == 6
    assert data["window"]["period"] == "6m"


@pytest.mark.parametrize("period,expected", [("6m", 6), ("12m", 12)])
def test_dashboard_period_selection(client, period, expected):
    res = client.get(f"/api/dashboard/performance?period={period}")
    assert res.status_code == 200
    assert len(res.get_json()["series"]) == expected


def test_dashboard_custom_range(client):
    res = client.get("/api/dashboard/performance?period=custom&from=2026-01-01&to=2026-03-31")
    data = res.get_json()
    assert [p["month"] for p in data["series"]] == ["2026-01", "2026-02", "2026-03"]


def test_a_hand_edited_period_cannot_break_the_dashboard(client):
    for query in ("?period=%00", "?period=custom&from=abc&to=def", "?period=999m"):
        assert client.get("/" + query).status_code == 200
        assert client.get("/api/dashboard/performance" + query).status_code == 200


def test_dashboard_labels_net_honestly_and_explains_the_limit(client):
    html = client.get("/").get_data(as_text=True)
    assert "Net" in html
    assert "Not gross profit" in html or "not gross or net profit" in html
    # Invoice value must never be presented as profit.
    assert "Invoiced" in html


def test_dashboard_shows_outstanding_and_overdue(client, conn):
    cid = add_customer(conn)
    add_invoice(conn, cid, "2020-01-01", [750.0], status="unpaid", due_date="2020-02-01")
    html = client.get("/").get_data(as_text=True)
    assert "Outstanding" in html
    assert "overdue" in html


def test_dashboard_totals_match_the_api(client, conn):
    cid = add_customer(conn)
    add_invoice(conn, cid, "2026-08-02", [1000.0], status="paid")
    add_expense(conn, 250.0, "2026-08-03")
    add_income(conn, 100.0, "2026-08-04")

    api = client.get("/api/dashboard/performance?period=6m").get_json()
    assert api["totals"]["revenue"] == 1100.0
    assert api["totals"]["costs"] == 250.0
    assert api["totals"]["net"] == 850.0

    html = client.get("/?period=6m").get_data(as_text=True)
    assert "£1,100" in html and "£850" in html


# --------------------------------------------------------------------------
# derived invoice status
# --------------------------------------------------------------------------

def test_unpaid_invoice_past_its_due_date_reads_as_overdue(client, conn):
    cid = add_customer(conn)
    add_invoice(conn, cid, "2020-01-01", [100.0], status="unpaid", due_date="2020-02-01")
    for path in ("/invoices", "/"):
        assert "badge-overdue" in client.get(path).get_data(as_text=True), path


def test_unpaid_invoice_before_its_due_date_is_just_unpaid(client, conn):
    cid = add_customer(conn)
    add_invoice(conn, cid, "2026-08-01", [100.0], status="unpaid", due_date="2099-01-01")
    html = client.get("/invoices").get_data(as_text=True)
    assert "badge-unpaid" in html
    assert "badge-overdue" not in html


def test_paid_invoice_is_never_overdue(client, conn):
    cid = add_customer(conn)
    add_invoice(conn, cid, "2020-01-01", [100.0], status="paid", due_date="2020-02-01")
    html = client.get("/invoices").get_data(as_text=True)
    assert "badge-paid" in html
    assert "badge-overdue" not in html


# --------------------------------------------------------------------------
# existing behaviour must keep working
# --------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "/", "/expenses", "/income", "/invoices", "/customers", "/reports",
    "/export", "/appearance", "/invoice-settings", "/webhooks", "/backup",
    "/health",
])
def test_every_page_still_renders(client, path):
    assert client.get(path).status_code == 200


def test_reports_counts_invoices_not_line_items(client, conn):
    """Regression: the old query joined invoice_lines and COUNT(*)'d the rows,
    so a three-line invoice was reported as three unpaid invoices."""
    cid = add_customer(conn)
    add_invoice(conn, cid, "2026-05-01", [10.0, 20.0, 30.0], status="unpaid")
    html = client.get("/reports?ty=2026").get_data(as_text=True)
    assert "1 (£60.00)" in html


def test_invoice_and_pdf_flow_still_works(client, conn):
    cid = add_customer(conn, "PDF Customer")
    inv_id = add_invoice(conn, cid, "2026-08-01", [120.0], status="unpaid")
    assert client.get(f"/invoices/{inv_id}").status_code == 200
    pdf = client.get(f"/invoices/{inv_id}/pdf")
    assert pdf.status_code == 200
    assert pdf.data[:4] == b"%PDF"


def test_csv_export_still_works(client, conn):
    cid = add_customer(conn)
    add_invoice(conn, cid, "2026-08-01", [120.0], status="paid")
    add_expense(conn, 30.0, "2026-08-02", "Travel")
    incoming = client.get("/export/incoming.csv").get_data(as_text=True)
    outgoing = client.get("/export/outgoing.csv").get_data(as_text=True)
    assert "120.00" in incoming
    assert "30.00" in outgoing and "Travel" in outgoing


def test_navigation_includes_appearance_without_losing_existing_links(client):
    html = client.get("/").get_data(as_text=True)
    for label in ("Dashboard", "Expenses", "Income", "Invoices", "Customers",
                  "Reports", "Export", "Appearance", "Invoice Settings",
                  "Webhooks", "Backup"):
        assert f">{label}</a>" in html, label


# --------------------------------------------------------------------------
# tax-year input validation (Reports)
# --------------------------------------------------------------------------

def test_reports_accepts_a_valid_tax_year(client, conn):
    add_income(conn, 500.0, "2025-05-01")
    res = client.get("/reports?ty=2025")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "Full Year 2025/2026" in html and "£500.00" in html
    assert "alert-danger" not in html


@pytest.mark.parametrize("ty", [
    "abc", "20x6", "2026.0", "-1", "2026/27", "%3Cscript%3E",   # malformed
    "1999", "0000", "99999999", "3000",                          # out of range
])
def test_reports_rejects_a_bad_tax_year_without_a_server_error(client, ty):
    res = client.get(f"/reports?ty={ty}")
    assert res.status_code == 302
    assert "error=" in res.headers["Location"]
    page = client.get(res.headers["Location"])
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "alert-danger" in html and "is not a valid tax year" in html
    assert "<script>" not in html


def test_reports_treats_an_empty_tax_year_as_the_current_one(client):
    res = client.get("/reports?ty=")
    assert res.status_code == 200
    assert "alert-danger" not in res.get_data(as_text=True)


def test_reports_accepts_next_tax_year_but_not_beyond(client):
    current = finance.tax_year_of(date.today())
    assert client.get(f"/reports?ty={current + 1}").status_code == 200
    assert client.get(f"/reports?ty={current + 2}").status_code == 302


@pytest.mark.parametrize("month", ["zz", "2026-13", "2026-4", "2027-05", "2026-03"])
def test_reports_rejects_a_month_outside_the_tax_year(client, month):
    res = client.get(f"/reports?ty=2026&month={month}")
    assert res.status_code == 302
    assert "ty=2026" in res.headers["Location"] and "error=" in res.headers["Location"]
    assert client.get(res.headers["Location"]).status_code == 200


def test_reports_accepts_a_month_inside_the_tax_year(client):
    for month in ("2026-04", "2027-03"):
        assert client.get(f"/reports?ty=2026&month={month}").status_code == 200
