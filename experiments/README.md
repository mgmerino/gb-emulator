# Experiments

Small standalone scripts that answer a question the codebase raised, and keep
the answer around. Each one runs on its own:

```
uv run python experiments/<name>.py
```

Nothing here is imported by `gameboy/`, and `mypy` does not check this
directory — `pyproject.toml` points it at `src` and `tests`. `ruff` does.

Each script's docstring carries the question, a sample run and what the numbers
meant. Timings are from one machine on one day: rerun them rather than trusting
them.

| Script | Question |
| --- | --- |
| `dispatch_shapes.py` | Does `if` / `elif` / `match` / `dict` dispatch cost different amounts, and does it matter for the memory bus? |
| `frame_to_png.py` | How do you get a viewable image out of the framebuffer, with no dependency? |
