# Step 14 — The joypad

## Goal

Replace the stub at `0xFF00` with a real joypad, and connect the keyboard to it
through the window.

At the end you can start a game of Tetris, move and rotate pieces, and pause.
It still runs at about 9 frames per second, so it plays in slow motion. Step 13B
fixes the speed.

---

## Theory

### 1. Where the buttons are

All eight buttons are read through one I/O register, `P1`, at `0xFF00`. It is the
first byte of the I/O block.

```
   0xFF00  P1 / JOYP
   ┌─────┬─────┬─────────┬─────────┬───────┬────────┬──────┬───────┐
   │  7  │  6  │    5    │    4    │   3   │   2    │  1   │   0   │
   ├─────┴─────┼─────────┼─────────┼───────┼────────┼──────┼───────┤
   │  unwired  │ select  │ select  │ Start │ Select │  B   │   A   │  if bit 5 is 0
   │ read as 1 │ buttons │  d-pad  │ Down  │  Up    │ Left │ Right │  if bit 4 is 0
   └───────────┴─────────┴─────────┴───────┴────────┴──────┴───────┘
                 written by the CPU   read-only: 0 means pressed
```

The register has three parts:

- **Bits 7-6** are not connected to anything and read as 1. The current stub
  already returns them that way.
- **Bits 5-4** are the select lines. The CPU writes them to choose which group of
  four buttons it wants to read. A 0 selects the group.
- **Bits 3-0** are the four button lines. The CPU only reads them. Each bit
  reports one button of the selected group, and a 0 means that button is held.

Eight buttons fit in four bits because only one group is read at a time. A game
writes the select bits, reads the low nibble, writes the other select bit, and
reads again. A nibble is four bits, half a byte.

### 2. Why it reads backwards

The buttons are wired as a grid of two rows and four columns.

```
                     bit 3      bit 2      bit 1      bit 0
                       │          │          │          │
   bit 4  (d-pad)  ────┼── Down ──┼── Up ────┼── Left ──┼── Right
                       │          │          │          │
   bit 5  (buttons) ───┼── Start ─┼── Select ┼── B ─────┼── A
                       │          │          │          │
                    each column is pulled up to 1 when nothing connects it
```

Each column line has a resistor that holds it at 1. The CPU selects a row by
driving that row line to 0. When a button is held, it connects its row to its
column, so the column reads the row's 0. If the row is not selected, it stays at
1 and the button changes nothing.

This explains the two rules from section 1. A selected row is a 0, and a held
button reads as a 0. It also explains what happens when both rows are selected:
a column reads 0 if a held button in either row pulls it down. That is an AND of
the two groups.

### 3. A worked example

Left and A are held, and nothing else.

```
   CPU writes   bits 5-4   group read      low nibble   P1 reads
   ──────────   ────────   ────────────    ──────────   ────────
   0x20         10         d-pad           1101         0xED     Left is bit 1
   0x10         01         buttons         1110         0xDE     A is bit 0
   0x30         11         nothing         1111         0xFF
   0x00         00         both, ANDed     1100         0xCC     1101 & 1110
```

Every value is built the same way:

```
   0xC0  |  (written value & 0x30)  |  low nibble
   bits 7-6       bits 5-4              bits 3-0
```

The first three rows are what a typical game does. It selects the d-pad, reads,
selects the buttons, reads, and then writes `0x30` to release both rows. Many
games read the same group several times in a row and keep the last value. On
the hardware this gives the lines time to settle after the select bits change.
Here the extra reads cost nothing and return the same value each time.

### 4. The interrupt

`JOYPAD` is interrupt 4, with its vector at `0x0060`. You already handle it; Step
08 built the vector table and `Interrupt.JOYPAD` exists.

The hardware requests it when any of bits 3-0 goes from 1 to 0. On a running
machine that is a button being pressed while its group is selected.

Few games use it. A game reads the buttons once per frame, so it does not need
to be told about a press. The interrupt exists mostly to wake the CPU from
`STOP`, which this emulator still treats as `HALT`. `HALT` already ends when an
enabled interrupt becomes pending, so a working joypad interrupt also wakes a
`HALT` with `IE` bit 4 set, and you get that without extra code.

The version to model is this one: a button goes down, its group is currently
selected, and so the interrupt is requested. Two cases are left out.

- Changing the select bits while a button is held also makes a line fall.
  A game that does this has to ignore the interrupt anyway, because it happens
  on every read.
- Real buttons bounce. One press produces several short falls in a row. A
  keyboard event is clean, so there is nothing to emulate.

