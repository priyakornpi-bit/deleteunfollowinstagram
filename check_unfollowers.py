"""
สคริปต์เช็คว่าใครไม่ follow กลับ ผ่าน instagrapi
ใช้กับบัญชีทดลองเท่านั้น! ห้ามใช้กับบัญชีหลัก

วิธีใช้:
1. ใส่ username/password ตอนรัน
2. รัน: .venv/bin/python check_unfollowers.py
"""

import getpass
import json
import random
import sqlite3
import time
from pathlib import Path

from instagrapi import Client
from instagrapi.exceptions import (
    ChallengeRequired,
    ClientError,
    LoginRequired,
    TwoFactorRequired,
)

SESSION_DIR = Path("sessions")
WHITELIST_FILE = Path("whitelist.txt")
# ค่าเริ่มต้นของตัวกรอง; ผู้ใช้สามารถเปลี่ยนค่าได้ตอนเริ่มโปรแกรม
FOLLOWER_THRESHOLD = 10000
# กันบัญชี verified ไว้เสมอ แม้ follower จะไม่เกิน threshold
SKIP_VERIFIED = True
# ฐานข้อมูลนี้ใช้เก็บรายการที่เลือก F เพื่อจัดการภายหลัง
DATABASE_FILE = Path("unfollow_queue.db")
RESULT_FILE = Path("not_following_back.json")


