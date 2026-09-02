# Step 12A — Sprites and OAM

## Goal

Add the second layer. Step 11B draws the background; this part draws objects on
top of it, line by line, and moves OAM from the bus to the PPU so the renderer
can read it.

Three registers join the map:

| Address | Name | What it is |
| --- | --- | --- |
| `0xFF46` | `DMA` | write a page number, get 160 bytes copied into OAM |
| `0xFF48` | `OBP0` | object palette 0, same shape as `BGP` |
| `0xFF49` | `OBP1` | object palette 1 |

And two `LCDC` bits: bit 1 turns objects on, bit 2 makes them 8×16 instead of
8×8.

Step 12B adds the window and closes the composition. The window is not in this
part.

---

## Theory

### 1. The map

```
0xFE00 ┌──────────────┐ ─┐
       │  entry 0     │  │  4 bytes
0xFE04 ├──────────────┤  │
       │  entry 1     │  ├── OAM · 160 bytes · 40 entries
0xFE08 ├──────────────┤  │
       │     ...      │  │
0xFE9C ├──────────────┤  │
       │  entry 39    │  │
0xFE9F └──────────────┘ ─┘
```

One entry per object, 40 of them, fixed. There is no list, no count and no
terminator: all 40 exist all the time. A game hides an object by parking it at
coordinates the screen does not reach.

Objects read their pixels from the same tile data at `0x8000`–`0x97FF` the
background uses, and always through the `0x8000` method with an unsigned index.
`LCDC` bit 4 does not apply to them. So a tile can be shared between the two
layers, and Step 11B's `decode_row_index` works unchanged.

What objects do not have is a map. The background gets its positions from a
32×32 grid of cells; an object carries its own X and Y in its entry. That is the
whole structural difference between the layers.

### 2. How a pixel gets decided

Both layers produce a colour index 0–3 for a pixel. Each layer has its own
palette turning that index into a shade.

```
   background:  tile map ──► tile data ──► index ──► BGP  ──► shade
   objects:     OAM entry ──► tile data ──► index ──► OBP0 or OBP1 ──► shade
```

For one pixel of one line, in order:

1. The background renderer from 11B writes a shade into `framebuffer[x]` and its
   raw index into `line_indices[x]`.
2. If objects are enabled, the object renderer looks for an object covering `x`.
3. If it finds one whose colour index is not 0, it may overwrite
   `framebuffer[x]`.

Sections 5 to 7 are the three questions hiding in "may": which objects are on
this line, which of them wins the pixel, and whether the winner beats the
background.

`line_indices` exists for step 3 of that list. 11B wrote it and nothing has read
it until now.

### 3. An entry is four bytes

```
byte 0   Y       screen row of the top edge, plus 16
byte 1   X       screen column of the left edge, plus 8
byte 2   tile    index into tile data, always the 0x8000 method
byte 3   flags   │ 7 │ 6 │ 5 │ 4 │ 3 │ 2 │ 1 │ 0 │
                   │   │   │   │   └───┴───┴───┴── CGB only, ignore on DMG
                   │   │   │   └────────────────── palette: 0 = OBP0, 1 = OBP1
                   │   │   └────────────────────── X flip
                   │   └────────────────────────── Y flip
                   └────────────────────────────── behind the background
```

### 4. Why Y is offset by 16 and X by 8

An object has to be able to slide off the top and left edges, half visible. With
unsigned bytes and no offset the smallest coordinate is 0, so nothing could sit
partly above row 0.

The offsets are the largest object size in each axis: 16 rows tall, 8 columns
wide. Y = 0 puts the whole object above the screen, and X = 0 puts it entirely to
the left, so both are the "fully hidden" value.

```
     Y = 16  ─►  top edge on screen row 0
     Y = 24  ─►  top edge on screen row 8
     Y = 0   ─►  16 rows above the screen, invisible at either size

     X = 8   ─►  left edge on screen column 0
     X = 0   ─►  8 columns left of the screen, invisible
```

Screen position is `y - 16` and `x - 8`. An 8×16 object shows at least one row
for Y in 1–159; an 8×8 one for Y in 9–159. Either shows at least one column for
X in 1–167.

