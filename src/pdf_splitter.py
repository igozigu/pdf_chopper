"""
PDF 북마크 기반 자동 분할 핵심 모듈 (pdf_splitter.py)
"""

import os
import re
import unicodedata
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple
import pymupdf


class PDFChopperError(Exception):
    """PDF 분할 관련 기본 예외"""
    pass


class EncryptedPDFError(PDFChopperError):
    """암호화된 PDF 예외"""
    pass


class NoBookmarksError(PDFChopperError):
    """북마크가 존재하지 않는 PDF 예외"""
    pass


class CorruptedPDFError(PDFChopperError):
    """손상되었거나 열 수 없는 PDF 예외"""
    pass


@dataclass
class PDFInfo:
    """PDF 메타데이터 및 북마크 정보"""
    file_path: str
    file_name: str
    file_size_bytes: int
    file_size_str: str
    page_count: int
    is_encrypted: bool
    has_bookmarks: bool
    toc: List[list]  # [[lvl, title, page], ...]
    max_level: int


@dataclass
class SplitRange:
    """분할 대상 페이지 범위 정보"""
    seq: int
    level: int
    title: str
    start_page: int  # 1-based
    end_page: int    # 1-based
    page_count: int


def format_file_size(size_bytes: int) -> str:
    """파일 크기를 읽기 쉬운 문자열(KB, MB 등)로 변환"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def sanitize_filename(name: str, max_length: int = 100) -> str:
    """
    윈도우 파일명에 사용할 수 없는 특수문자를 밑줄(_)로 치환하고
    유효한 파일명 문자열로 정제
    금지 문자: \\ / : * ? " < > |
    """
    if not name:
        return "section"

    # 유니코드 정규화 (NFC)
    name = unicodedata.normalize("NFC", name)

    # 윈도우 파일명 금지 문자 및 제어문자 치환
    cleaned = re.sub(r'[\\/*?:"<>|\r\n\t]', "_", name)

    # _와 공백이 섞인 연속된 패턴(_ _, _ 등)을 단일 밑줄로 정리
    cleaned = re.sub(r'[\s_]*_[\s_]*', "_", cleaned)

    # 남은 연속 공백 정리
    cleaned = re.sub(r'\s+', " ", cleaned)

    # 앞뒤 공백, 점, 밑줄 제거
    cleaned = cleaned.strip(" ._")

    if not cleaned:
        cleaned = "section"

    # 파일명 길이 제한 (확장자 고려)
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip(" ._")

    return cleaned


def get_pdf_info(pdf_path: str) -> PDFInfo:
    """
    PDF 파일을 열어 암호화 여부, 페이지 수, 북마크(TOC) 정보를 추출
    """
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {pdf_path}")

    file_size = os.path.getsize(pdf_path)
    file_name = os.path.basename(pdf_path)

    try:
        doc = pymupdf.open(pdf_path)
    except Exception as e:
        raise CorruptedPDFError(f"PDF 파일을 열 수 없습니다: {str(e)}") from e

    try:
        if doc.is_encrypted:
            # 빈 암호로 시도
            if not doc.authenticate(""):
                raise EncryptedPDFError("암호로 보호되어 있는 PDF 파일입니다. 암호를 해제한 후 다시 시도해 주세요.")

        page_count = len(doc)
        if page_count == 0:
            raise CorruptedPDFError("PDF 파일에 페이지가 없습니다.")

        toc = doc.get_toc()  # [[lvl, title, page, ...], ...]
        has_bookmarks = len(toc) > 0

        max_lvl = 0
        if has_bookmarks:
            max_lvl = max(item[0] for item in toc)

        return PDFInfo(
            file_path=pdf_path,
            file_name=file_name,
            file_size_bytes=file_size,
            file_size_str=format_file_size(file_size),
            page_count=page_count,
            is_encrypted=doc.is_encrypted,
            has_bookmarks=has_bookmarks,
            toc=toc,
            max_level=max_lvl,
        )
    finally:
        doc.close()


def calculate_split_ranges(
    toc: List[list],
    total_pages: int,
    max_level: int = 1,
    include_prefix_pages: bool = True
) -> List[SplitRange]:
    """
    북마크 목록(TOC)을 바탕으로 분할할 페이지 범위를 계산.
    - max_level: 분할 대상 북마크 최대 깊이 (기본: 1단계 최상위)
    - include_prefix_pages: 첫 북마크가 1페이지 이후에 시작될 때 앞부분을 00_앞부속으로 포함할지 여부
    """
    if not toc:
        raise NoBookmarksError("이 PDF에는 북마크(목차)가 없어 분할할 수 없습니다.")

    # 지정 레벨 이하의 북마크만 필터링
    filtered = [item for item in toc if item[0] <= max_level]

    if not filtered:
        raise NoBookmarksError(f"선택한 레벨({max_level}단계 이하)에 해당하는 북마크가 없습니다.")

    # 페이지 번호가 유효하지 않은 항목 보정 (1 ~ total_pages)
    valid_items = []
    for lvl, title, page in filtered:
        clean_title = title.strip() if title else f"Level_{lvl}"
        p = max(1, min(int(page), total_pages))
        valid_items.append((lvl, clean_title, p))

    ranges: List[SplitRange] = []
    seq = 1

    # 첫 북마크 시작 페이지가 1보다 큰 경우, 앞부분 보존 처리
    first_page = valid_items[0][2]
    if include_prefix_pages and first_page > 1:
        ranges.append(SplitRange(
            seq=0,
            level=1,
            title="시작부속",
            start_page=1,
            end_page=first_page - 1,
            page_count=first_page - 1
        ))

    num_items = len(valid_items)
    for i in range(num_items):
        lvl, title, start_p = valid_items[i]

        if i + 1 < num_items:
            next_start_p = valid_items[i + 1][2]
            if next_start_p > start_p:
                end_p = next_start_p - 1
            else:
                # 같은 페이지에 여러 북마크가 있는 경우 등
                end_p = start_p
        else:
            # 마지막 북마크는 문서 끝까지
            end_p = total_pages

        # 시작 페이지가 이전 항목보다 앞서거나 비정상적인 경우 보정
        if end_p < start_p:
            end_p = start_p

        ranges.append(SplitRange(
            seq=seq,
            level=lvl,
            title=title,
            start_page=start_p,
            end_page=end_p,
            page_count=(end_p - start_p + 1)
        ))
        seq += 1

    return ranges


def get_unique_output_dir(parent_dir: str, base_name: str) -> str:
    """
    원본 PDF와 동일한 이름의 하위 폴더 경로 생성.
    이미 존재하며 비어있지 않은 경우 '폴더명 (1)', '폴더명 (2)' 등으로 고유 폴더 생성.
    """
    target = os.path.join(parent_dir, base_name)
    if not os.path.exists(target):
        return target

    # 폴더가 비어있다면 그대로 사용
    try:
        if os.path.isdir(target) and len(os.listdir(target)) == 0:
            return target
    except OSError:
        pass

    # 중복 시 번호 추가
    counter = 1
    while True:
        cand = os.path.join(parent_dir, f"{base_name} ({counter})")
        if not os.path.exists(cand):
            return cand
        try:
            if os.path.isdir(cand) and len(os.listdir(cand)) == 0:
                return cand
        except OSError:
            pass
        counter += 1


def split_pdf(
    pdf_path: str,
    ranges: List[SplitRange],
    output_dir: Optional[str] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None
) -> Tuple[str, List[str]]:
    """
    지정된 페이지 범위에 따라 PDF를 분할하여 파일로 저장.
    - pdf_path: 원본 PDF 경로
    - ranges: SplitRange 목록
    - output_dir: 저장할 폴더 (None일 경우 원본 경로에 원본 파일명 폴더 자동 생성)
    - progress_callback: (현재작업인덱스, 전체개수, 저장된파일명) 콜백
    반환값: (출력 폴더 경로, 생성된 파일 경로 목록)
    """
    if not ranges:
        raise ValueError("분할할 범위 목록이 비어 있습니다.")

    src_dir = os.path.dirname(os.path.abspath(pdf_path))
    file_stem = os.path.splitext(os.path.basename(pdf_path))[0]

    if output_dir is None:
        sanitized_stem = sanitize_filename(file_stem, max_length=60)
        output_dir = get_unique_output_dir(src_dir, sanitized_stem)

    os.makedirs(output_dir, exist_ok=True)

    src_doc = pymupdf.open(pdf_path)
    created_files: List[str] = []
    total_count = len(ranges)

    try:
        # 파일명 중복 방지를 위한 집합
        used_filenames = set()

        for idx, r in enumerate(ranges, start=1):
            clean_title = sanitize_filename(r.title, max_length=60)
            base_fname = f"{r.seq:02d}_{clean_title}.pdf"

            # 동일 번호/제목 충돌 방지
            fname = base_fname
            counter = 1
            while fname.lower() in used_filenames:
                fname = f"{r.seq:02d}_{clean_title}_{counter}.pdf"
                counter += 1
            used_filenames.add(fname.lower())

            out_path = os.path.join(output_dir, fname)

            # 새 문서 생성 후 해당 범위 페이지만 복사
            new_doc = pymupdf.open()
            # PyMuPDF insert_pdf는 0-based index [from_page, to_page]
            new_doc.insert_pdf(
                src_doc,
                from_page=r.start_page - 1,
                to_page=r.end_page - 1
            )
            new_doc.save(out_path)
            new_doc.close()

            created_files.append(out_path)

            if progress_callback:
                progress_callback(idx, total_count, fname)

    finally:
        src_doc.close()

    return output_dir, created_files
