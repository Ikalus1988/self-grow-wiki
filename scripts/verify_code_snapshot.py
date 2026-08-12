#!/usr/bin/env python3
"""基线 code/ 快照验证门禁 (评审 F3/F4 落地)。

baseline_sync.py code 同步后必须通过本门禁, 否则拒绝提交:
1. 所有 .py 文件可编译 (py_compile)
2. 密钥扫描: 调用 gitleaks (业界标准, 规则见 scripts/gitleaks.toml)
3. 调用 _load_deepseek_key 的文件必须定义该函数 (防 f348c9d 同类事故)
4. scripts/import/ 4 个 CLI 灌库脚本必须含 invalidate_indexes hook (评审 F1)

用法: python3 scripts/verify_code_snapshot.py [code 目录]
默认验证: /mnt/d/MD/RAG知识库/code
退出码: 0=通过, 1=失败
"""
import pathlib
import py_compile
import shutil
import subprocess
import sys

DEFAULT_CODE = pathlib.Path("/mnt/d/MD/RAG知识库/code")
DEFAULT_TOML = pathlib.Path("/mnt/d/MD/RAG知识库/scripts/gitleaks.toml")

# 评审 F1: 必须含 invalidate_indexes hook 的 CLI 灌库脚本 (相对 code/)
F1_SCRIPTS = [
    "scripts/import/import_batch.py",
    "scripts/import/rag_builder.py",
    "scripts/import/rag_builder_ocr.py",
    "scripts/import/rag_import_fanuc.py",
]


def gitleaks_bin() -> str:
    """定位 gitleaks 可执行文件。"""
    p = shutil.which("gitleaks")
    if p:
        return p
    home = pathlib.Path.home() / ".local" / "bin" / "gitleaks"
    if home.exists():
        return str(home)
    return ""


def scan_gitleaks(code: pathlib.Path, toml: pathlib.Path) -> tuple:
    """调用 gitleaks dir 扫描目录, 返回 (是否通过, 错误信息列表)。"""
    exe = gitleaks_bin()
    if not exe:
        return False, ["  gitleaks 未安装: 请安装 (https://github.com/gitleaks/gitleaks) 后重试"]
    cmd = [exe, "dir", str(code), "--config", str(toml),
           "--no-banner", "--redact=0", "--exit-code=1"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    leaks = proc.returncode != 0
    errs = []
    if leaks:
        errs.append("  gitleaks 发现密钥残留, 详情:")
        for line in proc.stderr.splitlines():
            if "INF" not in line and "WRN" not in line and line.strip():
                errs.append("    " + line.strip())
    return not leaks, errs


def main() -> int:
    code = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CODE
    if not code.exists():
        print(f"[FAIL] code 目录不存在: {code}")
        return 1

    errors: list = []

    # 1. py_compile 所有 .py
    py_files = sorted(code.rglob("*.py"))
    compile_fail = 0
    for f in py_files:
        if "__pycache__" in f.parts:
            continue
        try:
            py_compile.compile(str(f), doraise=True)
        except Exception as e:
            compile_fail += 1
            errors.append(f"  py_compile 失败: {f.relative_to(code)}: {e}")
    if compile_fail:
        print(f"[FAIL] py_compile: {compile_fail}/{len(py_files)} 失败")
    else:
        print(f"[ok] py_compile: {len(py_files)} 个文件全部通过")

    # 2. gitleaks 密钥扫描 (成熟方案, 替代手写正则)
    src_files = [f for f in code.rglob("*.py")
                 if ".git" not in f.parts and "__pycache__" not in f.parts]
    ok, gitleak_errs = scan_gitleaks(code, DEFAULT_TOML)
    if ok:
        print(f"[ok] gitleaks: {len(src_files)} 个源文件无密钥残留")
    else:
        errors.extend(gitleak_errs)
        print("[FAIL] gitleaks: 发现密钥残留")

    # 3. _load_deepseek_key 调用-定义一致性 (防 f348c9d 事故)
    inconsistent = 0
    for f in src_files:
        src = f.read_text(encoding="utf-8", errors="replace")
        calls = src.count("_load_deepseek_key()")
        has_def = "def _load_deepseek_key" in src
        if calls > 0 and not has_def:
            inconsistent += 1
            errors.append(f"  调用无定义: {f.relative_to(code)} (调用 {calls} 处)")
    if inconsistent:
        print(f"[FAIL] helper 一致性: {inconsistent} 个文件调用 _load_deepseek_key 但无定义")
    else:
        print(f"[ok] helper 一致性: 全部有调用必有定义")

    # 4. F1 hook 完整性
    f1_missing = []
    for rel in F1_SCRIPTS:
        f = code / rel
        if not f.exists():
            f1_missing.append(f"{rel} (文件缺失)")
            continue
        src = f.read_text(encoding="utf-8", errors="replace")
        if "invalidate_indexes" not in src:
            f1_missing.append(f"{rel} (无 invalidate_indexes)")
    if f1_missing:
        errors.append("  F1 hook 缺失: " + "; ".join(f1_missing))
        print(f"[FAIL] F1 hook: {len(f1_missing)} 个脚本不完整")
    else:
        print(f"[ok] F1 hook: {len(F1_SCRIPTS)} 个 CLI 灌库脚本全部含 invalidate_indexes")

    if errors:
        print("\n=== 验证失败 ===")
        for e in errors:
            print(e)
        return 1
    print("\n=== 验证通过: code/ 快照可提交 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
