from telethon import TelegramClient, events, functions
import asyncio
import datetime
import re
import os
import json
from config import api_id, api_hash, phone, owner_id
from telethon.tl.types import InputReportReasonSpam, InputReportReasonOther
from telethon.errors import RPCError

client = TelegramClient('session_name', api_id, api_hash)

spamming = False
spam_task = None

spamming_snos = False
snos_task = None  # <-- здесь!

LOG_DB = "logs.json"

# Загрузка базы логирования из файла
def load_log_db():
    if os.path.exists(LOG_DB):
        with open(LOG_DB, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

# Сохранение базы логирования в файл
def save_log_db(data):
    with open(LOG_DB, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# Загрузка логируемых пользователей и открытие файлов
log_targets = load_log_db()  # словарь username -> user_id
log_files = {}  # user_id -> open file object

for username, uid in log_targets.items():
    log_files[str(uid)] = open(f"{username}.txt", "a", encoding="utf-8")

# --- Декоратор: прокси с новым raw_text, делегирует все методы оригиналу ---
def edit_delete_then_run(handler):
    class EventProxy:
        def __init__(self, original_event, new_raw_text):
            self._original_event = original_event
            self.raw_text = new_raw_text
        def __getattr__(self, item):
            return getattr(self._original_event, item)
    async def wrapper(event):
        if event.sender_id != owner_id:
            return
        proxy_event = EventProxy(event, event.raw_text)
        await handler(proxy_event)
        try:
            await event.edit(".")
            await asyncio.sleep(0.5)
            await event.delete()
        except Exception as e:
            print(f"Ошибка редактирования/удаления: {e}")
    return wrapper

# === ФУНКЦИЯ СПАМА ===
async def spam_loop(event, message, count):
    global spamming
    spamming = True
    i = 0
    while spamming and (count == -1 or i < count):
        await event.respond(message)
        i += 1
        await asyncio.sleep(0)

# === ФУНКЦИЯ АВТО ЖАЛОБ (.snos) ===
async def snos_loop(event, count, peer, msg_id, reason_text):
    global spamming_snos
    spamming_snos = True
    i = 0
    while spamming_snos and (count == -1 or i < count):
        try:
            if reason_text:
                reason = InputReportReasonOther(text=reason_text)
            else:
                reason = InputReportReasonSpam()

            await client(functions.messages.ReportRequest(
                peer=peer,
                id=[msg_id],
                reason=reason,
                message="Жалоба отправлена ботом"
            ))
            i += 1
            await asyncio.sleep(1)
        except Exception as e:
            await event.respond(f"❗ Ошибка при отправке жалобы: {e}")
            break

# === КОМАНДА .spam ===
@client.on(events.NewMessage(pattern=r'\.spam'))
@edit_delete_then_run
async def start_spam(event):
    global spam_task, spamming
    args = event.raw_text.split(' ', 2)
    if len(args) < 3:
        await event.respond("❗ Использование: `.spam <кол-во> <сообщение>`")
        return
    try:
        count = int(args[1])
        msg = args[2]
    except ValueError:
        await event.respond("❗ Кол-во должно быть числом или -1 для бесконечного.")
        return

    if spam_task and not spam_task.done():
        spam_task.cancel()
    spam_task = asyncio.create_task(spam_loop(event, msg, count))

# === КОМАНДА .off ===
@client.on(events.NewMessage(pattern=r'\.off'))
@edit_delete_then_run
async def stop_spam(event):
    global spamming
    spamming = False

# === КОМАНДА .т/.t ===
@client.on(events.NewMessage(pattern=r'\.(t|т)'))
@edit_delete_then_run
async def typing_effect(event):
    try:
        args = event.raw_text.split(' ', 1)
        if len(args) < 2:
            return

        full_text = args[1]
        typed = ""
        msg = await event.respond("·••")

        for char in full_text:
            typed += char
            await msg.edit(f"{typed}·••")
            await asyncio.sleep(0.2)

        await msg.edit(typed)
    except Exception as e:
        print("Ошибка в .t команде:", e)

# === КОМАНДА .help ===
@client.on(events.NewMessage(pattern=r'\.help'))
@edit_delete_then_run
async def show_help(event):
    await event.respond(
        "**📘 Команды:**\n"
        "`.spam <кол-во> <сообщение>` — спамит сообщение (используй `-1` для бесконечного спама)\n"
        "`.off` — остановить спам\n"
        "`.help` — показать это сообщение\n"
        "`.т/.t <текст>` — анимированное покадровое писание\n"
        "`.snos <кол-во> [причина жалобы] {ссылка на сообщение}` — авто отправка жалоб на сообщение\n"
        "`.snos_off` — остановить авто жалобы\n"
        "`.status` — показать текущий статус спама и жалоб\n"
        "`.log @username` — включить логирование сообщений пользователя\n"
        "`.logoff @username` — выключить логирование\n"
        "`.userinfo @username` — показать информацию о пользователе\n"
        "`.remindme <время> <сообщение>` — установить напоминание\n"
        "`.afk_on` — включить статус AFK (добавить [AFK] к имени)\n"
        "`.afk_off` — выключить статус AFK (убрать [AFK] из имени)\n"
    )

# === КОМАНДА .snos ===
@client.on(events.NewMessage(pattern=r'\.snos'))
@edit_delete_then_run
async def start_snos(event):
    global snos_task, spamming_snos
    args = event.raw_text.split(' ', 4)

    if len(args) < 2:
        await event.respond("❗ Использование: `.snos <кол-во> [причина жалобы] {ссылка на сообщение}`\n"
                            "Пример: `.snos 5 спам https://t.me/username/123`")
        return

    try:
        count = int(args[1])
    except ValueError:
        await event.respond("❗ Кол-во должно быть числом или -1 для бесконечного.")
        return

    reason_text = None
    message_link = None

    if len(args) == 3:
        if args[2].startswith("http"):
            message_link = args[2]
        else:
            reason_text = args[2]

    elif len(args) >= 4:
        reason_text = args[2]
        message_link = args[3]

    if not message_link:
        await event.respond("❗ Нужно указать ссылку на сообщение для жалобы.")
        return

    try:
        pattern = r"(?:https?://)?t\.me/(c/)?([\w\d_]+)/(\d+)"
        m = re.search(pattern, message_link)
        if not m:
            await event.respond("❗ Неверный формат ссылки на сообщение.")
            return

        is_private = m.group(1)
        chat_id_part = m.group(2)
        msg_id = int(m.group(3))

        if is_private:
            chat_id = int("-100" + chat_id_part)
        else:
            chat_id = chat_id_part

        peer = await client.get_entity(chat_id)
    except Exception as e:
        await event.respond(f"❗ Ошибка при разборе ссылки: {e}")
        return

    if snos_task and not snos_task.done():
        snos_task.cancel()

    snos_task = asyncio.create_task(snos_loop(event, count, peer, msg_id, reason_text))

    await event.respond(f"🚨 Запущено отправление {count if count != -1 else 'бесконечного'} жалоб на сообщение {message_link}")

# === КОМАНДА .snos_off ===
@client.on(events.NewMessage(pattern=r'\.snos_off'))
@edit_delete_then_run
async def stop_snos(event):
    global spamming_snos
    spamming_snos = False
    await event.respond("Авто жалобы остановлены.")

# === КОМАНДА .status ===
@client.on(events.NewMessage(pattern=r'\.status'))
@edit_delete_then_run
async def show_status(event):
    status_msg = f"📊 Статус:\nСпам: {'Включен' if spamming else 'Выключен'}\nАвто жалобы: {'Включены' if spamming_snos else 'Выключены'}"
    await event.respond(status_msg)

# === КОМАНДА .log ===
@client.on(events.NewMessage(pattern=r'\.log'))
@edit_delete_then_run
async def start_logging(event):
    global log_targets, log_files
    args = event.raw_text.split(' ', 1)
    if len(args) < 2:
        await event.respond("❗ Использование: `.log @username`")
        return
    username = args[1].lstrip('@')
    try:
        user = await client.get_entity(username)
    except Exception as e:
        await event.respond(f"❗ Не удалось найти пользователя @{username}: {e}")
        return

    uid = str(user.id)
    if uid in log_files:
        await event.respond(f"ℹ️ Логирование для @{username} уже включено.")
        return

    log_targets[username] = user.id
    save_log_db(log_targets)

    f = open(f"{username}.txt", "a", encoding="utf-8")
    log_files[uid] = f

    await event.respond(f"📝 Логирование сообщений пользователя @{username} включено.")

# === КОМАНДА .logoff ===
@client.on(events.NewMessage(pattern=r'\.logoff'))
@edit_delete_then_run
async def stop_logging(event):
    global log_targets, log_files
    args = event.raw_text.split(' ', 1)
    if len(args) < 2:
        await event.respond("❗ Использование: `.logoff @username`")
        return
    username = args[1].lstrip('@')
    uid = None
    try:
        user = await client.get_entity(username)
        uid = str(user.id)
    except Exception as e:
        await event.respond(f"❗ Не удалось найти пользователя @{username}: {e}")
        return

    if uid not in log_files:
        await event.respond(f"ℹ️ Логирование для @{username} не было включено.")
        return

    log_files[uid].close()
    del log_files[uid]
    if username in log_targets:
        del log_targets[username]
    save_log_db(log_targets)

    await event.respond(f"🛑 Логирование сообщений пользователя @{username} выключено.")

# === Логирование новых сообщений ===
@client.on(events.NewMessage())
async def log_new_message(event):
    global log_files
    uid = str(event.sender_id)
    if uid in log_files:
        f = log_files[uid]
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        text = event.raw_text.replace("\n", "\\n")
        f.write(f"[{now}] Отправлено (id {event.id}): {text}\n")
        f.flush()

# === Логирование редактированных сообщений ===
@client.on(events.MessageEdited())
async def log_edited_message(event):
    global log_files
    uid = str(event.sender_id)
    if uid in log_files:
        f = log_files[uid]
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        new_text = event.text.replace("\n", "\\n") if event.text else ""
        f.write(f"[{now}] Отредактировано (id {event.id}): {new_text}\n")
        f.flush()

# === Логирование удалённых сообщений ===
@client.on(events.MessageDeleted())
async def log_deleted_message(event):
    global log_files
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    deleted_ids = event.deleted_ids
    if not deleted_ids:
        return
    for uid, f in log_files.items():
        f.write(f"[{now}] Удалены сообщения с id: {deleted_ids}\n")
        f.flush()

# === КОМАНДА .userinfo ===
@client.on(events.NewMessage(pattern=r'\.userinfo'))
@edit_delete_then_run
async def user_info(event):
    args = event.raw_text.split(' ', 1)
    if len(args) < 2:
        await event.respond("❗ Использование: `.userinfo @username`")
        return
    username = args[1].lstrip('@')
    try:
        user = await client.get_entity(username)
    except Exception as e:
        await event.respond(f"❗ Не удалось найти пользователя @{username}: {e}")
        return

    info = (
        f"👤 Информация о пользователе @{username}:\n"
        f"ID: {user.id}\n"
        f"Имя: {user.first_name or '-'}\n"
        f"Фамилия: {user.last_name or '-'}\n"
        f"Username: @{user.username or '-'}\n"
        f"Бот: {'Да' if user.bot else 'Нет'}\n"
        f"Дата регистрации (примерная): {user.date.strftime('%Y-%m-%d') if hasattr(user, 'date') and user.date else '-'}"
    )
    await event.respond(info)

# === КОМАНДА .remindme ===
@client.on(events.NewMessage(pattern=r'\.remindme'))
@edit_delete_then_run
async def remind_me(event):
    args = event.raw_text.split(' ', 2)
    if len(args) < 3:
        await event.respond("❗ Использование: `.remindme <время> <сообщение>`\n"
                            "Пример времени: 10s (секунд), 5m (минут), 1h (час)")
        return
    time_str = args[1]
    message = args[2]

    match = re.match(r"(\d+)([smh])", time_str.lower())
    if not match:
        await event.respond("❗ Формат времени неверен. Используй число + s/m/h (например, 10s, 5m, 1h)")
        return
    amount, unit = int(match.group(1)), match.group(2)
    seconds = amount
    if unit == 'm':
        seconds *= 60
    elif unit == 'h':
        seconds *= 3600

    await event.respond(f"⏳ Напоминание установлено на {amount}{unit}")

    async def reminder():
        await asyncio.sleep(seconds)
        await client.send_message(event.chat_id, f"🔔 Напоминание: {message}")

    asyncio.create_task(reminder())

# === КОМАНДА .afk_on ===
@client.on(events.NewMessage(pattern=r'\.afk_on'))
@edit_delete_then_run
async def afk_on(event):
    me = await client.get_me()
    first_name = me.first_name or ""
    if first_name.startswith("[AFK]"):
        await event.respond("ℹ️ Статус AFK уже включён.")
        return

    new_name = "[AFK] " + first_name
    try:
        await client(functions.account.UpdateProfileRequest(first_name=new_name))
        await event.respond(f"✅ Статус AFK включён. Имя изменено на: {new_name}")
    except Exception as e:
        await event.respond(f"❗ Не удалось изменить имя: {e}")

# === КОМАНДА .afk_off ===
@client.on(events.NewMessage(pattern=r'\.afk_off'))
@edit_delete_then_run
async def afk_off(event):
    me = await client.get_me()
    first_name = me.first_name or ""
    if not first_name.startswith("[AFK]"):
        await event.respond("ℹ️ Статус AFK не был включён.")
        return

    new_name = first_name[6:]  # Убираем "[AFK] "
    try:
        await client(functions.account.UpdateProfileRequest(first_name=new_name))
        await event.respond(f"✅ Статус AFK выключен. Имя изменено на: {new_name}")
    except Exception as e:
        await event.respond(f"❗ Не удалось изменить имя: {e}")

# === СТАРТ КЛИЕНТА ===
while True:
    try:
        client.start(phone=phone)
        print("✅ Скрипт запущен.")
        client.run_until_disconnected()
    except (RpcError, ConnectionError, OSError) as e:
        print(f"Ошибка подключения: {e}. Пробую переподключиться через 5 секунд...")
        time.sleep(5)
    except KeyboardInterrupt:
        print("Выход по Ctrl+C")
        break