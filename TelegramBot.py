import asyncio
import logging
import json
import re
import os
from datetime import datetime
import aiosqlite

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, WebAppInfo,
    InlineKeyboardMarkup, InlineKeyboardButton
)


TG_TOKEN = os.getenv("TG_TOKEN")
DB_NAME = "snake_game.db"
WEBAPP_URL = "https://snake-mini-app-zjrw.vercel.app/" 

bot = Bot(token=TG_TOKEN)
dp = Dispatcher()

SKINS_CONFIG = {
    "classic": {"name": "🟢 Classic", "req": 0},
    "fire":    {"name": "🔥 Fire",    "req": 10},
    "neon":    {"name": "⚡ Neon",    "req": 20},
    "gold":    {"name": "👑 Gold",    "req": 50},
    "diamond": {"name": "💎 Diamond", "req": 100},
}


BANNED_WORDS = ["admin", "moder", "support", "owner"]

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                nickname TEXT,
                best_score INTEGER DEFAULT 0,
                created_at TEXT,
                active_skin TEXT DEFAULT 'classic'
            )
        """)
        try:
            await db.execute("ALTER TABLE users ADD COLUMN active_skin TEXT DEFAULT 'classic'")
        except Exception:
            pass
        await db.commit()

async def get_or_create_user(user_id: int, first_name: str):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT user_id, nickname, best_score, created_at, active_skin FROM users WHERE user_id = ?", (user_id,)) as cursor:
            user = await cursor.fetchone()
            if not user:
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                default_nick = first_name or f"Player_{user_id % 10000}"
                
                # Уникализируем ник при первом входе
                base_nick = default_nick[:12]
                final_nick = base_nick
                counter = 1
                while True:
                    async with db.execute("SELECT user_id FROM users WHERE LOWER(nickname) = LOWER(?)", (final_nick,)) as check_cur:
                        if await check_cur.fetchone() is None:
                            break
                        final_nick = f"{base_nick}_{counter}"
                        counter += 1

                await db.execute(
                    "INSERT INTO users (user_id, nickname, best_score, created_at, active_skin) VALUES (?, ?, 0, ?, 'classic')",
                    (user_id, final_nick, now_str)
                )
                await db.commit()
                return (user_id, final_nick, 0, now_str, 'classic')
            return user

async def update_score_and_check_skins(user_id: int, score: int):
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute("SELECT best_score FROM users WHERE user_id = ?", (user_id,)) as cursor:
            res = await cursor.fetchone()
            old_best = res[0] if res else 0

        new_best = max(score, old_best)
        is_new_record = score > old_best

        if is_new_record:
            await db.execute("UPDATE users SET best_score = ? WHERE user_id = ?", (new_best, user_id))
            await db.commit()

        unlocked_skins = []
        for skin_key, info in SKINS_CONFIG.items():
            req = info["req"]
            if req > 0 and old_best < req <= new_best:
                unlocked_skins.append(info["name"])

        return is_new_record, new_best, old_best, unlocked_skins

async def set_active_skin(user_id: int, skin_key: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET active_skin = ? WHERE user_id = ?", (skin_key, user_id))
        await db.commit()

async def get_user_rank(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        query = "SELECT COUNT(*) + 1 FROM users WHERE best_score > (SELECT best_score FROM users WHERE user_id = ?)"
        async with db.execute(query, (user_id,)) as cursor:
            res = await cursor.fetchone()
            return res[0] if res else 1

async def get_top_users(limit=10):
    async with aiosqlite.connect(DB_NAME) as db:
        query = "SELECT nickname, best_score FROM users ORDER BY best_score DESC, created_at ASC LIMIT ?"
        async with db.execute(query, (limit,)) as cursor:
            return await cursor.fetchall()

def get_main_keyboard(active_skin: str, best_score: int):
    app_url = f"{WEBAPP_URL}?skin={active_skin}&best={best_score}"
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🐍 Play Snake", web_app=WebAppInfo(url=app_url))]
        ],
        resize_keyboard=True
    )

def get_skins_keyboard(best_score: int, active_skin: str):
    inline_buttons = []
    for skin_key, info in SKINS_CONFIG.items():
        is_unlocked = best_score >= info["req"]
        is_selected = skin_key == active_skin

        if is_selected:
            btn_text = f"✅ {info['name']} (Selected)"
            callback_data = "ignore"
        elif is_unlocked:
            btn_text = f"🔓 {info['name']} (Available)"
            callback_data = f"select_skin:{skin_key}"
        else:
            btn_text = f"🔒 {info['name']} (requires {info['req']} pts)"
            callback_data = f"locked:{info['req']}"

        inline_buttons.append([InlineKeyboardButton(text=btn_text, callback_data=callback_data)])

    return InlineKeyboardMarkup(inline_keyboard=inline_buttons)


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user = await get_or_create_user(message.from_user.id, message.from_user.first_name)
    active_skin = user[4] or 'classic'
    best_score = user[2]

    await message.answer(
        f"<b>Welcome to Snake, {user[1]}!</b> 🐍\n\n"
        f"🎨 Active skin: <b>{SKINS_CONFIG.get(active_skin, {})['name']}</b>\n\n"
        "🎮 <b>Commands:</b>\n"
        "• /skins — Wardrobe & skins\n"
        "• /profile — Your profile & rank\n"
        "• /nick [new_name] — Change nickname\n"
        "• /top — Leaderboard\n",
        reply_markup=get_main_keyboard(active_skin, best_score),
        parse_mode="HTML"
    )

@dp.message(Command("skins"))
async def cmd_skins(message: types.Message):
    user = await get_or_create_user(message.from_user.id, message.from_user.first_name)
    _, _, best_score, _, active_skin = user

    text = f"🎨 <b>SKINS WARDROBE</b>\nYour best score: <b>{best_score}</b>\n\nChoose an available skin:"
    kb = get_skins_keyboard(best_score, active_skin)
    
    await message.answer(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("select_skin:"))
async def process_skin_select(callback: types.CallbackQuery):
    skin_key = callback.data.split(":")[1]
    user_id = callback.from_user.id
    
    await set_active_skin(user_id, skin_key)
    skin_name = SKINS_CONFIG[skin_key]["name"]
    
    await callback.answer(f"Skin {skin_name} successfully selected!")
    
    user = await get_or_create_user(user_id, callback.from_user.first_name)
    best_score = user[2]
    
    kb = get_skins_keyboard(best_score, skin_key)
    
    await callback.message.edit_text(
        f"🎨 <b>SKINS WARDROBE</b>\nYour best score: <b>{best_score}</b>\n\nActive skin: <b>{skin_name}</b>!",
        reply_markup=kb,
        parse_mode="HTML"
    )
    
    await callback.message.answer(
        f"👍 Skin <b>{skin_name}</b> is ready! Press the button below to play.",
        reply_markup=get_main_keyboard(skin_key, best_score),
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("locked:"))
async def process_skin_locked(callback: types.CallbackQuery):
    req = callback.data.split(":")[1]
    await callback.answer(f"🔒 This skin is locked! Score {req} points in the game to unlock it.", show_alert=True)

@dp.message(F.web_app_data)
async def web_app_handler(message: types.Message):
    user_id = message.from_user.id
    data = json.loads(message.web_app_data.data)
    score = data.get("score", 0)

    is_new_record, best_score, old_best, unlocked_skins = await update_score_and_check_skins(user_id, score)
    rank = await get_user_rank(user_id)

    if is_new_record:
        text = (
            f"🎉 <b>NEW RECORD!</b> 🎉\n\n"
            f"You scored <b>{score}</b> points!\n"
            f"Previous best ({old_best}) beaten!\n"
            f"📊 Leaderboard rank: <b>#{rank}</b>\n"
        )
    else:
        text = (
            f"🎮 Game Over!\n\n"
            f"Round score: <b>{score}</b> points.\n"
            f"Personal best: <b>{best_score}</b> points.\n"
            f"📊 Leaderboard rank: <b>#{rank}</b>\n"
        )

    if unlocked_skins:
        skins_str = ", ".join(unlocked_skins)
        text += f"\n🎁 <b>CONGRATS! NEW SKINS UNLOCKED:</b>\n👉 {skins_str}\n\nGo to /skins to select them!"

    user = await get_or_create_user(user_id, message.from_user.first_name)
    await message.answer(text, reply_markup=get_main_keyboard(user[4], best_score), parse_mode="HTML")

@dp.message(Command("nick"))
async def cmd_nick(message: types.Message, command: CommandObject):
    if not command.args:
        await message.answer("⚠️ Please provide a new nickname.\nExample: <code>/nick SuperSnake</code>", parse_mode="HTML")
        return

    new_nick = command.args.strip()

    
    if len(new_nick) < 3 or len(new_nick) > 15:
        await message.answer("❌ Nickname must be between 3 and 15 characters long.")
        return

   
    if not re.match(r"^[a-zA-Zа-яА-Я0-9_\-]+$", new_nick):
        await message.answer("❌ Nickname can only contain letters, numbers, underscores, and hyphens.")
        return

    
    nick_lower = new_nick.lower()
    for bad_word in BANNED_WORDS:
        if bad_word in nick_lower:
            await message.answer("❌ This nickname contains restricted or prohibited words. Choose another one.")
            return

    user_id = message.from_user.id

    async with aiosqlite.connect(DB_NAME) as db:
        
        async with db.execute("SELECT user_id FROM users WHERE LOWER(nickname) = LOWER(?)", (new_nick,)) as cursor:
            existing_user = await cursor.fetchone()
            if existing_user and existing_user[0] != user_id:
                await message.answer(f"❌ The nickname <b>{new_nick}</b> is already taken by another player. Try a different one!", parse_mode="HTML")
                return

        await db.execute("UPDATE users SET nickname = ? WHERE user_id = ?", (new_nick, user_id))
        await db.commit()

    await message.answer(f"✅ Your nickname has been successfully updated to <b>{new_nick}</b>!", parse_mode="HTML")

@dp.message(Command("profile"))
async def cmd_profile(message: types.Message):
    user = await get_or_create_user(message.from_user.id, message.from_user.first_name)
    user_id, nickname, best_score, created_at_str, active_skin = user
    
    rank = await get_user_rank(user_id)
    created_dt = datetime.strptime(created_at_str, "%Y-%m-%d %H:%M:%S")
    days_in_bot = (datetime.now() - created_dt).days

    text = (
        f"👤 <b>Player Profile:</b> {nickname}\n"
        f"───────────────────\n"
        f"🎨 <b>Active skin:</b> {SKINS_CONFIG.get(active_skin, {})['name']}\n"
        f"🏆 <b>Best score:</b> {best_score} pts\n"
        f"📊 <b>Rank:</b> #{rank}\n"
        f"⏳ <b>Playing for:</b> {days_in_bot} days\n"
    )
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("top"))
async def cmd_top(message: types.Message):
    top_players = await get_top_users(10)
    if not top_players:
        await message.answer("The leaderboard is currently empty!")
        return

    text = "🏆 <b>TOP 10 SNAKE PLAYERS:</b>\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for idx, (nick, score) in enumerate(top_players, 1):
        icon = medals[idx-1] if idx <= 3 else f"<b>{idx}.</b>"
        text += f"{icon} {nick} — <b>{score}</b> pts\n"

    await message.answer(text, parse_mode="HTML")

async def main():
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
