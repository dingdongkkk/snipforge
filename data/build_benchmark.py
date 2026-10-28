"""Benchmark sets: requirements + HIDDEN tests (never shown to the model, never used in prompts or repair).

Writes data/benchmark.jsonl (20-task frozen holdout, v1) and data/development.jsonl (10 tasks for tuning).

Each task carries a reference solution used only to prove its hidden tests are correct.
Tasks are deliberately different from the knowledge base to avoid leakage.

    python data/build_benchmark.py
"""
from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from snipforge.validator import run_tests  # noqa: E402


def T(id, requirement, reference, hidden):
    return {"id": id, "requirement": requirement,
            "reference": textwrap.dedent(reference).strip() + "\n",
            "hidden_tests": textwrap.dedent(hidden).strip() + "\n"}


BENCH = [
T("slugify", "Write a function slugify(text) that converts a title into a URL slug: lowercase, words joined by single hyphens, only a-z and 0-9 kept, no leading/trailing hyphens.", '''
import re
def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
''', '''
def test_basic(): assert slugify("Hello World") == "hello-world"
def test_punct(): assert slugify("  TCS: Tech Day 2025!! ") == "tcs-tech-day-2025"
def test_multi(): assert slugify("a -- b") == "a-b"
def test_empty(): assert slugify("") == ""
'''),
T("second-largest", "Write second_largest(nums) that returns the second largest DISTINCT number in a list, or None if it does not exist.", '''
def second_largest(nums):
    s = sorted(set(nums), reverse=True)
    return s[1] if len(s) > 1 else None
''', '''
def test_basic(): assert second_largest([3, 1, 4, 4, 2]) == 3
def test_dupes(): assert second_largest([5, 5, 5]) is None
def test_empty(): assert second_largest([]) is None
def test_negative(): assert second_largest([-1, -2]) == -2
'''),
T("validate-ifsc", "Write is_valid_ifsc(code) that validates an Indian IFSC bank code: 4 uppercase letters, then the digit 0, then 6 uppercase letters or digits (11 characters total). Return a bool.", '''
import re
def is_valid_ifsc(code):
    return isinstance(code, str) and bool(re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", code))
''', '''
def test_valid(): assert is_valid_ifsc("SBIN0001234")
def test_alnum(): assert is_valid_ifsc("HDFC0ABC123")
def test_fifth_char(): assert not is_valid_ifsc("SBIN1001234")
def test_length(): assert not is_valid_ifsc("SBIN000123")
'''),
T("rotate-list", "Write rotate_right(items, k) that returns a new list rotated right by k positions; k may exceed the length; empty list returns empty list.", '''
def rotate_right(items, k):
    if not items: return []
    k %= len(items)
    return items[-k:] + items[:-k] if k else list(items)
''', '''
def test_basic(): assert rotate_right([1, 2, 3, 4, 5], 2) == [4, 5, 1, 2, 3]
def test_big_k(): assert rotate_right([1, 2, 3], 4) == [3, 1, 2]
def test_zero(): assert rotate_right([1, 2], 0) == [1, 2]
def test_empty(): assert rotate_right([], 3) == []
'''),
T("count-words", "Write count_words(text) that returns a dict mapping each lowercase word to its count, ignoring punctuation.", '''
import re
from collections import Counter
def count_words(text):
    return dict(Counter(re.findall(r"[a-z0-9']+", text.lower())))
''', '''
def test_basic(): assert count_words("Hi hi, there!") == {"hi": 2, "there": 1}
def test_empty(): assert count_words("") == {}
'''),
T("parse-duration", "Write parse_duration(s) that converts strings like '1h30m', '45s', '2h5s' or '1h2m3s' into total seconds (int). Raise ValueError for invalid input such as '' or '5x'.", '''
import re
def parse_duration(s):
    m = re.fullmatch(r"(?:(\\d+)h)?(?:(\\d+)m)?(?:(\\d+)s)?", s or "")
    if not s or not m: raise ValueError(s)
    h, mi, se = (int(g or 0) for g in m.groups())
    return h * 3600 + mi * 60 + se
''', '''
def test_hm(): assert parse_duration("1h30m") == 5400
def test_s(): assert parse_duration("45s") == 45
def test_hs(): assert parse_duration("2h5s") == 7205
def test_all(): assert parse_duration("1h2m3s") == 3723
def test_bad():
    for bad in ["", "5x"]:
        try:
            parse_duration(bad); assert False
        except ValueError:
            pass
'''),
T("queue-two-stacks", "Implement a class Queue using two stacks with enqueue(x), dequeue() (raises IndexError when empty) and __len__.", '''
class Queue:
    def __init__(self): self.a, self.b = [], []
    def enqueue(self, x): self.a.append(x)
    def dequeue(self):
        if not self.b:
            while self.a: self.b.append(self.a.pop())
        if not self.b: raise IndexError("empty")
        return self.b.pop()
    def __len__(self): return len(self.a) + len(self.b)
''', '''
def test_fifo():
    q = Queue(); q.enqueue(1); q.enqueue(2); q.enqueue(3)
    assert q.dequeue() == 1 and len(q) == 2
    q.enqueue(4)
    assert [q.dequeue(), q.dequeue(), q.dequeue()] == [2, 3, 4]
def test_empty():
    try:
        Queue().dequeue(); assert False
    except IndexError:
        pass
'''),
T("mask-card", "Write mask_card(number) that masks a card number string, replacing every digit except the last 4 with '*'; non-digit characters such as spaces or dashes are kept as they are.", '''
def mask_card(number):
    total = sum(c.isdigit() for c in number); seen = 0; out = []
    for c in number:
        if c.isdigit():
            seen += 1
            out.append(c if seen > total - 4 else "*")
        else:
            out.append(c)
    return "".join(out)
''', '''
def test_plain(): assert mask_card("1234567812345678") == "************5678"
def test_spaces(): assert mask_card("1234 5678 1234 5678") == "**** **** **** 5678"
def test_short(): assert mask_card("123") == "123"
'''),
T("add-gst", "Write add_gst(amount, rate=18) that returns the amount including GST at the given percentage rate, rounded to 2 decimals. Raise ValueError if amount or rate is negative.", '''
def add_gst(amount, rate=18):
    if amount < 0 or rate < 0: raise ValueError("negative")
    return round(amount * (1 + rate / 100), 2)
''', '''
def test_default(): assert add_gst(100) == 118.0
def test_rate(): assert add_gst(250, 5) == 262.5
def test_round(): assert add_gst(99.99, 12) == 111.99
def test_neg():
    try:
        add_gst(-1); assert False
    except ValueError:
        pass
'''),
T("flatten-dict", "Write flatten_dict(d, sep='.') that flattens a nested dictionary so nested keys are joined with sep, e.g. {'a': {'b': 1}} -> {'a.b': 1}.", '''
def flatten_dict(d, sep=".", prefix=""):
    out = {}
    for k, v in d.items():
        key = f"{prefix}{sep}{k}" if prefix else str(k)
        if isinstance(v, dict) and v:
            out.update(flatten_dict(v, sep, key))
        else:
            out[key] = v
    return out
''', '''
def test_nested(): assert flatten_dict({"a": {"b": 1, "c": {"d": 2}}, "e": 3}) == {"a.b": 1, "a.c.d": 2, "e": 3}
def test_sep(): assert flatten_dict({"x": {"y": 1}}, sep="_") == {"x_y": 1}
def test_flat(): assert flatten_dict({"k": 1}) == {"k": 1}
'''),
T("leap-year", "Write is_leap_year(year) returning True if the year is a Gregorian leap year.", '''
def is_leap_year(year):
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
''', '''
def test_cases():
    assert is_leap_year(2024) and is_leap_year(2000)
    assert not is_leap_year(1900) and not is_leap_year(2023)
'''),
T("longest-common-prefix", "Write longest_common_prefix(strs) that returns the longest common prefix of a list of strings ('' if none or list empty).", '''
import os
def longest_common_prefix(strs):
    return os.path.commonprefix(strs) if strs else ""
''', '''
def test_basic(): assert longest_common_prefix(["flower", "flow", "flight"]) == "fl"
def test_none(): assert longest_common_prefix(["dog", "car"]) == ""
def test_empty(): assert longest_common_prefix([]) == ""
def test_single(): assert longest_common_prefix(["solo"]) == "solo"
'''),
T("factorial", "Write factorial(n) that returns n! for a non-negative integer and raises ValueError for negative input.", '''
import math
def factorial(n):
    if n < 0: raise ValueError("negative")
    return math.factorial(n)
''', '''
def test_values(): assert factorial(0) == 1 and factorial(5) == 120
def test_neg():
    try:
        factorial(-3); assert False
    except ValueError:
        pass
'''),
T("gcd-list", "Write gcd_list(nums) that returns the greatest common divisor of a non-empty list of positive integers.", '''
import math
from functools import reduce
def gcd_list(nums):
    return reduce(math.gcd, nums)
''', '''
def test_basic(): assert gcd_list([12, 18, 24]) == 6
def test_coprime(): assert gcd_list([7, 9]) == 1
def test_single(): assert gcd_list([10]) == 10
'''),
T("top-k-frequent", "Write top_k_frequent(nums, k) returning the k most frequent numbers, most frequent first; ties broken by smaller number first.", '''
from collections import Counter
def top_k_frequent(nums, k):
    return [n for n, _ in sorted(Counter(nums).items(), key=lambda x: (-x[1], x[0]))[:k]]
''', '''
def test_basic(): assert top_k_frequent([1, 1, 1, 2, 2, 3], 2) == [1, 2]
def test_ties(): assert top_k_frequent([5, 4, 4, 5, 3], 2) == [4, 5]
def test_k_large(): assert top_k_frequent([9], 3) == [9]
'''),
T("invert-dict", "Write invert_dict(d) that maps each value to a sorted list of keys that had that value.", '''
def invert_dict(d):
    out = {}
    for k, v in d.items(): out.setdefault(v, []).append(k)
    return {v: sorted(ks) for v, ks in out.items()}
''', '''
def test_basic(): assert invert_dict({"a": 1, "c": 2, "b": 1}) == {1: ["a", "b"], 2: ["c"]}
def test_empty(): assert invert_dict({}) == {}
'''),
T("inventory", "Create an Inventory class with add_item(name, qty), remove_item(name, qty) that raises ValueError if there is not enough stock, get_quantity(name) returning 0 for unknown items, and total_items() returning the sum of all quantities.", '''
class Inventory:
    def __init__(self): self.items = {}
    def add_item(self, name, qty):
        if qty <= 0: raise ValueError("qty")
        self.items[name] = self.items.get(name, 0) + qty
    def remove_item(self, name, qty):
        if self.items.get(name, 0) < qty: raise ValueError("insufficient")
        self.items[name] -= qty
    def get_quantity(self, name): return self.items.get(name, 0)
    def total_items(self): return sum(self.items.values())
''', '''
def test_flow():
    inv = Inventory(); inv.add_item("pen", 5); inv.add_item("pad", 2); inv.remove_item("pen", 3)
    assert inv.get_quantity("pen") == 2 and inv.total_items() == 4 and inv.get_quantity("x") == 0
def test_insufficient():
    inv = Inventory(); inv.add_item("pen", 1)
    try:
        inv.remove_item("pen", 2); assert False
    except ValueError:
        pass
'''),
T("median", "Write median(nums) returning the median of a list of numbers (average of the two middle values for even length); raise ValueError for an empty list.", '''
def median(nums):
    if not nums: raise ValueError("empty")
    s = sorted(nums); n = len(s); m = n // 2
    return s[m] if n % 2 else (s[m - 1] + s[m]) / 2
''', '''
def test_odd(): assert median([3, 1, 2]) == 2
def test_even(): assert median([4, 1, 3, 2]) == 2.5
def test_empty():
    try:
        median([]); assert False
    except ValueError:
        pass
'''),
T("extract-hashtags", "Write extract_hashtags(text) that returns the unique hashtags (without '#', lowercased) in order of first appearance. A hashtag is '#' followed by letters, digits or underscores.", '''
import re
def extract_hashtags(text):
    seen = []
    for t in re.findall(r"#(\\w+)", text):
        t = t.lower()
        if t not in seen: seen.append(t)
    return seen
''', '''
def test_basic(): assert extract_hashtags("Loving #TCS and #GenAI! #tcs") == ["tcs", "genai"]
def test_none(): assert extract_hashtags("no tags here") == []
def test_underscore(): assert extract_hashtags("#tech_day2025 rocks") == ["tech_day2025"]
'''),
T("to-binary", "Write to_binary(n) that returns the binary representation of an integer as a string without the '0b' prefix; negative numbers get a leading '-'. Do not use bin() or format().", '''
def to_binary(n):
    if n == 0: return "0"
    neg, n, d = n < 0, abs(n), []
    while n: d.append(str(n & 1)); n >>= 1
    return ("-" if neg else "") + "".join(reversed(d))
''', '''
def test_values(): assert to_binary(10) == "1010" and to_binary(0) == "0" and to_binary(1) == "1"
def test_negative(): assert to_binary(-5) == "-101"
'''),
T("chunk-string", "Write chunk_string(s, n) that splits a string into pieces of length n (last piece may be shorter); raise ValueError if n <= 0.", '''
def chunk_string(s, n):
    if n <= 0: raise ValueError("n")
    return [s[i:i + n] for i in range(0, len(s), n)]
''', '''
def test_basic(): assert chunk_string("abcdefg", 3) == ["abc", "def", "g"]
def test_empty(): assert chunk_string("", 2) == []
def test_bad():
    try:
        chunk_string("x", 0); assert False
    except ValueError:
        pass
'''),
T("days-until", "Write days_until(target, today) where both are 'YYYY-MM-DD' strings, returning the number of days from today until target (negative if target is in the past).", '''
from datetime import date
def days_until(target, today):
    return (date.fromisoformat(target) - date.fromisoformat(today)).days
''', '''
def test_future(): assert days_until("2025-12-25", "2025-12-01") == 24
def test_past(): assert days_until("2025-01-01", "2025-01-11") == -10
def test_leap(): assert days_until("2024-03-01", "2024-02-28") == 2
'''),
T("validate-gstin-format", "Write is_valid_gstin(gstin) that checks the format of an Indian GSTIN: 2 digits (state code), 10-character PAN (5 letters, 4 digits, 1 letter), 1 alphanumeric entity code (1-9 or A-Z), the letter 'Z', and 1 alphanumeric checksum character. Total 15 characters, uppercase. Return a bool (format check only).", '''
import re
def is_valid_gstin(gstin):
    return isinstance(gstin, str) and bool(re.fullmatch(r"\\d{2}[A-Z]{5}\\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]", gstin))
''', '''
def test_valid(): assert is_valid_gstin("27AAPFU0939F1ZV")
def test_no_z(): assert not is_valid_gstin("27AAPFU0939F1XV")
def test_short(): assert not is_valid_gstin("27AAPFU0939F1Z")
def test_lower(): assert not is_valid_gstin("27aapfu0939f1zv")
'''),
T("matrix-multiply", "Write matrix_multiply(a, b) that multiplies two matrices given as lists of lists and raises ValueError if the dimensions are incompatible.", '''
def matrix_multiply(a, b):
    if not a or not b or len(a[0]) != len(b): raise ValueError("dims")
    return [[sum(x * y for x, y in zip(row, col)) for col in zip(*b)] for row in a]
''', '''
def test_basic(): assert matrix_multiply([[1, 2], [3, 4]], [[5, 6], [7, 8]]) == [[19, 22], [43, 50]]
def test_rect(): assert matrix_multiply([[1, 2, 3]], [[1], [2], [3]]) == [[14]]
def test_bad():
    try:
        matrix_multiply([[1, 2]], [[1, 2]]); assert False
    except ValueError:
        pass
'''),
T("word-wrap", "Write wrap_text(text, width) that wraps text into lines no longer than width characters, breaking only at spaces (a single word longer than width goes on its own line), and returns the list of lines.", '''
def wrap_text(text, width):
    lines, cur = [], ""
    for w in text.split():
        if not cur: cur = w
        elif len(cur) + 1 + len(w) <= width: cur += " " + w
        else: lines.append(cur); cur = w
    if cur: lines.append(cur)
    return lines
''', '''
def test_basic(): assert wrap_text("the quick brown fox jumps", 10) == ["the quick", "brown fox", "jumps"]
def test_long_word(): assert wrap_text("a supercalifragilistic b", 5) == ["a", "supercalifragilistic", "b"]
def test_empty(): assert wrap_text("", 5) == []
'''),
T("csv-total-by-region", "Write total_by_region(csv_text) that takes CSV text with a header row containing columns region and amount (other columns may exist) and returns a dict mapping each region to the total amount as a float rounded to 2 decimals. Blank lines are ignored. Raise ValueError if the region or amount column is missing.", '''
import csv, io
def total_by_region(csv_text):
    rows = csv.DictReader(io.StringIO(csv_text.strip()))
    if not rows.fieldnames or "region" not in rows.fieldnames or "amount" not in rows.fieldnames:
        raise ValueError("missing column")
    out = {}
    for r in rows:
        if not r["region"]: continue
        out[r["region"]] = round(out.get(r["region"], 0.0) + float(r["amount"]), 2)
    return out
''', '''
def test_basic(): assert total_by_region("region,amount\\nnorth,10.5\\nsouth,2\\nnorth,4.25") == {"north": 14.75, "south": 2.0}
def test_extra_cols(): assert total_by_region("id,region,amount\\n1,east,1\\n\\n2,east,2") == {"east": 3.0}
def test_missing():
    try:
        total_by_region("region,value\\nx,1"); assert False
    except ValueError:
        pass
'''),
T("loyalty-tier", "Write loyalty_tier(points) returning 'bronze' for fewer than 1000 points, 'silver' for 1000 to 4999, and 'gold' for 5000 or more. Raise ValueError for negative points.", '''
def loyalty_tier(points):
    if points < 0: raise ValueError("negative")
    return "bronze" if points < 1000 else "silver" if points < 5000 else "gold"
''', '''
def test_bounds():
    assert loyalty_tier(0) == "bronze" and loyalty_tier(999) == "bronze"
    assert loyalty_tier(1000) == "silver" and loyalty_tier(4999) == "silver"
    assert loyalty_tier(5000) == "gold"
def test_negative():
    try:
        loyalty_tier(-1); assert False
    except ValueError:
        pass
'''),
T("active-customers", "Write active_customers(csv_text) that takes CSV text with columns name and status and returns the list of names whose status is 'active' (case-insensitive, surrounding whitespace ignored), in input order.", '''
import csv, io
def active_customers(csv_text):
    return [r["name"] for r in csv.DictReader(io.StringIO(csv_text.strip())) if (r.get("status") or "").strip().lower() == "active"]
''', '''
def test_basic(): assert active_customers("name,status\\nAsha,active\\nRavi,inactive\\nMeera, ACTIVE ") == ["Asha", "Meera"]
def test_none(): assert active_customers("name,status\\nX,closed") == []
'''),
T("late-fee", "Write late_fee(days_late, daily_rate=10, cap=500) returning the late fee as days_late * daily_rate but never more than cap; 0 days returns 0. Raise ValueError if days_late is negative.", '''
def late_fee(days_late, daily_rate=10, cap=500):
    if days_late < 0: raise ValueError("negative")
    return min(days_late * daily_rate, cap)
''', '''
def test_basic(): assert late_fee(3) == 30 and late_fee(0) == 0
def test_cap(): assert late_fee(100) == 500 and late_fee(10, daily_rate=100, cap=700) == 700
def test_negative():
    try:
        late_fee(-1); assert False
    except ValueError:
        pass
'''),
T("csv-column-average", "Write column_average(csv_text, column) that returns the average of a numeric column in CSV text (with a header row) rounded to 2 decimals. Raise ValueError if the column does not exist or there are no data rows.", '''
import csv, io
def column_average(csv_text, column):
    r = csv.DictReader(io.StringIO(csv_text.strip()))
    if not r.fieldnames or column not in r.fieldnames: raise ValueError("column")
    vals = [float(row[column]) for row in r]
    if not vals: raise ValueError("no rows")
    return round(sum(vals) / len(vals), 2)
''', '''
def test_basic(): assert column_average("a,b\\n1,2\\n2,4\\n4,5", "b") == 3.67
def test_missing():
    for args in [("a\\n1", "z"), ("a", "a")]:
        try:
            column_average(*args); assert False
        except ValueError:
            pass
'''),
T("unique-emails", "Implement unique_emails(emails). Strip whitespace and lowercase each string, remove empty strings, remove duplicates while preserving first-seen order. Raise ValueError if any element is not a string. Empty list returns [].", '''
def unique_emails(emails):
    seen, out = set(), []
    for e in emails:
        if not isinstance(e, str): raise ValueError("not a string")
        e = e.strip().lower()
        if e and e not in seen: seen.add(e); out.append(e)
    return out
''', '''
def test_basic(): assert unique_emails([" A@x.com", "a@x.com ", "", "b@y.com"]) == ["a@x.com", "b@y.com"]
def test_empty(): assert unique_emails([]) == []
def test_bad():
    try:
        unique_emails(["a@x.com", 5]); assert False
    except ValueError:
        pass
'''),
T("shipping-fee", "Implement shipping_fee(total, express). Reject negative totals with ValueError. Standard shipping costs 40 below 500 and 0 at or above 500. Express adds 60 to the standard fee. Return an integer for integer inputs.", '''
def shipping_fee(total, express):
    if total < 0: raise ValueError("negative")
    return (40 if total < 500 else 0) + (60 if express else 0)
''', '''
def test_bounds(): assert shipping_fee(499, False) == 40 and shipping_fee(500, False) == 0
def test_express(): assert shipping_fee(500, True) == 60 and shipping_fee(10, True) == 100
def test_int(): assert type(shipping_fee(10, False)) is int
def test_negative():
    try:
        shipping_fee(-1, False); assert False
    except ValueError:
        pass
'''),
]

