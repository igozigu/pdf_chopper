import os
import shutil
import tempfile
import pytest
import pymupdf

from src.pdf_splitter import (
    sanitize_filename,
    get_pdf_info,
    calculate_split_ranges,
    split_pdf,
    get_unique_output_dir,
    NoBookmarksError,
    EncryptedPDFError,
)


@pytest.fixture
def temp_workspace():
    """임시 작업 디렉토리 생성 및 정리 픽스처"""
    tmp_dir = tempfile.mkdtemp(prefix="pdf_chopper_test_")
    yield tmp_dir
    shutil.rmtree(tmp_dir, ignore_errors=True)


def create_sample_pdf(file_path: str, page_count: int = 5, toc: list = None, password: str = None) -> str:
    """테스트용 샘플 PDF 생성 헬퍼"""
    doc = pymupdf.open()
    for i in range(1, page_count + 1):
        page = doc.new_page()
        page.insert_text((72, 72), f"This is page {i} of {page_count}")

    if toc:
        doc.set_toc(toc)

    if password:
        # PDF 암호화 설정
        doc.save(
            file_path,
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            owner_pw=password,
            user_pw=password,
        )
    else:
        doc.save(file_path)
    doc.close()
    return file_path


def test_sanitize_filename():
    """특수문자 및 공백 처리 파일명 정제 테스트"""
    # 윈도우 금지 문자 치환
    assert sanitize_filename('제1장: 서론/개요? <중요> "test" * | \\') == "제1장_서론_개요_중요_test"
    # 한글 및 정상 문자 유지
    assert sanitize_filename("01_프로젝트 계획서 (최종)") == "01_프로젝트 계획서 (최종)"
    # 빈 문자열 처리
    assert sanitize_filename("") == "section"
    # 앞뒤 공백 및 점 제거
    assert sanitize_filename("  ...file name...  ") == "file name"


def test_pdf_info_normal(temp_workspace):
    """정상 북마크가 있는 PDF 정보 추출 테스트"""
    pdf_path = os.path.join(temp_workspace, "sample_toc.pdf")
    toc = [
        [1, "제1장 서론", 1],
        [2, "1.1 배경", 2],
        [1, "제2장 본론", 3],
        [1, "제3장 결론", 5],
    ]
    create_sample_pdf(pdf_path, page_count=5, toc=toc)

    info = get_pdf_info(pdf_path)
    assert info.page_count == 5
    assert info.has_bookmarks is True
    assert len(info.toc) == 4
    assert info.max_level == 2
    assert info.is_encrypted is False
    assert "KB" in info.file_size_str or "B" in info.file_size_str


def test_pdf_info_encrypted(temp_workspace):
    """암호화된 PDF 감지 테스트"""
    pdf_path = os.path.join(temp_workspace, "encrypted.pdf")
    create_sample_pdf(pdf_path, page_count=3, password="secret_password")

    with pytest.raises(EncryptedPDFError):
        get_pdf_info(pdf_path)


def test_calculate_split_ranges_level1(temp_workspace):
    """최상위 레벨(1단계) 기준 분할 범위 계산 테스트"""
    toc = [
        [1, "1장 개요", 1],
        [2, "1.1절", 2],
        [1, "2장 본문", 4],
        [1, "3장 결언", 6],
    ]
    ranges = calculate_split_ranges(toc, total_pages=8, max_level=1)

    assert len(ranges) == 3
    # 1장: 1페이지 ~ 3페이지 (2장 직전)
    assert ranges[0].title == "1장 개요"
    assert ranges[0].start_page == 1
    assert ranges[0].end_page == 3
    assert ranges[0].page_count == 3

    # 2장: 4페이지 ~ 5페이지 (3장 직전)
    assert ranges[1].title == "2장 본문"
    assert ranges[1].start_page == 4
    assert ranges[1].end_page == 5
    assert ranges[1].page_count == 2

    # 3장: 6페이지 ~ 8페이지 (마지막 페이지까지)
    assert ranges[2].title == "3장 결언"
    assert ranges[2].start_page == 6
    assert ranges[2].end_page == 8
    assert ranges[2].page_count == 3


