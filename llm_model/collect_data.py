import sqlite3
from typing import Optional, Dict


def get_user_profile(telegram_id: int) -> Optional[Dict]:
    conn = sqlite3.connect("clothes_bot.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT
            u.telegram_id,
            u.username,
            u.first_name,
            p.name,
            p.gender,
            p.city,
            p.clothing_style,
            p.timezone
        FROM users u
        JOIN profiles p ON p.user_id = u.id
        WHERE u.telegram_id = ?
    """, (telegram_id,))

    row = cur.fetchone()
    conn.close()

    if row is None:
        return None

    return dict(row)
