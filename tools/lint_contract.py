#!/usr/bin/env python3
"""契约校验：OpenAPI 3.1 结构与示例一致性检查。

用法：
    python tools/lint_contract.py [--root .]

校验内容：
1. openapi.yaml 可解析，版本为 3.1.0，存在 info/version/paths。
2. 所有 operationId 非空且唯一，每个 operation 都有 tags。
3. 文档内所有 `$ref` 指向存在（相对本文件内的 #/components/... 引用）。
4. enums.yaml 中声明的枚举值与 openapi.yaml 中对应枚举 Schema 一致。
5. fixtures/manifest.yaml 登记的 JSON 夹具能通过对应 Schema 的 JSON Schema 校验。

退出码：0 通过；1 失败。输出 JSON 报告到  .runtime/contract-lint/ 下（如可写）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

try:
    import jsonschema  # type: ignore
    from jsonschema import Draft202012Validator  # type: ignore
    _HAS_JSONSCHEMA = True
except Exception:  # pragma: no cover
    _HAS_JSONSCHEMA = False


def load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def iter_refs(node: Any, out: list[str]) -> None:
    if isinstance(node, dict):
        if "$ref" in node and isinstance(node["$ref"], str):
            out.append(node["$ref"])
        for v in node.values():
            iter_refs(v, out)
    elif isinstance(node, list):
        for v in node:
            iter_refs(v, out)


def resolve_internal(node: Any, root: dict, seen: set[str]) -> Any:
    """将 #/components/... 内部引用内联展开（带环保护）。"""
    if isinstance(node, list):
        return [resolve_internal(v, root, seen) for v in node]
    if not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/"):
        if ref in seen:
            return {}
        parts = ref[2:].split("/")
        cur: Any = root
        try:
            for p in parts:
                cur = cur[p]
        except (KeyError, TypeError):
            raise ValueError(f"无法解析引用: {ref}")
        return resolve_internal(cur, root, seen | {ref})
    return {k: resolve_internal(v, root, seen) for k, v in node.items()}


def to_json_schema(node: Any) -> dict:
    """去掉 OpenAPI 描述性键，保留 JSON Schema 可校验的键。"""
    if isinstance(node, dict):
        cleaned = {}
        for k, v in node.items():
            if k in ("example", "examples", "description", "title", "x-", "externalDocs"):
                continue
            cleaned[k] = to_json_schema(v)
        return cleaned
    if isinstance(node, list):
        return [to_json_schema(v) for v in node]
    return node


ENUM_SCHEMA_MAP = {
    "roles": "Role",
    "admin_role": "AdminRole",
    "review_status": "ReviewStatus",
    "quality_status": "QualityStatus",
    "quality_reason_code": "QualityReasonCode",
    "view_type": "ViewType",
    "part": "Part",
    "upload_state": "UploadState",
    "export_status": "ExportStatus",
    "question_status": "QuestionStatus",
    "ticket_status": "TicketStatus",
    "ticket_outcome": "TicketOutcome",
    "confidence_band": "ConfidenceBand",
    "routing_reason_code": "RoutingReasonCode",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]), help="app 目录（相对或绝对）")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    contracts = root / "contracts"
    openapi_path = contracts / "openapi.yaml"
    enums_path = contracts / "enums.yaml"
    fixtures_dir = contracts / "fixtures"
    manifest_path = fixtures_dir / "manifest.yaml"

    report: dict[str, Any] = {"errors": [], "warnings": [], "checks": []}
    errors: list[str] = report["errors"]

    def check(ok: bool, msg: str) -> None:
        report["checks"].append({"ok": ok, "message": msg})
        if not ok:
            errors.append(msg)

    # 1. 解析 OpenAPI
    try:
        doc = load_yaml(openapi_path)
    except Exception as e:  # noqa: BLE001
        check(False, f"openapi.yaml 解析失败: {e}")
        _write_report(report, root)
        return 1

    check(doc.get("openapi") == "3.1.0", "OpenAPI 版本为 3.1.0")
    check("info" in doc, "存在 info 对象")
    check("paths" in doc and isinstance(doc["paths"], dict), "存在 paths 对象")

    # 2. operationId 唯一 + tags
    op_ids: list[str] = []
    paths = doc.get("paths", {})
    check(bool(paths), "paths 非空")
    for path, methods in paths.items():
        for method, op in methods.items() if isinstance(methods, dict) else []:
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            oid = op.get("operationId")
            check(bool(oid), f"{method.upper()} {path} 缺少 operationId")
            if oid:
                if oid in op_ids:
                    check(False, f"operationId 重复: {oid}")
                op_ids.append(oid)
            check(bool(op.get("tags")), f"{method.upper()} {path} 缺少 tags")

    # 3. 所有内部 $ref 可解析
    refs: list[str] = []
    iter_refs(doc, refs)
    internal = [r for r in refs if r.startswith("#/")]
    for r in internal:
        parts = r[2:].split("/")
        cur: Any = doc
        ok = True
        try:
            for p in parts:
                cur = cur[p]
        except (KeyError, TypeError):
            ok = False
        if not ok:
            check(False, f"未解析的内部引用: {r}")

    check(all(r.startswith("#/") for r in refs if isinstance(r, str)),
          "无外部网络引用（所有 $ref 均为文档内引用）")

    # 4. enums.yaml 与 openapi 枚举一致性
    if enums_path.exists():
        enums = load_yaml(enums_path)
        schemas = (doc.get("components") or {}).get("schemas", {})
        for enum_key, schema_name in ENUM_SCHEMA_MAP.items():
            declared = enums.get(enum_key)
            schema = schemas.get(schema_name, {})
            spec_values = schema.get("enum")
            if declared is None or spec_values is None:
                check(False, f"枚举不一致或缺省: enums.{enum_key} ↔ schemas.{schema_name}")
                continue
            check(sorted(declared) == sorted(spec_values),
                  f"enums.{enum_key} 与 schemas.{schema_name} 取值一致")
    else:
        check(False, "缺少 enums.yaml")

    # 5. fixtures 校验
    if manifest_path.exists() and _HAS_JSONSCHEMA:
        manifest = load_yaml(manifest_path)
        schemas = (doc.get("components") or {}).get("schemas", {})
        for entry in manifest.get("entries", []):
            fname = entry["file"]
            schema_name = entry["schema"]
            fpath = fixtures_dir / fname
            check(fpath.exists(), f"夹具存在: {fname}")
            if not fpath.exists():
                continue
            schema_node = schemas.get(schema_name)
            check(schema_node is not None, f"Schema 存在: {schema_name}")
            if schema_node is None:
                continue
            resolved = resolve_internal(schema_node, doc, set())
            jschema = to_json_schema(resolved)
            try:
                with fpath.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
                Draft202012Validator.check_schema(jschema)
                validator = Draft202012Validator(jschema)
                errs = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
                if errs:
                    first = errs[0]
                    check(False, f"夹具 {fname} 未通过 {schema_name}: {first.message} @ {'/'.join(map(str, first.path))}")
                else:
                    check(True, f"夹具 {fname} 通过 {schema_name}")
            except Exception as e:  # noqa: BLE001
                check(False, f"夹具 {fname} 校验异常: {e}")
    elif not _HAS_JSONSCHEMA:
        check(False, "缺少 jsonschema 库，无法校验夹具")

    _write_report(report, root)

    if errors:
        print("契约校验失败：")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("契约校验通过：", len(report["checks"]), "项检查全部成功。")
    return 0


def _write_report(report: dict, root: Path) -> None:
    out_dir = root.resolve() / ".runtime" / "contract-lint"
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "contract-lint.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    sys.exit(main())
