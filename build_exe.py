#!/usr/bin/env python3
"""
build_exe.py — 一键打包脚本
将项目打包为 Windows 可执行文件，输出到 dist/ 目录
"""
import os
import sys
import shutil
import subprocess
import zipfile
import argparse
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)

DIST_NAME = "劳动法律智能体_根号三"
SPEC_FILE = "劳动法律智能体_根号三.spec"
ICON_FILE = "app_icon.ico"


def step(msg: str):
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}")


def cleanup():
    """清理旧的构建产物"""
    for d in ['build', 'dist']:
        path = os.path.join(SCRIPT_DIR, d)
        if os.path.exists(path):
            print(f"[清理] 删除 {d}/ ...")
            shutil.rmtree(path, ignore_errors=True)
    # 也删除 .spec 生成的临时文件
    for pattern in ['*.spec.bak', '*.manifest']:
        import glob
        for f in glob.glob(pattern):
            if os.path.exists(f):
                os.remove(f)


def check_icon():
    """检查图标文件是否存在，不存在则自动生成"""
    if not os.path.exists(os.path.join(SCRIPT_DIR, ICON_FILE)):
        print(f"[图标] {ICON_FILE} 不存在，正在自动生成...")
        subprocess.run([sys.executable, "generate_icon.py"], check=True)
        if not os.path.exists(os.path.join(SCRIPT_DIR, ICON_FILE)):
            print("[WARN] 图标生成失败，将使用默认图标")
            return False
    print(f"[图标] 使用: {ICON_FILE}")
    return True


