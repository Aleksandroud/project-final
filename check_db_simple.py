import sqlite3

print("🔍 Проверяю базу данных clothes_bot.db...")
conn = sqlite3.connect('clothes_bot.db')
cursor = conn.cursor()

# 1. Все таблицы
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
print(f"📊 Таблицы: {[t[0] for t in tables]}")

# 2. Пользователи
cursor.execute("SELECT COUNT(*) FROM users")
users_count = cursor.fetchone()[0]
print(f"👥 Пользователей: {users_count}")

if users_count > 0:
    cursor.execute("SELECT * FROM users")
    for row in cursor.fetchall():
        print(f"  ID: {row[0]}, TG: {row[1]}, Имя: {row[3]}")

# 3. Настройки
cursor.execute("SELECT COUNT(*) FROM user_preferences")
prefs_count = cursor.fetchone()[0]
print(f"⚙️ Настроек: {prefs_count}")

if prefs_count > 0:
    cursor.execute("SELECT * FROM user_preferences")
    for row in cursor.fetchall():
        print(f"  ID: {row[0]}, User_ID: {row[1]}, Имя: {row[2]}, Город: {row[4]}, Стиль: {row[5]}")

conn.close()