# Frozen v1 split. HOLDOUT: 5 text, 5 list/dict, 5 numeric, 5 CSV/business-rule tasks.
# DEVELOPMENT is the only set used for prompt tuning.
HOLDOUT = {
    "text": ["slugify", "count-words", "mask-card", "extract-hashtags", "validate-ifsc"],
    "list_dict": ["second-largest", "rotate-list", "flatten-dict", "top-k-frequent", "invert-dict"],
    "numeric": ["add-gst", "leap-year", "median", "gcd-list", "parse-duration"],
    "csv_business": ["csv-total-by-region", "loyalty-tier", "active-customers", "late-fee", "csv-column-average"],
}
DEVELOPMENT = ["factorial", "to-binary", "chunk-string", "longest-common-prefix", "word-wrap", "days-until",
               "matrix-multiply", "validate-gstin-format", "unique-emails", "shipping-fee"]



def main() -> int:
    by_id = {t["id"]: t for t in BENCH}
    bad = 0
    for t in BENCH:
        r = run_tests(t["reference"], t["hidden_tests"])
        ok = r["total"] > 0 and r["passed"] == r["total"]
        bad += not ok
        print(f"{'ok ' if ok else 'BAD'} {t['id']:<24} {r['passed']}/{r['total']} {r.get('error', '')}")
    sets = {"benchmark.jsonl": [(cat, i) for cat, ids in HOLDOUT.items() for i in ids],
            "development.jsonl": [("dev", i) for i in DEVELOPMENT]}
    for fname, items in sets.items():
        with (ROOT / "data" / fname).open("w") as fh:
            for cat, i in items:
                t = by_id[i]
                fh.write(json.dumps({"id": i, "category": cat, "version": "v1", "requirement": t["requirement"],
                                     "hidden_tests": t["hidden_tests"]}) + "\n")
        print(f"{len(items)} tasks -> data/{fname}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
