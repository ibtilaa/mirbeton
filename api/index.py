import os, re, logging, httpx, csv
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import Update, WebAppInfo, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from supabase import create_client, Client
from datetime import datetime
from dateutil import parser

# LOGS & CONFIG
logging.basicConfig(level=logging.INFO)
SUPABASE_URL, SUPABASE_KEY = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY")
BOT_TOKEN, SITE_URL = os.getenv("BOT_TOKEN"), os.getenv("SITE_URL")
CSV_URL = os.getenv("GOOGLE_SHEETS_CSV_URL")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
app = FastAPI()

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# --- BOT HANDLERS ---
@dp.message(F.text == "/start")
async def cmd_start(message: types.Message):
    tg_id = message.from_user.id
    res = supabase.table("users").select("*").eq("tg_id", tg_id).execute()
    user = res.data[0] if res.data else None

    if not user:
        kb = [[KeyboardButton(text="📱 Kontaktni ulash", request_contact=True)]]
        await message.answer("<b>MirBeton tizimiga xush kelibsiz!</b>\nRo'yxatdan o'tish uchun telefon raqamingizni yuboring:", 
                             reply_markup=ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, one_time_keyboard=True), parse_mode="HTML")
    elif not user.get("secondary_phone"):
        kb = [[KeyboardButton(text="📱 Telegram raqam bilan bir xil")], [KeyboardButton(text="❌ Qo'shimcha raqam yo'q")]]
        await message.answer("Rahmat! Endi doimiy aloqa uchun ikkinchi raqamingizni yozing yoki tanlang:", 
                             reply_markup=ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True), parse_mode="HTML")
    else:
        role = user['role']
        app_url = f"{SITE_URL}/app.html?role={role}&user_id={user['id']}"
        kb = [[KeyboardButton(text="🚀 Tizimni ochish", web_app=WebAppInfo(url=app_url))]]
        kb.append([KeyboardButton(text="📊 Narxlar", web_app=WebAppInfo(url=f"{SITE_URL}/app.html?role=prices"))])
        await message.answer(f"Siz tizimga <b>{role.upper()}</b> sifatida kirdingiz.", 
                             reply_markup=ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True), parse_mode="HTML")

@dp.message(F.contact)
async def handle_contact(message: types.Message):
    phone = message.contact.phone_number
    if not phone.startswith('+'): phone = '+' + phone
    supabase.table("users").upsert({"tg_id": message.from_user.id, "full_name": message.from_user.full_name, "phone": phone, "role": "client"}).execute()
    await cmd_start(message)

@dp.message(lambda m: not m.text.startswith('/'))
async def handle_text_inputs(message: types.Message):
    tg_id = message.from_user.id
    text = message.text.strip()
    user = supabase.table("users").select("*").eq("tg_id", tg_id).single().execute().data
    
    if user and not user.get("secondary_phone"):
        final_phone = ""
        if "bir xil" in text: final_phone = user['phone']
        elif "yo'q" in text: final_phone = "none"
        else:
            clean = re.sub(r'\D', '', text)
            if len(clean) == 9: final_phone = "+998" + clean
            elif len(clean) == 12 and clean.startswith("998"): final_phone = "+" + clean
            else:
                return await message.answer("⚠️ Raqam noto'g'ri. 9 ta raqam ko'rinishida yozing (Masalan: 901234567):")
        
        supabase.table("users").update({"secondary_phone": final_phone}).eq("tg_id", tg_id).execute()
        await message.answer("✅ Muvaffaqiyatli saqlandi!")
        await cmd_start(message)

# --- API ROUTES ---
@app.post("/api/webhook")
async def webhook(request: Request):
    body = await request.json()
    await dp.feed_update(bot=bot, update=Update(**body))
    return {"ok": True}

@app.get("/api/prices")
async def prices():
    async with httpx.AsyncClient() as client:
        r = await client.get(CSV_URL)
        return list(csv.DictReader(r.text.splitlines()))

@app.post("/api/admin/update-role")
async def update_role(request: Request):
    data = await request.json()
    admin_id, target_uid, new_role = data.get("admin_id"), data.get("target_uid"), data.get("new_role")
    # Xavfsizlik: Faqat admin qila olishini tekshirish
    check = supabase.table("users").select("role").eq("id", admin_id).single().execute()
    if check.data['role'] != 'admin': raise HTTPException(status_code=403, detail="Ruxsat yo'q")
    
    supabase.table("users").update({"role": new_role}).eq("id", target_uid).execute()
    return {"success": True}

@app.get("/api/admin/dashboard")
async def admin_db(user_id: str):
    check = supabase.table("users").select("role").eq("id", user_id).single().execute()
    if check.data['role'] != 'admin': return {"error": "Unauthorized"}
    users = supabase.table("users").select("*").execute().data
    orders = supabase.table("orders").select("*, client_id(full_name)").execute().data
    return {"users": users, "orders": orders}

@app.post("/api/driver-event")
async def dr_event(request: Request):
    d = await request.json()
    supabase.table("order_logs").insert({"order_id": d['order_id'], "event_type": d['step'], "location_lat": d.get('lat'), "location_lng": d.get('lng')}).execute()
    return {"ok": True}