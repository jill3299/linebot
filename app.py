def handle_new_event(event, user_message):
    prompt = f"""
    使用者說：「{user_message}」
    請從這句話中萃取所有行程資訊，用 JSON 陣列格式回傳：
    [
        {{
            "title": "行程名稱",
            "start_date": "YYYY-MM-DD",
            "end_date": "YYYY-MM-DD",
            "start_time": "HH:MM 或 null",
            "end_time": "HH:MM 或 null",
            "is_event": true 或 false
        }}
    ]
    規則：
    - 今天是 {datetime.now().strftime("%Y-%m-%d")}
    - 單天行程 start_date 和 end_date 填同一天
    - 多天行程填對應開始和結束日
    - 沒有指定時間填 null
    - 不像行程的話 is_event 填 false
    - 就算只有一個行程也要回傳陣列格式
    只回傳 JSON 陣列，不要其他文字。
    """

    result_text = ask_gemini(prompt)
    result_text = re.sub(r"```json|```", "", result_text).strip()
    data_list = json.loads(result_text)

    # 確保是陣列格式
    if isinstance(data_list, dict):
        data_list = [data_list]

    reply_lines = []
    has_event = False

    for data in data_list:
        if not data.get("is_event"):
            continue

        has_event = True

        if data.get("start_time") and data.get("end_time"):
            event_body = {
                "summary": data["title"],
                "start": {"dateTime": f"{data['start_date']}T{data['start_time']}:00", "timeZone": "Asia/Taipei"},
                "end": {"dateTime": f"{data['end_date']}T{data['end_time']}:00", "timeZone": "Asia/Taipei"}
            }
            reply_lines.append(f"📌 {data['title']}｜{data['start_date']} {data['start_time']}-{data['end_time']}")
        else:
            end = datetime.strptime(data["end_date"], "%Y-%m-%d") + timedelta(days=1)
            event_body = {
                "summary": data["title"],
                "start": {"date": data["start_date"]},
                "end": {"date": end.strftime("%Y-%m-%d")}
            }
            if data["start_date"] == data["end_date"]:
                reply_lines.append(f"📌 {data['title']}｜{data['start_date']}")
            else:
                reply_lines.append(f"📌 {data['title']} ｜{data['start_date']} ~ {data['end_date']}")

        created = calendar_service.events().insert(
            calendarId=GOOGLE_CALENDAR_ID,
            body=event_body
        ).execute()

        fallback_key = f"{data['title']}_{data['start_date']}"
        message_event_map[fallback_key] = created["id"]

    if not has_event:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="我只能幫你新增行程喔！例如：「明天下午三點開會」")
        )
        return

    reply_text = f"✅ 已新增 {len(reply_lines)} 個行程！\n\n" + "\n".join(reply_lines)
    reply_text += "\n\n💡 回覆此訊息可修改或刪除單一行程"
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
