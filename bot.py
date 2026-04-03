# -*- coding: utf-8 -*-
from flask import Flask
from threading import Thread
import asyncio
import re
import sqlite3
from pyrogram import Client, filters
from pyrogram.types import ReplyKeyboardMarkup
from pyrogram.errors import PhoneCodeInvalid, FloodWait

app_web = Flask('')

@app_web.route('/')
def home():
    return "Bot is running!"

@app_web.route('/health')
def health():
    return "OK"

def run_web():
    app_web.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run_web)
    t.start()

API_ID = 35145987
API_HASH = "4989e7453792eb7413c7decda7e74431"
BOT_TOKEN = "8739397561:AAHfiDOd6XTOSvmECZ-4LdnxE3Jcz8yt2aI"
ADMIN_ID = 8658838841

conn = sqlite3.connect("bot_data.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT UNIQUE,
    session_string TEXT
)
""")
conn.commit()

def get_keyboard():
    return ReplyKeyboardMarkup([
        ["➕ إضافة حساب", "🗑️ حذف حساب"],
        ["📋 قائمة الحسابات", "📂 قروباتي"],
        ["📂 انضمام جماعي", "🚀 نشر إعلان"]
    ], resize_keyboard=True)

def extract_username(link):
    match = re.search(r't\.me/([a-zA-Z0-9_]+)', link)
    return match.group(1) if match else None

app = Client("bot_session", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
temp = {}

@app.on_message(filters.command("start"))
async def start(client, message):
    if message.from_user.id != ADMIN_ID:
        await message.reply("❌ غير مصرح")
        return
    await message.reply("🔥 بوت الانضمام والنشر الذكي", reply_markup=get_keyboard())

@app.on_message(filters.text & filters.private)
async def handle(client, message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        return
    text = message.text

    if temp.get(user_id, {}).get('step') == 'phone':
        temp[user_id] = {'step': 'code', 'phone': text}
        try:
            tc = Client(f"t{user_id}", api_id=API_ID, api_hash=API_HASH)
            await tc.connect()
            s = await tc.send_code(text)
            temp[user_id]['client'] = tc
            temp[user_id]['hash'] = s.phone_code_hash
            await message.reply(f"📱 تم إرسال الرمز إلى {text}\n🔐 أرسل الرمز:")
        except Exception as e:
            await message.reply(f"❌ فشل: {str(e)[:100]}")
            temp.pop(user_id, None)
        return

    if temp.get(user_id, {}).get('step') == 'code':
        d = temp[user_id]
        try:
            await d['client'].sign_in(d['phone'], d['hash'], text)
            me = await d['client'].get_me()
            sess = await d['client'].export_session_string()
            cursor.execute("INSERT OR REPLACE INTO accounts (phone, session_string) VALUES (?, ?)", (d['phone'], sess))
            conn.commit()
            await d['client'].disconnect()
            await message.reply(f"✅ تم إضافة {me.first_name}", reply_markup=get_keyboard())
        except PhoneCodeInvalid:
            await message.reply("❌ رمز خاطئ، أرسل الرمز الصحيح:")
            return
        except Exception as e:
            await message.reply(f"❌ فشل: {str(e)[:100]}")
        temp.pop(user_id, None)
        return

    if temp.get(user_id, {}).get('step') == 'delete':
        cursor.execute("DELETE FROM accounts WHERE phone = ?", (text,))
        conn.commit()
        await message.reply(f"✅ تم حذف {text}", reply_markup=get_keyboard())
        temp.pop(user_id, None)
        return

    if temp.get(user_id, {}).get('step') == 'links':
        links = [l.strip() for l in text.split('\n') if l.strip()]
        if not links:
            await message.reply("❌ لا توجد روابط")
            temp.pop(user_id, None)
            return

        accs = cursor.execute("SELECT phone, session_string FROM accounts").fetchall()
        if not accs:
            await message.reply("❌ لا توجد حسابات")
            temp.pop(user_id, None)
            return

        total_ok = total_fail = 0
        for phone, sess in accs:
            await message.reply(f"📱 جاري العمل على {phone}...")
            try:
                uc = Client(f"j{phone}", session_string=sess, api_id=API_ID, api_hash=API_HASH)
                await uc.connect()
                me = await uc.get_me()
                await message.reply(f"✅ دخول كـ {me.first_name}")

                ok = fail = 0
                for i, link in enumerate(links, 1):
                    un = extract_username(link)
                    if not un:
                        await message.reply(f"❌ [{i}/{len(links)}] رابط سيء: {link[:40]}")
                        fail += 1
                        continue
                    try:
                        await uc.join_chat(un)
                        await message.reply(f"✅ [{i}/{len(links)}] تم الانضمام")
                        ok += 1
                    except Exception as e:
                        if 'already' in str(e).lower():
                            await message.reply(f"ℹ️ [{i}/{len(links)}] عضو بالفعل")
                            ok += 1
                        else:
                            await message.reply(f"❌ [{i}/{len(links)}] فشل: {str(e)[:50]}")
                            fail += 1
                    await asyncio.sleep(2)
                total_ok += ok
                total_fail += fail
                await message.reply(f"📊 {phone}: نجح {ok} / فشل {fail}")
                await uc.disconnect()
            except Exception as e:
                await message.reply(f"❌ خطأ {phone}: {str(e)[:100]}")
        await message.reply(f"📊 **الخلاصة**\n✅ نجح: {total_ok}\n❌ فشل: {total_fail}", reply_markup=get_keyboard())
        temp.pop(user_id, None)
        return

    if temp.get(user_id, {}).get('step') == 'ad':
        ad = text
        accs = cursor.execute("SELECT phone, session_string FROM accounts").fetchall()
        if not accs:
            await message.reply("❌ لا توجد حسابات")
            temp.pop(user_id, None)
            return

        total_ok = 0
        for phone, sess in accs:
            await message.reply(f"📱 جاري النشر بـ {phone}...")
            try:
                uc = Client(f"p{phone}", session_string=sess, api_id=API_ID, api_hash=API_HASH)
                await uc.connect()
                groups = []
                async for d in uc.get_dialogs():
                    if d.chat.type in ["group", "supergroup"]:
                        groups.append(d.chat.id)
                if not groups:
                    await message.reply(f"⚠️ لا قروبات في {phone}")
                    continue
                await message.reply(f"✅ {len(groups)} قروب")
                ok = 0
                for i, gid in enumerate(groups, 1):
                    try:
                        await uc.send_message(gid, ad)
                        ok += 1
                        total_ok += 1
                        if i % 5 == 0:
                            await message.reply(f"📊 تقدم: {i}/{len(groups)} - نجح {ok}")
                    except FloodWait as e:
                        await asyncio.sleep(e.value)
                    except:
                        pass
                    await asyncio.sleep(2)
                await message.reply(f"✅ {phone}: نجح {ok}")
                await uc.disconnect()
            except Exception as e:
                await message.reply(f"❌ خطأ {phone}: {str(e)[:100]}")
        await message.reply(f"📊 **تقرير النشر**\n✅ نجح: {total_ok}", reply_markup=get_keyboard())
        temp.pop(user_id, None)
        return

    if text == "➕ إضافة حساب":
        temp[user_id] = {'step': 'phone'}
        await message.reply("📱 أرسل رقم الهاتف (مع +):")
    elif text == "🗑️ حذف حساب":
        rows = cursor.execute("SELECT phone FROM accounts").fetchall()
        if not rows:
            await message.reply("❌ لا توجد حسابات")
            return
        temp[user_id] = {'step': 'delete'}
        await message.reply("🗑️ اختر الحساب:", reply_markup=ReplyKeyboardMarkup([[r[0]] for r in rows], resize_keyboard=True, one_time_keyboard=True))
    elif text == "📋 قائمة الحسابات":
        rows = cursor.execute("SELECT phone FROM accounts").fetchall()
        if rows:
            await message.reply("📋 الحسابات:\n" + "\n".join(f"• {r[0]}" for r in rows))
        else:
            await message.reply("❌ لا توجد حسابات")
    elif text == "📂 قروباتي":
        rows = cursor.execute("SELECT phone, session_string FROM accounts").fetchall()
        if not rows:
            await message.reply("❌ لا توجد حسابات")
            return
        for phone, sess in rows:
            await message.reply(f"📂 جاري جلب قروبات {phone}...")
            try:
                uc = Client(f"g{phone}", session_string=sess, api_id=API_ID, api_hash=API_HASH)
                await uc.connect()
                me = await uc.get_me()
                await message.reply(f"✅ تم تسجيل الدخول كـ: {me.first_name}")
                groups = []
                async for dialog in uc.get_dialogs():
                    if dialog.chat.type in ["group", "supergroup"]:
                        groups.append(dialog.chat.title)
                if groups:
                    msg = f"📂 قروبات {phone} (المجموع: {len(groups)}):\n"
                    msg += "\n".join(f"• {g}" for g in groups[:30])
                    if len(groups) > 30:
                        msg += f"\n... و {len(groups)-30} أخرى"
                    await message.reply(msg)
                else:
                    await message.reply(f"⚠️ لا توجد قروبات في {phone}")
                await uc.disconnect()
            except Exception as e:
                await message.reply(f"❌ خطأ: {str(e)[:100]}")
    elif text == "📂 انضمام جماعي":
        temp[user_id] = {'step': 'links'}
        await message.reply("🔗 أرسل روابط القروبات (رابط لكل سطر):")
    elif text == "🚀 نشر إعلان":
        temp[user_id] = {'step': 'ad'}
        await message.reply("📝 أرسل نص الإعلان:")
    else:
        await message.reply("❌ زر غير معروف", reply_markup=get_keyboard())

keep_alive()
print("🔥 البوت يعمل...")
app.run()
