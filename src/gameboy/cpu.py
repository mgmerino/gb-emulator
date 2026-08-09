"""Reference table:
| Register | Width | Conventional use                                              |
| -------- | ----- | ------------------------------------------------------------- |
| `A`      | 8     | The accumulator. Every ALU result ends here                  |
| `F`      | 8     | Flags. Not addressable directly, only through `AF`            |
| `B`, `C` | 8     | General purpose.                                              |
| `D`, `E` | 8     | General purpose                                               |
| `H`, `L` | 8     | General purpose, but `HL` is *the* pointer register           |
| `SP`     | 16    | Stack pointer.                                                |
| `PC`     | 16    | Program counter.                                              |
"""

from dataclasses import dataclass

from gameboy.bits import get_bit, high_byte, join_bytes, low_byte

# Since masking is _expected_ to be executed from the top layer, we want to ensure
# no invalid values slip into the Registers class.
#
# The properties are listed too. Their setters run `high_byte`/`low_byte`, which
# mask, so a too-wide value assigned to a pair reaches both halves already in
# range and the guard on the halves never fires.
_WIDTHS = {
    "a": 0xFF,
    "b": 0xFF,
    "c": 0xFF,
    "d": 0xFF,
    "e": 0xFF,
    "h": 0xFF,
    "l": 0xFF,
    "f": 0xFF,
    "sp": 0xFFFF,
    "pc": 0xFFFF,
    "af": 0xFFFF,
    "bc": 0xFFFF,
    "de": 0xFFFF,
    "hl": 0xFFFF,
}


@dataclass(slots=True)
class Registers:
    a: int = 0  # 8 bits (a-l)
    b: int = 0
    c: int = 0
    d: int = 0
    e: int = 0
    h: int = 0
    l: int = 0
    sp: int = 0  # 16 bits (sp & pc)
    pc: int = 0
    z_flag: bool = False  # bit 7
    n_flag: bool = False  # bit 6
    h_flag: bool = False  # bit 5
    c_flag: bool = False  # bit 4

    if __debug__:

        def __setattr__(self, name: str, value: object) -> None:
            width = _WIDTHS.get(name)
            # isinstance narrows `value` to int for the comparison, and rejects
            # anything that is not an integer.
            if width is not None and (
                not isinstance(value, int) or not 0 <= value <= width
            ):
                raise ValueError(f"{value!r} does not fit in register {name}")
            object.__setattr__(self, name, value)

    @property
    def f(self) -> int:
        return (
            (0x80 if self.z_flag else 0)
            | (0x40 if self.n_flag else 0)
            | (0x20 if self.h_flag else 0)
            | (0x10 if self.c_flag else 0)
        )

    @f.setter
    def f(self, value: int) -> None:
        self.z_flag = get_bit(value, 7)
        self.n_flag = get_bit(value, 6)
        self.h_flag = get_bit(value, 5)
        self.c_flag = get_bit(value, 4)

    @property
    def af(self) -> int:
        return join_bytes(self.a, self.f)

    @af.setter
    def af(self, value: int) -> None:
        self.a = high_byte(value)
        self.f = low_byte(value)

    @property
    def bc(self) -> int:
        return join_bytes(self.b, self.c)

    @bc.setter
    def bc(self, value: int) -> None:
        self.b = high_byte(value)
        self.c = low_byte(value)

    @property
    def de(self) -> int:
        return join_bytes(self.d, self.e)

    @de.setter
    def de(self, value: int) -> None:
        self.d = high_byte(value)
        self.e = low_byte(value)

    @property
    def hl(self) -> int:
        return join_bytes(self.h, self.l)

    @hl.setter
    def hl(self, value: int) -> None:
        self.h = high_byte(value)
        self.l = low_byte(value)
