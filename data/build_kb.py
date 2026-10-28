"""Source of truth for the knowledge base. Edit here, then run:

    python data/build_kb.py

Every entry is executed against its own tests before being written to kb.jsonl,
so the retrieval corpus only ever contains verified, working snippets.
"""
from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from snipforge.validator import run_tests  # noqa: E402


def E(id, requirement, tags, code, tests):
    return {"id": id, "requirement": requirement, "tags": tags,
            "code": textwrap.dedent(code).strip() + "\n", "tests": textwrap.dedent(tests).strip() + "\n"}


KB = [
E("validate-email", "Validate an email address and return True if it is well formed.", ["validation", "regex", "string"], '''
import re

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\\.[A-Za-z0-9-]+)*\\.[A-Za-z]{2,}$")


def is_valid_email(email: str) -> bool:
    """Return True if `email` looks like a valid address (local@domain.tld)."""
    if not isinstance(email, str) or len(email) > 254:
        return False
    return bool(_EMAIL_RE.match(email.strip()))
''', '''
def test_valid():
    assert is_valid_email("dev.team+ci@tcs.com")

def test_missing_at():
    assert not is_valid_email("dev.tcs.com")

def test_bad_tld():
    assert not is_valid_email("a@b.c")

def test_non_string():
    assert not is_valid_email(None)
'''),
E("validate-pan", "Validate an Indian PAN card number (5 letters, 4 digits, 1 letter).", ["validation", "regex", "india", "kyc"], '''
import re

_PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")


def is_valid_pan(pan: str) -> bool:
    """Return True if `pan` matches the PAN format, e.g. ABCDE1234F (case-insensitive)."""
    if not isinstance(pan, str):
        return False
    return bool(_PAN_RE.match(pan.strip().upper()))
''', '''
def test_valid():
    assert is_valid_pan("ABCDE1234F")

def test_lowercase_ok():
    assert is_valid_pan("abcde1234f")

def test_wrong_length():
    assert not is_valid_pan("ABCD1234F")

def test_digits_in_wrong_place():
    assert not is_valid_pan("12345ABCDF")
'''),
E("fibonacci", "Return the n-th Fibonacci number efficiently.", ["math", "sequence", "iterative"], '''
def fibonacci(n: int) -> int:
    """Return F(n) with F(0)=0, F(1)=1. Raises ValueError for negative n."""
    if not isinstance(n, int) or n < 0:
        raise ValueError("n must be a non-negative integer")
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a
''', '''
def test_base():
    assert fibonacci(0) == 0 and fibonacci(1) == 1

def test_ten():
    assert fibonacci(10) == 55

def test_large():
    assert fibonacci(90) == 2880067194370816120

def test_negative():
    try:
        fibonacci(-1)
        assert False
    except ValueError:
        pass
'''),
E("palindrome", "Check whether a string is a palindrome ignoring case, spaces and punctuation.", ["string", "two-pointer"], '''
def is_palindrome(text: str) -> bool:
    """Return True if `text` reads the same backwards, considering only alphanumerics."""
    cleaned = [c.lower() for c in text if c.isalnum()]
    return cleaned == cleaned[::-1]
''', '''
def test_sentence():
    assert is_palindrome("A man, a plan, a canal: Panama")

def test_not():
    assert not is_palindrome("hello")

def test_empty():
    assert is_palindrome("")
'''),
E("flatten-list", "Flatten an arbitrarily nested list into a single flat list.", ["list", "recursion"], '''
from typing import Any, Iterable


def flatten(items: Iterable[Any]) -> list:
    """Flatten nested lists/tuples into one list, preserving order. Strings are not split."""
    out: list = []
    stack = [iter(items)]
    while stack:
        for item in stack[-1]:
            if isinstance(item, (list, tuple)):
                stack.append(iter(item))
                break
            out.append(item)
        else:
            stack.pop()
    return out
''', '''
def test_nested():
    assert flatten([1, [2, [3, [4]], 5]]) == [1, 2, 3, 4, 5]

def test_strings_kept():
    assert flatten(["ab", ["cd"]]) == ["ab", "cd"]

def test_empty():
    assert flatten([[], [[]]]) == []
'''),
E("word-frequency", "Count word frequencies in a text and return the top N most common words.", ["string", "counter", "nlp"], '''
import re
from collections import Counter


def top_words(text: str, n: int = 3) -> list[tuple[str, int]]:
    """Return the `n` most frequent lowercase words as (word, count), ties broken alphabetically."""
    words = re.findall(r"[a-z0-9']+", text.lower())
    counts = Counter(words)
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n]
''', '''
def test_basic():
    assert top_words("the cat and the hat and the bat", 2) == [("the", 3), ("and", 2)]

def test_case_insensitive():
    assert top_words("Go go GO", 1) == [("go", 3)]

def test_empty():
    assert top_words("", 3) == []
'''),
E("chunk-list", "Split a list into chunks of size n; the last chunk may be smaller.", ["list", "batching"], '''
from typing import Sequence, TypeVar

T = TypeVar("T")


def chunk(items: Sequence[T], size: int) -> list[list[T]]:
    """Split `items` into consecutive lists of length `size` (last one may be shorter)."""
    if size <= 0:
        raise ValueError("size must be positive")
    return [list(items[i:i + size]) for i in range(0, len(items), size)]
''', '''
def test_even():
    assert chunk([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]

def test_remainder():
    assert chunk([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]

def test_empty():
    assert chunk([], 3) == []

def test_bad_size():
    try:
        chunk([1], 0)
        assert False
    except ValueError:
        pass
'''),
E("merge-sorted", "Merge two sorted lists into one sorted list in linear time.", ["list", "sorting", "two-pointer"], '''
def merge_sorted(a: list, b: list) -> list:
    """Merge two ascending lists into a single ascending list in O(len(a) + len(b))."""
    i = j = 0
    out = []
    while i < len(a) and j < len(b):
        if a[i] <= b[j]:
            out.append(a[i]); i += 1
        else:
            out.append(b[j]); j += 1
    out.extend(a[i:]); out.extend(b[j:])
    return out
''', '''
def test_merge():
    assert merge_sorted([1, 4, 9], [2, 3, 10]) == [1, 2, 3, 4, 9, 10]

def test_one_empty():
    assert merge_sorted([], [1, 2]) == [1, 2]

def test_duplicates():
    assert merge_sorted([1, 1], [1]) == [1, 1, 1]
'''),
E("binary-search", "Implement binary search returning the index of a target in a sorted list or -1.", ["search", "algorithm"], '''
def binary_search(items: list, target) -> int:
    """Return the index of `target` in ascending `items`, or -1 if absent."""
    lo, hi = 0, len(items) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if items[mid] == target:
            return mid
        if items[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1
''', '''
def test_found():
    assert binary_search([1, 3, 5, 7, 9], 7) == 3

def test_missing():
    assert binary_search([1, 3, 5], 4) == -1

def test_empty():
    assert binary_search([], 1) == -1
'''),
E("retry-decorator", "Write a retry decorator that retries a function up to N times with exponential backoff.", ["decorator", "resilience", "backoff"], '''
import functools
import time
from typing import Callable, Tuple, Type


def retry(times: int = 3, base_delay: float = 0.5, exceptions: Tuple[Type[BaseException], ...] = (Exception,),
          sleep: Callable[[float], None] = time.sleep):
    """Retry the wrapped function up to `times` attempts, doubling the delay after each failure."""
    if times < 1:
        raise ValueError("times must be >= 1")

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            delay = base_delay
            for attempt in range(1, times + 1):
                try:
                    return fn(*args, **kwargs)
                except exceptions:
                    if attempt == times:
                        raise
                    sleep(delay)
                    delay *= 2
        return wrapper
    return decorator
''', '''
def test_succeeds_after_failures():
    calls, delays = [], []

    @retry(times=3, base_delay=1, sleep=delays.append)
    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise IOError("boom")
        return "ok"

    assert flaky() == "ok"
    assert delays == [1, 2]

def test_gives_up():
    @retry(times=2, base_delay=0, sleep=lambda s: None)
    def always_fails():
        raise ValueError("nope")

    try:
        always_fails()
        assert False
    except ValueError:
        pass
'''),
E("lru-cache", "Implement an LRU cache class with get and put operations in O(1).", ["class", "data-structure", "cache"], '''
from collections import OrderedDict
from typing import Any, Hashable


class LRUCache:
    """Least-recently-used cache with fixed capacity."""

    def __init__(self, capacity: int):
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self._data: OrderedDict = OrderedDict()

    def get(self, key: Hashable, default: Any = None) -> Any:
        """Return the value for `key` and mark it as recently used."""
        if key not in self._data:
            return default
        self._data.move_to_end(key)
        return self._data[key]

    def put(self, key: Hashable, value: Any) -> None:
        """Insert/update `key`, evicting the least recently used item when full."""
        self._data[key] = value
        self._data.move_to_end(key)
        if len(self._data) > self.capacity:
            self._data.popitem(last=False)

    def __len__(self) -> int:
        return len(self._data)
''', '''
def test_eviction():
    c = LRUCache(2)
    c.put("a", 1); c.put("b", 2); c.get("a"); c.put("c", 3)
    assert c.get("b") is None and c.get("a") == 1 and c.get("c") == 3

def test_len():
    c = LRUCache(1); c.put(1, 1); c.put(2, 2)
    assert len(c) == 1
'''),
E("parse-csv", "Parse CSV text with a header row into a list of dictionaries.", ["csv", "parsing", "io"], '''
import csv
import io


def parse_csv(text: str, delimiter: str = ",") -> list[dict]:
    """Parse CSV `text` (first row = header) into a list of row dicts with stripped values."""
    reader = csv.DictReader(io.StringIO(text.strip()), delimiter=delimiter)
    return [{k.strip(): (v or "").strip() for k, v in row.items()} for row in reader]
''', '''
def test_basic():
    rows = parse_csv("name,age\\nAsha,30\\nRavi,25")
    assert rows == [{"name": "Asha", "age": "30"}, {"name": "Ravi", "age": "25"}]

def test_quoted():
    assert parse_csv('a,b\\n"x, y",2')[0]["a"] == "x, y"
'''),
E("deep-merge", "Deep merge two dictionaries, recursively merging nested dicts.", ["dict", "config", "recursion"], '''
from copy import deepcopy


def deep_merge(base: dict, override: dict) -> dict:
    """Return a new dict where `override` is merged into `base`; nested dicts merge recursively."""
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result
''', '''
def test_nested():
    assert deep_merge({"db": {"host": "x", "port": 1}}, {"db": {"port": 2}}) == {"db": {"host": "x", "port": 2}}

def test_does_not_mutate():
    a = {"k": {"v": 1}}
    deep_merge(a, {"k": {"v": 2}})
    assert a == {"k": {"v": 1}}
'''),
E("password-strength", "Check password strength: at least 8 chars with upper, lower, digit and special character; return list of problems.", ["validation", "security", "string"], '''
import string


def password_problems(password: str) -> list[str]:
    """Return a list of unmet rules; an empty list means the password is strong."""
    problems = []
    if len(password) < 8:
        problems.append("at least 8 characters")
    if not any(c.isupper() for c in password):
        problems.append("an uppercase letter")
    if not any(c.islower() for c in password):
        problems.append("a lowercase letter")
    if not any(c.isdigit() for c in password):
        problems.append("a digit")
    if not any(c in string.punctuation for c in password):
        problems.append("a special character")
    return problems
''', '''
def test_strong():
    assert password_problems("Str0ng!Pass") == []

def test_weak():
    assert set(password_problems("abc")) >= {"at least 8 characters", "an uppercase letter", "a digit"}
'''),
E("token-bucket", "Implement a token-bucket rate limiter class with allow() that returns whether a request may proceed.", ["class", "rate-limit", "time"], '''
import time
from typing import Callable


class TokenBucket:
    """Token bucket: `capacity` burst size, refilled at `rate` tokens per second."""

    def __init__(self, capacity: float, rate: float, clock: Callable[[], float] = time.monotonic):
        if capacity <= 0 or rate <= 0:
            raise ValueError("capacity and rate must be positive")
        self.capacity, self.rate, self._clock = capacity, rate, clock
        self._tokens = capacity
        self._last = clock()

    def allow(self, cost: float = 1.0) -> bool:
        """Consume `cost` tokens if available and return True, else False."""
        now = self._clock()
        self._tokens = min(self.capacity, self._tokens + (now - self._last) * self.rate)
        self._last = now
        if self._tokens >= cost:
            self._tokens -= cost
            return True
        return False
''', '''
def test_burst_then_block():
    t = [0.0]
    b = TokenBucket(2, 1, clock=lambda: t[0])
    assert b.allow() and b.allow() and not b.allow()

def test_refill():
    t = [0.0]
    b = TokenBucket(1, 1, clock=lambda: t[0])
    assert b.allow() and not b.allow()
    t[0] = 1.0
    assert b.allow()
'''),
E("dedupe-ordered", "Remove duplicates from a list while preserving original order.", ["list", "set"], '''
from typing import Hashable, Iterable


def dedupe(items: Iterable[Hashable]) -> list:
    """Return items with duplicates removed, keeping first occurrences in order."""
    seen = set()
    out = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
''', '''
def test_order():
    assert dedupe([3, 1, 3, 2, 1]) == [3, 1, 2]

def test_strings():
    assert dedupe("banana") == ["b", "a", "n"]
'''),
E("group-by", "Group a list of dictionaries by a key and sum an amount field per group, sorted by total descending.", ["dict", "aggregation", "reporting"], '''
from collections import defaultdict


def total_by(records: list[dict], key: str, value: str) -> list[tuple]:
    """Sum `value` per distinct `key`; return (key, total) pairs sorted by total desc, then key."""
    totals: dict = defaultdict(float)
    for rec in records:
        totals[rec[key]] += rec[value]
    return sorted(totals.items(), key=lambda kv: (-kv[1], str(kv[0])))
''', '''
def test_totals():
    orders = [{"c": "a", "amt": 10}, {"c": "b", "amt": 5}, {"c": "a", "amt": 1}]
    assert total_by(orders, "c", "amt") == [("a", 11), ("b", 5)]

def test_empty():
    assert total_by([], "c", "amt") == []
'''),
E("roman-to-int", "Convert a Roman numeral string to an integer.", ["string", "conversion", "math"], '''
_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def roman_to_int(s: str) -> int:
    """Convert a Roman numeral (e.g. 'MCMXCIV') to an int. Raises ValueError on bad symbols."""
    total = 0
    s = s.upper()
    for i, ch in enumerate(s):
        if ch not in _VALUES:
            raise ValueError(f"invalid roman symbol: {ch}")
        v = _VALUES[ch]
        if i + 1 < len(s) and _VALUES.get(s[i + 1], 0) > v:
            total -= v
        else:
            total += v
    return total
''', '''
def test_values():
    assert roman_to_int("MCMXCIV") == 1994 and roman_to_int("iv") == 4

def test_invalid():
    try:
        roman_to_int("ABC")
        assert False
    except ValueError:
        pass
'''),
E("temperature", "Convert temperatures between Celsius and Fahrenheit.", ["conversion", "math"], '''
def convert_temperature(value: float, to: str) -> float:
    """Convert `value` to 'C' or 'F' (from the other scale), rounded to 2 decimals."""
    to = to.upper()
    if to == "F":
        return round(value * 9 / 5 + 32, 2)
    if to == "C":
        return round((value - 32) * 5 / 9, 2)
    raise ValueError("to must be 'C' or 'F'")
''', '''
def test_c_to_f():
    assert convert_temperature(100, "F") == 212

def test_f_to_c():
    assert convert_temperature(32, "c") == 0
'''),
E("primes-sieve", "Return all prime numbers up to n using the Sieve of Eratosthenes.", ["math", "primes", "algorithm"], '''
def primes_upto(n: int) -> list[int]:
    """Return all primes <= n."""
    if n < 2:
        return []
    sieve = bytearray([1]) * (n + 1)
    sieve[0] = sieve[1] = 0
    for i in range(2, int(n ** 0.5) + 1):
        if sieve[i]:
            sieve[i * i::i] = bytearray(len(range(i * i, n + 1, i)))
    return [i for i, is_p in enumerate(sieve) if is_p]
''', '''
def test_small():
    assert primes_upto(20) == [2, 3, 5, 7, 11, 13, 17, 19]

def test_edge():
    assert primes_upto(1) == [] and primes_upto(2) == [2]
'''),
E("moving-average", "Compute the simple moving average of a numeric list with a given window size.", ["math", "statistics", "time-series"], '''
def moving_average(values: list[float], window: int) -> list[float]:
    """Return averages of each full window of length `window` (len(values)-window+1 results)."""
    if window <= 0:
        raise ValueError("window must be positive")
    if window > len(values):
        return []
    total = sum(values[:window])
    out = [total / window]
    for i in range(window, len(values)):
        total += values[i] - values[i - window]
        out.append(total / window)
    return out
''', '''
def test_basic():
    assert moving_average([1, 2, 3, 4, 5], 2) == [1.5, 2.5, 3.5, 4.5]

def test_too_short():
    assert moving_average([1], 3) == []
'''),
E("validate-ipv4", "Validate an IPv4 address string.", ["validation", "network", "string"], '''
def is_valid_ipv4(address: str) -> bool:
    """Return True for dotted-quad IPv4 addresses with octets 0-255 and no leading zeros."""
    parts = address.split(".")
    if len(parts) != 4:
        return False
    for p in parts:
        if not p.isdigit() or (len(p) > 1 and p[0] == "0") or int(p) > 255:
            return False
    return True
''', '''
def test_valid():
    assert is_valid_ipv4("192.168.0.1")

def test_out_of_range():
    assert not is_valid_ipv4("256.1.1.1")

def test_leading_zero():
    assert not is_valid_ipv4("01.1.1.1")
'''),
E("camel-to-snake", "Convert a camelCase or PascalCase identifier to snake_case.", ["string", "regex", "naming"], '''
import re


def camel_to_snake(name: str) -> str:
    """Convert 'parseHTTPResponse' -> 'parse_http_response'."""
    s = re.sub(r"(.)([A-Z][a-z]+)", r"\\1_\\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\\1_\\2", s).lower()
''', '''
def test_camel():
    assert camel_to_snake("userId") == "user_id"

def test_acronym():
    assert camel_to_snake("parseHTTPResponse") == "parse_http_response"
'''),
E("matrix-transpose", "Transpose a 2D matrix (list of lists).", ["matrix", "list"], '''
def transpose(matrix: list[list]) -> list[list]:
    """Return the transpose of a rectangular matrix."""
    if not matrix:
        return []
    if any(len(r) != len(matrix[0]) for r in matrix):
        raise ValueError("matrix must be rectangular")
    return [list(col) for col in zip(*matrix)]
''', '''
def test_rect():
    assert transpose([[1, 2, 3], [4, 5, 6]]) == [[1, 4], [2, 5], [3, 6]]

def test_empty():
    assert transpose([]) == []
'''),
E("group-anagrams", "Group a list of words into lists of anagrams.", ["string", "hashing", "dict"], '''
from collections import defaultdict


def group_anagrams(words: list[str]) -> list[list[str]]:
    """Group words that are anagrams of each other, preserving first-seen order."""
    groups: dict = defaultdict(list)
    for w in words:
        groups["".join(sorted(w.lower()))].append(w)
    return list(groups.values())
''', '''
def test_groups():
    assert group_anagrams(["eat", "tea", "tan", "ate", "nat"]) == [["eat", "tea", "ate"], ["tan", "nat"]]
'''),
E("stack-class", "Implement a Stack class with push, pop, peek, is_empty and size.", ["class", "data-structure"], '''
from typing import Any


class Stack:
    """LIFO stack backed by a Python list."""

    def __init__(self) -> None:
        self._items: list = []

    def push(self, item: Any) -> None:
        self._items.append(item)

    def pop(self) -> Any:
        """Remove and return the top item. Raises IndexError if empty."""
        if not self._items:
            raise IndexError("pop from empty stack")
        return self._items.pop()

    def peek(self) -> Any:
        if not self._items:
            raise IndexError("peek from empty stack")
        return self._items[-1]

    def is_empty(self) -> bool:
        return not self._items

    def size(self) -> int:
        return len(self._items)
''', '''
def test_lifo():
    s = Stack(); s.push(1); s.push(2)
    assert s.peek() == 2 and s.pop() == 2 and s.size() == 1

def test_empty_pop():
    try:
        Stack().pop()
        assert False
    except IndexError:
        pass
'''),
E("timing-decorator", "Write a decorator that measures and logs how long a function takes to run.", ["decorator", "logging", "performance"], '''
import functools
import logging
import time

logger = logging.getLogger(__name__)


def timed(fn):
    """Log the wall-clock duration of each call; the last duration is stored on `wrapper.last_duration`."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        try:
            return fn(*args, **kwargs)
        finally:
            wrapper.last_duration = time.perf_counter() - start
            logger.info("%s took %.4fs", fn.__name__, wrapper.last_duration)
    wrapper.last_duration = None
    return wrapper
''', '''
def test_returns_and_records():
    @timed
    def add(a, b):
        return a + b
    assert add(2, 3) == 5
    assert add.last_duration is not None and add.last_duration >= 0
    assert add.__name__ == "add"
'''),
E("bank-account", "Create a BankAccount class with deposit, withdraw and balance; reject invalid amounts and overdrafts.", ["class", "oop", "validation", "finance"], '''
class InsufficientFundsError(Exception):
    """Raised when a withdrawal exceeds the balance."""


class BankAccount:
    """Simple account with validated deposits and withdrawals."""

    def __init__(self, owner: str, balance: float = 0.0):
        if balance < 0:
            raise ValueError("opening balance cannot be negative")
        self.owner = owner
        self._balance = float(balance)

    @property
    def balance(self) -> float:
        return self._balance

    def deposit(self, amount: float) -> float:
        if amount <= 0:
            raise ValueError("deposit must be positive")
        self._balance += amount
        return self._balance

    def withdraw(self, amount: float) -> float:
        if amount <= 0:
            raise ValueError("withdrawal must be positive")
        if amount > self._balance:
            raise InsufficientFundsError(f"balance {self._balance} < {amount}")
        self._balance -= amount
        return self._balance
''', '''
def test_flow():
    a = BankAccount("Asha", 100)
    a.deposit(50); a.withdraw(30)
    assert a.balance == 120

def test_overdraft():
    try:
        BankAccount("x", 10).withdraw(20)
        assert False
    except InsufficientFundsError:
        pass

def test_negative_deposit():
    try:
        BankAccount("x").deposit(-5)
        assert False
    except ValueError:
        pass
'''),
E("paginate", "Paginate a list: return items for a given page number and page size with total pages.", ["list", "api", "pagination"], '''
import math


def paginate(items: list, page: int, per_page: int = 10) -> dict:
    """Return {'items', 'page', 'per_page', 'total', 'pages'} for a 1-based `page`."""
    if page < 1 or per_page < 1:
        raise ValueError("page and per_page must be >= 1")
    start = (page - 1) * per_page
    return {"items": items[start:start + per_page], "page": page, "per_page": per_page,
            "total": len(items), "pages": math.ceil(len(items) / per_page)}
''', '''
def test_page2():
    r = paginate(list(range(25)), 2, 10)
    assert r["items"] == list(range(10, 20)) and r["pages"] == 3

def test_past_end():
    assert paginate([1, 2], 5, 10)["items"] == []
'''),
E("json-config", "Load a JSON configuration string and fill missing keys from defaults.", ["json", "config", "dict"], '''
import json


def load_config(text: str, defaults: dict) -> dict:
    """Parse JSON `text` and return defaults overridden by its values. Raises ValueError on bad JSON."""
    try:
        data = json.loads(text) if text.strip() else {}
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid config JSON: {e}") from e
    if not isinstance(data, dict):
        raise ValueError("config root must be an object")
    return {**defaults, **data}
''', '''
def test_defaults():
    assert load_config('{"port": 9000}', {"host": "localhost", "port": 8000}) == {"host": "localhost", "port": 9000}

def test_bad_json():
    try:
        load_config("{bad", {})
        assert False
    except ValueError:
        pass
'''),
E("date-diff", "Calculate the number of days between two dates given as YYYY-MM-DD strings.", ["date", "datetime", "parsing"], '''
from datetime import date


def days_between(start: str, end: str) -> int:
    """Return (end - start) in days; negative if end is before start."""
    return (date.fromisoformat(end) - date.fromisoformat(start)).days
''', '''
def test_basic():
    assert days_between("2024-01-01", "2024-03-01") == 60

def test_negative():
    assert days_between("2024-01-10", "2024-01-01") == -9
'''),
E("dataclass-invoice", "Create a dataclass for an invoice line item with quantity, unit price, tax rate and a total property.", ["dataclass", "finance", "oop"], '''
from dataclasses import dataclass


@dataclass(frozen=True)
class LineItem:
    """Invoice line; `tax_rate` is a percentage (e.g. 18 for 18%)."""
    name: str
    quantity: int
    unit_price: float
    tax_rate: float = 0.0

    def __post_init__(self):
        if self.quantity < 0 or self.unit_price < 0 or self.tax_rate < 0:
            raise ValueError("quantity, unit_price and tax_rate must be non-negative")

    @property
    def subtotal(self) -> float:
        return round(self.quantity * self.unit_price, 2)

    @property
    def total(self) -> float:
        return round(self.subtotal * (1 + self.tax_rate / 100), 2)
''', '''
def test_total():
    assert LineItem("pen", 3, 10.0, 18).total == 35.4

def test_negative():
    try:
        LineItem("x", -1, 1)
        assert False
    except ValueError:
        pass
'''),
E("balanced-brackets", "Check whether brackets (), [], {} in a string are balanced.", ["stack", "string", "parsing"], '''
def is_balanced(text: str) -> bool:
    """Return True if every bracket is closed in the correct order."""
    pairs = {")": "(", "]": "[", "}": "{"}
    stack = []
    for ch in text:
        if ch in "([{":
            stack.append(ch)
        elif ch in pairs:
            if not stack or stack.pop() != pairs[ch]:
                return False
    return not stack
''', '''
def test_balanced():
    assert is_balanced("{[()()]}")

def test_unbalanced():
    assert not is_balanced("([)]") and not is_balanced("((")
'''),
E("run-length", "Run-length encode a string, e.g. 'aaabcc' -> 'a3b1c2', and decode it back.", ["string", "compression"], '''
import re


def rle_encode(text: str) -> str:
    """Encode runs as <char><count>."""
    if not text:
        return ""
    out, prev, count = [], text[0], 1
    for ch in text[1:]:
        if ch == prev:
            count += 1
        else:
            out.append(f"{prev}{count}")
            prev, count = ch, 1
    out.append(f"{prev}{count}")
    return "".join(out)


def rle_decode(encoded: str) -> str:
    return "".join(ch * int(n) for ch, n in re.findall(r"(\\D)(\\d+)", encoded))
''', '''
def test_roundtrip():
    assert rle_encode("aaabcc") == "a3b1c2"
    assert rle_decode("a3b1c2") == "aaabcc"

def test_empty():
    assert rle_encode("") == ""
'''),
E("parse-log-line", "Parse a log line like '2024-05-01 12:00:03 ERROR db timeout' into a dict with date, time, level and message.", ["parsing", "regex", "logging"], '''
import re

_LOG_RE = re.compile(r"^(?P<date>\\d{4}-\\d{2}-\\d{2})\\s+(?P<time>\\d{2}:\\d{2}:\\d{2})\\s+(?P<level>[A-Z]+)\\s+(?P<message>.*)$")


def parse_log_line(line: str) -> dict | None:
    """Return {'date','time','level','message'} or None if the line doesn't match."""
    m = _LOG_RE.match(line.strip())
    return m.groupdict() if m else None
''', '''
def test_parse():
    assert parse_log_line("2024-05-01 12:00:03 ERROR db timeout") == {
        "date": "2024-05-01", "time": "12:00:03", "level": "ERROR", "message": "db timeout"}

def test_no_match():
    assert parse_log_line("garbage") is None
'''),
E("read-write-json-file", "Save a dictionary to a JSON file and load it back safely.", ["file", "io", "json"], '''
import json
import os
import tempfile
from pathlib import Path


def save_json(path: str, data: dict) -> None:
    """Atomically write `data` as pretty JSON to `path`."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    with os.fdopen(fd, "w") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, p)


def load_json(path: str, default=None):
    """Load JSON from `path`, returning `default` if the file is missing."""
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text())
''', '''
def test_roundtrip():
    import tempfile, os
    d = tempfile.mkdtemp()
    f = os.path.join(d, "x", "cfg.json")
    save_json(f, {"a": 1})
    assert load_json(f) == {"a": 1}

def test_missing():
    assert load_json("/nonexistent/zzz.json", default={}) == {}
'''),
E("http-get-json", "Fetch JSON from a REST API URL with timeout and error handling.", ["http", "api", "network", "requests"], '''
import json
import urllib.error
import urllib.request


def fetch_json(url: str, timeout: float = 10.0, headers: dict | None = None) -> dict:
    """GET `url` and decode the JSON body. Raises RuntimeError with context on failure."""
    req = urllib.request.Request(url, headers={"Accept": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} for {url}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"cannot reach {url}: {e.reason}") from e
''', '''
def test_signature_only():
    import inspect
    assert list(inspect.signature(fetch_json).parameters) == ["url", "timeout", "headers"]
'''),
E("sqlite-crud", "Create a SQLite table for users and functions to insert and fetch users by email.", ["database", "sqlite", "crud"], '''
import sqlite3


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL)")
    conn.commit()


def add_user(conn: sqlite3.Connection, name: str, email: str) -> int:
    """Insert a user and return its id (parameterised query, safe from SQL injection)."""
    cur = conn.execute("INSERT INTO users (name, email) VALUES (?, ?)", (name, email))
    conn.commit()
    return cur.lastrowid


def get_user_by_email(conn: sqlite3.Connection, email: str) -> dict | None:
    row = conn.execute("SELECT id, name, email FROM users WHERE email = ?", (email,)).fetchone()
    return {"id": row[0], "name": row[1], "email": row[2]} if row else None
''', '''
def test_crud():
    import sqlite3
    c = sqlite3.connect(":memory:")
    init_db(c)
    uid = add_user(c, "Asha", "asha@x.com")
    assert get_user_by_email(c, "asha@x.com") == {"id": uid, "name": "Asha", "email": "asha@x.com"}
    assert get_user_by_email(c, "none@x.com") is None
'''),
]


def main() -> int:
    out = ROOT / "data" / "kb.jsonl"
    failures = 0
    with out.open("w") as fh:
        for e in KB:
            r = run_tests(e["code"], e["tests"])
            ok = r["total"] > 0 and r["passed"] == r["total"]
            print(f"{'ok ' if ok else 'BAD'} {e['id']:<22} {r['passed']}/{r['total']} {r.get('error', '')}")
            if not ok:
                failures += 1
                for res in r["results"]:
                    if not res["passed"]:
                        print("    ", res)
                continue
            fh.write(json.dumps(e) + "\n")
    print(f"\n{len(KB) - failures}/{len(KB)} snippets verified and written to {out}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
