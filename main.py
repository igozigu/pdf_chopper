"""
PDF Chopper - 북마크 기반 PDF 자동 분할 프로그램
메인 진입점 (main.py)
"""

import sys
import tkinter as tk

try:
    import tkinterdnd2 as tkdnd
    HAS_DND = True
except ImportError:
    HAS_DND = False

from src.gui import PDFChopperApp


def main():
    if HAS_DND:
        root = tkdnd.Tk()
    else:
        root = tk.Tk()

    # 창 화면 중앙 배치
    root.update_idletasks()
    width = 720
    height = 740
    x = (root.winfo_screenwidth() // 2) - (width // 2)
    y = (root.winfo_screenheight() // 2) - (height // 2)
    root.geometry(f"{width}x{height}+{x}+{y}")

    app = PDFChopperApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