def test_calculate_split_ranges_with_prefix(temp_workspace):
    """첫 북마크가 1페이지 이후에 시작될 때 앞부속 포함 테스트"""
    toc = [
        [1, "제1장", 3],
        [1, "제2장", 5],
    ]
    ranges = calculate_split_ranges(toc, total_pages=6, max_level=1, include_prefix_pages=True)
    assert len(ranges) == 3
    # 00_시작부속: 1 ~ 2페이지
    assert ranges[0].title == "시작부속"
    assert ranges[0].start_page == 1
    assert ranges[0].end_page == 2

    assert ranges[1].title == "제1장"
    assert ranges[1].start_page == 3
    assert ranges[1].end_page == 4

    assert ranges[2].title == "제2장"
    assert ranges[2].start_page == 5
    assert ranges[2].end_page == 6


def test_split_pdf_execution(temp_workspace):
    """실제 PDF 분할 실행 및 결과 파일 검증 테스트"""
    pdf_path = os.path.join(temp_workspace, "report.pdf")
    toc = [
        [1, "Part 1 Intro", 1],
        [1, "Part 2 Content", 3],
    ]
    create_sample_pdf(pdf_path, page_count=5, toc=toc)

    ranges = calculate_split_ranges(toc, total_pages=5, max_level=1)
    out_dir, created = split_pdf(pdf_path, ranges)

    assert os.path.exists(out_dir)
    assert len(created) == 2
    assert os.path.basename(created[0]) == "01_Part 1 Intro.pdf"
    assert os.path.basename(created[1]) == "02_Part 2 Content.pdf"

    # 생성된 첫 번째 PDF 페이지 수 검증 (1~2페이지 = 2장)
    doc1 = pymupdf.open(created[0])
    assert len(doc1) == 2
    doc1.close()

    # 생성된 두 번째 PDF 페이지 수 검증 (3~5페이지 = 3장)
    doc2 = pymupdf.open(created[1])
    assert len(doc2) == 3
    doc2.close()


def test_no_bookmarks(temp_workspace):
    """북마크가 전혀 없는 PDF 예외 테스트"""
    pdf_path = os.path.join(temp_workspace, "no_toc.pdf")
    create_sample_pdf(pdf_path, page_count=3, toc=[])

    info = get_pdf_info(pdf_path)
    assert info.has_bookmarks is False

    with pytest.raises(NoBookmarksError):
        calculate_split_ranges(info.toc, total_pages=info.page_count)


def test_calculate_split_ranges_level2(temp_workspace):
    """2단계 북마크까지 포함하여 분할하는 테스트"""
    toc = [
        [1, "1장 개요", 1],
        [2, "1.1절 배경", 2],
        [2, "1.2절 목표", 3],
        [1, "2장 본론", 4],
    ]
    ranges = calculate_split_ranges(toc, total_pages=5, max_level=2)
    assert len(ranges) == 4
    assert ranges[0].title == "1장 개요"
    assert ranges[0].start_page == 1
    assert ranges[0].end_page == 1

    assert ranges[1].title == "1.1절 배경"
    assert ranges[1].start_page == 2
    assert ranges[1].end_page == 2

    assert ranges[2].title == "1.2절 목표"
    assert ranges[2].start_page == 3
    assert ranges[2].end_page == 3

    assert ranges[3].title == "2장 본론"
    assert ranges[3].start_page == 4
    assert ranges[3].end_page == 5


def test_unique_output_dir(temp_workspace):
    """폴더 중복 시 넘버링 테스트"""
    base_folder = "report"
    first = get_unique_output_dir(temp_workspace, base_folder)
    assert os.path.basename(first) == "report"
    os.makedirs(first, exist_ok=True)
    # 폴더 내에 임의 파일 생성
    with open(os.path.join(first, "dummy.txt"), "w") as f:
        f.write("content")

    second = get_unique_output_dir(temp_workspace, base_folder)
    assert os.path.basename(second) == "report (1)"

