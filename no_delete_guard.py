#!/usr/bin/env python3
"""
PreToolUse Hook for Antigravity: Hard-blocks any command that attempts to delete files.
"""

import json
import re
import sys

FORBIDDEN_PATTERNS = [
    r"(^|[;&|\s])rm(\s|$)",
    r"(^|[;&|\s])rmdir(\s|$)",
    r"(^|[;&|\s])unlink(\s|$)",
    r"(^|[;&|\s])trash(\s|$)",
    r"(^|[;&|\s])srm(\s|$)",
    r"-delete(\s|$)",
    r"shutil\.rmtree",
    r"os\.remove",
    r"os\.unlink",
    r"\.unlink\(",
]


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        print(json.dumps({"decision": "allow"}))
        return

    tool_call = payload.get("toolCall", {})
    args = tool_call.get("args", {})
    cmd = args.get("CommandLine", "")

    for pattern in FORBIDDEN_PATTERNS:
        if re.search(pattern, cmd):
            print(
                json.dumps({
                    "decision": "deny",
                    "reason": "CHẶN BỞI CHẾ ĐỘ AN TOÀN: Không được phép xoá file dưới mọi hình thức (rm, rmdir, unlink, trash bị khoá cứng).",
                })
            )
            return

    print(json.dumps({"decision": "allow"}))


if __name__ == "__main__":
    main()
