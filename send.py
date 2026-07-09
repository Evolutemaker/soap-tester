#!/usr/bin/env python3
"""
send.py — отправка тестовых SOAP/REST-запросов. Работает на Windows / macOS / Linux.

Примеры:
    python send.py                  # интерактивное меню
    python send.py ACTIVE           # сразу конкретное событие
    python send.py --list           # показать все события с номерами
    python send.py ACTIVE --dry     # собрать запрос, показать, НЕ отправлять
    python send.py ACTIVE --op UPDATE
    python send.py ACTIVE --rest    # послать чистый JSON на REST-эндпоинт
    python send.py ACTIVE --debug   # показать эквивалентную curl-команду
"""
import json
import os
import re
import ssl
import sys
import time
import uuid
import xml.dom.minidom as minidom
from datetime import datetime, timezone, timedelta
from urllib import request as urlreq
from urllib.error import HTTPError, URLError

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE  = os.path.join(ROOT, "config.env")
INDEX_FILE   = os.path.join(ROOT, "events.index.json")
TEMPLATES    = os.path.join(ROOT, "templates")
RESPONSES    = os.path.join(ROOT, "responses")
TZ           = timezone(timedelta(hours=5))

# ── colours ───────────────────────────────────────────────────────────────────
def _colors():
    if not sys.stdout.isatty():
        return {k: "" for k in ("B","DIM","R","CYAN","GRN","YEL","RED","MAG")}
    if sys.platform == "win32":
        os.system("")  # activates VT-processing on Windows 10+
    return {"B":"\033[1m","DIM":"\033[2m","R":"\033[0m",
            "CYAN":"\033[36m","GRN":"\033[32m","YEL":"\033[33m",
            "RED":"\033[31m","MAG":"\033[35m"}

C = _colors()
def hr(): print(f"{C['DIM']}{'─'*60}{C['R']}")

# ── config.env ────────────────────────────────────────────────────────────────
def load_config():
    cfg = {}
    if not os.path.exists(CONFIG_FILE):
        return cfg
    with open(CONFIG_FILE, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r'^([A-Za-z_]\w*)=(.*)$', line)
            if not m:
                continue
            k, v = m.group(1), m.group(2)
            cfg[k] = re.sub(r'^(["\'])(.*)\1$', r'\2', v)
    return cfg

CFG = load_config()
def cfg(key, default=""):
    return CFG.get(key) or default

# ── time helpers ──────────────────────────────────────────────────────────────
def now_ts(millis=False):
    n = datetime.now(TZ)
    if millis:
        return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond//1000:03d}"
    z = n.strftime("%z")        # +0500
    return n.strftime("%Y-%m-%dT%H:%M:%S") + z[:3] + ":" + z[3:]

# ── events index ──────────────────────────────────────────────────────────────
def load_events():
    data = json.load(open(INDEX_FILE, encoding="utf-8"))
    items = [v for v in data.values()
             if os.path.exists(os.path.join(TEMPLATES, v["eventType"] + ".json"))]
    return sorted(items, key=lambda x: x["eventType"])

# ── pretty print ──────────────────────────────────────────────────────────────
def pretty(text):
    s = text.lstrip()
    try:
        if s.startswith("<"):
            out = minidom.parseString(text).toprettyxml(indent="  ")
            print("\n".join(ln for ln in out.splitlines() if ln.strip()))
        elif s.startswith(("{","[")):
            print(json.dumps(json.loads(text), ensure_ascii=False, indent=2))
        else:
            print(text.rstrip())
    except Exception:
        print(text.rstrip())

