import os, re, math, httpx, csv, logging
from fastapi import FastAPI, Request, Body
from fastapi.middleware.cors import CORSMiddleware
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Update, WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from supabase import create_client, Client
from datetime import datetime

# CONFIG
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
BOT_TOKEN = os.getenv("BOT_TOKEN")
SITE_URL = os.getenv("SITE_URL")
CSV_URL = os.getenv("GOOGLE_SHEETS_CSV_URL")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
app = FastAPI()

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# --- BOT HANDLERS ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    tg_id = message.from_user.id
    res = supabase.table("users").select("*").eq("tg_id", tg_id).execute()
    user = res.data[0] if res.data else None

    if not user:
        kb = [[KeyboardButton(text="📱 Kontaktni ulash", request_contact=True)]]
        markup = ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, one_time_keyboard=True)
        return await message.answer("<b>MirBeton tizimiga xush kelibsiz!</b>\nRo'yxatdan o'tish uchun telefon raqamingizni yuboring:", reply_markup=markup, parse_mode="HTML")

    if not user.get("secondary_phone"):
        kb = [[KeyboardButton(text="📱 Telegram raqam bilan bir xil")], [KeyboardButton(text="❌ Qo'shimcha raqam yo'q")]]
        markup = ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
        return await message.answer("Endi qo'shimcha bog'lanish raqamingizni yuboring yoki tanlang:", reply_markup=markup)

    # Main Menu
    role = user['role']
    app_url = f"{SITE_URL}/app.html?role={role}&user_id={user['id']}"
    
    kb = [[KeyboardButton(text="🏗 Tizimga kirish", web_app=WebAppInfo(url=app_url))]]
    if role in ['admin', 'sales']:
        kb.append([KeyboardButton(text="📊 Narxlar", web_app=WebAppInfo(url=f"{SITE_URL}/app.html?role=prices"))])
    
    await message.answer(f"Xush kelibsiz! Rolingiz: {role.upper()}", reply_markup=ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True))

@dp.message(F.contact)
async def handle_contact(message: types.Message):
    phone = "+" + message.contact.phone_number.replace("+", "")
    supabase.table("users").upsert({"tg_id": message.from_user.id, "full_name": message.from_user.full_name, "phone": phone, "role": "client"}).execute()
    await cmd_start(message)

@dp.message(Command("narxlar"))
async def show_prices(message: types.Message):
    async with httpx.AsyncClient() as client:
        r = await client.get(CSV_URL)
        data = list(csv.DictReader(r.text.splitlines()))
        text = "<b>Beton narxlari:</b>\n\n"
        for row in data:
            text += f"• {row['Marka']}: {row['Narx']} so'm\n"
        await message.answer(text, parse_mode="HTML")

# --- API ROUTES ---

@app.post("/api/webhook")
async def webhook(request: Request):
    body = await request.json()
    await dp.feed_update(bot=bot, update=Update(**body))
    return {"ok": True}

@app.post("/api/prod/pour")
async def prod_pour(data: dict = Body(...)):
    """Operator mikserga quyib bo'lgach"""
    trip_id = data['trip_id']
    driver_id = data['driver_id']
    
    # 1. Status yangilash
    supabase.table("order_trips").update({"status": "poured", "poured_at": datetime.now().isoformat(), "driver_id": driver_id}).eq("id", trip_id).execute()
    
    # 2. Haydovchiga xabar
    driver = supabase.table("users").select("tg_id").eq("id", driver_id).single().execute()
    await bot.send_message(driver.data['tg_id'], "✅ <b>Beton tayyor!</b>\nMikseringiz to'ldirildi. Yo'lga chiqishingiz mumkin.", parse_mode="HTML")
    return {"success": True}

@app.post("/api/driver/event")
async def driver_event(data: dict = Body(...)):
    trip_id = data['trip_id']
    event = data['event'] # 'en_route', 'arrived', 'completed'
    
    status_map = {"en_route": "en_route", "arrived": "arrived", "completed": "completed"}
    update_field = {"en_route": "departed_at", "arrived": "arrived_at", "completed": "completed_at"}[event]
    
    supabase.table("order_trips").update({
        "status": status_map[event],
        update_field: datetime.now().isoformat(),
        "last_lat": data.get('lat'),
        "last_lng": data.get('lng')
    }).eq("id", trip_id).execute()

    # Mijozga bildirishnoma
    trip = supabase.table("order_trips").select("*, orders(*)").eq("id", trip_id).single().execute()
    client = supabase.table("users").select("tg_id").eq("id", trip.data['orders']['client_id']).single().execute()
    
    msgs = {
        "en_route": "🚚 Buyurtmangiz yo'lga chiqdi! Mikser manzilga qarab kelmoqda.",
        "arrived": "📍 Mikser manzilga yetib keldi!",
        "completed": "✅ Buyurtma muvaffaqiyatli yakunlandi. Rahmat!"
    }
    await bot.send_message(client.data['tg_id'], msgs[event])
    return {"success": True}

# --- ADMIN API ENDPOINTS ---

@app.get("/api/admin/users")
async def admin_get_users(user_id: str):
    """Barcha foydalanuvchilarni olish (Faqat admin uchun)"""
    # Xavfsizlik: so'rov yuborgan foydalanuvchi admin ekanligini tekshirish
    check = supabase.table("users").select("role").eq("id", user_id).single().execute()
    if not check.data or check.data['role'] != 'admin':
        return {"error": "Ruxsat berilmagan"}
    
    res = supabase.table("users").select("*").order("created_at").execute()
    return res.data

@app.post("/api/admin/update-user")
async def admin_update_user(data: dict = Body(...)):
    """Foydalanuvchi ma'lumotlarini tahrirlash (Role, Phone, Active status)"""
    admin_id = data.get('admin_id')
    target_id = data.get('target_id')
    
    # Adminlikni tekshirish
    check = supabase.table("users").select("role").eq("id", admin_id).single().execute()
    if not check.data or check.data['role'] != 'admin':
        return {"error": "Ruxsat yo'q"}

    update_payload = {
        "role": data['role'],
        "full_name": data['full_name'],
        "phone": data['phone'],
        "secondary_phone": data.get('secondary_phone'),
        "is_active": data.get('is_active', True)
    }
    
    supabase.table("users").update(update_payload).eq("id", target_id).execute()
    return {"success": True}