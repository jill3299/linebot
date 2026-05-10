from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime, timedelta
import json
import re
import os
import requests
from apscheduler.schedulers.background import BackgroundScheduler
import pytz

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GOOGLE_CALENDAR_ID = os.environ.get("GOOGLE_CALENDAR_ID")
LINE_USER_ID = os.environ.get("LINE_USER_ID")
LINE_GROUP_ID = os.environ.get("LINE_GROUP_ID")
BOT_USER_ID = os.environ.get("BOT_USER_ID")  # Bot 自己的 User ID

credentials_json = os.environ.get("GOOGLE_CREDENTIALS")
credentials_dict = json.loads(credentials_json)
credentials = service_account.Credentials.from_service_account_info(
    credentials_dict,
    scopes=["https://www.googleapis.com/auth/calendar"]
)

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
calendar_service = build("calendar", "v3", credentials=credentials)

message_event_map = {}
TAIPEI_TZ = pytz.timezone("Asia/Taipei")
WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"]

# ==================
# Gemini 呼叫
# ==================
def ask_gemini(prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    response = requests.post(url, json=body)
    result = response.json()
    print("Gemini 回傳：", result)
    if "candidates" not in result:
        raise Exception(f"Gemini 錯誤：{result}")
    return result["candidates"][0]["content"]["parts"][0]["text"]

# ==================
# 取得行程
# ==================
def get_events(start_date, end_date):
    start_str = f"{start_date}T00:00:00+08:00"
    end_str = f"{end_date}T23:59:59+08:00"
    events_result = calendar_service.events().list(
        calendarId=GOOGLE_CALENDAR_ID,
        timeMin=start_str,
        timeMax=end_str,
        singleEvents=True,
        orderBy="startTime"
    ).execute()
    return events_result.get("items", [])

# ==================
# 格式化行程文字
# ==================
def fmt_date(date_str):
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return f"{d.month}/{d.day}({WEEKDAYS[d.weekday()]})"

def format_events(events, title):
    if not events:
        return f"📅 【{title}】\n\n（本期間沒有行程）\n──────────"

    lines = [f"📅 【{title}】", ""]

    for e in events:
        start = e.get("start", {})
        end = e.get("end", {})
        name = e.get("summary", "（無標題）")

        if "dateTime" in start:
            # 有時間的行程
            start_dt = datetime.fromisoformat(start["dateTime"]).astimezone(TAIPEI_TZ)
            end_dt = datetime.fromisoformat(end["dateTime"]).astimezone(TAIPEI_TZ)
            date_part = fmt_date(start_dt.strftime("%Y-%m-%d"))
            time_part = f"{start_dt.strftime('%H:%M')}-{end_dt.strftime('%H:%M')}"
            lines.append(f"{date_part} {time_part} {name}")
        else:
            # 全天或多天行程
            start_date = start["date"]
            # Google Calendar 的全天行程 end date 會多一天，要減回來
            end_date_raw = datetime.strptime(end["date"], "%Y-%m-%d") - timedelta(days=1)
            end_date = end_date_raw.strftime("%Y-%m-%d")

            if start_date == end_date:
                date_part = fmt_date(start_date)
            else:
                date_part = f"{fmt_date(start_date)}-{fmt_date(end_date)}"
            lines.append(f"{date_part} {name}")

    lines.append("──────────")
    return "\n".join(lines)

# ==================
# 主動推送訊息
# ==================
def push_message(text):
    targets = []
    if LINE_GROUP_ID:
        targets.append(LINE_GROUP_ID)
    elif LINE_USER_ID:
        targets.append(LINE_USER_ID)
    for target in targets:
        line_bot_api.push_message(target, TextSendMessage(text=text))

# ==================
# 定時任務
# ==================
def send_weekly_schedule():
    today = datetime.now(TAIPEI_TZ)
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    events = get_events(monday.strftime("%Y-%m-%d"), sunday.strftime("%Y-%m-%d"))
    title = f"本週行程 {monday.month}/{monday.day} - {sunday.month}/{sunday.day}"
    push_message(format_events(events, title))

def send_tomorrow_schedule():
    tomorrow = datetime.now(TAIPEI_TZ) + timedelta(days=1)
    tomorrow_str = tomorrow.strftime("%Y-%m-%d")
    events = get_events(tomorrow_str, tomorrow_str)
    title = f"明天的行程 {tomorrow.month}/{tomorrow.day}({WEEKDAYS[tomorrow.weekday()]})"
    push_message(format_events(events, title))

scheduler = BackgroundScheduler(timezone=TAIPEI_TZ)
scheduler.add_job(send_weekly_schedule, "cron", day_of_week="mon", hour=10, minute=0)
scheduler.add_job(send_tomorrow_schedule, "cron", hour=23, minute=0)
scheduler.start()

# ==================
# Webhook
# ==================
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text
    source_type = event.source.type
    print("來源類型：", source_type, "｜來源ID：", event.source.sender_id)

    # 群組裡只有被標注才處理
    if source_type == "group":
        bot_mention = f"@{os.environ.get('BOT_NAME', '行事曆小幫手')}"
        if bot_mention not in user_message:
            return
        user_message = user_message.replace(bot_mention, "").strip()

    # 查詢行程關鍵字
    query_today = ["今天的行程", "今天行程", "我今天要幹嘛", "今天要幹嘛"]
    query_week = ["這週的行程", "這週行程", "本週行程", "我這週要幹嘛", "這週要幹嘛"]

    if any(k in user_message for k in query_today):
        today = datetime.now(TAIPEI_TZ)
        today_str = today.strftime("%Y-%m-%d")
        events = get_events(today_str, today_str)
        title = f"今天的行程 {today.month}/{today.day}({WEEKDAYS[today.weekday()]})"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=format_events(events, title)))
        return

    if any(k in user_message for k in query_week):
        today = datetime.now(TAIPEI_TZ)
        monday = today - timedelta(days=today.weekday())
        sunday = monday + timedelta(days=6)
        events = get_events(monday.strftime("%Y-%m-%d"), sunday.strftime("%Y-%m-%d"))
        title = f"本週行程 {monday.month}/{monday.day} - {sunday.month}/{sunday.day}"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=format_events(events, title)))
        return

    # 回覆修改/刪除
    quoted_message_id = None
    if hasattr(event.message, 'quoted_message_id') and event.message.quoted_message_id:
        quoted_message_id = event.message.quoted_message_id

    if quoted_message_id and quoted_message_id in message_event_map:
        handle_edit_or_delete(event, user_message, message_event_map[quoted_message_id])
        return

    # 新增行程
    handle_new_event(event, user_message)