def load_whitelist() -> set[str]:
    # อ่านชื่อจากไฟล์ครั้งเดียว แล้วเปรียบเทียบแบบตัวพิมพ์เล็ก
    if not WHITELIST_FILE.exists():
        WHITELIST_FILE.write_text("", encoding="utf-8")
        print(f"[i] สร้างไฟล์ {WHITELIST_FILE} แล้ว เติม username ที่ต้องการกันไว้ได้")
        return set()

    return {
        line.strip().lstrip("@").lower()
        for line in WHITELIST_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def get_session_file(username: str) -> Path:
    # แยก session ตาม account เพื่อไม่ให้สลับ session ระหว่างบัญชี
    safe_username = "".join(
        character for character in username.lower()
        if character.isalnum() or character in "._-"
    )
    return SESSION_DIR / f"session_{safe_username}.json"


def get_follower_threshold() -> int | None:
    """รับเกณฑ์ follower ที่จะใช้คัดกรองในรอบนี้"""
    while True:
        value = input(
            f"เกณฑ์ follower สูงสุด (Enter = {FOLLOWER_THRESHOLD:,}, 0 = ไม่กรอง): "
        ).strip()
        if not value:
            return FOLLOWER_THRESHOLD
        try:
            threshold = int(value)
        except ValueError:
            print("[!] กรุณาใส่ตัวเลข หรือกด Enter")
            continue
        if threshold >= 0:
            return threshold or None
        print("[!] เกณฑ์ต้องไม่ติดลบ")


def choose_delay() -> bool:
    """เลือกว่าจะหน่วงสุ่ม 30-120 วินาทีระหว่างการลบหรือไม่"""
    while True:
        choice = input("หน่วงเวลาระหว่างลบหรือไม่? [Y] หน่วง / [N] ไม่หน่วง: ").strip().upper()
        if choice in {"Y", "N"}:
            return choice == "Y"
        print("[!] กรุณาเลือก Y หรือ N")


def load_previous_results() -> list[dict] | None:
    """โหลดผลลัพธ์เดิมเพื่อใช้เป็นรายการคัดกรอง โดยไม่ดึงรายชื่อใหม่"""
    if not RESULT_FILE.exists():
        print(f"[!] ไม่พบไฟล์ข้อมูลเก่า: {RESULT_FILE}")
        return None

    try:
        results = json.loads(RESULT_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"[!] อ่านข้อมูลเก่าไม่ได้ ({error})")
        return None

    if not isinstance(results, list) or not all(
        isinstance(user, dict)
        and {"user_id", "username", "full_name"}.issubset(user)
        for user in results
    ):
        print("[!] รูปแบบข้อมูลเก่าไม่ถูกต้อง")
        return None

    print(f"[i] โหลดข้อมูลเก่าแล้ว {len(results)} บัญชี")
    return results


def choose_data_source() -> list[dict] | None:
    """ถามว่าจะใช้ JSON เก่าหรือดึงข้อมูล following/followers ใหม่"""
    while True:
        choice = input(
            "ใช้ข้อมูลเก่าจาก not_following_back.json เลยไหม? "
            "[Y] ใช้ข้อมูลเก่า / [N] ดึงข้อมูลใหม่: "
        ).strip().upper()
        if choice == "Y":
            previous_results = load_previous_results()
            if previous_results is not None:
                print("[!] ข้อมูลนี้อาจเก่าและสถานะการติดตามอาจเปลี่ยนไปแล้ว")
                return previous_results
            print("[!] ไม่สามารถใช้ข้อมูลเก่าได้ จะเลือกใหม่")
        elif choice == "N":
            return None
        else:
            print("[!] กรุณาเลือก Y หรือ N")


def login_with_2fa(cl: Client, username: str, password: str) -> None:
    # ลอง login ปกติก่อน; ถ้าเปิด 2FA จึงถามรหัสยืนยันเพิ่ม
    try:
        cl.login(username, password)
    except TwoFactorRequired:
        print("[!] บัญชีนี้เปิด 2FA ไว้ ต้องใส่รหัสยืนยัน")
        code = input("ใส่รหัส 6 หลักจาก authenticator app / SMS: ").strip()
        cl.login(username, password, verification_code=code)


def get_client(username: str, password: str) -> Client:
    cl = Client()
    session_file = get_session_file(username)

    if session_file.exists():
        try:
            # ตรวจ session เดิมก่อน เพื่อไม่ต้อง login ใหม่ทุกครั้ง
            cl.load_settings(session_file)
            cl.get_timeline_feed()
            print("[+] ใช้ session เดิม (ไม่ต้อง login ใหม่)")
            return cl
        except Exception as error:
            reason = "session หมดอายุ" if isinstance(error, LoginRequired) else str(error)
            print(f"[!] session เดิมใช้ไม่ได้ ({reason}) จะ login ใหม่")

    try:
        login_with_2fa(cl, username, password)
    except ChallengeRequired:
        print("[!] Instagram ขอ challenge verification")
        print("    ให้ยืนยันการ login ในแอป Instagram หรือทาง email แล้วลองใหม่")
        raise SystemExit(1)
    except ClientError as error:
        message = str(error)
        if "CAA login did not return a session" in message:
            print("[!] Instagram ไม่ส่ง session กลับมา จึงยัง login ไม่สำเร็จ")
            print("    ตรวจ username/password และยืนยัน login จากแอป Instagram ก่อน")
            print(f"    หาก session เสีย ให้ลบไฟล์: {session_file}")
        else:
            print(f"[!] Instagram login ไม่สำเร็จ: {message}")
        raise SystemExit(1)

    # สร้างโฟลเดอร์และบันทึก session หลัง login สำเร็จ
    SESSION_DIR.mkdir(exist_ok=True)
    cl.dump_settings(session_file)
    print(f"[+] login สำเร็จ และบันทึก session ของ @{username} แล้ว")
    return cl


def save_to_unfollow_queue(account: str, users: list[dict]) -> None:
    """เก็บรายการไว้ใน SQLite เพื่อรวมและลบในภายหลัง"""
    with sqlite3.connect(DATABASE_FILE) as connection:
        # ใช้ UNIQUE กันรายการเดิมของ account เดิมถูกบันทึกซ้ำ
        connection.execute(
            """CREATE TABLE IF NOT EXISTS unfollow_queue (
                account TEXT NOT NULL,
                user_id TEXT NOT NULL,
                username TEXT NOT NULL,
                full_name TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(account, user_id)
            )"""
        )
        connection.executemany(
            """INSERT OR IGNORE INTO unfollow_queue
               (account, user_id, username, full_name)
               VALUES (?, ?, ?, ?)""",
            [
                (account, user["user_id"], user["username"], user["full_name"])
                for user in users
            ],
        )
    print(f"[+] เก็บข้อมูล {len(users)} บัญชีไว้ใน {DATABASE_FILE} แล้ว")


def unfollow_users(
    cl: Client,
    account: str,
    users: list[dict],
    delay_enabled: bool,
) -> None:
    if not users:
        print("[+] ไม่มีบัญชีที่ต้องลบฟอล")
        return

    print(f"\nพบบัญชีที่ไม่ follow กลับจำนวน {len(users)} คน")
    while True:
        try:
            requested_count = int(input(
                f"วันนี้ต้องการลบกี่บัญชี (1-{len(users)}, 0 เพื่อยกเลิก): "
            ).strip())
        except ValueError:
            print("[!] กรุณาใส่จำนวนเป็นตัวเลข")
            continue
        if 0 <= requested_count <= len(users):
            break
        print(f"[!] จำนวนต้องอยู่ระหว่าง 0 ถึง {len(users)}")

    if requested_count == 0:
        print("[-] ยกเลิกการลบฟอล")
        return

    # ใช้เฉพาะจำนวนแรกตามที่ผู้ใช้เลือก ไม่ลบเกินจำนวนในรอบนี้
    selected_users = users[:requested_count]
    print(f"\nจะลบฟอลจำนวน {len(selected_users)} บัญชีในรอบนี้:")
    for user in selected_users:
        print(f"  - @{user['username']} ({user['full_name']})")

    action = input("เลือกการทำงาน [U] ลบเลย / [F] เก็บไว้ก่อน: ").strip().upper()
    if action == "F":
        # โหมด F เป็นการเก็บข้อมูลเท่านั้น จะไม่เรียก API ลบฟอล
        save_to_unfollow_queue(account, selected_users)
        print("[+] เก็บรายการไว้ก่อน ยังไม่มีการลบฟอล")
        return
    if action != "U":
        print("[-] ยกเลิก: กรุณาเลือก U หรือ F")
        return

    success_count = 0
    failure_count = 0
    for user in selected_users:
        try:
            cl.user_unfollow(user["user_id"])
            success_count += 1
            print(f"[+] ลบฟอล @{user['username']} แล้ว")
        except Exception as error:
            failure_count += 1
            print(f"[!] ลบฟอล @{user['username']} ไม่สำเร็จ ({error})")
        # หน่วงเฉพาะเมื่อผู้ใช้เลือก Y; โหมด N จะไปบัญชีถัดไปทันที
        if delay_enabled:
            delay_seconds = random.randint(30, 120)
            print(f"    หน่วงเวลา {delay_seconds} วินาทีก่อนดำเนินการถัดไป")
            time.sleep(delay_seconds)

    print(f"\n[+] ลบฟอลสำเร็จ: {success_count} คน")
    if failure_count:
        print(f"[!] ลบฟอลไม่สำเร็จ: {failure_count} คน")


def filter_not_following_back(
    cl: Client,
    following: dict,
    followers: dict,
    follower_threshold: int | None,
) -> set:
    # เซตลบกันจะได้รายชื่อที่เราติดตาม แต่เขาไม่ได้ติดตามเรากลับ
    raw_ids = set(following) - set(followers)
    whitelist = load_whitelist()
    filtered_ids = {
        uid for uid in raw_ids
        if following[uid].username.lower() not in whitelist
    }
    skipped_by_whitelist = len(raw_ids) - len(filtered_ids)

    # ถ้าไม่เปิดทั้งสองตัวกรอง ไม่ต้องยิง user_info เพิ่ม
    if follower_threshold is None and not SKIP_VERIFIED:
        return filtered_ids

    result = set()
    skipped_by_threshold = 0
    skipped_by_verified = 0
    print(
        f"[+] กำลังเช็คข้อมูลของ {len(filtered_ids)} คน..."
    )
    # ขอข้อมูลเพิ่มเฉพาะรายชื่อที่ผ่าน whitelist แล้ว เพื่อลดจำนวน request
    for index, uid in enumerate(sorted(filtered_ids), 1):
        try:
            info = cl.user_info(uid)
            follower_count = info.follower_count
            is_verified = info.is_verified
        except Exception as error:
            print(f"  [!] เช็ค @{following[uid].username} ไม่ได้ ({error}) -> นับตามปกติ")
            result.add(uid)
        else:
            if SKIP_VERIFIED and is_verified:
                skipped_by_verified += 1
            elif follower_threshold is not None and follower_count > follower_threshold:
                skipped_by_threshold += 1
            else:
                result.add(uid)
        time.sleep(1)
        if index % 20 == 0:
            print(f"    เช็คไปแล้ว {index}/{len(filtered_ids)} คน")

    print(f"กันไว้เพราะอยู่ใน whitelist: {skipped_by_whitelist} คน")
    print(f"กันไว้เพราะมีติ๊กฟ้า (verified): {skipped_by_verified} คน")
    print(f"กันไว้เพราะ follower เกิน threshold: {skipped_by_threshold} คน")
    return result


def main() -> None:
    print("=== เช็คคนไม่ follow กลับ (Instagram) ===")
    print("!! ใช้กับบัญชีทดลองเท่านั้น !!\n")
    username = input("Username: ").strip()
    password = getpass.getpass("Password: ")
    delay_enabled = choose_delay()
    cl = get_client(username, password)
    user_id = cl.user_id

    print(f"[+] user_id: {user_id}")
    # ใช้ snapshot เดิมทันที เพื่อไม่ต้องดึงข้อมูลจาก Instagram ซ้ำหลายพันรายการ
    result = load_previous_results()
    if result is None:
        print("[!] ไม่มีข้อมูลเก่าที่ใช้ได้ จึงหยุดการทำงาน")
        raise SystemExit(1)

    print("[i] ใช้ข้อมูลเก่าโดยไม่ตรวจสถานะ follower ซ้ำ")
    for user in result:
        print(f"  - @{user['username']} ({user['full_name']})")

    # เก็บ snapshot เป็น JSON ไว้ตรวจสอบย้อนหลัง แม้เลือก F ก็ยังมีข้อมูลชุดนี้
    # เขียนผลลัพธ์กลับไฟล์เพื่อให้รอบถัดไปเลือกใช้ข้อมูลชุดนี้ได้
    RESULT_FILE.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n[+] บันทึกผลลัพธ์ไว้ที่ {RESULT_FILE} แล้ว")
    unfollow_users(cl, username, result, delay_enabled)


if __name__ == "__main__":
    main()