### 5. Which objects are on this line

The hardware walks OAM during mode 2, entry 0 to entry 39, and keeps the first
ten whose vertical range covers the current line. The number ten is the size of
the buffer it fills. It cannot keep an eleventh, so an eleventh object on a line
does not appear.

The test is on Y alone:

```
    height = 16 if LCDC bit 2 else 8

    covered  ⟺  ly + 16 >= entry.y  and  ly + 16 < entry.y + height

    row within the object = ly + 16 - entry.y        # 0 … height-1
```

X is not consulted. An object parked at X = 0 is invisible and still takes one of
the ten slots.

Games work with the limit rather than around it. Rotating the order of entries in
OAM between frames changes which ten survive, so with twelve objects on a line
each one is drawn most frames and dropped some. That is the flicker on sprite-
heavy DMG games, and it is a deliberate technique.

### 6. Which of them wins a pixel

Two objects can overlap. On the DMG the one with the smaller X is in front. If
two share an X, the one earlier in OAM is in front.

That ordering is separate from the selection in section 5, and it runs on the
same ten entries afterwards:

```
    selection order   OAM order, entry 0 upward       decides who is dropped
    priority order    by X, ties by OAM index         decides who is on top
```

Getting these two the same way round is a common bug. Selecting the ten by X
would keep the wrong ten; ordering by OAM index would put the wrong object on
top.

The pixel goes to the first object in priority order whose colour index at that
column is not 0. Once an object claims a pixel, the objects behind it are out of
the running for it, whatever happens next.

### 7. Transparency and the flag against the background

Colour index 0 in an object tile means transparent. The background shows through
and `OBP0`/`OBP1` bits 1-0 are never used, which is why they are documented as
ignored. An object is an 8×8 stamp with a hole cut in it wherever index 0 lands.

Flag bit 7 decides what happens when the object does have a pixel there:

```
    bit 7 = 0    the object draws over the background, always

    bit 7 = 1    the object draws only where the background's colour index is 0
```

Bit 7 set is how a game puts an object behind scenery. The background's index 0
is its "nothing here" colour, so the object shows through the gaps and is covered
by everything else.

The comparison is against the background's colour *index*, which is what
`line_indices` holds. It cannot be done against the shade in the framebuffer,
because `BGP` can map index 0 to any of the four shades and can map another index
to the same one.

Putting sections 6 and 7 together, one pixel resolves like this:

```
    for each of the line's objects, in priority order:
        index = its colour index at this column
        if index == 0:                  continue, it is transparent here
        this object claims the pixel and no other object is considered
        if flags bit 7 and line_indices[x] != 0:   the background keeps the pixel
        otherwise:  framebuffer[x] = palette >> (index * 2) & 0b11
        stop
```

The claim happens before the background test. An object in front that loses to
the background does not hand the pixel to the object behind it.

### 8. `OBP0` and `OBP1`

Same layout as `BGP`, same arithmetic, `shade = (OBP >> (index * 2)) & 0b11`.
Flag bit 4 picks which one the object uses.

Two palettes exist so two objects can use one tile and come out different. The
usual DMG pairing is a light palette and a dark one for the same character
sprite.

### 9. Flips, and the 8×16 size

Flag bit 5 mirrors the object horizontally, bit 6 vertically. They are applied to
the coordinates inside the object, not to its position on screen:

```
    column = 7 - column                  if X flip
    row    = (height - 1) - row          if Y flip
```

The flips are what lets a walking character face both ways from one tile, and a
16-frame animation cost 8 tiles.

`LCDC` bit 2 set makes every object 8×16. Two tiles stack:

```
    top half     tile index with bit 0 forced to 0     (index & 0xFE)
    bottom half  tile index with bit 0 forced to 1     (index | 0x01)
```

Bit 0 of the entry's tile byte is ignored in this mode, so 0x58 and 0x59 both
name the pair 0x58/0x59.

Compute the Y flip on the full 0–15 row first, then split. Then
`tile = (index & 0xFE) + row // 8` and `row % 8` inside it, and the flip has
swapped the halves without a second branch.

