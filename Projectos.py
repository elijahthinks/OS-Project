import tkinter as tk
from tkinter import simpledialog, messagebox, filedialog, scrolledtext
import cv2
import threading
from PIL import Image, ImageTk
import os

# ==== Main OS Class ====
class PythonOS:
    def __init__(self, root):
        self.root = root
        self.root.title("Python OS Prototype")
        self.root.geometry("800x600")

        self.dark_mode = False
        self.create_desktop()

    def create_desktop(self):
        self.desktop_frame = tk.Frame(self.root)
        self.desktop_frame.pack(expand=True, fill="both")

        apps = [
            ("File Explorer", self.open_file_explorer),
            ("Camera", self.open_camera),
            ("Messaging", self.open_messaging),
            ("Notes", self.open_notes),
            ("Settings", self.open_settings)
        ]

        for i, (label, cmd) in enumerate(apps):
            b = tk.Button(self.desktop_frame, text=label, width=20, height=2, command=cmd)
            b.grid(row=i // 2, column=i % 2, padx=20, pady=20)

    # ==== File Explorer ====
    def open_file_explorer(self):
        filedialog.askopenfilename(title="Browse Files")

    # ==== Camera ====
    def open_camera(self):
        cam_win = tk.Toplevel(self.root)
        cam_win.title("Camera")

        l = tk.Label(cam_win)
        l.pack()

        cap = cv2.VideoCapture(0)

        def show_frame():
            ret, frame = cap.read()
            if ret:
                cv2image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGBA)
                img = Image.fromarray(cv2image)
                imgtk = ImageTk.PhotoImage(image=img)
                l.imgtk = imgtk
                l.configure(image=imgtk)
            l.after(10, show_frame)

        show_frame()
        cam_win.protocol("WM_DELETE_WINDOW", lambda: [cap.release(), cam_win.destroy()])

    # ==== Messaging App ====
    def open_messaging(self):
        msg_win = tk.Toplevel(self.root)
        msg_win.title("Messenger")

        chat_box = scrolledtext.ScrolledText(msg_win, width=50, height=20)
        chat_box.pack(pady=5)
        chat_box.config(state="disabled")

        entry = tk.Entry(msg_win, width=40)
        entry.pack(side="left", padx=5)

        def send():
            text = entry.get()
            if text:
                chat_box.config(state="normal")
                chat_box.insert(tk.END, "You: " + text + "\n")
                chat_box.config(state="disabled")
                entry.delete(0, tk.END)

        tk.Button(msg_win, text="Send", command=send).pack(side="left")

    # ==== Notes App ====
    def open_notes(self):
        note_win = tk.Toplevel(self.root)
        note_win.title("Notes")
        text_area = scrolledtext.ScrolledText(note_win, width=60, height=25)
        text_area.pack()

        def save_note():
            content = text_area.get("1.0", tk.END)
            with open("note.txt", "w") as f:
                f.write(content)
            messagebox.showinfo("Saved", "Note saved to note.txt")

        tk.Button(note_win, text="Save", command=save_note).pack()

    # ==== Settings App ====
    def open_settings(self):
        settings_win = tk.Toplevel(self.root)
        settings_win.title("Settings")

        def toggle_theme():
            self.dark_mode = not self.dark_mode
            bg = "black" if self.dark_mode else "SystemButtonFace"
            fg = "white" if self.dark_mode else "black"
            self.desktop_frame.configure(bg=bg)
            for widget in self.desktop_frame.winfo_children():
                widget.configure(bg=bg, fg=fg)

        tk.Button(settings_win, text="Toggle Dark Mode", command=toggle_theme).pack(pady=10)

# ==== Run OS ====
if __name__ == '__main__':
    root = tk.Tk()
    os_app = PythonOS(root)
    root.mainloop()
