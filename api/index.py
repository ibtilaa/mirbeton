import os, re, logging, httpx, csv
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import Update, WebAppInfo, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from supabase import create_client, Client
from datetime import datetime

# LOGGING
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# CONFIG
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
BOT_TOKEN = os.getenv("BOT_TOKEN")
SITE_URL = os.getenv("SITE_URL")
CSV_URL = os.getenv("GOOGLE_SHEETS_CSV_URL")

# INIT
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
app = FastAPI()

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# --- BOT MANTIQI ---

@dp.message(F.text == "/start")
async def cmd_start(message: types.Message):
    tg_id = message.from_user.id
    # Xavfsiz qidiruv: .single() o'rniga .execute() ishlatamiz
    res = supabase.table("users").select("*").eq("tg_id", tg_id).execute()
    user = res.data[0] if res.data else None

    # 1. Ro'yxatdan o'tmagan bo'lsa
    if not user:
        kb = [[KeyboardButton(text="📱 Kontaktni ulash", request_contact=True)]]
        markup = ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, one_time_keyboard=True)
        return await message.answer(
            "<b>MirBeton tizimiga xush kelibsiz!</b>\n\nDavom etish uchun telefon raqamingizni yuboring:", 
            reply_markup=markup, parse_mode="HTML"
        )
    
    # 2. Kontakt bor, lekin 2-raqam yo'q bo'lsa
    if not user.get("secondary_phone"):
        kb = [
            [KeyboardButton(text="📱 Telegram raqam bilan bir xil")],
            [KeyboardButton(text="❌ Qo'shimcha raqam yo'q")]
        ]
        markup = ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True, one_time_keyboard=True)
        return await message.answer(
            "<b>Ma'lumotlar saqlandi!</b>\nEndi doimiy aloqa uchun ikkinchi raqamingizni yozing (masalan: 901234567) yoki tanlang:", 
            reply_markup=markup, parse_mode="HTML"
        )

    # 3. Hamma ma'lumotlar joyida bo'lsa - ASOSIY MENYU
    role = user['role']
    app_url = f"{SITE_URL}/app.html?role={role}&user_id={user['id']}"
    
    btn_text = "📦 Buyurtmalarim"
    if role == 'admin': btn_text = "⚙️ Admin Panel"
    elif role == 'driver': btn_text = "🚚 Haydovchi Paneli"
    elif role == 'sales': btn_text = "📊 Sotuv Bo'limi"

    kb = [
        [KeyboardButton(text=btn_text, web_app=WebAppInfo(url=app_url))],
        [KeyboardButton(text="📊 Narxlar", web_app=WebAppInfo(url=f"{SITE_URL}/app.html?role=prices"))]
    ]
    await message.answer(
        f"<b>Asosiy Menyu</b>\n\nSizning rolingiz: <code>{role.upper()}</code>", 
        reply_markup=ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True), 
        parse_mode="HTML"
    )

@dp.message(F.contact)
async def handle_contact(message: types.Message):
    phone = message.contact.phone_number
    if not phone.startswith('+'): phone = '+' + phone
    supabase.table("users").upsert({
        "tg_id": message.from_user.id, 
        "full_name": message.from_user.full_name, 
        "phone": phone, 
        "role": "client"
    }).execute()
    await cmd_start(message)

@dp.message(lambda m: not m.text.startswith('/'))
async def handle_text_inputs(message: types.Message):
    tg_id = message.from_user.id
    text = message.text.strip()
    
    res = supabase.table("users").select("*").eq("tg_id", tg_id).execute()
    user = res.data[0] if res.data else None
    
    if user and not user.get("secondary_phone"):
        final_phone = ""
        if "bir xil" in text.lower():
            final_phone = user['phone']
        elif "yo'q" in text.lower():
            final_phone = "none"
        else:
            # Raqamlarni tozalash va formatlash
            clean = re.sub(r'\D', '', text)
            if len(clean) == 9: final_phone = "+998" + clean
            elif len(clean) == 12 and clean.startswith("998"): final_phone = "+" + clean
            else:
                return await message.answer("⚠️ <b>Xato!</b> Iltimos, raqamni 901234567 ko'rinishida yozing:")
        
        supabase.table("users").update({"secondary_phone": final_phone}).eq("tg_id", tg_id).execute()
        await message.answer("✅ <b>Muvaffaqiyatli saqlandi!</b>")
        return await cmd_start(message) # Menyuni chiqarish uchun qaytamiz

    await cmd_start(message)

# --- API ROUTES ---

@app.post("/api/webhook")
async def webhook(request: Request):
    try:
        body = await request.json()
        update = Update(**body)
        await dp.feed_update(bot=bot, update=update)
        return {"ok": True}
    except Exception as e:
        logger.error(f"Error: {e}")
        return {"ok": True} # Telegram qayta yubormasligi uchun True qaytaramiz

@app.get("/api/prices")
async def get_prices():
    async with httpx.AsyncClient() as client:
        r = await client.get(CSV_URL)
        return list(csv.DictReader(r.text.splitlines()))

@app.post("/api/admin/set-role")
async def set_role(request: Request):
    d = await request.json()
    # Faqat adminligini tekshirish
    check = supabase.table("users").select("role").eq("id", d['admin_id']).single().execute()
    if check.data['role'] != 'admin': return {"error": "No access"}
    
    supabase.table("users").update({"role": d['role']}).eq("id", d['target_id']).execute()
    return {"ok": True}

@app.get("/api/admin/data")
async def admin_data(user_id: str):
    res = supabase.table("users").select("role").eq("id", user_id).single().execute()
    if res.data['role'] != 'admin': return {"error": "No access"}
    
    users = supabase.table("users").select("*").execute()
    orders = supabase.table("orders").select("*, client_id(full_name)").execute()
    return {"users": users.data, "orders": orders.data}
    