The size is global. There is no per-object size bit, so a game switching to 8×16
switches every object at once.

### 10. OAM DMA

Writing a byte `N` to `0xFF46` copies 160 bytes from `N × 0x100` into OAM. Write
`0xC0`, get `0xC000`–`0xC09F` copied to `0xFE00`–`0xFE9F`.

Games do it this way for two reasons. Writing 160 bytes with `LD` costs over 600
M-cycles; the DMA costs 160 plus the setup. And OAM is unreadable and unwritable
by the CPU outside VBlank and HBlank, so a game keeps its real object table in
WRAM, edits it whenever it likes, and pushes the finished copy across during
VBlank.

That WRAM copy is the shadow OAM. Tetris keeps it at `0xC000` and fires the DMA
once per frame, which is the 598 DMA writes measured over 600 frames.

On hardware the transfer takes 640 dots, and while it runs the CPU can only reach
HRAM. Games handle that by copying a short routine into HRAM at startup and
calling it: it writes `0xFF46` and then spins in a `DEC`/`JR NZ` loop long enough
for the transfer to finish. We copy all 160 bytes inside the register write and
charge nothing, so the HRAM routine still runs and its wait loop is simply
redundant.

The transfer belongs on the bus. Its source can be ROM, WRAM or anywhere else in
the map, and only the bus knows how to read those. The PPU owns OAM but has no
way to reach the rest of the address space.

### 11. What this changes in the code you have

`_render_scanline` currently does one thing, and it needs to do two. The early
return for `LCDC` bit 0 is the part to look at first: on a DMG that bit blanks
the background and the window, and objects are drawn anyway. An early return that
skips the object pass gets that wrong.

`memory_map.PPU_REGISTERS_2` is a bare `BGP` today because `BGP` was alone.
`OBP0` and `OBP1` sit next to it, so it becomes a range. `0xFF46` stays outside
it: the DMA is the bus's, and 11A already decided that letting it fall through to
the bus's `io` array gives the read-back for free.

`Bus.oam` moves to `PPU.oam` and the two routing arms in `read` and `write`
follow. 11B left it on the bus because nothing read it. Now the renderer does.

### 12. Python concepts this part introduces

- **`NamedTuple` for a decoded record.** Four fields, immutable, indexable, and
  it costs nothing to build. Closer to Ruby's `Struct.new(:y, :x, :tile, :flags)`
  than to a class, but typed and with no methods unless you add them. A frozen
  dataclass works too; try both and see which reads better at the call site.
- **`sorted` is stable.** Equal keys keep their input order. Section 6 wants "by
  X, ties by OAM index", and if the list is already in OAM order then
  `sorted(objects, key=lambda o: o.x)` gives exactly that, with no index in the
  key. Ruby's `sort_by` is not stable, so this is one of the places where a habit
  from Ruby will make you write more than you need.
- **`itertools.batched`.** New in 3.12. `batched(oam, 4)` yields the entries as
  4-tuples without any index arithmetic. `range(0, 160, 4)` and a slice is the
  other spelling; the first says what it means.
- **A reused scratch buffer.** The object pass needs to remember which columns
  are already claimed. Allocating a 160-byte list per line means 144 allocations
  per frame. A `bytearray` on the instance, cleared at the start of each line,
  does not.
- **`enumerate` for the OAM index.** Section 6 needs it only if you break the
  input order somewhere. If you keep the list in OAM order until the sort, you do
  not need it at all.

---

## Tasks

### 1. OAM and the two palettes move to the PPU

Add to `PPU`: an `oam` bytearray of 160 bytes, and `obp0`/`obp1`. Wire
`0xFF48`/`0xFF49` into `read` and `write` next to `BGP`.

Add `OBP0` and `OBP1` to `memory_map.py` and widen `PPU_REGISTERS_2` to the range
that now covers `0xFF47`–`0xFF49`. Leave `0xFF46` out of it.

Route `0xFE00`–`0xFE9F` in `Bus.read` and `Bus.write` to `self.ppu.oam`, the way
VRAM was routed in 11B.

