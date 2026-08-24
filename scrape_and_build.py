# -*- coding: utf-8 -*-
"""
삼성생명 변액보험 펀드 수익률 대시보드 - 자동 갱신 스크립트
GitHub Actions에서 매일 실행되어 index.html을 최신 데이터로 갱신합니다.
"""
import re
import json
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TARGETS = ["KLVL0326040","KLVL0326390","KLVL0326380","KLVL0326430","KLVL0326460","KLVL0326450","KLVL0326440","KLVL0326260","KLVL0326530","KLVL0326490","KLVL0326360","KLVL0327300","KLVL0326480","KLVL0326630","KLVL0326620","KLVL0326610","KLVL0326600","KLVL0326350","KLVL0326500","KLVL0326520","KLVL0326510","KLVL0326300","KLVL0327310","KLVL0326340","KLVL0327290","KLVL0326470","KLVL0326250","KLVL0326310","KLVL0326280","KLVL0326330","KLVL0326400","KLVL0326540","KLVL0326370","KLVL0327050","KLVL0326410","KLVL0326010","KLVL0326290"]
TARGET_SET = set(TARGETS)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    "Referer": "https://pub.insure.or.kr/",
}

KST = ZoneInfo("Asia/Seoul")


def http_get(url, retries=4, backoff=8):
    last_exc = None
    for attempt in range(retries):
        try:
            return requests.get(url, headers=HEADERS, timeout=30)
        except requests.exceptions.RequestException as e:
            last_exc = e
            print(f"  request failed (attempt {attempt + 1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(backoff)
    raise last_exc


def pct_cell(td):
    if td is None:
        return None
    first = next((c for c in td.contents if isinstance(c, str)), None)
    raw = (first or td.get_text()).strip()
    if raw in ("-", ""):
        return None
    neg = "▼" in raw
    clean = raw.replace("▲", "").replace("▼", "").strip()
    try:
        v = float(clean)
    except ValueError:
        return None
    return -v if neg else v


def fetch_base(std_date, page):
    url = f"https://pub.insure.or.kr/compareDis/variableInsrn/fundDay/list.do?pageIndex={page}&search_stdYmd={std_date}&search_item=itemTypeAll&search_memberCd=L03&pageUnit=30"
    r = http_get(url)
    soup = BeautifulSoup(r.text, "lxml")
    out = []
    for tr in soup.select("table tbody tr"):
        lbl = tr.select_one('label[id^="l_fundCd_"]')
        if not lbl:
            continue
        code = lbl.get_text(strip=True)
        if code not in TARGET_SET:
            continue
        tds = tr.find_all("td")
        out.append({
            "code": code,
            "est": tds[3].get_text(strip=True) if len(tds) > 3 else "",
            "fee": float((tds[16].get_text(strip=True) or "0").replace(",", "")) if len(tds) > 16 else 0,
            "nav": float((tds[24].get_text(strip=True) or "0").replace(",", "")) if len(tds) > 24 else 0,
            "y1": pct_cell(tds[5]) if len(tds) > 5 else None,
            "y3": pct_cell(tds[6]) if len(tds) > 6 else None,
            "y5": pct_cell(tds[7]) if len(tds) > 7 else None,
            "cum": pct_cell(tds[11]) if len(tds) > 11 else None,
        })
    return out


def fetch_period(std_date, from_date):
    out = []
    for page in [1, 2, 3, 4]:
        url = f"https://pub.insure.or.kr/compareDis/variableInsrn/fundDay/list.do?pageIndex={page}&search_stdYmd={std_date}&search_item=itemTypeComp&search_stdStartYmd={from_date}&search_stdEndYmd={std_date}&search_memberCd=L03&pageUnit=30"
        r = http_get(url)
        soup = BeautifulSoup(r.text, "lxml")
        for tr in soup.select("table tbody tr"):
            lbl = tr.select_one('label[id^="l_fundCd_"]')
            if not lbl:
                continue
            code = lbl.get_text(strip=True)
            if code not in TARGET_SET:
                continue
            tds = tr.find_all("td")
            val = tds[8].get_text(strip=True) if len(tds) > 8 else None
            out.append((code, val))
    return out


def numfmt(v, dec=2):
    if v is None:
        return "null"
    return ("%." + str(dec) + "f") % v


def current_std_date():
    try:
        html = open("index.html", encoding="utf-8").read()
    except FileNotFoundError:
        return None
    m = re.search(r'id="stdDateInput"[^>]*value="(\d{4}-\d{2}-\d{2})"', html)
    return m.group(1) if m else None


def main():
    today = datetime.now(KST).date()
    today_str = today.strftime("%Y-%m-%d")

    existing = current_std_date()
    if existing is not None and existing >= today_str:
        print(f"index.html already reflects {existing} (today is {today_str}) — skipping fetch")
        return

    std_date = today

    # If today has zero matches (site not updated yet, or weekend), step back to the
    # most recent weekday and try again, up to 5 attempts.
    data = {}
    for attempt in range(5):
        candidate = std_date - timedelta(days=attempt)
        if candidate.weekday() >= 5:  # Sat=5, Sun=6
            continue
        candidate_str = candidate.strftime("%Y-%m-%d")
        base = []
        for p in [1, 2, 3, 4]:
            base.extend(fetch_base(candidate_str, p))
        if base:
            std_date = candidate
            for b in base:
                data[b["code"]] = dict(b)
            break
    else:
        print("No data found in the last 5 weekdays — aborting without modifying index.html")
        return

    std_date_str = std_date.strftime("%Y-%m-%d")
    period_defs = {
        "d1": (std_date - timedelta(days=1)).strftime("%Y-%m-%d"),
        "w1": (std_date - timedelta(days=7)).strftime("%Y-%m-%d"),
        "m1": (std_date - timedelta(days=30)).strftime("%Y-%m-%d"),
        "m3": (std_date - timedelta(days=90)).strftime("%Y-%m-%d"),
        "m6": (std_date - timedelta(days=180)).strftime("%Y-%m-%d"),
    }
    for key, from_date in period_defs.items():
        rows = fetch_period(std_date_str, from_date)
        for code, val in rows:
            if code in data:
                data[code][key] = float(val) if val is not None else None

    matched_full = sum(1 for v in data.values() if all(k in v for k in ["d1", "w1", "m1", "m3", "m6"]))
    print(f"std_date={std_date_str}  base={len(data)}/37  fully_matched={matched_full}/37")

    if len(data) < 37 or matched_full < 37:
        print("Incomplete data — aborting without modifying index.html")
        return

    # ---- apply to index.html ----
    html = open("index.html", encoding="utf-8").read()
    pattern = re.compile(r'\{code:"(KLVL\d+)"[\s\S]*?desc:"[^"]*"\}')

    def repl(m):
        code = m.group(1)
        d = data.get(code)
        if not d:
            return m.group(0)
        s = m.group(0)
        s = re.sub(r'est:"[^"]*"', 'est:"%s"' % d["est"], s)
        s = re.sub(r'fee:[-0-9.]+', 'fee:%s' % numfmt(d["fee"], 4), s)
        s = re.sub(r'nav:[-0-9.]+', 'nav:%s' % numfmt(d["nav"], 2), s)
        s = re.sub(r'd1:[-0-9.]+', 'd1:%s' % numfmt(d.get("d1")), s)
        s = re.sub(r'w1:[-0-9.]+', 'w1:%s' % numfmt(d.get("w1")), s)
        s = re.sub(r'm1:[-0-9.]+', 'm1:%s' % numfmt(d.get("m1")), s)
        s = re.sub(r'm3:[-0-9.]+', 'm3:%s' % numfmt(d.get("m3")), s)
        s = re.sub(r'm6:[-0-9.]+', 'm6:%s' % numfmt(d.get("m6")), s)
        s = re.sub(r'y1:[-0-9.]+', 'y1:%s' % numfmt(d["y1"]), s)
        s = re.sub(r'y3:[-0-9.]+', 'y3:%s' % numfmt(d["y3"]), s)
        s = re.sub(r'y5:(null|[-0-9.]+)', 'y5:%s' % numfmt(d["y5"]), s)
        s = re.sub(r'cum:[-0-9.]+', 'cum:%s' % numfmt(d["cum"]), s)
        return s

    new_html, n = pattern.subn(repl, html)
    print("objects replaced:", n)

    new_html = re.sub(r'value="2026-[0-9-]+"', 'value="%s"' % std_date_str, new_html)
    new_html = re.sub(r'생성 시각: 2026-[0-9-]+ 기준 스냅샷', '생성 시각: %s 기준 스냅샷' % std_date_str, new_html)
    # clear any leftover failure banner
    new_html = re.sub(r'(<div id="autoStatusLine" class="auto-status-line">)[^<]*(</div>)', r'\1\2', new_html)

    open("index.html", "w", encoding="utf-8").write(new_html)
    print("index.html updated for", std_date_str)


if __name__ == "__main__":
    main()