### 5. Where button state comes from

`PLAN.md` constraint 1 says the core "exposes a framebuffer and accepts button
state". Step 13A built the first half. This step builds the second.

```
   keyboard ──► pygame events ──► screen/        ──► Bus ──► Joypad
                                  key -> Button
                                  once per frame
```

The keyboard is the frontend's business, and so is the choice of keys. The core
only knows the eight buttons. So the core gets a `Button` type and a way to tell
it which buttons are held, and `screen/` gets a table from pygame key codes to
`Button`.

The window samples the keyboard once per frame, between two calls to
`run_frame`. A game also reads its buttons about once per frame, so nothing is
lost. A key pressed and released inside one frame is missed, and at 9 fps a
frame is 110 ms, so a very quick tap can be lost. At 59.7 fps it is 16.7 ms,
which no person can tap faster than.

### 6. Keys

There is no standard mapping. This one is common among emulators:

```
   Game Boy    key
   ────────    ──────────────
   d-pad       arrow keys
   A           X
   B           Z
   Start       Enter
   Select      Backspace
```

Z is to the left of X on the keyboard, and B is to the left of A on the Game Boy.

### 7. Python concepts this step introduces

- **`enum.Enum`.** Eight buttons are a closed set of names, and Ruby would use
  symbols for them. A symbol can be misspelled and Ruby accepts it. An `Enum`
  member that does not exist is an `AttributeError` at import time, and `mypy`
  reports it before you run anything. `Interrupt` is an `IntEnum` because its
  members are bit numbers used in arithmetic. Decide whether a `Button` needs to
  be an `int` too, or whether the bit it lives in belongs somewhere else.
- **`frozenset`.** Which buttons are held is a set. A `frozenset` cannot be
  changed after it is built, which makes it safe to hand from the frontend to
  the core: neither side can change the other's copy. Ruby has `Set` and
  `#freeze`. In Python the immutable set is a separate type, and `mypy` treats
  `set[Button]` and `frozenset[Button]` as different.
- **Set operators.** `now - before` gives the buttons that were just pressed,
  and `now & group` the ones in a group. Ruby's `Set` has the same operators.
  This is the shortest correct way to find a falling edge across eight lines.
- **A dict as a lookup table.** The key mapping is data, written as a
  `dict[int, Button]` literal. Changing a key should be a change to that table
  and nothing else.

---

## Tasks

### 1. The `Button` type and the `Joypad`

Create `src/gameboy/joypad.py` with a `Button` enum of the eight buttons and a
`Joypad` that owns two things: the select bits the CPU last wrote, and the set of
buttons currently held.

`Joypad` needs `read` and `write`, the same shape as `Serial`. `read` builds the
byte as in section 3. `write` keeps bits 5-4 and ignores the rest, because the
CPU cannot write the button lines.

Each button needs two facts: its group and its bit in the low nibble. Where those
facts live is the main design decision of this task. They can go in the enum
values, in a table next to the enum, or in two tuples of four, one per group.
Pick one and say why in a comment.

**Acceptance:** with Left and A held, the four writes in the section 3 table
read back the four values in its last column. With nothing held, the joypad
returns exactly what the stub returned for every value you write.

---

### 2. Give the bus its joypad

Replace the stub in `Bus.read` with a call to the joypad, and send writes to
`0xFF00` there too, instead of into `self.io`. Construct the joypad in `Bus`, as
the serial port already is: it has no post-boot state a caller could want to
choose.

`memory_map.JOYPAD_NONE_PRESSED` exists only for the stub. Move the constants the
joypad needs next to it, or remove them, so that `memory_map.py` stops describing
the stub.

**Acceptance:** the three existing joypad tests in `test_memory.py` still pass
without changes. They describe the joypad with nothing held, and that has not
changed.

---

### 3. Pressing, and the interrupt

The core needs a way to be told which buttons are held. There are two shapes:

```python
bus.press(Button.A)  # one event at a time
bus.release(Button.A)

bus.hold(frozenset({Button.A, ...}))  # the whole state, once per frame
```

The second shape is a better fit for section 5. The frontend sends the whole
state each frame, and the core finds the difference itself. Either one is
correct. Pick one.

Wherever the difference is computed, the interrupt follows from it. Request
`Interrupt.JOYPAD` when a newly held button belongs to a group that is selected
at that moment. Follow the timer's pattern for this: the joypad method returns a
`bool`, and the bus calls `request`. The joypad does not know about `IF`.