def run_pyinstaller():
    """执行 PyInstaller 打包"""
    step("开始 PyInstaller 打包")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--clean",
        "--noconfirm",
        SPEC_FILE,
    ]
    print(f"[命令] {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=SCRIPT_DIR)
    if result.returncode != 0:
        print("[ERROR] PyInstaller 打包失败！")
        sys.exit(1)
    print("[OK] PyInstaller 打包完成")


def verify_output():
    """验证输出文件"""
    dist_dir = os.path.join(SCRIPT_DIR, "dist", DIST_NAME)
    exe_path = os.path.join(dist_dir, f"{DIST_NAME}.exe")

    if not os.path.exists(exe_path):
        print(f"[ERROR] 未找到输出文件: {exe_path}")
        sys.exit(1)

    size_mb = os.path.getsize(exe_path) / (1024 * 1024)
    print(f"\n[验证] EXE 文件: {exe_path}")
    print(f"[验证] 大小: {size_mb:.1f} MB")

    # 统计 dist 目录总大小
    total_size = 0
    for root, dirs, files in os.walk(dist_dir):
        for f in files:
            total_size += os.path.getsize(os.path.join(root, f))
    total_mb = total_size / (1024 * 1024)
    print(f"[验证] 安装包总大小: {total_mb:.1f} MB")


def create_zip():
    """将 dist 目录压缩为 zip 包"""
    step("创建 ZIP 安装包")
    dist_dir = os.path.join(SCRIPT_DIR, "dist", DIST_NAME)
    version = "v1.0.0"
    ver_file = os.path.join(SCRIPT_DIR, "version.txt")
    if os.path.exists(ver_file):
        with open(ver_file, "r", encoding="utf-8") as f:
            version = f.read().strip()

    date_str = datetime.now().strftime("%Y%m%d")
    zip_name = f"{DIST_NAME}_{version}_Windows_{date_str}.zip"
    zip_path = os.path.join(SCRIPT_DIR, "dist", zip_name)

    print(f"[压缩] {zip_name} ...")
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(dist_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, os.path.join(SCRIPT_DIR, "dist"))
                zf.write(file_path, arcname)

    zip_mb = os.path.getsize(zip_path) / (1024 * 1024)
    print(f"[OK] ZIP 包已生成: {zip_path} ({zip_mb:.1f} MB)")
    return zip_path


def print_instructions(zip_path: str):
    """打印发布说明"""
    step("发布说明")
    print(f"""
📦 安装包已生成: {zip_path}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  上传到 GitHub Releases 的步骤：
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. 打开你的 GitHub 仓库 → 点击 "Releases"
2. 点击 "Create a new release"
3. 填写 Tag 版本号（如 v1.0.0）
4. 填写 Release 标题（如「劳动法律智能体_根号三 v1.0.0」）
5. 在描述中粘贴以下内容：

--- 粘贴以下内容到 Release 描述 ---
## 📥 下载说明

### 方式一：主程序（必装）
下载下方 `{os.path.basename(zip_path)}`，解压后双击 `{DIST_NAME}.exe` 即可使用。

### 方式二：知识库数据（可选）
如需完整的法律法规知识库（离线 RAG 检索），请额外下载 `知识库数据包.zip`，
解压后将 `data/` 和 `vectorstore.pkl` 放入程序目录。

### 使用步骤
1. 下载主程序 ZIP 包并解压
2. 双击 `{DIST_NAME}.exe` 运行
3. 首次使用请注册账号并配置 API Key
4. 不需要安装 Python 或 Git

### ⚠️ 注意事项
- 本程序需要 API Key（阿里云百炼 / DeepSeek / 硅基流动）才能使用 AI 功能
- 知识库数据包可选下载，用于离线法律法规检索
- 用户数据保存在「我的文档\\劳动法律智能体_根号三\\」目录

--- 以上内容 ---

6. 上传 `{os.path.basename(zip_path)}` 作为附件
7. 如果有知识库数据包，一并上传
8. 点击 "Publish release"

✅ 完成！用户可以在 Releases 页面下载安装包。
""")


def upload_to_github(zip_path: str, version: str):
    """通过 gh CLI 上传到 GitHub Releases"""
    step("上传到 GitHub Releases")

    # 检查 gh CLI 是否安装
    result = subprocess.run(["gh", "--version"], capture_output=True)
    if result.returncode != 0:
        print("[ERROR] 未检测到 GitHub CLI (gh)。")
        print("请先安装: https://cli.github.com/ 或使用 winget install GitHub.cli")
        return False

    # 检查是否已登录
    result = subprocess.run(["gh", "auth", "status"], capture_output=True)
    if result.returncode != 0:
        print("[ERROR] gh 未登录，请先运行: gh auth login")
        return False

    tag = f"v{version}"
    title = f"劳动法律智能体_根号三 v{version}"

    # 读取知识库说明
    kb_note = ""
    kb_md = os.path.join(SCRIPT_DIR, "知识库下载说明.md")
    if os.path.exists(kb_md):
        kb_note = "> 📚 知识库数据包需单独下载，详见仓库中的 `知识库下载说明.md`"

    release_body = f"""## 📥 下载说明

### 方式一：主程序（必装）
下载下方 ZIP 包，解压后双击 `{DIST_NAME}.exe` 即可使用。

### 方式二：知识库数据（可选）
如需完整的法律法规知识库（离线 RAG 检索），请额外下载 `知识库数据包.zip`，
解压后将 `data/` 和 `vectorstore.pkl` 放入程序目录。

{kb_note}

### 使用步骤
1. 下载主程序 ZIP 包并解压
2. 双击 `{DIST_NAME}.exe` 运行
3. 首次使用请注册账号并配置 API Key
4. 不需要安装 Python 或 Git

### ⚠️ 注意事项
- 本程序需要 API Key（阿里云百炼 / DeepSeek / 硅基流动）才能使用 AI 功能
- 知识库数据包可选下载，用于离线法律法规检索
- 用户数据保存在「我的文档\\{DIST_NAME}\\」目录"""

    # 创建或获取 release
    print(f"[GitHub] 创建 Release: {tag}")
    # 先检查 tag 是否存在
    tag_check = subprocess.run(
        ["git", "tag", "-l", tag], cwd=SCRIPT_DIR,
        capture_output=True, text=True
    )
    if not tag_check.stdout.strip():
        print(f"[GitHub] 本地 tag {tag} 不存在，正在创建...")
        subprocess.run(["git", "tag", tag], cwd=SCRIPT_DIR, check=False)

    # 推送 tag 到远程
    print(f"[GitHub] 推送 tag {tag} ...")
    subprocess.run(["git", "push", "origin", tag], cwd=SCRIPT_DIR, check=False)

    # 使用 gh release create 创建 release 并上传文件
    cmd = [
        "gh", "release", "create", tag,
        "--title", title,
        "--notes", release_body,
        zip_path,
    ]

    print(f"[GitHub] 上传文件: {os.path.basename(zip_path)}")
    print(f"[GitHub] 这可能需要几分钟（取决于网速和文件大小）...")
    result = subprocess.run(cmd, cwd=SCRIPT_DIR)

    if result.returncode == 0:
        print(f"\n✅ Release 发布成功！")
        print(f"   查看: https://github.com/luzimo6-gif/LaborLaw-AI-Agent-AI-/releases/tag/{tag}")
        return True
    else:
        print(f"\n❌ 上传失败（返回码: {result.returncode}）")
        print("   如果 tag 已存在，请手动运行:")
        print(f"   gh release upload {tag} {zip_path}")
        return False


def main():
    parser = argparse.ArgumentParser(description="一键打包劳动法律智能体")
    parser.add_argument("--no-zip", action="store_true", help="不创建 ZIP 压缩包")
    parser.add_argument("--skip-build", action="store_true", help="跳过 PyInstaller 打包，仅压缩已有 dist/")
    parser.add_argument("--release", action="store_true", help="打包完成后自动上传到 GitHub Releases（需要 gh CLI）")
    parser.add_argument("--upload-only", type=str, metavar="ZIP_PATH", help="仅上传已有 ZIP 到 GitHub Releases，不重新打包")
    args = parser.parse_args()

    print("=" * 60)
    print("  劳动法律智能体_根号三 — 一键打包工具")
    print("=" * 60)

    # 读取版本号
    version = "1.0.0"
    ver_file = os.path.join(SCRIPT_DIR, "version.txt")
    if os.path.exists(ver_file):
        with open(ver_file, "r", encoding="utf-8") as f:
            version = f.read().strip()
    print(f"  版本: v{version}")

    # 仅上传模式
    if args.upload_only:
        zip_path = args.upload_only
        if not os.path.exists(zip_path):
            print(f"[ERROR] 文件不存在: {zip_path}")
            sys.exit(1)
        upload_to_github(zip_path, version)
        return

    if not args.skip_build:
        cleanup()
        check_icon()
        run_pyinstaller()

    verify_output()

    if not args.no_zip:
        zip_path = create_zip()
        if args.release:
            upload_to_github(zip_path, version)
        else:
            print_instructions(zip_path)
    else:
        print(f"\n[OK] 打包完成！EXE 在 dist/{DIST_NAME}/ 目录下")


if __name__ == "__main__":
    main()
