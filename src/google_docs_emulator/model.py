"""Paragraph document model. Character records keep styles stable across edits."""

import re
from copy import deepcopy
from uuid import uuid4


class Invalid(ValueError):
    pass


def units(text):
    return len(text.encode("utf-16-le")) // 2


def position(chars, index):
    if not isinstance(index, int) or isinstance(index, bool):
        raise Invalid("Index must be an integer")
    offset = 1
    for i, char in enumerate(chars):
        if offset == index:
            return i
        offset += units(char["c"])
    if offset == index:
        return len(chars)
    raise Invalid("Index outside body or splits a UTF-16 surrogate pair")


def new_document(title="", text="", document_id=None):
    if not isinstance(title, str) or not isinstance(text, str):
        raise Invalid("Title and text must be strings")
    if document_id is not None and (
        not isinstance(document_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", document_id)
    ):
        raise Invalid("Fixture documentId must contain letters, digits, hyphens or underscores")
    try:
        units(text)
    except UnicodeError as exc:
        raise Invalid("Text contains invalid Unicode") from exc
    if not text.endswith("\n"):
        text += "\n"
    return {
        "documentId": document_id or uuid4().hex,
        "title": title,
        "revision": 1,
        "chars": [{"c": c, "textStyle": {}, "paragraphStyle": {}} for c in text],
    }


def document(doc):
    content = [{"startIndex": 0, "endIndex": 1, "sectionBreak": {"sectionStyle": {}}}]
    index = 1
    paragraph = []
    for char in doc["chars"]:
        paragraph.append(char)
        if char["c"] != "\n":
            continue
        start = index
        elements = []
        for item in paragraph:
            end = index + units(item["c"])
            if elements and elements[-1]["textRun"]["textStyle"] == item["textStyle"]:
                elements[-1]["textRun"]["content"] += item["c"]
                elements[-1]["endIndex"] = end
            else:
                elements.append(
                    {
                        "startIndex": index,
                        "endIndex": end,
                        "textRun": {"content": item["c"], "textStyle": deepcopy(item["textStyle"])},
                    }
                )
            index = end
        content.append(
            {
                "startIndex": start,
                "endIndex": index,
                "paragraph": {"elements": elements, "paragraphStyle": deepcopy(paragraph[-1]["paragraphStyle"])},
            }
        )
        paragraph = []
    return {
        "documentId": doc["documentId"],
        "title": doc["title"],
        "revisionId": str(doc["revision"]),
        "body": {"content": content},
        "documentStyle": {},
        "suggestionsViewMode": "SUGGESTIONS_INLINE",
    }


def check_location(value):
    if any(key in value for key in ("segmentId", "tabId")):
        raise Invalid("Segments and tabs are not supported")


def span(chars, value):
    check_location(value)
    start = position(chars, value.get("startIndex", 1))
    end = position(chars, value.get("endIndex", 1 + sum(units(c["c"]) for c in chars)))
    if start >= end:
        raise Invalid("Range must be nonempty and ordered")
    return start, end


def batch(doc, requests):
    if not isinstance(requests, list):
        raise Invalid("requests must be an array")
    result = deepcopy(doc)
    chars = result["chars"]
    replies = []
    for request in requests:
        if not isinstance(request, dict) or len(request) != 1:
            raise Invalid("Each request must contain one operation")
        operation, value = next(iter(request.items()))
        if not isinstance(value, dict):
            raise Invalid("Operation payload must be an object")
        reply = {}
        if operation == "insertText":
            if ("location" in value) == ("endOfSegmentLocation" in value):
                raise Invalid("Specify exactly one location or endOfSegmentLocation")
            location = value.get("location", value.get("endOfSegmentLocation", {}))
            check_location(location)
            at = position(chars, location["index"]) if "location" in value else len(chars) - 1
            if at >= len(chars):
                raise Invalid("Cannot insert after final newline")
            text = re.sub("[\x00-\x08\x0c-\x1f\ue000-\uf8ff]", "", value["text"])
            try:
                units(text)
            except UnicodeError as exc:
                raise Invalid("Invalid Unicode text") from exc
            template = chars[max(0, at - 1)]
            chars[at:at] = [dict(deepcopy(template), c=c) for c in text]
        elif operation == "deleteContentRange":
            start, end = span(chars, value["range"])
            if end == len(chars):
                raise Invalid("Cannot delete final newline")
            del chars[start:end]
        elif operation == "replaceAllText":
            if value.get("tabsCriteria"):
                raise Invalid("Tabs are not supported")
            criteria = value["containsText"]
            if criteria.get("searchByRegex"):
                raise Invalid("Regex replacement is not supported")
            needle = criteria["text"]
            if not needle:
                raise Invalid("Search text must not be empty")
            text = "".join(c["c"] for c in chars[:-1])
            matches = list(re.finditer(re.escape(needle), text, 0 if criteria.get("matchCase") else re.IGNORECASE))
            try:
                units(value["replaceText"])
            except UnicodeError as exc:
                raise Invalid("Invalid Unicode replacement") from exc
            for match in reversed(matches):
                template = chars[match.start()]
                chars[match.start() : match.end()] = [dict(deepcopy(template), c=c) for c in value["replaceText"]]
            reply = {"replaceAllText": {"occurrencesChanged": len(matches)}}
        elif operation in ("updateParagraphStyle", "updateTextStyle"):
            style_key = "paragraphStyle" if operation == "updateParagraphStyle" else "textStyle"
            start, end = span(chars, value["range"])
            if style_key == "paragraphStyle":
                while start > 0 and chars[start - 1]["c"] != "\n":
                    start -= 1
                while end < len(chars) and chars[end - 1]["c"] != "\n":
                    end += 1
            style = value.get(style_key, {})
            fields = value.get("fields", "")
            if not fields:
                raise Invalid("Style fields mask is required")
            keys = list(style) if fields == "*" else [k.removeprefix(style_key + ".") for k in fields.split(",")]
            for char in chars[start:end]:
                if fields == "*":
                    char[style_key] = deepcopy(style)
                else:
                    for key in keys:
                        if "." in key:
                            raise Invalid("Nested style masks are not supported")
                        if key in style:
                            char[style_key][key] = deepcopy(style[key])
                        else:
                            char[style_key].pop(key, None)
        else:
            raise Invalid(f"Unsupported request: {operation}")
        replies.append(reply)
    result["revision"] += 1
    return result, replies


def from_fixture(item):
    if "body" not in item:
        return new_document(item.get("title", ""), item.get("text", ""), item.get("documentId"))
    chars = []
    for element in item["body"]["content"]:
        if "sectionBreak" in element:
            continue
        if "paragraph" not in element:
            raise Invalid("Fixture supports paragraphs only")
        paragraph = element["paragraph"]
        for run in paragraph.get("elements", []):
            if "textRun" not in run:
                raise Invalid("Fixture supports text runs only")
            chars.extend(
                {
                    "c": c,
                    "textStyle": deepcopy(run["textRun"].get("textStyle", {})),
                    "paragraphStyle": deepcopy(paragraph.get("paragraphStyle", {})),
                }
                for c in run["textRun"]["content"]
            )
    if not chars or chars[-1]["c"] != "\n":
        raise Invalid("Structural fixture must end with newline")
    doc = new_document(item.get("title", ""), document_id=item.get("documentId"))
    doc["chars"] = chars
    return doc
