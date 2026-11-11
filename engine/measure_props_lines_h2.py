"""CONFIRMATION (Caden 2026-11-11): the same real-lines test on games it has NOT seen: 2025-26 from Jan 24 to the
end of the season. The first run (Oct 30 - Jan 23) found the injury spots: model 3+ off the line with a rotation
teammate freshly out 109-79, and on bench players (under 20 mpg) 45-25. Nothing is changed between the runs.
Run: python -m engine.measure_props_lines_h2"""
from .measure_props_lines import main

if __name__ == "__main__":
    main("2026-01-24")
