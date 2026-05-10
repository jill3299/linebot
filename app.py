from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import google.generativeai as genai
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime
import json
import re
import os

app = Flask(__name__)

# 從環境變數讀取金鑰
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GOOGLE_CALENDAR_ID = os.environ.get("GOOGLE_CALENDAR_ID")

# 從環境變數讀取 Google 憑證
credentials_json = os.environ.get("GOOGLE_CREDENTIALS")
credentials_dict = json.loads(credentials_json)
credentials = service_account.Credentials.from_service_account_info(
    credentials_dict,
    scopes=["https://www.googleapis.com/auth/calendar"]
)

# 初始化各服務
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")
calendar_service = build("calendar", "v3", credentials=credentials)

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

    prompt = f"""
    使用者說：「{user_message}」
    請從這句話中萃取行程資訊，用 JSON 格式回傳，格式如下：
    {{
        "title": "行程名稱",
        "date": "YYYY-MM-DD",
        "start_time": "HH:MM",
        "end_time": "HH:MM",
        "is_event": true 或 false
    }}
    今天是 {datetime.now().strftime("%Y-%m-%d")}。
    如果這句話不像在新增行程，is_event 填 false。
    只回傳 JSON，不要其他文字。
    """

    response = model.generate_content(prompt)
    result_text = response.text.strip()
    result_text = re.sub(r"```json|```", "", result_text).strip()
    data = json.loads(result_text)

    if not data.get("is_event"):
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="我只能幫你新增行程喔！例如：「明天下午三點開會」")
        )
        return

    event_body = {
        "summary": data["title"],
        "start": {
            "dateTime": f"{data['date']}T{data['start_time']}:00",
            "timeZone": "Asia/Taipei"
        },
        "end": {
            "dateTime": f"{data['date']}T{data['end_time']}:00",
            "timeZone": "Asia/Taipei"
        }
    }

    calendar_service.events().insert(
        calendarId=GOOGLE_CALENDAR_ID,
        body=event_body
    ).execute()

    reply = f"✅ 已新增行程！\n📌 {data['title']}\n📅 {data['date']}\n⏰ {data['start_time']} - {data['end_time']}"
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply)
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