# ── build request ─────────────────────────────────────────────────────────────
def build_soap(data_json, event_id, event_type, op):
    msg_id  = str(uuid.uuid4())
    corr_id = cfg("CORRELATION_ID") or str(uuid.uuid4())[:8]
    return (
        f'<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"'
        f' xmlns:typ="http://bip.bee.kz/SyncChannel/v10/Types">\n'
        f'    <soapenv:Header/>\n'
        f'    <soapenv:Body>\n'
        f'        <typ:SendMessage>\n'
        f'            <request>\n'
        f'                <requestInfo>\n'
        f'                    <messageId>{msg_id}</messageId>\n'
        f'                    <correlationId>{corr_id}</correlationId>\n'
        f'                    <serviceId>{cfg("SERVICE_ID","EHD-DATA-RECEIVER")}</serviceId>\n'
        f'                    <operationType>{op}</operationType>\n'
        f'                    <messageDate>{now_ts(millis=True)}</messageDate>\n'
        f'                    <sender>\n'
        f'                        <senderId>{cfg("SENDER_ID")}</senderId>\n'
        f'                        <password>{cfg("SENDER_PASSWORD")}</password>\n'
        f'                    </sender>\n'
        f'                </requestInfo>\n'
        f'                <requestData>\n'
        f'                    <data xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"\n'
        f'                          xmlns:tns="http://mz.kz/exd/integration"'
        f' xsi:type="tns:RequestDataMessage">\n'
        f'                        <login>{cfg("LOGIN")}</login>\n'
        f'                        <password>{cfg("PASSWORD")}</password>\n'
        f'                        <eventId>{event_id}</eventId>\n'
        f'                        <eventType>{event_type}</eventType>\n'
        f'                        <operationType>{op}</operationType>\n'
        f'                        <misId>{cfg("MIS_ID")}</misId>\n'
        f'                        <sendDate>{now_ts()}</sendDate>\n'
        f'                        <eventData><![CDATA[\n'
        f'{data_json}\n'
        f']]>\n'
        f'                        </eventData>\n'
        f'                    </data>\n'
        f'                </requestData>\n'
        f'            </request>\n'
        f'        </typ:SendMessage>\n'
        f'    </soapenv:Body>\n'
        f'</soapenv:Envelope>'
    )

def build_payload(event_type, event_id, op, mode):
    raw = open(os.path.join(TEMPLATES, f"{event_type}.json"), encoding="utf-8").read()
    raw = raw.replace("{{TEST_IIN}}", cfg("TEST_IIN"))
    body = json.loads(raw)
    body["eventId"]   = event_id
    body["eventType"] = event_type
    data_json = json.dumps(body, ensure_ascii=False, indent=2)
    return data_json if mode == "rest" else build_soap(data_json, event_id, event_type, op)

# ── SSL context (respects CURL_EXTRA=-k) ──────────────────────────────────────
def ssl_ctx():
    if "-k" in cfg("CURL_EXTRA", "").split():
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    return ssl.create_default_context()

# ── send ──────────────────────────────────────────────────────────────────────
def send(url, payload, content_type, op, mode):
    method = "POST"
    if mode == "rest":
        if op == "UPDATE": method = "PUT"
        elif op == "DELETE": method = "DELETE"

    headers = {"Content-Type": content_type}
    if mode == "soap" and cfg("SOAP_ACTION"):
        headers["SOAPAction"] = cfg("SOAP_ACTION")
    for line in cfg("EXTRA_HEADERS", "").splitlines():
        line = line.strip()
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip()] = v.strip()

    data = payload.encode("utf-8") if op != "DELETE" else None
    req  = urlreq.Request(url, data=data, headers=headers, method=method)

    t0 = time.time()
    try:
        with urlreq.urlopen(req, context=ssl_ctx(), timeout=60) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace"), time.time()-t0
    except HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace"), time.time()-t0
    except URLError as e:
        return 0, str(e), time.time()-t0

