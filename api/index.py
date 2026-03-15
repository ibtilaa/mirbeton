import os
import re
import math
import logging
import httpx
import csv
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, Request, Body, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    Update, WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from supabase import create_client, Client
from datetime import datetime

# --- API ROUTES ---

# --- LOGGING ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
BOT_TOKEN = os.getenv("BOT_TOKEN")
SITE_URL = os.getenv("SITE_URL")
CSV_URL = os.getenv("GOOGLE_SHEETS_CSV_URL")

# --- INITIALIZATION ---
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- UTILS ---
MAX_MIXER_M3 = 10.0

async def get_user_by_tg_id(tg_id: int):
    res = supabase.table("users").select("*").eq("tg_id", tg_id).execute()
    return res.data[0] if res.data else None

# --- BOT HANDLERS ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    tg_id = message.from_user.id
    user = await get_user_by_tg_id(tg_id)

    # 1. Ro'yxatdan o'tmagan bo'lsa
    if not user:
        kb = [[KeyboardButton(text="📱 Kontaktni ulash", request_contact=True)]]
        markup = ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, one_time_keyboard=True)
        return await message.answer(
            "<b>MirBeton ERP tizimiga xush kelibsiz!</b>\n\nDavom etish uchun telefon raqamingizni yuboring:", 
            reply_markup=markup, parse_mode="HTML"
        )
    
    # 2. Ikkinchi raqam so'rash
    if not user.get("secondary_phone"):
        kb = [[KeyboardButton(text="📱 Telegram raqam bilan bir xil")], [KeyboardButton(text="❌ Qo'shimcha raqam yo'q")]]
        markup = ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, one_time_keyboard=True)
        return await message.answer(
            "<b>Ma'lumotlar saqlandi!</b>\nEndi qo'shimcha bog'lanish raqamingizni yuboring (masalan: 901234567) yoki tanlang:", 
            reply_markup=markup, parse_mode="HTML"
        )

    # 3. Asosiy Menyu (Role-based)
    role = user['role']
    app_url = f"{SITE_URL}/app.html?role={role}&user_id={user['id']}"
    
    btn_text = "📦 BUYURTMALARIM"
    if role == 'admin': btn_text = "⚙️ ADMIN PANEL"
    elif role == 'driver': btn_text = "🚚 HAYDOVCHI PANELI"
    elif role == 'sales': btn_text = "📊 SOTUV BO'LIMI"
    elif role == 'prod_ops': btn_text = "🏭 ISHLAB CHIQARISH"

    kb = [
        [KeyboardButton(text=btn_text, web_app=WebAppInfo(url=app_url))],
        [KeyboardButton(text="📊 NARXLAR", web_app=WebAppInfo(url=f"{SITE_URL}/app.html?role=prices"))]
    ]
    await message.answer(
        f"<b>Sizning rolingiz:</b> <code>{role.upper()}</code>\nQuyidagi tugma orqali tizimga kiring:", 
        reply_markup=ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True), 
        parse_mode="HTML"
    )

@dp.message(F.contact)
async def handle_contact(message: types.Message):
    phone = "+" + message.contact.phone_number.replace("+", "")
    supabase.table("users").upsert({
        "tg_id": message.from_user.id, 
        "full_name": message.from_user.full_name, 
        "phone": phone, 
        "role": "client"
    }).execute()
    await cmd_start(message)

@dp.message(lambda m: not m.text.startswith('/'))
async def handle_secondary_phone(message: types.Message):
    user = await get_user_by_tg_id(message.from_user.id)
    if user and not user.get("secondary_phone"):
        text = message.text.strip()
        final_phone = user['phone'] if "bir xil" in text.lower() else ("none" if "yo'q" in text.lower() else text)
        
        if final_phone != "none" and not "bir xil" in text.lower():
            clean = re.sub(r'\D', '', final_phone)
            if len(clean) == 9: final_phone = "+998" + clean
            elif len(clean) == 12: final_phone = "+" + clean
            else: return await message.answer("⚠️ Raqam noto'g'ri. Masalan: 901234567")

        supabase.table("users").update({"secondary_phone": final_phone}).eq("tg_id", message.from_user.id).execute()
        await message.answer("✅ Muvaffaqiyatli saqlandi!")
        await cmd_start(message)