**Acceptance:** `bus.write(0xFE00, 0x42)` lands in `bus.ppu.oam[0]`. `0xFF48` and
`0xFF49` round-trip a byte. Every existing bus test still passes.

---

### 2. One entry, decoded

```python
class Sprite(NamedTuple):
    """One OAM entry, with the coordinate offsets still in it."""
    y: int
    x: int
    tile: int
    flags: int
```

Keep `y` and `x` raw, as OAM stores them. Subtracting 16 and 8 at construction
time makes the section 5 test read worse, because the hardware's condition is
written in raw coordinates.

Give it the four flag questions as properties, named for what they mean rather
than for their bit number: whether it is behind the background, the two flips,
and which palette.

**Acceptance:** decode the bytes `0x10 0x08 0x2F 0xA0` and assert screen position
`(0, 0)`, tile `0x2F`, behind the background, Y-flipped, not X-flipped, palette
`OBP0`. Work the flags out from the diagram in section 3 before running it.

---

### 3. The line's objects

```python
def _sprites_on_line(self, ly: int) -> list[Sprite]:
    """The objects covering line `ly`, at most ten, in OAM order."""
```

Per section 5: walk OAM in order, keep the ones whose Y range covers the line,
stop at ten. Height comes from `LCDC` bit 2.

Return them in OAM order. The priority sort is task 4's business, and doing it
here would hide which order the ten were chosen in.

**Acceptance:** twelve objects all covering line 0 give ten, and they are entries
0 to 9. An object at X = 0 covering line 0 is one of the ten. An 8×8 object at
Y = 8 covers no line; at Y = 9 it covers line 0 only.

---

### 4. Drawing the objects into the line

Split the renderer in two: the background pass 11B wrote, then an object pass.
Per section 11, `LCDC` bit 0 clear blanks the background and must not skip the
object pass. `LCDC` bit 1 clear skips the object pass.

Sort the ten by X, per section 6. Then per section 7, walk them in priority order
and let the first non-transparent one claim each column, using a scratch buffer
for what is claimed.

The eight columns of one object are `x - 8` through `x - 1`. Some of those fall
outside 0–159 and are dropped. There is no wrapping here: unlike the background,
objects have edges.

**Acceptance:** one 8×8 object at Y = 16, X = 8 with a known tile puts that
tile's top row at framebuffer columns 0–7 of line 0. Its index-0 pixels leave the
background's shade in place. With flag bit 7 set and a background whose index is
non-zero there, none of its pixels land. With the same flag and a background of
index 0, all of them do.

---

### 5. The DMA register, on the bus

`0xFF46` in `Bus.write`: copy 160 bytes from `value << 8` into `ppu.oam`,
through `self.read` so the source can be any region. Store the value in `io` so
reading `0xFF46` gives it back.

Do it in one pass with no cycle cost, per section 10. Say in a comment that the
640 dots and the HRAM restriction are not modelled, next to 11A's list of the
other things that are not.

**Acceptance:** with `0x42` at `0xC000` and `0x99` at `0xC09F`, writing `0xC0` to
`0xFF46` puts both at the matching offsets of `ppu.oam`, and reading `0xFF46`
gives `0xC0`. A source in ROM works the same way.

---

### 6. Tests

**Unit level, `PPU` alone:**

- an entry decodes to the right position and flags
- the ten-per-line limit keeps the first ten in OAM order, and an off-screen X
  still consumes a slot
- both heights select the right lines, at the boundaries
- the priority sort puts the smaller X in front, and equal X falls back to OAM
  order
- colour index 0 is transparent whatever `OBP0` says about it
- flag bit 7 against a background index of 0 and of non-zero
- both flips, and an 8×16 object's halves swapping under a Y flip
- `LCDC` bit 1 clear draws no objects; `LCDC` bit 0 clear still draws them

**Bus level:**

- `0xFE00`–`0xFE9F` routes to `ppu.oam`
- a DMA from WRAM and a DMA from ROM

