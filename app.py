"""หน้าต่างสำหรับจัดการรายการ unfollow จาก not_following_back.json"""

import getpass
import json
import os
import queue
import random
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

# Finder อาจเปิดแอปด้วย working directory อื่น จึงกำหนดโฟลเดอร์ข้อมูลเอง
if getattr(sys, "frozen", False):
    DATA_DIR = Path(sys.executable).resolve().parents[3]
else:
    DATA_DIR = Path(__file__).resolve().parent
os.chdir(DATA_DIR)

import check_unfollowers


class UnfollowApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Instagram Unfollow Manager")
        self.root.geometry("760x620")
        self.root.minsize(680, 520)
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.users: list[dict] = []
        self.busy = False
        self.stop_event = threading.Event()
        self.stop_requested = False
        self.progress_window: tk.Toplevel | None = None
        self.progress_text: tk.StringVar | None = None
        self.progress_detail: tk.StringVar | None = None
        self.progress_bar: ttk.Progressbar | None = None
        self.progress_stop_button: ttk.Button | None = None

        self.username = tk.StringVar()
        self.password = tk.StringVar()
        self.amount = tk.StringVar(value="0")
        self.threshold = tk.StringVar(value=str(check_unfollowers.FOLLOWER_THRESHOLD))
        self.delay_enabled = tk.BooleanVar(value=True)
        self.action = tk.StringVar(value="F")
        self.status = tk.StringVar(value="ยังไม่ได้โหลดข้อมูล")

        self.build_ui()
        self.root.after(100, self.process_logs)
        self.load_results()

    def build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=16)
        main.pack(fill="both", expand=True)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(5, weight=1)

        ttk.Label(main, text="Instagram Unfollow Manager", font=("TkDefaultFont", 16, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 14)
        )

        ttk.Label(main, text="Username").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(main, textvariable=self.username).grid(row=1, column=1, columnspan=2, sticky="ew", pady=4)
        ttk.Label(main, text="Password").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Entry(main, textvariable=self.password, show="*").grid(row=2, column=1, columnspan=2, sticky="ew", pady=4)

        controls = ttk.Frame(main)
        controls.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(10, 4))
        ttk.Label(controls, text="จำนวนที่จะจัดการ").pack(side="left")
        ttk.Entry(controls, textvariable=self.amount, width=8).pack(side="left", padx=(8, 20))
        ttk.Checkbutton(
            controls,
            text="หน่วงสุ่ม 30-120 วินาที",
            variable=self.delay_enabled,
        ).pack(side="left")
        ttk.Label(controls, text="Follower สูงสุด").pack(side="left", padx=(16, 4))
        ttk.Entry(controls, textvariable=self.threshold, width=8).pack(side="left")
        ttk.Button(controls, text="อัพเดทข้อมูลจาก Instagram", command=self.start_update).pack(
            side="right", padx=(8, 0)
        )
        ttk.Button(controls, text="โหลด JSON ใหม่", command=self.load_results).pack(side="right")

        actions = ttk.LabelFrame(main, text="การทำงาน")
        actions.grid(row=4, column=0, columnspan=3, sticky="ew", pady=8)
        ttk.Radiobutton(actions, text="F เก็บข้อมูลไว้ก่อน", variable=self.action, value="F").pack(
            side="left", padx=12, pady=8
        )
        ttk.Radiobutton(actions, text="U ลบฟอลทันที", variable=self.action, value="U").pack(
            side="left", padx=12, pady=8
        )
        self.stop_button = ttk.Button(actions, text="หยุดการทำงาน", command=self.stop, state="disabled")
        self.stop_button.pack(side="right", padx=(4, 12), pady=6)
        ttk.Button(actions, text="เริ่มทำงาน", command=self.start).pack(side="right", padx=4, pady=6)

        list_frame = ttk.LabelFrame(main, text="รายการจาก not_following_back.json")
        list_frame.grid(row=5, column=0, columnspan=3, sticky="nsew", pady=8)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        self.listbox = tk.Listbox(list_frame, height=14, activestyle="none")
        self.listbox.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.listbox.configure(yscrollcommand=scrollbar.set)

        ttk.Label(main, textvariable=self.status).grid(row=6, column=0, columnspan=3, sticky="w", pady=(4, 4))
        self.log = tk.Text(main, height=6, state="disabled", wrap="word")
        self.log.grid(row=7, column=0, columnspan=3, sticky="ew")

    def load_results(self) -> None:
        try:
            loaded = check_unfollowers.load_previous_results()
        except Exception as error:
            messagebox.showerror("โหลดข้อมูลไม่สำเร็จ", str(error))
            return
        if loaded is None:
            self.users = []
            self.listbox.delete(0, tk.END)
            self.status.set("ไม่พบข้อมูลที่ใช้ได้")
            return

        self.users = loaded
        self.listbox.delete(0, tk.END)
        for index, user in enumerate(self.users, 1):
            self.listbox.insert(tk.END, f"{index:>4}. @{user['username']}  {user['full_name']}")
        self.amount.set(str(len(self.users)))
        self.status.set(f"โหลดแล้ว {len(self.users):,} บัญชี")
        self.write_log(f"โหลดข้อมูลเก่า {len(self.users):,} บัญชี")

    def write_log(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert(tk.END, message + "\n")
        self.log.see(tk.END)
        self.log.configure(state="disabled")

    def apply_results(self, users: list[dict], message: str) -> None:
        """แสดงผลลัพธ์ใหม่บนหน้าต่างหลัง worker ทำงานเสร็จ"""
        self.users = users
        self.listbox.delete(0, tk.END)
        for index, user in enumerate(users, 1):
            self.listbox.insert(tk.END, f"{index:>4}. @{user['username']}  {user['full_name']}")
        self.amount.set(str(len(users)))
        self.status.set(message)
        self.write_log(message)

    def start_update(self) -> None:
        """เริ่มดึงข้อมูลใหม่ของ account ที่กรอกไว้ โดยไม่เริ่มลบฟอล"""
        if self.busy:
            return
        account = self.username.get().strip()
        password = self.password.get()
        if not account or not password:
            messagebox.showwarning("ข้อมูลไม่ครบ", "การอัพเดทต้องกรอก username และ password")
            return
        try:
            threshold_value = int(self.threshold.get().strip())
        except ValueError:
            messagebox.showwarning("ค่า follower ไม่ถูกต้อง", "กรุณาใส่ตัวเลข หรือ 0 เพื่อไม่กรอง")
            return
        if threshold_value < 0:
            messagebox.showwarning("ค่า follower ไม่ถูกต้อง", "ค่าต้องไม่ติดลบ")
            return

        self.busy = True
        self.stop_requested = False
        self.stop_event.clear()
        self.status.set("กำลังอัพเดทข้อมูล...")
        self.set_controls_enabled(False)
        self.show_progress("กำลังอัพเดทข้อมูล", 0)
        threading.Thread(
            target=self.run_update,
            args=(account, password, threshold_value or None),
            daemon=True,
        ).start()

    def run_update(self, account: str, password: str, threshold: int | None) -> None:
        try:
            self.log_queue.put("กำลัง login และดึงข้อมูล account ปัจจุบัน...")
            self.update_progress("กำลัง login...", "กำลังตรวจสอบ session")
            client = check_unfollowers.get_client(account, password)
            user_id = client.user_id
            self.update_progress("กำลังดึง Following...", "อาจใช้เวลาสักครู่")
            following = client.user_following(user_id)
            if self.stop_event.wait(2):
                self.log_queue.put("หยุดการอัพเดทแล้ว")
                return
            followers = client.user_followers(user_id)
            if self.stop_event.is_set():
                self.log_queue.put("หยุดการอัพเดทแล้ว")
                return

            filtered_ids = check_unfollowers.filter_not_following_back(
                client, following, followers, threshold
            )
            self.update_progress("กำลังจัดทำรายการ...", f"พบ {len(filtered_ids):,} บัญชี")
            result = []
            for uid in sorted(filtered_ids, key=lambda item: following[item].username.lower()):
                info = following[uid]
                result.append({
                    "user_id": uid,
                    "username": info.username,
                    "full_name": info.full_name,
                })
            check_unfollowers.RESULT_FILE.write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            self.root.after(0, lambda: self.apply_results(
                result, f"อัพเดทแล้ว {len(result):,} บัญชี"
            ))
        except Exception as error:
            self.log_queue.put(f"อัพเดทไม่สำเร็จ: {error}")
        finally:
            self.root.after(0, self.finish_action)

    def process_logs(self) -> None:
        while True:
            try:
                self.write_log(self.log_queue.get_nowait())
            except queue.Empty:
                break
        self.root.after(100, self.process_logs)

    def start(self) -> None:
        if self.busy:
            return
        if not self.users:
            messagebox.showwarning("ยังไม่มีข้อมูล", "กรุณาวาง not_following_back.json แล้วกดโหลดใหม่")
            return
        if not self.username.get().strip():
            messagebox.showwarning("ข้อมูลไม่ครบ", "กรุณากรอก username")
            return
        if self.action.get() == "U" and not self.password.get():
            messagebox.showwarning("ข้อมูลไม่ครบ", "โหมด U ต้องกรอก password")
            return
        try:
            count = int(self.amount.get())
        except ValueError:
            messagebox.showwarning("จำนวนไม่ถูกต้อง", "จำนวนต้องเป็นตัวเลข")
            return
        if not 1 <= count <= len(self.users):
            messagebox.showwarning("จำนวนไม่ถูกต้อง", f"กรุณาใส่จำนวนระหว่าง 1 ถึง {len(self.users)}")
            return
        if self.action.get() == "U" and not messagebox.askyesno(
            "ยืนยันการลบฟอล", f"จะลบฟอล {count} บัญชี ต้องการดำเนินการต่อหรือไม่?"
        ):
            return

        selected = self.users[:count]
        account = self.username.get().strip()
        password = self.password.get()
        action = self.action.get()
        delay_enabled = self.delay_enabled.get()
        self.busy = True
        self.stop_requested = False
        self.stop_event.clear()
        self.status.set("กำลังทำงาน...")
        self.set_controls_enabled(False)
        self.show_progress(
            "กำลังดำเนินการ",
            f"เตรียมจัดการ {len(selected):,} บัญชี",
            len(selected),
        )
        threading.Thread(
            target=self.run_action,
            args=(account, password, action, delay_enabled, selected),
            daemon=True,
        ).start()

    def stop(self) -> None:
        """ขอหยุดงานอย่างปลอดภัย โดยไม่เริ่มคำสั่งลบรายการถัดไป"""
        if self.busy:
            self.stop_requested = True
            self.stop_event.set()
            self.status.set("กำลังหยุดการทำงาน...")
            self.write_log("ขอหยุดการทำงานแล้ว จะหยุดก่อนรายการถัดไป")

    def show_progress(self, title: str, detail: str, maximum: int = 0) -> None:
        """สร้างหน้าต่างสถานะที่ไม่บังหน้าต่างหลักและมีปุ่มหยุดแยก"""
        window = tk.Toplevel(self.root)
        self.progress_window = window
        window.title(title)
        window.geometry("440x190")
        window.resizable(False, False)
        window.transient(self.root)
        window.protocol("WM_DELETE_WINDOW", self.stop)

        frame = ttk.Frame(window, padding=18)
        frame.pack(fill="both", expand=True)
        self.progress_text = tk.StringVar(value=title)
        self.progress_detail = tk.StringVar(value=detail)
        ttk.Label(frame, textvariable=self.progress_text, font=("TkDefaultFont", 13, "bold")).pack(anchor="w")
        ttk.Label(frame, textvariable=self.progress_detail).pack(anchor="w", pady=(8, 12))
        self.progress_bar = ttk.Progressbar(frame, mode="indeterminate" if maximum == 0 else "determinate")
        if maximum:
            self.progress_bar.configure(maximum=maximum, value=0)
        else:
            self.progress_bar.start(12)
        self.progress_bar.pack(fill="x")
        self.progress_stop_button = ttk.Button(frame, text="หยุดการทำงาน", command=self.stop)
        self.progress_stop_button.pack(anchor="e", pady=(16, 0))

    def update_progress(self, title: str, detail: str) -> None:
        """อัปเดตข้อความผ่านคิวของ Tkinter เพื่อไม่ให้ worker แตะ widget โดยตรง"""
        self.root.after(0, lambda: self._update_progress(title, detail))

    def _update_progress(self, title: str, detail: str) -> None:
        if self.progress_text is not None:
            self.progress_text.set(title)
        if self.progress_detail is not None:
            self.progress_detail.set(detail)

    def close_progress(self) -> None:
        if self.progress_bar is not None and self.progress_bar.cget("mode") == "indeterminate":
            self.progress_bar.stop()
        if self.progress_window is not None and self.progress_window.winfo_exists():
            self.progress_window.destroy()
        self.progress_window = None
        self.progress_text = None
        self.progress_detail = None
        self.progress_bar = None
        self.progress_stop_button = None

    def run_action(
        self,
        account: str,
        password: str,
        action: str,
        delay_enabled: bool,
        selected: list[dict],
    ) -> None:
        try:
            if action == "F":
                check_unfollowers.save_to_unfollow_queue(account, selected)
                self.log_queue.put(f"F: เก็บข้อมูล {len(selected)} บัญชีลงฐานข้อมูลแล้ว")
                return

            self.log_queue.put("กำลัง login เพื่อดำเนินการ U...")
            client = check_unfollowers.get_client(account, password)
            success = 0
            for index, user in enumerate(selected, 1):
                if self.stop_event.is_set():
                    self.log_queue.put("หยุดแล้วก่อนดำเนินการรายการถัดไป")
                    break
                try:
                    self.update_progress(
                        f"กำลังลบ {index}/{len(selected)}",
                        f"@{user['username']}",
                    )
                    client.user_unfollow(user["user_id"])
                    success += 1
                    self.log_queue.put(f"U: ลบ @{user['username']} แล้ว ({index}/{len(selected)})")
                except Exception as error:
                    self.log_queue.put(f"ลบ @{user['username']} ไม่สำเร็จ: {error}")
                if delay_enabled and index < len(selected):
                    delay = random.randint(30, 120)
                    self.log_queue.put(f"รอ {delay} วินาที...")
                    self.update_progress("กำลังหน่วงเวลา", f"รอ {delay} วินาทีก่อนรายการถัดไป")
                    if self.stop_event.wait(delay):
                        self.log_queue.put("หยุดระหว่างช่วงหน่วงเวลาแล้ว")
                        break
            self.log_queue.put(f"เสร็จแล้ว: ลบสำเร็จ {success}/{len(selected)} บัญชี")
        except Exception as error:
            self.log_queue.put(f"เกิดข้อผิดพลาด: {error}")
        finally:
            self.root.after(0, self.finish_action)

    def set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for child in self.root.winfo_children():
            self.set_widget_state(child, state)
        self.stop_button.configure(state="normal" if self.busy else "disabled")

    def set_widget_state(self, widget: tk.Widget, state: str) -> None:
        try:
            widget.configure(state=state)
        except tk.TclError:
            pass
        for child in widget.winfo_children():
            self.set_widget_state(child, state)

    def finish_action(self) -> None:
        self.busy = False
        self.close_progress()
        self.status.set("หยุดแล้ว" if self.stop_requested else "ทำงานเสร็จแล้ว")
        self.set_controls_enabled(True)


if __name__ == "__main__":
    root = tk.Tk()
    UnfollowApp(root)
    root.mainloop()
