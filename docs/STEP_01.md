# Step 01 — Project scaffolding & bit primitives

## Goal

End this step with a Python project you can lint, type-check and test in one
command, plus the handful of bit-twiddling helpers that every later component
will be built on top of.

---

## Theory

### 1. Why bit primitives are step one

The Game Boy CPU is 8-bit. Its registers hold values 0–255 and *wrap around*:
`0xFF + 1 == 0x00`, and that wrap sets the carry flag. Addresses are 16-bit and
wrap at `0xFFFF`.

Python integers are arbitrary precision. `0xFF + 1` is `256`, and it will stay
`256` forever, silently corrupting every register it touches. C would have
wrapped for you; Python will not. (Ruby behaves the same way here — `Integer` is
also unbounded — so this is not a Python surprise for you, but it *is* an
emulation surprise: in a C emulator `uint8_t` does the masking for free.)

So the rule for the whole project: **every arithmetic result that lands in an
8-bit register must be masked with `& 0xFF`, every 16-bit one with `& 0xFFFF`.**
Rather than sprinkle those masks over 500 opcodes, we write them once, name
them, and test them.

### 2. The bit operations you will actually need

| Operation | Expression | Used for |
| --- | --- | --- |
| Wrap to 8 bits | `v & 0xFF` | Every ALU result, every register store |
| Wrap to 16 bits | `v & 0xFFFF` | Program counter, stack pointer, `HL` |
| Test bit *n* | `(v >> n) & 1` | Flags, `BIT` opcodes, LCD status |
| Set bit *n* | `v \| (1 << n)` | `SET` opcodes, raising interrupt flags |
| Clear bit *n* | `v & ~(1 << n)` | `RES` opcodes, acknowledging interrupts |
| Split 16 → two 8 | `v >> 8`, `v & 0xFF` | Reading `BC` as `B` and `C` |
| Join two 8 → 16 | `(hi << 8) \| lo` | Writing `BC` from `B` and `C` |

Two subtleties worth internalising now:

- **`~` on a Python int gives a negative number.** `~(1 << 3)` is `-9`, not
  `0xF7`. `v & -9` still produces the right answer for non-negative `v`, but the
  intermediate is not what a C programmer expects. Mask the result to be safe
  and explicit.
- **Endianness.** The Game Boy is **little-endian**: the 16-bit value `0x1234`
  stored at address `0xC000` occupies `0xC000 = 0x34` (low byte first) and
  `0xC001 = 0x12`. Every 16-bit read and write in this project goes low byte
  first. Get it wrong once and you will chase the bug for hours.

### 3. Signed 8-bit values

A few instructions (`JR`, `ADD SP,e8`) take a *signed* 8-bit offset: the byte
`0xFF` means −1, not 255. The conversion is two's complement: if bit 7 is set,
subtract 256.

### 4. Python project anatomy (vs. Ruby)

| Ruby | Python | Notes |
| --- | --- | --- |
| `Gemfile` + `.gemspec` | `pyproject.toml` | One file for metadata *and* tool config |
| `bundler` | `uv` | `uv` is the fast modern one; resolves, locks, creates the venv |
| `Gemfile.lock` | `uv.lock` | Commit it |
| `lib/my_gem/` | `src/gameboy/` | The "src layout" — see below |
| autoloading (Zeitwerk) | explicit `import` | Nothing is loaded for you, ever |
| `lib/my_gem.rb` | `src/gameboy/__init__.py` | Marks a directory as a package |
| RSpec | pytest | Plain `assert`, no `expect().to` DSL |
| `bundle exec rspec` | `uv run pytest` | |
| Sorbet / RBS | type hints + `mypy` | Types live inline in the signature |

**Why `src/` layout?** If your package sits at the repo root, `import gameboy`
silently picks up the working-directory copy, so your tests may pass against
files that are not actually installed. Putting the code under `src/` forces the
import to go through the installed package, which is what your users get. It is
the current community default and it costs nothing to adopt now.

**`__init__.py`** is what makes a directory a package. An empty one is normal and
expected — do not feel obliged to put anything in it.

---

## Tasks

### 1. Initialise the project

Create the repo skeleton with `uv`:

```
uv init --lib --name gameboy .
```

Then check what it generated and adjust: you want `requires-python = ">=3.12"`
at least (we will use `match` statements and modern typing syntax).

Target layout:

```
gb-emulator/
├── pyproject.toml
├── uv.lock
├── README.md
├── docs/
├── src/
│   └── gameboy/
│       ├── __init__.py
│       └── bits.py
└── tests/
    └── test_bits.py
```

### 2. Add the dev toolchain

```
uv add --dev pytest ruff mypy
```

### 3. Configure the tools in `pyproject.toml`

Add sections for:

