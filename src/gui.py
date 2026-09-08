"""
PDF Chopper GUI 모듈 (gui.py)
Tkinter 및 TkinterDnD2 기반의 드래그 앤 드롭 지원 GUI
"""

import os
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from typing import Optional, List

try:
    import tkinterdnd2 as tkdnd
    HAS_DND = True
except ImportError:
    HAS_DND = False

from src.pdf_splitter import (
    get_pdf_info,
    calculate_split_ranges,
    split_pdf,
    PDFInfo,
    SplitRange,
    PDFChopperError,
    EncryptedPDFError,
    NoBookmarksError,
    CorruptedPDFError,
)


class PDFChopperApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("PDF Chopper - 북마크 기반 PDF 자동 분할기")
        self.root.geometry("680x680")
        self.root.minsize(580, 580)

        # 시스템 기본 폰트 설정
        self.default_font = ("Malgun Gothic", 9)
        self.title_font = ("Malgun Gothic", 10, "bold")
        self.big_font = ("Malgun Gothic", 11, "bold")

        # 상태 변수
        self.current_pdf_info: Optional[PDFInfo] = None
        self.current_ranges: List[SplitRange] = []
        self.is_processing = False
        self.last_output_dir: Optional[str] = None

        # 테마 및 스타일 설정
        self.setup_styles()

        # UI 위젯 빌드
        self.build_ui()

    def setup_styles(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure(".", font=self.default_font)
        style.configure("Header.TLabel", font=self.big_font, foreground="#1f2937")
        style.configure("SubHeader.TLabel", font=self.title_font, foreground="#374151")
        style.configure("Info.TLabel", font=self.default_font, foreground="#4b5563")

        # 강조 버튼 스타일
        style.configure("Accent.TButton", font=self.title_font, background="#2563eb", foreground="#ffffff")
        style.map("Accent.TButton",
                  background=[("active", "#1d4ed8"), ("disabled", "#9ca3af")],
                  foreground=[("disabled", "#f3f4f6")])

        # 일반/보조 버튼 스타일
        style.configure("Action.TButton", font=self.default_font)
        style.configure("Treeview.Heading", font=self.title_font)
        style.configure("Treeview", font=self.default_font, rowheight=24)

    def build_ui(self):
        # 최상위 컨테이너 패딩
        main_frame = ttk.Frame(self.root, padding="16 12 16 16")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 1. 상단 드래그 앤 드롭 영역
        self.drop_frame = tk.Frame(
            main_frame,
            bg="#f8fafc",
            highlightbackground="#cbd5e1",
            highlightcolor="#3b82f6",
            highlightthickness=2,
            bd=0,
            cursor="hand2"
        )
        self.drop_frame.pack(fill=tk.X, pady=(0, 10), ipady=16)

        # 드래그앤드롭 이벤트 등록 (TkinterDnD 지원 시)
        if HAS_DND and hasattr(self.drop_frame, "drop_target_register"):
            self.drop_frame.drop_target_register(tkdnd.DND_FILES)
            self.drop_frame.dnd_bind("<<Drop>>", self.on_file_drop)
            drop_text = "여기로 PDF 파일을 드래그 앤 드롭하세요"
        else:
            drop_text = "아래 '파일 선택' 버튼을 클릭하여 PDF 파일을 선택하세요"

        self.drop_label = tk.Label(
            self.drop_frame,
            text=f"📂 {drop_text}",
            font=("Malgun Gothic", 11, "bold"),
            bg="#f8fafc",
            fg="#2563eb"
        )
        self.drop_label.pack(pady=(6, 4))

        self.drop_sublabel = tk.Label(
            self.drop_frame,
            text="북마크(목차)가 포함된 PDF 파일을 올리면 자동으로 분할 항목을 분석합니다.",
            font=("Malgun Gothic", 9),
            bg="#f8fafc",
            fg="#64748b"
        )
        self.drop_sublabel.pack(pady=(0, 8))

        browse_btn = ttk.Button(self.drop_frame, text="파일 선택 (탐색기)", command=self.on_browse_file)
        browse_btn.pack()

        # 클릭 이벤트로도 파일 선택 가능하게 연결
        self.drop_frame.bind("<Button-1>", lambda e: self.on_browse_file())
        self.drop_label.bind("<Button-1>", lambda e: self.on_browse_file())
        self.drop_sublabel.bind("<Button-1>", lambda e: self.on_browse_file())

        # 2. 파일 정보 및 분할 옵션 영역
        info_frame = ttk.LabelFrame(main_frame, text=" 업로드 파일 정보 & 분할 설정 ", padding="10 8 10 8")
        info_frame.pack(fill=tk.X, pady=(0, 10))

        grid_frame = ttk.Frame(info_frame)
        grid_frame.pack(fill=tk.X)

        # 파일명
        ttk.Label(grid_frame, text="파일명:", font=self.title_font).grid(row=0, column=0, sticky="w", padx=(0, 8), pady=2)
        self.lbl_filename = ttk.Label(grid_frame, text="선택된 파일 없음", foreground="#6b7280")
        self.lbl_filename.grid(row=0, column=1, sticky="w", pady=2, columnspan=3)

        # 페이지 수 / 파일 크기 / 북마크 수
        ttk.Label(grid_frame, text="파일 정보:", font=self.title_font).grid(row=1, column=0, sticky="w", padx=(0, 8), pady=2)
        self.lbl_file_detail = ttk.Label(grid_frame, text="-", foreground="#6b7280")
        self.lbl_file_detail.grid(row=1, column=1, sticky="w", pady=2, columnspan=3)

        # 분할 레벨 설정
        ttk.Label(grid_frame, text="분할 기준:", font=self.title_font).grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)
        self.combo_level = ttk.Combobox(
            grid_frame,
            values=["1단계 (최상위 목차만)", "1~2단계 목차까지", "모든 목차 레벨"],
            state="readonly",
            width=22
        )
        self.combo_level.current(0)
        self.combo_level.bind("<<ComboboxSelected>>", self.on_level_changed)
        self.combo_level.grid(row=2, column=1, sticky="w", pady=4)

        # 시작 앞부속 포함 체크박스
        self.var_prefix = tk.BooleanVar(value=True)
        self.chk_prefix = ttk.Checkbutton(
            grid_frame,
            text="첫 목차 이전 페이지 포함 (00_시작부속)",
            variable=self.var_prefix,
            command=self.update_ranges
        )
        self.chk_prefix.grid(row=2, column=2, sticky="w", padx=(16, 0), pady=4)

        # 3. 북마크 분할 미리보기 (트리뷰)
        preview_frame = ttk.LabelFrame(main_frame, text=" 분할 대상 북마크 목록 미리보기 ", padding="8")
        preview_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # 트리뷰 및 스크롤바
        tree_container = ttk.Frame(preview_frame)
        tree_container.pack(fill=tk.BOTH, expand=True)

        columns = ("seq", "level", "title", "pages", "page_count")
        self.tree = ttk.Treeview(tree_container, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("seq", text="순번")
        self.tree.heading("level", text="레벨")
        self.tree.heading("title", text="북마크 제목 (생성될 파일명)")
        self.tree.heading("pages", text="페이지 범위")
        self.tree.heading("page_count", text="매수")

        self.tree.column("seq", width=45, anchor="center")
        self.tree.column("level", width=45, anchor="center")
        self.tree.column("title", width=340, anchor="w")
        self.tree.column("pages", width=95, anchor="center")
        self.tree.column("page_count", width=55, anchor="center")

        tree_scroll = ttk.Scrollbar(tree_container, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # 4. 진행 상태 표시 (프로그레스바 및 상태 라벨)
        progress_frame = ttk.Frame(main_frame)
        progress_frame.pack(fill=tk.X, pady=(0, 10))

        self.lbl_status = ttk.Label(progress_frame, text="PDF 파일을 선택하거나 드래그하여 올려주세요.")
        self.lbl_status.pack(anchor="w", pady=(0, 4))

        self.progress_bar = ttk.Progressbar(progress_frame, orient="horizontal", mode="determinate")
        self.progress_bar.pack(fill=tk.X)

        # 5. 하단 액션 버튼 영역
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X)

        self.btn_start = ttk.Button(
            btn_frame,
            text="▶ 작업 시작 (PDF 분할)",
            style="Accent.TButton",
            command=self.on_start_split,
            state="disabled"
        )
        self.btn_start.pack(side=tk.LEFT, padx=(0, 8), ipady=4)

        self.btn_reset = ttk.Button(
            btn_frame,
            text="취소 / 초기화",
            command=self.reset_ui
        )
        self.btn_reset.pack(side=tk.LEFT, padx=(0, 8), ipady=4)

        self.btn_open_folder = ttk.Button(
            btn_frame,
            text="📁 결과 폴더 열기",
            command=self.on_open_folder,
            state="disabled"
        )
        self.btn_open_folder.pack(side=tk.RIGHT, ipady=4)

    def on_file_drop(self, event):
        """드래그 앤 드롭 파일 수신 처리"""
        if self.is_processing:
            return

        raw_data = event.data
        if not raw_data:
            return

        # TkinterDnD의 공백 포함 경로 중괄호({}) 처리
        try:
            files = self.root.tk.splitlist(raw_data)
        except Exception:
            files = [raw_data]

        if not files:
            return

        target_file = files[0].strip('{}').strip()
        if not target_file.lower().endswith(".pdf"):
            messagebox.showwarning("지원하지 않는 파일", "PDF 파일(.pdf)만 업로드할 수 있습니다.")
            return

        self.load_pdf(target_file)

    def on_browse_file(self):
        """파일 탐색기를 통한 PDF 선택 처리"""
        if self.is_processing:
            return

        file_path = filedialog.askopenfilename(
            title="분할할 PDF 파일을 선택하세요",
            filetypes=[("PDF 파일", "*.pdf"), ("모든 파일", "*.*")]
        )
        if file_path:
            self.load_pdf(file_path)

    def load_pdf(self, pdf_path: str):
        """PDF 파일 검증 및 북마크 로드"""
        self.btn_open_folder.config(state="disabled")
        self.last_output_dir = None

        try:
            info = get_pdf_info(pdf_path)
            self.current_pdf_info = info

            # 북마크 유무 확인
            if not info.has_bookmarks:
                self.reset_ui()
                messagebox.showwarning(
                    "북마크 없음",
                    f"선택한 PDF 파일({info.file_name})에는 북마크(목차)가 존재하지 않아 분할할 수 없습니다."
                )
                return

            # 파일 정보 표시
            self.lbl_filename.config(text=info.file_name, foreground="#111827")
            self.lbl_file_detail.config(
                text=f"전체 {info.page_count}페이지 | 크기: {info.file_size_str} | 감지된 북마크: {len(info.toc)}개 (최대 {info.max_level}단계)",
                foreground="#374151"
            )

            # 분할 범위 계산 및 트리뷰 갱신
            self.update_ranges()

            self.lbl_status.config(
                text=f"분할 준비 완료: 총 {len(self.current_ranges)}개의 분할 파일이 생성될 예정입니다. '작업 시작'을 눌러주세요."
            )
            self.btn_start.config(state="normal")

        except EncryptedPDFError as e:
            self.reset_ui()
            messagebox.showerror("암호화된 PDF", str(e))
        except CorruptedPDFError as e:
            self.reset_ui()
            messagebox.showerror("파일 오류", str(e))
        except Exception as e:
            self.reset_ui()
            messagebox.showerror("오류 발생", f"PDF를 불러오는 중 오류가 발생했습니다:\n{str(e)}")

    def get_selected_max_level(self) -> int:
        """선택된 콤보박스 기준 최대 분할 레벨 반환"""
        idx = self.combo_level.current()
        if idx == 0:
            return 1
        elif idx == 1:
            return 2
        else:
            return 999  # 모든 레벨

    def on_level_changed(self, event=None):
        """분할 레벨 변경 시 범위 재계산"""
        if self.current_pdf_info:
            self.update_ranges()

    def update_ranges(self):
        """현재 선택된 조건에 따라 분할 범위 재계산 및 트리뷰 갱신"""
        if not self.current_pdf_info:
            return

        max_lvl = self.get_selected_max_level()
        include_prefix = self.var_prefix.get()

        try:
            ranges = calculate_split_ranges(
                self.current_pdf_info.toc,
                total_pages=self.current_pdf_info.page_count,
                max_level=max_lvl,
                include_prefix_pages=include_prefix
            )
            self.current_ranges = ranges

            # 트리뷰 비우고 새로 채우기
            for item in self.tree.get_children():
                self.tree.delete(item)

            for r in ranges:
                self.tree.insert(
                    "",
                    "end",
                    values=(
                        f"{r.seq:02d}",
                        f"L{r.level}",
                        r.title,
                        f"p.{r.start_page} ~ {r.end_page}",
                        f"{r.page_count}장"
                    )
                )

            self.lbl_status.config(
                text=f"분할 예정 파일: {len(ranges)}개 | 시작 버튼을 누르면 원본 폴더에 분할 저장됩니다."
            )
            self.btn_start.config(state="normal" if ranges else "disabled")

        except NoBookmarksError as e:
            for item in self.tree.get_children():
                self.tree.delete(item)
            self.current_ranges = []
            self.lbl_status.config(text=str(e))
            self.btn_start.config(state="disabled")

    def on_start_split(self):
        """분할 작업 시작 (별도 스레드에서 실행하여 GUI 멈춤 방지)"""
        if not self.current_pdf_info or not self.current_ranges or self.is_processing:
            return

        self.is_processing = True
        self.btn_start.config(state="disabled")
        self.btn_reset.config(state="disabled")
        self.btn_open_folder.config(state="disabled")
        self.progress_bar["maximum"] = len(self.current_ranges)
        self.progress_bar["value"] = 0

        # 백그라운드 스레드 가동
        thread = threading.Thread(target=self._split_worker, daemon=True)
        thread.start()

    def _split_worker(self):
        """백그라운드에서 실제 분할 작업 수행"""
        pdf_path = self.current_pdf_info.file_path
        ranges = list(self.current_ranges)

        def progress_cb(current, total, filename):
            self.root.after(0, self._update_progress, current, total, filename)

        try:
            out_dir, created_files = split_pdf(
                pdf_path=pdf_path,
                ranges=ranges,
                output_dir=None,
                progress_callback=progress_cb
            )
            self.last_output_dir = out_dir
            self.root.after(0, self._on_split_success, out_dir, len(created_files))
        except Exception as e:
            self.root.after(0, self._on_split_error, str(e))

    def _update_progress(self, current: int, total: int, filename: str):
        """메인 스레드에서 프로그레스바 및 상태 레이블 업데이트"""
        self.progress_bar["value"] = current
        self.lbl_status.config(text=f"분할 중 ({current}/{total}): {filename}")

    def _on_split_success(self, output_dir: str, file_count: int):
        """분할 완료 처리"""
        self.is_processing = False
        self.btn_reset.config(state="normal")
        self.btn_open_folder.config(state="normal")
        self.lbl_status.config(text=f"✔ 분할 완료! 총 {file_count}개의 파일이 생성되었습니다.")

        # 사용자 완료 팝업
        msg = (
            f"PDF 분할이 성공적으로 완료되었습니다!\n\n"
            f"• 분할된 파일 개수: {file_count}개\n"
            f"• 저장 폴더:\n{output_dir}\n\n"
            f"지금 바로 결과 폴더를 여시겠습니까?"
        )
        if messagebox.askyesno("분할 완료", msg):
            self.on_open_folder()

    def _on_split_error(self, error_msg: str):
        """분할 중 오류 발생 처리"""
        self.is_processing = False
        self.btn_start.config(state="normal")
        self.btn_reset.config(state="normal")
        self.lbl_status.config(text="분할 실패")
        messagebox.showerror("분할 오류", f"PDF 분할 중 오류가 발생했습니다:\n{error_msg}")

    def on_open_folder(self):
        """저장된 결과 폴더를 윈도우 파일 탐색기로 열기"""
        if self.last_output_dir and os.path.exists(self.last_output_dir):
            try:
                os.startfile(self.last_output_dir)
            except Exception:
                subprocess.Popen(["explorer", self.last_output_dir])

    def reset_ui(self):
        """업로드 상태 및 UI 초기화"""
        if self.is_processing:
            return

        self.current_pdf_info = None
        self.current_ranges = []
        self.last_output_dir = None

        self.lbl_filename.config(text="선택된 파일 없음", foreground="#6b7280")
        self.lbl_file_detail.config(text="-", foreground="#6b7280")

        for item in self.tree.get_children():
            self.tree.delete(item)

        self.progress_bar["value"] = 0
        self.lbl_status.config(text="PDF 파일을 선택하거나 드래그하여 올려주세요.")
        self.btn_start.config(state="disabled")
        self.btn_open_folder.config(state="disabled")