# --- API ROUTES ---
@app.post("/api/orders/create")
async def create_order(request: Request):
    """Sotuv bo'limi yangi buyurtma kiritganda reyslarni avtomatik yaratadi"""
    data = await request.json()
    
    # 1. Asosiy buyurtmani yaratish
    order_res = supabase.table("orders").insert({
        "client_id": data['client_id'],
        "grade": data['grade'],
        "total_m3": data['total_m3'],
        "address": data['address']
    }).execute()
    
    order_id = order_res.data[0]['id']
    total_m3 = float(data['total_m3'])
    
    # 2. Multi-trip generator: Hajmni reyslarga bo'lish
    trips_count = math.ceil(total_m3 / MAX_MIXER_M3)
    remaining_m3 = total_m3
    
    for i in range(trips_count):
        trip_m3 = min(MAX_MIXER_M3, remaining_m3)
        supabase.table("order_trips").insert({
            "order_id": order_id,
            "m3": trip_m3,
            "status": "pending"
        }).execute()
        remaining_m3 -= trip_m3
        
    return {"success": True, "order_id": order_id}

@app.post("/api/driver/update-status")
async def update_trip_status(request: Request):
    """Haydovchi statusni o'zgartirganda (GPS va Overtime hisobi bilan)"""
    data = await request.json()
    trip_id = data['trip_id']
    new_status = data['status'] # 'jonadi', 'manzilda', 'quyish', 'done'
    
    update_data = {
        "status": new_status,
        "current_lat": data.get('lat'),
        "current_lng": data.get('lng')
    }
    
    now = datetime.now()
    if new_status == 'quyish':
        update_data["start_time"] = now.isoformat()
    elif new_status == 'done':
        update_data["end_time"] = now.isoformat()
        
        # Overtime hisoblash (Agar quyish 60 min dan oshsa)
        trip_res = supabase.table("order_trips").select("*").eq("id", trip_id).single().execute()
        if trip_res.data.get('start_time'):
            start = datetime.fromisoformat(trip_res.data['start_time'].replace('Z', '+00:00'))
            diff = (now.astimezone() - start.astimezone()).total_seconds() / 60
            if diff > 60:
                update_data["overtime_minutes"] = int(diff - 60)

    supabase.table("order_trips").update(update_data).eq("id", trip_id).execute()
    return {"success": True}

# Webhook handler
@app.post("/api/webhook")
async def webhook(request: Request):
    try:
        body = await request.json()
        update = Update(**body)
        await dp.feed_update(bot=bot, update=update)
        return {"ok": True}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {"ok": True}

# --- SALES & ORDERS ---

@app.post("/api/sales/create-order")
async def create_order(data: dict = Body(...)):
    # 1. ID Generatsiya: MB-2603-001
    now = datetime.now()
    date_code = now.strftime("%d%m")
    res_count = supabase.table("orders").select("id").ilike("id", f"MB-{date_code}-%").execute()
    order_id = f"MB-{date_code}-{str(len(res_count.data) + 1).zfill(3)}"

    total_amount = int(float(data['volume']) * int(data['price_per_m3']))
    
    # 2. Buyurtmani yaratish
    supabase.table("orders").insert({
        "id": order_id,
        "client_id": data['client_id'],
        "grade": data['grade'],
        "volume": data['volume'],
        "address": data['address'],
        "price_per_m3": data['price_per_m3'],
        "total_amount": total_amount,
        "status": "pending"
    }).execute()

    # 3. Multi-trip Split (10m3 dan bo'lish)
    total_vol = float(data['volume'])
    trips_count = math.ceil(total_vol / MAX_MIXER_M3)
    for i in range(trips_count):
        m3 = min(MAX_MIXER_M3, total_vol - (i * MAX_MIXER_M3))
        supabase.table("order_trips").insert({
            "order_id": order_id, "m3": m3, "status": "pending"
        }).execute()
        
    return {"success": True, "order_id": order_id}