# ── CLI ───────────────────────────────────────────────────────────────────────
def main():
    args = sys.argv[1:]

    # --help / -h
    if "--help" in args or "-h" in args:
        print(__doc__)
        return

    # --list / -l
    if "--list" in args or "-l" in args:
        events = load_events()
        w = max(len(e["eventType"]) for e in events)
        for n, e in enumerate(events, 1):
            print(f"{n:>3}) {e['eventType']:<{w}}  {e['ru']}")
        return

    # parse flags
    dry   = "--dry" in args or "--dry-run" in args
    debug = "--debug" in args
    mode  = cfg("MODE", "soap")
    if "--rest" in args: mode = "rest"
    if "--soap" in args: mode = "soap"

    op = "CREATE"
    if "--op" in args:
        idx = args.index("--op")
        op = args[idx+1].upper() if idx+1 < len(args) else "CREATE"

    event = next((a.upper().replace("-","_") for a in args if not a.startswith("-")), "")

    # interactive menu if no event given
    if not event:
        events = load_events()
        print(f"{C['B']}Доступные события:{C['R']}")
        w = max(len(e["eventType"]) for e in events)
        for n, e in enumerate(events, 1):
            print(f"{n:>3}) {e['eventType']:<{w}}  {e['ru']}")
        hr()
        try:
            num = input("Номер события: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nОтменено.")
            return
        try:
            event = events[int(num)-1]["eventType"]
        except (ValueError, IndexError):
            print(f"{C['RED']}Нет такого номера.{C['R']}")
            sys.exit(1)

    tpl = os.path.join(TEMPLATES, f"{event}.json")
    if not os.path.exists(tpl):
        print(f"{C['RED']}Нет шаблона для '{event}'.{C['R']}  Список: python send.py --list")
        sys.exit(1)

    stamp    = datetime.now().strftime("%m%d%H%M")
    event_id = f"EVENT_{event}_{stamp}"
    payload  = build_payload(event, event_id, op, mode)

    # target URL
    if mode == "soap":
        target = cfg("ENDPOINT")
    else:
        ev_map = {e["eventType"]: e for e in load_events()}
        path   = ev_map.get(event, {}).get("path", "/" + event.lower().replace("_","-"))
        target = cfg("REST_BASE") + path
        if op != "CREATE":
            target += f"/{event_id}"

    # print header
    hr()
    print(f"{C['B']}Событие:{C['R']}    {C['CYAN']}{event}{C['R']}")
    print(f"{C['B']}eventId:{C['R']}    {event_id}")
    print(f"{C['B']}operation:{C['R']}  {op}")
    print(f"{C['B']}режим:{C['R']}      {mode}")
    print(f"{C['B']}endpoint:{C['R']}   {target}")
    hr()
    print(f"{C['B']}{C['MAG']}REQUEST{C['R']}")
    hr()
    pretty(payload)
    hr()

    if dry:
        print(f"{C['YEL']}--dry: запрос НЕ отправлен.{C['R']}")
        return

    if mode == "soap" and "REPLACE-ME" in target:
        print(f"{C['RED']}ENDPOINT не настроен.{C['R']} Открой config.env и впиши реальный URL шины.")
        sys.exit(1)

    if debug:
        ct = cfg("SOAP_CONTENT_TYPE","text/xml") if mode=="soap" else "application/json"
        print(f"{C['YEL']}DEBUG — эквивалентная curl-команда:{C['R']}")
        print(f"curl -sS -X POST '{target}' -H 'Content-Type: {ct}' --data-binary @<payload>")
        hr()

    content_type = cfg("SOAP_CONTENT_TYPE","text/xml") if mode=="soap" else "application/json"

    print(f"{C['B']}{C['MAG']}RESPONSE{C['R']}")
    hr()

    http_code, body, elapsed = send(target, payload, content_type, op, mode)

    pretty(body)
    hr()

    sc = C["GRN"] if str(http_code).startswith("2") else (C["RED"] if http_code==0 else C["YEL"])
    print(f"{C['B']}HTTP:{C['R']} {sc}{http_code}{C['R']}   {C['B']}время:{C['R']} {elapsed:.6f}s   {C['B']}eventId:{C['R']} {event_id}")
    if http_code == 0:
        print(f"{C['RED']}Соединение не удалось — проверь ENDPOINT/сеть/сертификат"
              f" (CURL_EXTRA=-k в config.env).{C['R']}")

    os.makedirs(RESPONSES, exist_ok=True)
    arch = os.path.join(RESPONSES, f"{event_id}.txt")
    with open(arch, "w", encoding="utf-8") as f:
        f.write(f"URL: {target}\nHTTP: {http_code}  time: {elapsed:.6f}s\n---\n{body}")
    print(f"{C['DIM']}Ответ сохранён: {arch}{C['R']}")


if __name__ == "__main__":
    main()
