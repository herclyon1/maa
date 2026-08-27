#!/usr/bin/env python3
"""Mask secret-looking values on the way out of the machine.

Why this exists: on 2026-08-23 a wide grep over AUTO-MAS's config printed
WECOM_SECRET into the transcript, and on 2026-08-24 a whole-config dump printed
part of MaaEnd's cdkEncrypted. Both were the same mistake - reaching for the
raw bytes when only the shape was needed - and both are unfixable after the
fact, because a transcript cannot be un-read.

Masking happens by key name, not by looking for high-entropy strings. Entropy
heuristics fire on hashes and IDs we legitimately need to read, and miss short
secrets entirely. Key names are what we actually know.

JSON in, JSON out: the structure survives, so piping a config through this and
then parsing it still works for every field that is not a secret.

    winrun.sh --get 'D:\\path\\config.json' | scripts/mac/redact.py
"""
import json
import re
import sys

MASK = "<已隐藏>"
# Substrings that make a key's value secret. Matched case-insensitively against
# the key name, so "MirrorChyanCDK", "cdkEncrypted" and "SendKey" all hit.
SECRET_KEY_HINTS = (
    "key", "cdk", "secret", "token", "password", "passwd", "credential",
    "sendkey", "webhook", "cookie", "authorization", "auth", "corpsecret",
    "apikey", "access", "private", "signature",
)
# Keys that contain a hint substring but are not secrets. Without this,
# "keyboard", "keymap" and "hotkeys" would be masked in MaaEnd's config.
SECRET_KEY_ALLOW = (
    "keyboard", "keymap", "hotkey", "keyword", "monkey", "keep",
    "accesskeytype", "privateworld",
)


def is_secret_key(key: str) -> bool:
    k = key.lower()
    if any(a in k for a in SECRET_KEY_ALLOW):
        return False
    return any(h in k for h in SECRET_KEY_HINTS)


def walk(obj):
    if isinstance(obj, dict):
        return {k: (MASK if (is_secret_key(str(k)) and isinstance(v, str) and v)
                    else walk(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [walk(v) for v in obj]
    return obj


# For plain text: KEY=value, KEY: value, "KEY": "value", --key=value
_TEXT = re.compile(
    r'(?i)([\'"]?[\w.\-]*(?:' + "|".join(SECRET_KEY_HINTS) + r')[\w.\-]*[\'"]?'
    r'\s*[:=]\s*)([\'"]?)([^\s,;\'"}\]]{4,})(\2)')


def redact_text(text: str) -> str:
    def sub(m):
        key = m.group(1)
        bare = re.sub(r'[^\w.\-]', '', key.split(":")[0].split("=")[0])
        if not is_secret_key(bare):
            return m.group(0)
        return f"{key}{m.group(2)}{MASK}{m.group(4)}"
    return _TEXT.sub(sub, text)


def main() -> int:
    raw = sys.stdin.read()
    stripped = raw.lstrip()
    if stripped[:1] in "{[":
        try:
            sys.stdout.write(json.dumps(walk(json.loads(raw)),
                                        ensure_ascii=False, indent=2))
            sys.stdout.write("\n")
            return 0
        except ValueError:
            pass          # not actually JSON - fall through to the text path
    sys.stdout.write(redact_text(raw))
    return 0


if __name__ == "__main__":
    sys.exit(main())