- `[tool.ruff]` — set `line-length`, and in `[tool.ruff.lint]` select at least
  `E`, `F`, `I` (import sorting), `UP` (pyupgrade), `B` (bugbear).
- `[tool.mypy]` — `strict = true`, and point `files` at `src` and `tests`.
- `[tool.pytest.ini_options]` — `testpaths = ["tests"]`.

### 4. Write `src/gameboy/bits.py`

Implement these, all fully type-hinted:

```python
def u8(value: int) -> int: ...          # wrap to 8 bits
def u16(value: int) -> int: ...         # wrap to 16 bits
def to_signed8(value: int) -> int: ...  # 0xFF -> -1
def get_bit(value: int, bit: int) -> bool: ...
def set_bit(value: int, bit: int) -> int: ...
def clear_bit(value: int, bit: int) -> int: ...
def high_byte(value: int) -> int: ...   # 0x1234 -> 0x12
def low_byte(value: int) -> int: ...    # 0x1234 -> 0x34
def join_bytes(high: int, low: int) -> int: ...  # (0x12, 0x34) -> 0x1234
```

Add a module docstring explaining the masking rule from the theory section —
future-you will thank present-you.

### 5. Write `tests/test_bits.py`

Cover at minimum:

- `u8` wraps: `u8(0x100) == 0x00`, `u8(0x1FF) == 0xFF`, `u8(-1) == 0xFF`
- `u16` wraps: `u16(0x10000) == 0x0000`
- `to_signed8`: `0x00 → 0`, `0x7F → 127`, `0x80 → -128`, `0xFF → -1`
- bit helpers round-trip: setting then clearing bit *n* returns the original
- `join_bytes(high_byte(v), low_byte(v)) == v` for a few 16-bit values

### 6. Add a `.gitignore` and a `README.md`

`.gitignore`: at least `__pycache__/`, `.venv/`, `*.pyc`, `.mypy_cache/`,
`.pytest_cache/`, `.ruff_cache/`, and `*.gb` / `*.sav` (never commit ROMs).

`README.md`: what the project is, how to install, how to run the checks.

---

## Hints

- **`uv run <cmd>`** runs a command inside the project venv without you
  activating anything — it is `bundle exec`.
- `u8(-1)` should give `0xFF`, and `-1 & 0xFF` already does exactly that in
  Python. Python's `%` and `&` follow the sign of the *divisor/mask*, unlike C.
  This is one of the rare places where Python's semantics are the ones you want.
- For `to_signed8`, either the explicit `if value & 0x80: value -= 256`, or the
  one-liner `int.from_bytes(bytes([value]), "little", signed=True)`. Write the
  explicit one first; you should be able to explain why it works.
- `get_bit` returns `bool`, not `int` — the flag registers are booleans in
  disguise, and returning `bool` keeps `if cpu.flag_z:` honest. Beware:
  `bool` *is* a subclass of `int` in Python (`True + True == 2`), a wart with no
  Ruby equivalent.
- Prefer plain functions over a class here. There is no state. Python is not
  Ruby: a module of functions is idiomatic, not a code smell.
- Parametrised tests are a good fit and are how pytest replaces RSpec's shared
  examples:
  ```python
  @pytest.mark.parametrize(("raw", "expected"), [(0x00, 0), (0x80, -128), (0xFF, -1)])
  def test_to_signed8(raw: int, expected: int) -> None:
      assert to_signed8(raw) == expected
  ```
- Type-hint your test functions too (`-> None`), otherwise `mypy --strict`
  skips them entirely as untyped.

---

## Acceptance criteria

- [ ] `uv run pytest` — all tests pass, and there are at least 8 of them.
- [ ] `uv run ruff check .` — clean.
- [ ] `uv run ruff format --check .` — clean.
- [ ] `uv run mypy` — clean under `strict = true`, zero `Any`, zero `# type: ignore`.
- [ ] `uv run python -c "from gameboy.bits import u8; print(hex(u8(0x1FF)))"` prints `0xff`.
- [ ] `uv.lock` and `pyproject.toml` are committed; `.venv/` is not.
- [ ] You can explain, without looking: why `& 0xFF` is mandatory, what
      little-endian means for a 16-bit read, and why `src/` layout exists.

---

## Questions to ask yourself before moving on

1. If `u8` returned the value unmasked, which later component would break first,
   and how would the bug present itself?
2. Why does `get_bit` take the bit index rather than a mask?
3. `join_bytes(0x12, 0x34)` is `0x1234` — but in memory those bytes are stored
   in the opposite order. Where should the swap live: in `bits.py`, or in the
   memory bus? (There is a defensible answer either way. Pick one and be
   consistent — Step 03 will hold you to it.)

When these pass, ping me and I will review the code before we start Step 02.