# ==================
# 新增行程
# ==================
def handle_new_event(event, user_message):
    prompt = f"""
    使用者說：「{user_message}」
    請從這句話中萃取行程資訊，用 JSON 格式回傳：
    {{
        "title": "行程名稱",
        "start_date": "YYYY-MM-DD",
        "end_date": "YYYY-MM-DD",
        "start_time": "HH:MM 或 null",
        "end_time": "HH:MM 或 null",
        "is_event": true 或 false
    }}
    規則：
    - 今天是 {datetime.now().strftime("%Y-%m-%d")}
    - 單天行程 start_date 和 end_date 填同一天
    - 多天行程填對應開始和結束日
    - 沒有指定時間填 null
    - 不像行程的話 is_event 填 false
    只回傳 JSON，不要其他文字。
    """

    result_text = ask_gemini(prompt)
    result_text = re.sub(r"```json|```", "", result_text).strip()
    data = json.loads(result_text)

    if not data.get("is_event"):
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="我只能幫你新增行程喔！例如：「明天下午三點開會」")
        )
        return

    if data.get("start_time") and data.get("end_time"):
        event_body = {
            "summary": data["title"],
            "start": {"dateTime": f"{data['start_date']}T{data['start_time']}:00", "timeZone": "Asia/Taipei"},
            "end": {"dateTime": f"{data['end_date']}T{data['end_time']}:00", "timeZone": "Asia/Taipei"}
        }
        reply_text = f"✅ 已新增行程！\n📌 {data['title']}\n📅 {data['start_date']}\n⏰ {data['start_time']} - {data['end_time']}\n\n💡 回覆此訊息可修改或刪除"
    else:
        end = datetime.strptime(data["end_date"], "%Y-%m-%d") + timedelta(days=1)
        event_body = {
            "summary": data["title"],
            "start": {"date": data["start_date"]},
            "end": {"date": end.strftime("%Y-%m-%d")}
        }
        if data["start_date"] == data["end_date"]:
            reply_text = f"✅ 已新增行程！\n📌 {data['title']}\n📅 {data['start_date']}\n\n💡 回覆此訊息可修改或刪除"
        else:
            reply_text = f"✅ 已新增行程！\n📌 {data['title']}\n📅 {data['start_date']} ~ {data['end_date']}\n\n💡 回覆此訊息可修改或刪除"

    created = calendar_service.events().insert(
        calendarId=GOOGLE_CALENDAR_ID,
        body=event_body
    ).execute()

    event_key = f"{data['title']}_{data['start_date']}"
    message_event_map[event_key] = created["id"]

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

# ==================
# 修改或刪除
# ==================
def handle_edit_or_delete(event, user_message, event_id):
    prompt = f"""
    使用者說：「{user_message}」
    針對已存在的行程，判斷要刪除還是修改，用 JSON 回傳：
    {{
        "action": "delete" 或 "update",
        "title": "新名稱或 null",
        "start_date": "YYYY-MM-DD 或 null",
        "end_date": "YYYY-MM-DD 或 null",
        "start_time": "HH:MM 或 null",
        "end_time": "HH:MM 或 null"
    }}
    今天是 {datetime.now().strftime("%Y-%m-%d")}。
    只回傳 JSON。
    """

    result_text = ask_gemini(prompt)
    result_text = re.sub(r"```json|```", "", result_text).strip()
    data = json.loads(result_text)

    if data["action"] == "delete":
        calendar_service.events().delete(calendarId=GOOGLE_CALENDAR_ID, eventId=event_id).execute()
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="🗑️ 行程已刪除！"))
    elif data["action"] == "update":
        existing = calendar_service.events().get(calendarId=GOOGLE_CALENDAR_ID, eventId=event_id).execute()
        if data.get("title"):
            existing["summary"] = data["title"]
        if data.get("start_date") and data.get("start_time") and data.get("end_time"):
            existing["start"] = {"dateTime": f"{data['start_date']}T{data['start_time']}:00", "timeZone": "Asia/Taipei"}
            existing["end"] = {"dateTime": f"{data['end_date'] or data['start_date']}T{data['end_time']}:00", "timeZone": "Asia/Taipei"}
        elif data.get("start_date"):
            end = datetime.strptime(data.get("end_date") or data["start_date"], "%Y-%m-%d") + timedelta(days=1)
            existing["start"] = {"date": data["start_date"]}
            existing["end"] = {"date": end.strftime("%Y-%m-%d")}
        calendar_service.events().update(calendarId=GOOGLE_CALENDAR_ID, eventId=event_id, body=existing).execute()
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="✏️ 行程已更新！"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
