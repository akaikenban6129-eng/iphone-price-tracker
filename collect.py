# iPhone 15シリーズ 中古価格 収集＋買い時メール通知（GitHub Actionsで毎朝実行）
import csv, json, os, re, smtplib, time, datetime as dt
from email.mime.text import MIMEText
import requests
from bs4 import BeautifulSoup

JST = dt.timezone(dt.timedelta(hours=9))
TODAY = dt.datetime.now(JST).strftime("%Y/%m/%d")
CFG = json.load(open("config.json", encoding="utf-8"))
CSV_PATH = "data/prices.csv"
HEADER = ["取得日","サイト","モデル","色","容量(GB)","バッテリー(%)","元ランク","SIM","利用制限","価格(円)","送料(円)","URL","備考"]
UA = {"User-Agent": "Mozilla/5.0 (personal price tracker; 1 req/day)"}
COLORS = ["ブラックチタニウム","ホワイトチタニウム","ブルーチタニウム","ナチュラルチタニウム",
          "ブラック","ブルー","グリーン","イエロー","ピンク"]
RANKS = sorted(CFG["rank_map"].keys(), key=len, reverse=True)

def detect_model(t):
    for m in ["iPhone 15 Pro Max","iPhone 15 Pro","iPhone 15 Plus","iPhone 15"]:
        if re.search(m.replace(" ", r"\s*"), t, re.I):
            return m
    return None

def parse_block(text, site, url):
    model = detect_model(text)
    cap = re.search(r"(128|256|512)\s*GB", text, re.I)
    price = re.search(r"[¥￥]\s*([\d,]{5,})|([\d,]{5,})\s*円", text)
    if not (model and cap and price):
        return None
    p = int((price.group(1) or price.group(2)).replace(",", ""))
    bat = re.search(r"バッテリー[^\d]{0,15}(\d{2,3})\s*%", text)
    color = next((c for c in COLORS if c in text), "")
    rank = next((r for r in RANKS if r in text), "")
    if site == "Apple整備品":
        rank, bat_v = "整備済製品", 100
    else:
        bat_v = int(bat.group(1)) if bat else ""
    sim = "SIMフリー" if "SIMフリー" in text or site == "Apple整備品" else ("SIMロック" if "SIMロック" in text else "")
    lim = "○" if re.search(r"(利用制限|ネットワーク)[^\n]{0,10}[○〇]", text) or site == "Apple整備品" else \
          ("△" if "△" in text else ("×" if "×" in text else ""))
    return [TODAY, site, model, color, int(cap.group(1)), bat_v, rank, sim, lim, p,
            CFG["sites"][site].get("shipping", 0), url, ""]

def scrape(site, info):
    rows = []
    for url in info["urls"]:
        r = requests.get(url, headers=UA, timeout=30); r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for el in soup.find_all(["li", "article", "div", "tr"]):
            t = el.get_text(" ", strip=True)
            if 20 < len(t) < 600 and "iPhone" in t and ("円" in t or "¥" in t or "￥" in t):
                row = parse_block(t, site, url)
                if row:
                    a = el.find("a", href=True)
                    if a: row[11] = requests.compat.urljoin(url, a["href"])
                    rows.append(row)
        time.sleep(5)
    return list({tuple(r[1:10]): r for r in rows}.values())

def load_all():
    if not os.path.exists(CSV_PATH): return []
    with open(CSV_PATH, encoding="utf-8-sig") as f: return list(csv.DictReader(f))

def is_target(r):
    c = CFG["conditions"]
    try:
        return (int(r["バッテリー(%)"] or 0) >= c["min_battery"] and int(r["容量(GB)"]) == c["capacity_gb"]
                and CFG["rank_map"].get(r["元ランク"], "") in c["ok_ranks"]
                and r["SIM"] == c["sim"] and r["利用制限"] == c["network_limit"])
    except ValueError:
        return False

def check_buy_signal(all_rows):
    c = CFG["conditions"]; today = dt.datetime.strptime(TODAY, "%Y/%m/%d").date(); msgs = []
    for m in CFG["models"]:
        daily = {}
        for r in all_rows:
            if r["モデル"] == m and is_target(r):
                p = int(r["価格(円)"]) + int(r["送料(円)"] or 0)
                if r["取得日"] not in daily or p < daily[r["取得日"]][0]:
                    daily[r["取得日"]] = (p, r)
        if TODAY not in daily: continue
        p_today, row = daily[TODAY]
        past30 = [v[0] for d, v in daily.items()
                  if 0 <= (today - dt.datetime.strptime(d, "%Y/%m/%d").date()).days < 30]
        avg30 = sum(past30) / len(past30); low = min(v[0] for v in daily.values())
        if len(past30) >= 7 and (p_today <= avg30*(1-c["drop_vs_30d"]) or p_today <= low*(1+c["near_low"])):
            msgs.append(f"■ {m}：¥{p_today:,}（{row['サイト']}／{row['色']}／バッテリー{row['バッテリー(%)']}%）\n"
                        f"   30日平均 ¥{avg30:,.0f}（{p_today/avg30-1:+.1%}）／過去最安 ¥{low:,}\n   {row['URL']}")
    return msgs

def send_mail(body):
    user, pw, to = os.environ.get("GMAIL_USER"), os.environ.get("GMAIL_APP_PASSWORD"), os.environ.get("MAIL_TO")
    if not (user and pw and to): print("メール設定なし"); return
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = f"【買い時】iPhone 15シリーズ中古 {TODAY}"; msg["From"], msg["To"] = user, to
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(user, pw); s.send_message(msg)

def main():
    os.makedirs("data", exist_ok=True); new_rows, log = [], []
    for site, info in CFG["sites"].items():
        if not info.get("enabled"): continue
        try:
            rs = scrape(site, info); new_rows += rs; log.append(f"{site}: {len(rs)}件")
        except Exception as e:
            log.append(f"{site}: 失敗 {e}")
    print("\n".join(log))
    exists = os.path.exists(CSV_PATH)
    with open(CSV_PATH, "a", newline="", encoding="utf-8" if exists else "utf-8-sig") as f:
        w = csv.writer(f)
        if not exists: w.writerow(HEADER)
        w.writerows(new_rows)
    msgs = check_buy_signal(load_all())
    if msgs:
        send_mail("本日の買い時候補です。\n\n" + "\n\n".join(msgs) + "\n\n取得状況：\n" + "\n".join(log))

if __name__ == "__main__":
    main()
