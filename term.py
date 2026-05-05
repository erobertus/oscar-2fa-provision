"""Terminal styling helpers — ANSI colors and small print utilities.

The constants and palette mirror lib/common.sh from the provider-onboarding
bash project so the two tools feel like siblings on the terminal:

    RED      errors
    YELLOW   warnings, validation hints
    GREEN    success ("found N matches", "updated N rows", "on")
    CYAN     picker indices, light emphasis
    BOLD     prompts
    DIM      rules, subordinate text, defaults

Colors are emitted only when stdout is a TTY. When the output is piped
to a file or another process (e.g. grep), the constants resolve to
empty strings so logs and pipelines stay clean.
"""

from __future__ import annotations

import sys


def _enabled() -> bool:
    """Return True when ANSI colors should be emitted."""
    # Mirrors the bash check `[[ -t 1 ]]`.
    return sys.stdout.isatty()


if _enabled():
    RESET = "\033[0m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    CYAN = "\033[36m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
else:
    RESET = RED = GREEN = YELLOW = BLUE = CYAN = BOLD = DIM = ""


# ---------------------------------------------------------------------------
# Colored print helpers
# ---------------------------------------------------------------------------
def say(msg: str = "") -> None:
    """Plain print, kept for symmetry with the colored variants."""
    print(msg)


def say_ok(msg: str) -> None:
    """Green — success / positive confirmations."""
    print(f"{GREEN}{msg}{RESET}")


def say_warn(msg: str) -> None:
    """Yellow — soft warnings, validation hints, missing-but-recoverable."""
    print(f"{YELLOW}{msg}{RESET}")


def say_err(msg: str) -> None:
    """Red — errors. Goes to stderr so it stays separable from normal output."""
    print(f"{RED}{msg}{RESET}", file=sys.stderr)


def say_dim(msg: str) -> None:
    """Dim — subordinate detail, default values, rules."""
    print(f"{DIM}{msg}{RESET}")


# ---------------------------------------------------------------------------
# Layout primitives
# ---------------------------------------------------------------------------
RULE_CHAR = "─"
RULE_WIDTH = 70


def hr() -> None:
    """Print a 70-char horizontal rule in dim grey."""
    print(f"{DIM}{RULE_CHAR * RULE_WIDTH}{RESET}")


def header(text: str) -> None:
    """A section header: rule, bold-cyan title, rule.

    Used to separate top-level steps in the workflow (e.g. "Search",
    "Confirm", "Result").
    """
    print()
    hr()
    print(f"{BOLD}{CYAN}{text}{RESET}")
    hr()


# ---------------------------------------------------------------------------
# Inline color helpers
# ---------------------------------------------------------------------------
def bold(s: str) -> str:
    return f"{BOLD}{s}{RESET}"


def dim(s: str) -> str:
    return f"{DIM}{s}{RESET}"


def cyan(s: str) -> str:
    return f"{CYAN}{s}{RESET}"


def green(s: str) -> str:
    return f"{GREEN}{s}{RESET}"


def yellow(s: str) -> str:
    return f"{YELLOW}{s}{RESET}"


def red(s: str) -> str:
    return f"{RED}{s}{RESET}"


def picker_index(n: int) -> str:
    """Format `n` as the cyan bracketed index used by the picker.

    Mirrors the bash project's `[ 1]` / `[12]` style — fixed two-column
    width so single- and double-digit lists line up.
    """
    return f"{CYAN}[{n:2d}]{RESET}"