@app.get("/api/sales/clients")
async def get_clients():
    res = supabase.table("users").select("id, full_name, phone").eq("role", "client").execute()
    return res.data

# --- PROD OPS ---

@app.post("/api/prod/pour")
async def prod_pour(data: dict = Body(...)):
    trip_id = data['trip_id']
    driver_id = data['driver_id']
    
    # Status: poured (quyildi)
    supabase.table("order_trips").update({
        "status": "poured", 
        "driver_id": driver_id, 
        "poured_at": datetime.now(timezone.utc).isoformat()
    }).eq("id", trip_id).execute()
    
    # Haydovchiga xabar
    driver = supabase.table("users").select("tg_id").eq("id", driver_id).single().execute()
    await bot.send_message(driver.data['tg_id'], f"✅ <b>Beton tayyor!</b>\nReys #{trip_id} yuklandi. Yo'lga chiqishingiz mumkin.", parse_mode="HTML")
    return {"success": True}

# --- DRIVER & GPS ---

@app.post("/api/driver/event")
async def driver_event(data: dict = Body(...)):
    trip_id = data['trip_id']
    event = data['event'] # 'en_route', 'arrived', 'pouring', 'completed'
    
    fields = {
        "en_route": "departed_at",
        "arrived": "arrived_at",
        "completed": "completed_at"
    }
    
    update_data = {
        "status": event,
        "last_lat": data.get('lat'),
        "last_lng": data.get('lng')
    }
    if event in fields:
        update_data[fields[event]] = datetime.now(timezone.utc).isoformat()

    # Log yozish
    supabase.table("order_logs").insert({
        "order_id": data.get('order_id'),
        "event_type": event,
        "location_lat": data.get('lat'),
        "location_lng": data.get('lng')
    }).execute()

    supabase.table("order_trips").update(update_data).eq("id", trip_id).execute()

    # Mijozga bildirishnoma
    trip_res = supabase.table("order_trips").select("*, orders(client_id)").eq("id", trip_id).single().execute()
    client = supabase.table("users").select("tg_id").eq("id", trip_res.data['orders']['client_id']).

@app.get("/api/sales/clients")
async def get_clients():
    """Mijozlar ro'yxatini olish (Select uchun)"""
    res = supabase.table("users").select("id, full_name, phone").eq("role", "client").execute()
    return res.data

@app.post("/api/sales/create-order")
async def create_sales_order(data: dict = Body(...)):
    """Sotuv bo'limi tomonidan buyurtma yaratish va reyslarni generatsiya qilish"""
    
    # 1. ID generatsiya (MB-DDMM-XXX)
    now = datetime.now()
    date_str = now.strftime("%d%m") # 2603
    
    # Bugungi buyurtmalar sonini aniqlash
    count_res = supabase.table("orders").select("id", count="exact").ilike("id", f"MB-{date_str}-%").execute()
    order_num = (count_res.count or 0) + 1
    custom_id = f"MB-{date_str}-{str(order_num).zfill(3)}"
    
    total_amount = int(data['volume']) * int(data['price_per_m3'])
    
    # 2. Buyurtmani saqlash
    order_payload = {
        "id": custom_id,
        "client_id": data['client_id'],
        "grade": data['grade'],
        "volume": data['volume'],
        "address": data['address'],
        "price_per_m3": data['price_per_m3'],
        "total_amount": total_amount,
        "status": "pending"
    }
    
    supabase.table("orders").insert(order_payload).execute()
    
    # 3. Multi-trip generator (10m3 dan bo'lib chiqish)
    total_vol = float(data['volume'])
    max_capacity = 10.0 # Bitta mikser sig'imi
    trips_count = math.ceil(total_vol / max_capacity)
    
    # Eslatma: 'order_trips' jadvali oldingi darsda kelishilganidek bo'lishi kerak
    for i in range(trips_count):
        trip_vol = min(max_capacity, total_vol - (i * max_capacity))
        supabase.table("order_trips").insert({
            "order_id": custom_id,
            "m3": trip_vol,
            "status": "pending"
        }).execute()
        
    return {"success": True, "order_id": custom_id}