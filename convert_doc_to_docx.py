"""
批量将 data 目录下所有 .doc 文件转换为 .docx
使用 LibreOffice headless 模式（单进程串行，避免冲突）

用法：
    python convert_doc_to_docx.py          # 转换并保留原文件
    python convert_doc_to_docx.py --delete # 转换后删除原 .doc 文件
"""
import os
import sys
import subprocess
import time
from pathlib import Path

# ============ 配置 ============
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
SOFFICE = r"C:\Program Files\LibreOffice\program\soffice.exe"

# 单个文件超时时间（秒）
TIMEOUT = 120
# 批量转换：每处理多少文件输出一次进度
PROGRESS_INTERVAL = 20
# =============================


def find_all_doc_files(data_dir: Path) -> list:
    """递归查找所有 .doc 文件（排除 .docx）"""
    doc_files = []
    for doc_path in data_dir.rglob("*.doc"):
        if doc_path.suffix.lower() == ".doc":
            doc_files.append(doc_path)
    return doc_files


def convert_single(doc_path: Path, delete_after: bool) -> dict:
    """
    转换单个 .doc -> .docx
    返回: {"path": ..., "status": "success"|"skipped"|"failed", "message": ...}
    """
    docx_path = doc_path.with_suffix(".docx")

    # 如果 .docx 已存在，跳过
    if docx_path.exists() and docx_path.stat().st_size > 0:
        return {
            "path": doc_path,
            "status": "skipped",
            "message": f"already exists -> {docx_path.name}"
        }

    output_dir = str(doc_path.parent)

    try:
        # 使用 --norestore 避免崩溃恢复对话框阻塞
        # 使用 -env:UserInstallation 指定临时用户目录，避免多实例冲突
        result = subprocess.run(
            [
                SOFFICE,
                "--headless",
                "--norestore",
                "--convert-to", "docx",
                "--outdir", output_dir,
                str(doc_path),
            ],
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            # 传递空环境变量避免继承问题，用 os.environ 保持原环境
            env={**os.environ},
        )

        if docx_path.exists() and docx_path.stat().st_size > 0:
            if delete_after:
                try:
                    doc_path.unlink()
                    print(f"  [OK+DEL] {doc_path.relative_to(DATA_DIR)}")
                except Exception:
                    print(f"  [OK] {doc_path.relative_to(DATA_DIR)} (delete failed)")
            else:
                print(f"  [OK] {doc_path.relative_to(DATA_DIR)}")
            return {
                "path": doc_path,
                "status": "success",
                "message": f"-> {docx_path.name}"
            }
        else:
            print(f"  [FAIL] No output: {doc_path.relative_to(DATA_DIR)}")
            if result.stderr:
                err_msg = result.stderr.strip()[:200]
                print(f"         stderr: {err_msg}")
            return {
                "path": doc_path,
                "status": "failed",
                "message": f"No output file generated"
            }

    except subprocess.TimeoutExpired:
        print(f"  [TIMEOUT] {doc_path.relative_to(DATA_DIR)}")
        return {"path": doc_path, "status": "failed", "message": "timeout"}
    except Exception as e:
        print(f"  [ERROR] {doc_path.relative_to(DATA_DIR)} - {e}")
        return {"path": doc_path, "status": "failed", "message": str(e)}


def main():
    delete_after = "--delete" in sys.argv

    print("=" * 60)
    print("[DOC->DOCX] .doc to .docx Batch Converter")
    print(f"  Data Dir: {DATA_DIR}")
    print(f"  LibreOffice: {SOFFICE}")
    print(f"  Mode: Serial (single process, no conflicts)")
    print(f"  Delete after convert: {'Yes' if delete_after else 'No (keep originals)'}")
    print("=" * 60)

    # 检查 LibreOffice
    if not os.path.exists(SOFFICE):
        print(f"[ERROR] LibreOffice not found: {SOFFICE}")
        print("   Please install LibreOffice or update SOFFICE path.")
        sys.exit(1)

    # 查找所有 .doc 文件
    print("\n[SCAN] Searching for .doc files...")
    doc_files = find_all_doc_files(DATA_DIR)
    total = len(doc_files)

    if total == 0:
        print("[INFO] No .doc files found. Nothing to convert!")
        return

    print(f"[SCAN] Found {total} .doc files.\n")

    # 确认（删除模式）
    if delete_after:
        confirm = input(
            f"[WARN] This will DELETE {total} original .doc files after conversion.\n"
            f"       Type YES to confirm: "
        )
        if confirm.strip().upper() != "YES":
            print("Cancelled.")
            return

    # 串行转换
    results = {"success": 0, "skipped": 0, "failed": 0}
    failed_files = []
    start_time = time.time()

    for i, doc_path in enumerate(doc_files, 1):
        result = convert_single(doc_path, delete_after)
        results[result["status"]] += 1

        if result["status"] == "failed":
            failed_files.append(result)

        # 进度报告
        if i % PROGRESS_INTERVAL == 0 or i == total:
            elapsed = time.time() - start_time
            speed = i / elapsed if elapsed > 0 else 0
            eta = (total - i) / speed if speed > 0 else 0
            print(f"\n[PROGRESS] {i}/{total} | "
                  f"OK:{results['success']} Skip:{results['skipped']} Fail:{results['failed']} | "
                  f"Speed:{speed:.1f}/s | ETA:{eta:.0f}s\n")

    # 统计
    elapsed = time.time() - start_time
    print("\n" + "=" * 60)
    print("[DONE] Conversion Complete!")
    print(f"   Total files: {total}")
    print(f"   Success:     {results['success']}")
    print(f"   Skipped:     {results['skipped']}")
    print(f"   Failed:      {results['failed']}")
    print(f"   Time:        {elapsed:.1f}s ({elapsed/60:.1f}min)")
    print("=" * 60)

    # 输出失败列表
    if failed_files:
        print(f"\n[FAILED] {len(failed_files)} files:")
        for f in failed_files[:50]:  # 最多显示50个
            rel_path = Path(f['path']).relative_to(DATA_DIR)
            print(f"   - {rel_path}: {f['message']}")
        if len(failed_files) > 50:
            print(f"   ... and {len(failed_files) - 50} more")

        # 保存完整失败列表
        error_log = BASE_DIR / "convert_errors.txt"
        with open(error_log, "w", encoding="utf-8") as ef:
            for f in failed_files:
                rel_path = Path(f['path']).relative_to(DATA_DIR)
                ef.write(f"{rel_path}: {f['message']}\n")
        print(f"\nFull error list saved to: {error_log}")

    # 统计当前文件分布
    print("\n[SUMMARY] Current file distribution:")
    for ext in ['.doc', '.docx', '.pdf']:
        count = len(list(DATA_DIR.rglob(f"*{ext}")))
        print(f"   {ext}: {count} files")


if __name__ == "__main__":
    main()
