import os
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from aiogram import Bot, Dispatcher, types
from aiogram.types import Update, WebAppInfo, ReplyKeyboardMarkup, KeyboardButton
from supabase import create_client, Client
from datetime import datetime
from dateutil import parser

# LOGLAR
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ENV
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
BOT_TOKEN = os.getenv("BOT_TOKEN")
SITE_URL = os.getenv("SITE_URL")

# INIT
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
app = FastAPI()

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# --- BOT MANTIQI ---
@dp.message()
async def start_handler(message: types.Message):
    tg_id = message.from_user.id
    user_res = supabase.table("users").select("*").eq("tg_id", tg_id).execute()
    user_data = user_res.data[0] if user_res.data else None

    if not user_data:
        user_res = supabase.table("users").insert({"tg_id": tg_id, "full_name": message.from_user.full_name, "role": "client"}).execute()
        user_data = user_res.data[0]

    role = user_data.get("role", "client")
    app_url = f"{SITE_URL}/app.html?role={role}&tg_id={tg_id}&user_id={user_data['id']}"

    kb = []
    btn_text = "📦 Buyurtmalarim"
    if role in ["admin", "sales"]: btn_text = "📊 CRM Dashboard"
    elif role == "prod_ops": btn_text = "🏭 Ishlab chiqarish"
    elif role == "driver": btn_text = "🚚 Haydovchi paneli"

    kb.append([KeyboardButton(text=btn_text, web_app=WebAppInfo(url=app_url))])
    await message.answer(f"MirBeton tizimiga xush kelibsiz!\nRolingiz: <b>{role.upper()}</b>", 
                         reply_markup=ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True), parse_mode="HTML")

# --- API: STATUS VA INVOYS ---
@app.post("/api/driver-event")
async def driver_event(request: Request):
    data = await request.json()
    order_id, step, user_id = data.get("order_id"), data.get("step"), data.get("user_id")

    # 1. Log yozish
    supabase.table("order_logs").insert({"order_id": order_id, "event_type": step}).execute()

    # 2. Status yangilash
    status_map = {"en_route": "en_route", "arrived": "arrived", "pouring": "pouring", "done": "completed"}
    if step in status_map:
        supabase.table("orders").update({"status": status_map[step]}).eq("id", order_id).execute()

    # 3. Mijozni topish va xabardor qilish
    order_res = supabase.table("orders").select("*, client_id(tg_id)").eq("id", order_id).single().execute()
    client_tg_id = order_res.data['client_id']['tg_id']
    
    msg_map = {
        "en_route": "🚚 <b>Mikser yo'lga chiqdi!</b>\nTaxminan 20-30 daqiqada yetib boradi.",
        "arrived": "📍 <b>Mikser manzilga yetib keldi.</b>",
        "pouring": "🏗 <b>Beton quyish boshlandi.</b>",
        "done": "🏁 <b>Buyurtma yakunlandi!</b> Invoys hozir yuboriladi."
    }
    if step in msg_map:
        await bot.send_message(client_tg_id, msg_map[step], parse_mode="HTML")

    # 4. Invoys hisoblash (Agar yakunlangan bo'lsa)
    if step == "done":
        await send_final_invoice(order_id, client_tg_id, order_res.data)

    return {"success": True}

async def send_final_invoice(order_id, tg_id, order_data):
    # Loglardan vaqtni olish
    logs = supabase.table("order_logs").select("*").eq("order_id", order_id).execute()
    start_time = next((l['event_time'] for l in logs.data if l['event_type'] == 'pouring'), None)
    end_time = next((l['event_time'] for l in logs.data if l['event_type'] == 'done'), None)
    
    overtime_msg = ""
    total = int(order_data['total_amount'] or 0)

    if start_time and end_time:
        duration = (parser.parse(end_time) - parser.parse(start_time)).total_seconds() / 60
        if duration > 60: # 60 min bepul
            overtime_min = int(duration - 60)
            overtime_sum = (overtime_min // 30 + 1) * 100000 # Har 30 min uchun 100k
            total += overtime_sum
            overtime_msg = f"⚠️ Ortiqcha vaqt: {overtime_min} min (+{overtime_sum:,} so'm)\n"

    invoice = (
        f"🧾 <b>YAKUNIY INVOYS #{order_id}</b>\n\n"
        f"🧱 Marka: {order_data['grade']}\n"
        f"📐 Hajm: {order_data['volume']} m³\n"
        f"{overtime_msg}"
        f"💰 <b>JAMI TO'LOV: {total:,} so'm</b>\n\n"
        f"Rahmat! Yana kutib qolamiz. 🏗"
    )
    await bot.send_message(tg_id, invoice, parse_mode="HTML")

@app.post("/api/webhook")
async def webhook(request: Request):
    body = await request.json()
    await dp.feed_update(bot=bot, update=Update(**body))
    return {"ok": True}
