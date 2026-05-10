{\rtf1\ansi\ansicpg950\cocoartf2822
\cocoatextscaling0\cocoaplatform0{\fonttbl\f0\froman\fcharset0 Times-Roman;}
{\colortbl;\red255\green255\blue255;\red0\green0\blue0;}
{\*\expandedcolortbl;;\cssrgb\c0\c0\c0;}
\paperw11900\paperh16840\margl1440\margr1440\vieww11520\viewh8400\viewkind0
\deftab720
\pard\pardeftab720\partightenfactor0

\f0\fs24 \cf0 \expnd0\expndtw0\kerning0
\outl0\strokewidth0 \strokec2 from flask import Flask, request, abort\
from linebot import LineBotApi, WebhookHandler\
from linebot.exceptions import InvalidSignatureError\
from linebot.models import MessageEvent, TextMessage, TextSendMessage\
import google.generativeai as genai\
from google.oauth2 import service_account\
from googleapiclient.discovery import build\
from datetime import datetime\
import json\
import re\
import os\
\
app = Flask(__name__)\
\
# ==============================\
# \uc0\u25226 \u20320 \u30340 \u37329 \u38000 \u22635 \u22312 \u36889 \u35041 \
# ==============================\
LINE_CHANNEL_ACCESS_TOKEN = "\uc0\u22635 \u20837 \u20320 \u30340  LINE Channel Access Token"\
LINE_CHANNEL_SECRET = "\uc0\u22635 \u20837 \u20320 \u30340  LINE Channel Secret"\
GEMINI_API_KEY = "\uc0\u22635 \u20837 \u20320 \u30340  Gemini API Key"\
GOOGLE_CALENDAR_ID = "\uc0\u22635 \u20837 \u20320 \u30340  Google \u26085 \u26310  ID\u65288 \u36890 \u24120 \u26159 \u20320 \u30340  Gmail \u20449 \u31665 \u65289 "\
SERVICE_ACCOUNT_FILE = "credentials.json"  # \uc0\u20320 \u19979 \u36617 \u30340  JSON \u27284 \u26696 \u21517 \u31281 \
# ==============================\
\
# \uc0\u21021 \u22987 \u21270  LINE\
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)\
handler = WebhookHandler(LINE_CHANNEL_SECRET)\
\
# \uc0\u21021 \u22987 \u21270  Gemini\
genai.configure(api_key=GEMINI_API_KEY)\
model = genai.GenerativeModel("gemini-pro")\
\
# \uc0\u21021 \u22987 \u21270  Google Calendar\
SCOPES = ["https://www.googleapis.com/auth/calendar"]\
credentials = service_account.Credentials.from_service_account_file(\
    SERVICE_ACCOUNT_FILE, scopes=SCOPES\
)\
calendar_service = build("calendar", "v3", credentials=credentials)\
\
@app.route("/callback", methods=["POST"])\
def callback():\
    signature = request.headers["X-Line-Signature"]\
    body = request.get_data(as_text=True)\
    try:\
        handler.handle(body, signature)\
    except InvalidSignatureError:\
        abort(400)\
    return "OK"\
\
@handler.add(MessageEvent, message=TextMessage)\
def handle_message(event):\
    user_message = event.message.text\
\
    # \uc0\u35531  Gemini \u35299 \u26512 \u34892 \u31243 \u36039 \u35338 \
    prompt = f"""\
    \uc0\u20351 \u29992 \u32773 \u35498 \u65306 \u12300 \{user_message\}\u12301 \
    \uc0\u35531 \u24478 \u36889 \u21477 \u35441 \u20013 \u33795 \u21462 \u34892 \u31243 \u36039 \u35338 \u65292 \u29992  JSON \u26684 \u24335 \u22238 \u20659 \u65292 \u26684 \u24335 \u22914 \u19979 \u65306 \
    \{\{\
        "title": "\uc0\u34892 \u31243 \u21517 \u31281 ",\
        "date": "YYYY-MM-DD",\
        "start_time": "HH:MM",\
        "end_time": "HH:MM",\
        "is_event": true \uc0\u25110  false\
    \}\}\
    \uc0\u20170 \u22825 \u26159  \{datetime.now().strftime("%Y-%m-%d")\}\u12290 \
    \uc0\u22914 \u26524 \u36889 \u21477 \u35441 \u19981 \u20687 \u22312 \u26032 \u22686 \u34892 \u31243 \u65292 is_event \u22635  false\u12290 \
    \uc0\u21482 \u22238 \u20659  JSON\u65292 \u19981 \u35201 \u20854 \u20182 \u25991 \u23383 \u12290 \
    """\
\
    response = model.generate_content(prompt)\
    result_text = response.text.strip()\
\
    # \uc0\u28165 \u38500  Gemini \u21487 \u33021 \u22810 \u21152 \u30340 \u31526 \u34399 \
    result_text = re.sub(r"```json|```", "", result_text).strip()\
\
    data = json.loads(result_text)\
\
    # \uc0\u22914 \u26524 \u19981 \u26159 \u34892 \u31243 \u65292 \u22238 \u35206 \u25552 \u31034 \
    if not data.get("is_event"):\
        line_bot_api.reply_message(\
            event.reply_token,\
            TextSendMessage(text="\uc0\u25105 \u21482 \u33021 \u24171 \u20320 \u26032 \u22686 \u34892 \u31243 \u21908 \u65281 \u20363 \u22914 \u65306 \u12300 \u26126 \u22825 \u19979 \u21320 \u19977 \u40670 \u38283 \u26371 \u12301 ")\
        )\
        return\
\
    # \uc0\u26032 \u22686 \u21040  Google \u26085 \u26310 \
    event_body = \{\
        "summary": data["title"],\
        "start": \{\
            "dateTime": f"\{data['date']\}T\{data['start_time']\}:00",\
            "timeZone": "Asia/Taipei"\
        \},\
        "end": \{\
            "dateTime": f"\{data['date']\}T\{data['end_time']\}:00",\
            "timeZone": "Asia/Taipei"\
        \}\
    \}\
\
    calendar_service.events().insert(\
        calendarId=GOOGLE_CALENDAR_ID,\
        body=event_body\
    ).execute()\
\
    # \uc0\u22238 \u35206 \u20351 \u29992 \u32773 \
    reply = f"\uc0\u9989  \u24050 \u26032 \u22686 \u34892 \u31243 \u65281 \\n\u55357 \u56524  \{data['title']\}\\n\u55357 \u56517  \{data['date']\}\\n\u9200  \{data['start_time']\} - \{data['end_time']\}"\
    line_bot_api.reply_message(\
        event.reply_token,\
        TextSendMessage(text=reply)\
    )\
\
if __name__ == "__main__":\
    port = int(os.environ.get("PORT", 5000))\
    app.run(host="0.0.0.0", port=port)}