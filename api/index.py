import os
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from aiogram import Bot, Dispatcher, types
from aiogram.types import Update, WebAppInfo, ReplyKeyboardMarkup, KeyboardButton
from supabase import create_client, Client

# 1. LOGLAR
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 2. KONFIGURATSIYA (Vercel Environment Variables dan olinadi)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
BOT_TOKEN = os.getenv("BOT_TOKEN")
# Saytingiz manzili (masalan: https://mirbeton-landing.vercel.app)
SITE_URL = os.getenv("SITE_URL", "https://mirbeton-landing.vercel.app")

# 3. INITIALIZATION
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

# --- TELEGRAM HANDLERS ---

@dp.message()
async def start_handler(message: types.Message):
    tg_id = message.from_user.id
    
    # Supabase'dan foydalanuvchini tekshirish
    try:
        user_res = supabase.table("users").select("*").eq("tg_id", tg_id).execute()
        user_data = user_res.data[0] if user_res.data else None

        # Foydalanuvchi yo'q bo'lsa, yangi mijoz ochamiz
        if not user_data:
            new_user = {
                "tg_id": tg_id,
                "full_name": message.from_user.full_name,
                "role": "client"
            }
            res = supabase.table("users").insert(new_user).execute()
            user_data = res.data[0]
            await message.answer("Siz tizimda mijoz sifatida ro'yxatdan o'tdingiz. 👤")

        role = user_data.get("role", "client")
        app_url = f"{SITE_URL}/app.html?role={role}&tg_id={tg_id}"

        # Rolga qarab tugmalar
        kb = []
        if role in ["admin", "sales"]:
            kb.append([KeyboardButton(text="📊 CRM Dashboard", web_app=WebAppInfo(url=app_url))])
        elif role == "prod_ops":
            kb.append([KeyboardButton(text="🏭 Ishlab chiqarish", web_app=WebAppInfo(url=app_url))])
        elif role == "driver":
            kb.append([KeyboardButton(text="🚚 Haydovchi paneli", web_app=WebAppInfo(url=app_url))])
        else: # client
            kb.append([KeyboardButton(text="📦 Buyurtmalarim", web_app=WebAppInfo(url=app_url))])

        markup = ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
        await message.answer(
            f"Xush kelibsiz, <b>{message.from_user.full_name}</b>!\nRo'yxatdan o'tgan rolingiz: <b>{role.upper()}</b>",
            reply_markup=markup,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Start error: {str(e)}")
        await message.answer("Xatolik yuz berdi. Iltimos keyinroq urinib ko'ring.")

# --- API ROUTES ---

@app.post("/api/webhook")
async def telegram_webhook(request: Request):
    body = await request.json()
    update = Update(**body)
    await dp.feed_update(bot=bot, update=update)
    return {"ok": True}

@app.get("/api/health")
def health():
    return {"status": "ok", "bot": "active" if BOT_TOKEN else "offline"}
