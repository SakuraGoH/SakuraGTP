import tkinter as tk
from tkinter import filedialog
from PIL import Image, ImageTk

class BackgroundManager:
    def __init__(self, root):
        self.root = root
        self.label = None
        self.image = None
        self.path = ""

    def set_background(self, path):
        if not path:
            return
        try:
            img = Image.open(path)
            img = img.resize((self.root.winfo_width(), self.root.winfo_height()), Image.LANCZOS)
            self.image = ImageTk.PhotoImage(img)
            if self.label is None:
                self.label = tk.Label(self.root, image=self.image)
                self.label.place(x=0, y=0, relwidth=1, relheight=1)
                self.label.lower()
            else:
                self.label.configure(image=self.image)
            self.path = path
        except Exception as e:
            print(f"背景设置失败: {e}")

    def choose_from_gallery(self):
        path = filedialog.askopenfilename(
            title="选择背景图",
            filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp *.gif"), ("所有文件", "*.*")]
        )
        if path:
            self.set_background(path)
        return path