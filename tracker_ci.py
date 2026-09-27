import json, os, sys, requests
from datetime import datetime
from pathlib import Path
import pytz

TW = pytz.timezone("Asia/Taipei")
STATE_FILE = Path("state.json")

def now_tw(): return datetime.now(TW)
def now_str(): return now_tw().strftime("%Y/%m/%d %H:%M:%S")
def parse_tw(s):
    return TW.localize(datetime.strptime(s, "%Y-%m-%d %H:%M"))

def load_state():
    return json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}

def save_state(s):
    STATE_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2))

def get_active_rule(cfg):
    now = now_tw()
    for rule in cfg.get("schedules", []):
        try:
            if parse_tw(rule["start"]) <= now <= parse_tw(rule["end"]):
                return rule
        except Exception:
            pass
    return None

def fetch_product(url):
    json_url = url.rstrip("/")
    if not json_url.endswith(".json"):
        json_url += ".json"
    try:
        r = requests.get(json_url, timeout=15, headers={"User-Agent": "KMonstar-CI/1.0"})
        r.raise_for_status()
        d = r.json()
        v = d.get("variants", [])
        return {
            "id": d.get("id"),
            "title": d.get("title", "（未知）"),
            "inventory_quantity": v[0].get("inventory_quantity", 0) if v else 0
        }
    except Exception as e:
        print(f"[錯誤] {e}"); return None

def get_name(cfg, p_cfg, fetched):
    pid = str(fetched.get("id", ""))
    if pid in cfg.get("id_name_map", {}): return cfg["id_name_map"][pid]
    if p_cfg.get("custom_name"): return p_cfg["custom_name"]
    return fetched.get("title", "（未知）")

def get_webhook_ids(webhook_url):
    parts = webhook_url.rstrip("/").split("/")
    return parts[-2], parts[-1]

def send_new_message(webhook_url, content):
    try:
        r = requests.post(
            webhook_url + "?wait=true",
            json={"content": content},
            timeout=10
        )
        r.raise_for_status()
        return r.json().get("id")
    except Exception as e:
        print(f"[DC新訊息錯誤] {e}")
        return None

def edit_message(webhook_url, message_id, content):
    wh_id, token = get_webhook_ids(webhook_url)
    url = f"https://discord.com/api/webhooks/{wh_id}/{token}/messages/{message_id}"
    try:
        r = requests.patch(url, json={"content": content}, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f"[DC編輯錯誤] {e}")

def build_content(name, lines):
    header = f"**活動：{name}**"
    body_lines = []
    for i, line in enumerate(lines):
        if i == 0:
            body_lines.append(f"時間：{line}")
        else:
            body_lines.append(f"　　　{line}")
    return header + "\n```\n" + "\n".join(body_lines) + "\n```"

def main():
    cfg     = json.loads(Path("config.json").read_text(encoding="utf-8"))
    state   = load_state()
    webhook = os.environ.get("DISCORD_WEBHOOK_URL") or cfg.get("discord_webhook_url", "")
    rule    = get_active_rule(cfg)

    print(f"[CI] {now_str()}")
    if not rule:
        print("[CI] 不在排程時段，結束"); sys.exit(0)

    for p_cfg in cfg.get("products", []):
        url = p_cfg.get("url", "").strip()
        if not url: continue
        f = fetch_product(url)
        if not f: continue

        pid      = str(f["id"])
        name     = get_name(cfg, p_cfg, f)
        inv_now  = f["inventory_quantity"]

        prev     = state.get(pid, {})
        inv_prev = prev.get("inv")

        if inv_prev is not None and inv_now == inv_prev:
            print(f"[{name}] 無變動（{inv_now}），略過")
            continue

        if inv_prev is not None:
            diff = inv_prev - inv_now
            sign = f"（+{diff}）" if diff > 0 else f"（{diff}）"
        else:
            sign = ""

        new_line = f"{now_str()} ｜ 庫存：{inv_now}{sign}"

        lines = prev.get("lines", [])
        lines.append(new_line)

        content = build_content(name, lines)

        if len(content) > 1900:
            lines = [new_line]
            content = build_content(name, lines)
            prev["msg_id"] = None

        msg_id = prev.get("msg_id")
        if msg_id and webhook:
            edit_message(webhook, msg_id, content)
            print(f"[{name}] 已更新訊息 {msg_id}")
        elif webhook:
            msg_id = send_new_message(webhook, content)
            print(f"[{name}] 已發新訊息 {msg_id}")
        else:
            print(content)

        state[pid] = {"inv": inv_now, "msg_id": msg_id, "lines": lines}

    save_state(state)

if __name__ == "__main__":
    main()