**Acceptance:** pressing A with the buttons group selected sets `IF` bit 4.
Pressing A with only the d-pad selected does not. Holding A for a second frame
does not set it again.

---

### 4. The keyboard

Add input to the `Display` Protocol. A method such as
`held(self) -> frozenset[Button]` is enough. The loop in `screen/loop.py` calls
it once per frame and passes the result to the bus, before `run_frame`.

In the pygame display there are two ways to find out which keys are down:

- keep a set, add to it on `KEYDOWN`, and remove from it on `KEYUP`
- call `pygame.key.get_pressed()`, which returns the state of every key at the
  time of the last event pump

`wants_to_close` already drains the event queue. The second option works on top
of that without reading events twice. Whichever you pick, the queue is still
drained in one place.

The key table from section 6 goes in `pygame_display.py` as a module-level
constant, next to `GREENS`.

**Acceptance:** the fake display in the loop tests can hold buttons, and the
test shows the bus receives them before the frame runs. The `gameboy` package
still imports nothing from `screen`.

---

### 5. Tests

- the four reads from section 3
- nothing selected reads `0xFF` whatever is held
- writes to bits 3-0 are ignored
- both groups selected reads the AND of the two
- the interrupt: requested on a press in a selected group, not on a press in an
  unselected one, and not on a held button
- releasing a button never requests the interrupt
- the loop hands the fake display's held buttons to the bus once per frame

None of them need pygame.

**Acceptance:** `uv run pytest` is green with the `gui` extra absent and with it
present.

---

### 6. Play

```
uv run --extra gui python -m screen path/to/TETRIS.gb --scale 3
```

Press Enter on the title screen, choose a game type and a level with the arrows
and Enter, and play. Left and Right move the piece, X and Z rotate it, and Down
drops it faster. Enter pauses.

Tetris seeds its piece generator from `DIV`, so the first piece depends on how
long you wait on the title screen. If the same piece always comes first, the
timer is not running while the title screen waits.

---

### 7. Docs

`README.md`: add the 13A and 14 rows to the step table. 13A is missing from it.
In "What is missing", remove the joypad paragraph and add a line with the key
map from section 6 to the window's usage.

`instructions.py`: the comment above `_stop` says `STOP` needs the joypad. It
still behaves like `HALT`. Update the comment to say what still blocks it, or
leave it as it is if you decide in question 3 that it is not worth doing.

---

## Hints

- If every button seems held, and the game skips through its menus on its own,
  the low nibble is inverted. A 1 means released.
- If the d-pad works and the buttons do not, or the other way round, the two
  select bits are swapped. Bit 4 selects the d-pad.
- If nothing responds at all, check that writes to `0xFF00` reach the joypad. If
  they still go to `self.io`, the joypad never learns which group is selected.
- If the title screen ignores Enter, check the mapping first:
  `pygame.K_RETURN` is Enter, and `pygame.K_KP_ENTER` is the one on the keypad.
- If the window stops responding when a key is held, the event queue is being
  read in two places and one of them is falling behind.
- If a piece moves two cells per tap, the frontend is sending presses rather
  than state and the same press is applied twice.
- The full register description is at <https://gbdev.io/pandocs/Joypad_Input.html>.

---

## Acceptance criteria

- [ ] `Button` and `Joypad` live in `gameboy/` and import nothing from `screen/`
- [ ] `0xFF00` reads back the section 3 table exactly
- [ ] Writes to bits 3-0 of `0xFF00` are ignored
- [ ] The stub and its constants are gone from `memory.py` and `memory_map.py`
- [ ] `JOYPAD` is requested on a press in a selected group, and only then
- [ ] The key table is a single dict in `screen/`
- [ ] The keyboard is sampled once per frame and passed to the bus
- [ ] A game of Tetris can be started, played and paused from the keyboard
- [ ] `uv run pytest` green, `ruff check`, `ruff format --check`, `mypy` clean

---

## Questions to ask yourself before moving on

1. A real d-pad cannot press Left and Right at the same time, and a keyboard
   can. Some games behave strangely when both are reported. Is filtering that
   the core's job or the frontend's, and what would you filter it to?
2. The interrupt you modelled ignores a fall caused by changing the select bits.
   Write down a sequence of writes and a held button that would request it on
   the hardware and not here. Does any game you know of depend on it?
3. `STOP` waits for a button. With a working joypad, what is still missing to
   model it properly, and which game would show the difference?
4. The bus is now given three devices and builds two itself. Is the rule for
   which is which still the one written in `Bus.__init__`?