Tetris uses one 8×8 object with no flips, no priority flag and no crowding, so
the ROM will not tell you whether the other eight bullets work. Build the VRAM
and OAM by hand, as 11B's render tests do.

---

### 7. Run the real thing

```
uv run python -m gameboy ~/games/TETRIS.gb --frame 600 --budget 12000000
```

Frame 600 is the title screen, and it has exactly one object: OAM entry 0, tile
`0x58`, flags `0x00`, at screen `(8, 112)`. It is the menu cursor next to
`1PLAYER`. Frame 120, the copyright screen, has none, so use frame 600 or later.

Before the DMA works, OAM is 160 zero bytes and nothing appears. Tetris writes
`0xFF46` once per frame with `0xC0` and never touches OAM directly, so task 5 is
what makes tasks 1 to 4 visible.

If you want to see the cursor without squinting at ASCII, dump the frame with
`--out` and open the PGM.

None of the other ROMs in a normal collection will help yet. Super Mario Land,
Wario Land and Batman are MBC1 or MBC3 and stall without bank switching, which is
Step 15. Tintin hits an opcode the CPU does not know.

---

### 8. Docs

`README.md`: the step table gets a 12A row. `PLAN.md`: split the Step 12 row into
12A and 12B, the way 11 was split.

---

## Hints

- If nothing appears at all, check OAM before anything in the renderer. Dump
  `0xFE00` and see whether it is still 160 zeros. If it is, the DMA is the
  problem, not the drawing.
- If objects are 8 pixels too far right and 16 too far down, you used the raw Y
  and X instead of subtracting.
- If they are drawn but the background covers them, you compared flag bit 7
  against the framebuffer's shade instead of `line_indices`.
- If overlapping objects flicker between frames in a way the game did not ask
  for, the priority sort is unstable or is keying on the OAM index first.
- If an object vanishes when a tenth appears on the line, the selection is
  sorting before it counts to ten.
- If 8×16 objects show their bottom half on top, the Y flip is being applied
  after the split into two tiles instead of before.
- If everything is mirrored, the X flip is inverting the screen column instead of
  the column inside the object.
- Cross-check the flag bits and the coordinate offsets against
  <https://gbdev.io/pandocs/OAM.html>.

---

## Acceptance criteria

- [ ] OAM lives on the PPU, and `0xFE00`–`0xFE9F` routes to it
- [ ] `OBP0` and `OBP1` are stored and readable, and `0xFF46` is not claimed by
      `PPU_REGISTERS_2`
- [ ] An OAM entry decodes to a typed record, tested against a hand-worked
      example
- [ ] At most ten objects per line, chosen in OAM order, asserted by a test
- [ ] Priority is by X with OAM order as the tie-break, asserted by a test
- [ ] Colour index 0 is transparent, and flag bit 7 is tested against a
      background index of both 0 and non-zero
- [ ] Both flips and 8×16 are tested, including the halves swapping under a Y
      flip
- [ ] `LCDC` bit 0 clear still draws objects
- [ ] A DMA write to `0xFF46` copies 160 bytes from anywhere in the map
- [ ] Tetris at frame 600 shows the cursor at screen `(8, 112)`
- [ ] `uv run pytest` green, `ruff check`, `ruff format --check`, `mypy` clean

---

## Questions to ask yourself before moving on

1. The ten-per-line limit drops objects, and a game rotates OAM between frames so
   the dropped ones change. Your emulator renders every frame the ROM asks for.
   What would a player see on your emulator that they would not see on hardware,
   and which direction is the difference in?
2. You copy 160 bytes inside the write to `0xFF46` and charge zero cycles.
   Describe a ROM that would work here and fail on hardware. Then describe one
   that would fail here and work on hardware, or argue that none can exist.
3. Objects read tile data through the `0x8000` method regardless of `LCDC` bit 4,
   and the background follows the bit. What does that let a game do with the
   128 tiles in block 1 that it could not do if both layers followed the bit?
4. You kept `y` and `x` raw in the record and subtract the offsets at use. Where
   else in this codebase is a value stored in the hardware's units rather than in
   the units it is used in, and what does that pattern cost when it is wrong?
