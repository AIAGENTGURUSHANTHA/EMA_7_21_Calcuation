"""
Google Sheet -> Stock EMA Updater (GitHub Actions version)
---------------------------------------------------------------------
Column A : Ticker            (input, provided by user)
Column B : EMA_10
Column C : EMA_7
Column D : EMA_21
Column E : Last Updated (IST)
Column F : Bullish / Bearish  (EMA7 > EMA21 => Bullish, else Bearish)
           - Bullish rows filled light green
           - Bearish rows filled light red

Credentials come from the GOOGLE_CREDENTIALS environment variable
(a GitHub Secret holding the full service-account JSON) — nothing
sensitive is stored in the repo itself.
"""

import os
import json
from datetime import datetime, timezone, timedelta

import gspread
from google.oauth2.service_account import Credentials
import yfinance as yf

# ---------- CONFIG ----------
SHEET_NAME = "My Stock Sheet"     # exact name of the Google Sheet
WORKSHEET_NAME = "Sheet1"         # tab name inside the spreadsheet
EMA_10 = 10
EMA_FAST = 7
EMA_SLOW = 21
HISTORY_DAYS = "3mo"
# -----------------------------

IST = timezone(timedelta(hours=5, minutes=30))

LIGHT_GREEN = {"red": 0.80, "green": 0.93, "blue": 0.80}
LIGHT_RED = {"red": 0.96, "green": 0.80, "blue": 0.80}


def connect_to_sheet():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds_json = os.environ["GOOGLE_CREDENTIALS"]
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    sheet = client.open(SHEET_NAME).worksheet(WORKSHEET_NAME)
    return sheet


def get_tickers(sheet) -> list:
    col_a = sheet.col_values(1)
    return [t.strip().upper() for t in col_a[1:] if t.strip()]


def calculate_emas(ticker: str):
    """Return (ema10, ema7, ema21) for a ticker, or (None, None, None) on failure."""
    try:
        data = yf.download(ticker, period=HISTORY_DAYS, progress=False)
        if data.empty:
            print(f"  No data for {ticker}")
            return None, None, None
        close = data["Close"]
        ema10 = close.ewm(span=EMA_10, adjust=False).mean().iloc[-1]
        ema7 = close.ewm(span=EMA_FAST, adjust=False).mean().iloc[-1]
        ema21 = close.ewm(span=EMA_SLOW, adjust=False).mean().iloc[-1]
        return round(float(ema10), 2), round(float(ema7), 2), round(float(ema21), 2)
    except Exception as e:
        print(f"  Error fetching {ticker}: {e}")
        return None, None, None


def update_sheet():
    sheet = connect_to_sheet()
    tickers = get_tickers(sheet)
    now_ist = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")

    print(f"Run started: {now_ist} IST")
    print(f"Found {len(tickers)} tickers.\n")

    # Headers
    sheet.update_cell(1, 2, f"EMA_{EMA_10}")
    sheet.update_cell(1, 3, f"EMA_{EMA_FAST}")
    sheet.update_cell(1, 4, f"EMA_{EMA_SLOW}")
    sheet.update_cell(1, 5, "Last Updated (IST)")
    sheet.update_cell(1, 6, "Signal")

    last_row = len(tickers) + 1
    value_cells = sheet.range(f"B2:F{last_row}")  # 5 columns wide, 1 API call to fetch
    color_requests = []

    for row_offset, ticker in enumerate(tickers):
        row = row_offset + 2  # sheet row number (row 1 = header)
        print(f"Row {row}: {ticker}")
        ema10, ema7, ema21 = calculate_emas(ticker)

        # index into value_cells: 5 cells per row (B, C, D, E, F)
        base = row_offset * 5
        b_cell, c_cell, d_cell, e_cell, f_cell = value_cells[base:base + 5]

        if ema10 is not None and ema7 is not None and ema21 is not None:
            signal = "Bullish" if ema7 > ema21 else "Bearish"
            b_cell.value = ema10
            c_cell.value = ema7
            d_cell.value = ema21
            e_cell.value = now_ist
            f_cell.value = signal
            print(f"  EMA10={ema10}  EMA7={ema7}  EMA21={ema21}  -> {signal}")

            fill_color = LIGHT_GREEN if signal == "Bullish" else LIGHT_RED
            color_requests.append({
                "repeatCell": {
                    "range": {
                        "sheetId": sheet.id,
                        "startRowIndex": row - 1,
                        "endRowIndex": row,
                        "startColumnIndex": 5,  # column F (0-indexed)
                        "endColumnIndex": 6,
                    },
                    "cell": {"userEnteredFormat": {"backgroundColor": fill_color}},
                    "fields": "userEnteredFormat.backgroundColor",
                }
            })
        else:
            b_cell.value = "N/A"
            c_cell.value = "N/A"
            d_cell.value = "N/A"
            e_cell.value = now_ist
            f_cell.value = "N/A"

    # One API call to write all values
    sheet.update_cells(value_cells, value_input_option="USER_ENTERED")

    # One API call to apply all color formatting
    if color_requests:
        sheet.spreadsheet.batch_update({"requests": color_requests})

    print(f"\nDone. Columns B, C, D, E, F updated at {now_ist} IST.")


if __name__ == "__main__":
    update_sheet()
