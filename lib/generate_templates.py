#!/usr/bin/env python3
"""
Генератор шаблонов тела события (eventData) из OpenAPI/Swagger (api-docs.json).

Для каждого POST-эндпоинта без {eventId} строит образец JSON-тела по его схеме
и кладёт его в templates/<EVENT_TYPE>.json.

По умолчанию НЕ перезаписывает уже существующие файлы — так сохраняются
твои выверенные («рабочие») шаблоны. Перегенерировать всё: --force.

Использование:
    python3 lib/generate_templates.py path/to/api-docs.json [--force]
"""
import json
import sys
import os
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(os.path.dirname(HERE), "templates")
INDEX_FILE = os.path.join(os.path.dirname(HERE), "events.index.json")

NOW_ISO = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000+05:00")


def path_to_event_type(path: str) -> str:
    return path.strip("/").replace("-", "_").upper()


def resolve_ref(ref: str, schemas: dict) -> dict:
    return schemas.get(ref.split("/")[-1], {})


def sample_from_schema(schema: dict, schemas: dict, stack: tuple = (), depth: int = 0):
    """Рекурсивно строит образец значения по схеме. Защита от циклов через stack."""
    if depth > 25:
        return None

    if "$ref" in schema:
        name = schema["$ref"].split("/")[-1]
        if name in stack:          # цикл — обрываем
            return None
        target = resolve_ref(schema["$ref"], schemas)
        return sample_from_schema(target, schemas, stack + (name,), depth + 1)

    # allOf / oneOf / anyOf — берём первый осмысленный вариант и сливаем
    for comb in ("allOf", "oneOf", "anyOf"):
        if comb in schema:
            merged = {}
            for sub in schema[comb]:
                val = sample_from_schema(sub, schemas, stack, depth + 1)
                if isinstance(val, dict):
                    merged.update(val)
                elif val is not None:
                    return val
            return merged if merged else None

    if "example" in schema:
        return schema["example"]

    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]

    t = schema.get("type")

    if t == "object" or "properties" in schema:
        obj = {}
        for prop, sub in schema.get("properties", {}).items():
            obj[prop] = sample_from_schema(sub, schemas, stack, depth + 1)
        return obj

    if t == "array":
        item = sample_from_schema(schema.get("items", {}), schemas, stack, depth + 1)
        return [item] if item is not None else []

    if t == "string":
        fmt = schema.get("format")
        if fmt == "date-time":
            return NOW_ISO
        if fmt == "date":
            return NOW_ISO[:10]
        if fmt == "uuid":
            return "00000000-0000-0000-0000-000000000000"
        return "string"

    if t == "integer":
        return 0
    if t == "number":
        return 0
    if t == "boolean":
        return False

    # тип не указан, но это явно объект
    if "properties" in schema:
        return {p: sample_from_schema(s, schemas, stack, depth + 1)
                for p, s in schema["properties"].items()}
    return None


def main():
    if len(sys.argv) < 2:
        print("usage: generate_templates.py <api-docs.json> [--force]", file=sys.stderr)
        sys.exit(1)
    force = "--force" in sys.argv
    spec = json.load(open(sys.argv[1], encoding="utf-8"))
    schemas = spec["components"]["schemas"]
    tags = {t["name"]: t.get("description", "") for t in spec.get("tags", [])}

    os.makedirs(TEMPLATES_DIR, exist_ok=True)
    index = {}
    created, skipped = 0, 0

    for path, ops in spec["paths"].items():
        if "post" not in ops or "{" in path:
            continue
        post = ops["post"]
        event_type = path_to_event_type(path)
        ref = (post.get("requestBody", {}).get("content", {})
               .get("application/json", {}).get("schema", {}).get("$ref"))
        ru_name = (post.get("tags") or [""])[0]

        index[event_type] = {
            "path": path,
            "eventType": event_type,
            "ru": ru_name,
            "summary": post.get("summary", ""),
        }

        if not ref:
            continue
        body = sample_from_schema({"$ref": ref}, schemas) or {}
        # гарантируем корректные служебные поля
        body["eventType"] = event_type
        body["eventId"] = f"EVENT_{event_type}_TEMPLATE"

        out = os.path.join(TEMPLATES_DIR, f"{event_type}.json")
        if os.path.exists(out) and not force:
            skipped += 1
            continue
        with open(out, "w", encoding="utf-8") as f:
            json.dump(body, f, ensure_ascii=False, indent=2)
        created += 1

    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    print(f"Событий в swagger: {len(index)}")
    print(f"Сгенерировано шаблонов: {created}, пропущено (уже есть): {skipped}")
    print(f"Индекс событий: {INDEX_FILE}")


if __name__ == "__main__":
    main()
