#!/usr/bin/env python3
"""Validate a Markdown bundle intended for the Inkment editor."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import unquote


IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
HIGHLIGHT_OPEN_RE = re.compile(r"\{\{highlight:")
VALID_HIGHLIGHT_RE = re.compile(r"\{\{highlight:[^}\n]+\}\}")
ABSOLUTE_PATH_RE = re.compile(r"(?:file://|/(?:Users|home|private|tmp)/|[A-Za-z]:[\\/])")
PROJECT_NAME_RE = re.compile(r"^\d{8}｜[^/]+(?:｜\d{2})?$")
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif"}


def validate(markdown_path: Path) -> list[str]:
    errors: list[str] = []
    if not markdown_path.is_file():
        return [f"Markdown 文件不存在: {markdown_path}"]

    text = markdown_path.read_text(encoding="utf-8")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    h1_lines: list[int] = []
    subtitles: list[int] = []
    code_line_indexes: set[int] = set()
    previous_heading_level = 0
    in_code_block = False
    code_fence_count = 0
    for line_number, line in enumerate(lines, start=1):
        if re.match(r"^\s*```", line):
            code_line_indexes.add(line_number - 1)
            in_code_block = not in_code_block
            code_fence_count += 1
            continue
        if in_code_block:
            code_line_indexes.add(line_number - 1)
            continue
        if re.match(r"^#\s+\S", line):
            h1_lines.append(line_number)
        if re.match(r"^@subtitle\s+\S", line, re.I):
            subtitles.append(line_number)
        match = re.match(r"^(#{1,6})\s+\S", line)
        if not match:
            continue
        level = len(match.group(1))
        if level > 3:
            errors.append(f"第 {line_number} 行使用墨布未定义的 {level} 级标题")
        if previous_heading_level and level > previous_heading_level + 1:
            errors.append(f"第 {line_number} 行标题从 H{previous_heading_level} 跳到 H{level}")
        previous_heading_level = level

    if len(h1_lines) != 1:
        errors.append(f"主标题数量应为 1，实际为 {len(h1_lines)}")
    if len(subtitles) > 1:
        errors.append(f"副标题数量最多为 1，实际为 {len(subtitles)}")

    if code_fence_count % 2:
        errors.append("代码块围栏未闭合")

    def table_cells(line: str) -> list[str]:
        source = line.strip().strip("|")
        return [cell.strip() for cell in re.split(r"(?<!\\)\|", source)]

    for index in range(len(lines) - 1):
        if index in code_line_indexes or index + 1 in code_line_indexes:
            continue
        header = lines[index]
        separator = lines[index + 1]
        if "|" not in header or not re.match(
            r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$",
            separator,
        ):
            continue
        expected_columns = len(table_cells(header))
        if len(table_cells(separator)) != expected_columns:
            errors.append(f"第 {index + 2} 行表格分隔列数与表头不一致")
        row_index = index + 2
        while row_index < len(lines) and "|" in lines[row_index] and lines[row_index].strip():
            if len(table_cells(lines[row_index])) != expected_columns:
                errors.append(f"第 {row_index + 1} 行表格列数与表头不一致")
            row_index += 1

    unmatched_highlights = HIGHLIGHT_OPEN_RE.findall(VALID_HIGHLIGHT_RE.sub("", text))
    if unmatched_highlights:
        errors.append("重点标记可能未闭合，或存在无法配对的 `}}`")

    referenced_paths: set[Path] = set()
    for match in IMAGE_RE.finditer(text):
        raw_path = match.group(2).strip().strip("<>").split(maxsplit=1)[0]
        if re.match(r"^(?:https?:|data:)", raw_path, re.I):
            errors.append(f"图片必须位于文章包内，发现远程或 data URL: {raw_path}")
            continue
        if ABSOLUTE_PATH_RE.search(raw_path) or Path(unquote(raw_path)).is_absolute():
            errors.append(f"图片不能使用绝对路径: {raw_path}")
            continue
        relative_path = Path(unquote(raw_path))
        resolved = (markdown_path.parent / relative_path).resolve()
        referenced_paths.add(resolved)
        if not resolved.is_file():
            errors.append(f"图片引用不存在: {raw_path}")

    names: dict[str, Path] = {}
    for path in referenced_paths:
        key = path.name.casefold()
        if key in names and names[key] != path:
            errors.append(f"图片文件名重复: {path.name}")
        names[key] = path

    return errors


def validate_project(project_path: Path) -> tuple[Path | None, list[str]]:
    errors: list[str] = []
    if not project_path.is_dir():
        return None, [f"项目目录不存在: {project_path}"]
    if not PROJECT_NAME_RE.match(project_path.name):
        errors.append(f"项目目录名不符合 YYYYMMDD｜主题: {project_path.name}")

    markdown_files = sorted(project_path.glob("*-墨布排版.md"))
    markdown_path = markdown_files[0] if len(markdown_files) == 1 else None
    if len(markdown_files) != 1:
        errors.append(f"根目录应有且仅有一个 `主题-墨布排版.md`，实际为 {len(markdown_files)}")

    required_dirs = [
        project_path / "图片" / "头图",
        project_path / "图片" / "插图",
        project_path / "原始素材" / "正文",
        project_path / "原始素材" / "图片",
        project_path / "原始素材" / "未使用图片",
    ]
    for directory in required_dirs:
        if not directory.is_dir():
            errors.append(f"缺少归档目录: {directory.relative_to(project_path)}")
    if not (project_path / "归档清单.md").is_file():
        errors.append("缺少归档清单.md")

    if markdown_path:
        errors.extend(validate(markdown_path))
        text = markdown_path.read_text(encoding="utf-8")
        referenced: set[Path] = set()
        for match in IMAGE_RE.finditer(text):
            raw_path = match.group(2).strip().strip("<>").split(maxsplit=1)[0]
            relative_path = Path(unquote(raw_path))
            if not (
                len(relative_path.parts) >= 3
                and relative_path.parts[0] == "图片"
                and relative_path.parts[1] in {"头图", "插图"}
            ):
                errors.append(f"图片应归档在 图片/头图 或 图片/插图: {raw_path}")
            if not relative_path.is_absolute():
                referenced.add((project_path / relative_path).resolve())

        archived_images = {
            path.resolve()
            for path in (project_path / "图片").rglob("*")
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        } if (project_path / "图片").is_dir() else set()
        unreferenced = sorted(path.relative_to(project_path) for path in archived_images - referenced)
        if unreferenced:
            errors.append("图片目录存在正文未引用文件: " + ", ".join(map(str, unreferenced)))

    return markdown_path, errors


def main() -> int:
    parser = argparse.ArgumentParser(description="验证墨布 Markdown 或规范归档项目")
    parser.add_argument("target", type=Path, help="待验证的项目目录或 Markdown 文件")
    args = parser.parse_args()
    target = args.target.expanduser().resolve()
    if target.is_dir():
        markdown_path, errors = validate_project(target)
    else:
        markdown_path, errors = target, validate(target)
    if errors:
        print("FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print("PASS")
    if target.is_dir():
        print(f"- 项目: {target}")
    if markdown_path:
        print(f"- Markdown: {markdown_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
