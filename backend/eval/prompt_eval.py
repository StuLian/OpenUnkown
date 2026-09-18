"""prompt 结构回归检查。

用法：
  .venv/bin/python -m backend.eval.prompt_eval

不调用模型（免费、CI 友好）：验证各层 prompt 是否仍包含关键规则短语，
防止重构/裁剪时误删「如实说明」「不要编造」「不要虚构工具名」等行为约束。
任一检查失败即非零退出，可接入 pre-commit / CI 门禁。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import backend.agent.prompts as prompts

CASES_PATH = Path(__file__).resolve().parent / "datasets" / "prompt_cases.json"

# section 名 → prompts 模块里的实际字符串
_SECTIONS = {
    "persona": prompts.PERSONA_SECTION,
    "behavior": prompts.BEHAVIOR_SECTION,
    "output_format": prompts.OUTPUT_FORMAT_SECTION,
    "context": prompts.CONTEXT_SECTION_TEMPLATE,
}


def run_checks(cases: dict) -> tuple[list[dict], bool]:
    """执行全部检查，返回 (逐条结果, 是否全部通过)。"""
    results: list[dict] = []
    ok = True
    for check in cases["checks"]:
        section_name = check["section"]
        text = _SECTIONS.get(section_name, "")
        missing = [phrase for phrase in check["must_contain"] if phrase not in text]
        passed = not missing and bool(text)
        if not passed:
            ok = False
        results.append(
            {
                "section": section_name,
                "label": check["label"],
                "passed": passed,
                "missing": missing if not passed else [],
                "empty": not text,
            }
        )
    return results, ok


def main() -> int:
    parser = argparse.ArgumentParser(description="prompt 结构回归检查")
    parser.add_argument("--html-out", default=None, help="生成可视化 HTML 报告到指定文件")
    args = parser.parse_args()

    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    print(f"prompt 版本：{prompts.PROMPT_VERSION}")
    print("=" * 72)
    results, ok = run_checks(cases)
    for r in results:
        mark = "✓" if r["passed"] else "✗"
        detail = ""
        if not r["passed"]:
            if r["empty"]:
                detail = "（该层为空）"
            else:
                detail = f"（缺少：{', '.join(r['missing'])}）"
        print(f"[{mark}] {r['label']}{detail}")
    print("=" * 72)
    print("结果：" + ("全部通过" if ok else "存在失败项"))

    if args.html_out:
        from backend.eval.report import render_prompt_report

        Path(args.html_out).write_text(
            render_prompt_report(prompts.PROMPT_VERSION, results, ok), encoding="utf-8"
        )
        print(f"HTML 报告已写入 {args.html_out}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
