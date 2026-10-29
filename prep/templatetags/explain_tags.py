"""Format raw explanation text into a standard, readable solution layout.

Explanations (seed data and user contributions) are stored as plain text,
usually as one line: "Step 1: ... Step 2: ... Correct answer: Option B - 144."
This filter renders that as structured HTML: one row per step with a step
chip, (a)/(b) fractions as real stacked fractions, and the final answer as a
highlighted bar. The input is HTML-escaped before any markup is added, so
contributed text can never inject tags.
"""
import html
import re

from django import template
from django.utils.safestring import mark_safe

register = template.Library()

_STEP_SPLIT = re.compile(r"(?=Step\s*\d+\s*:)")
_STEP_HEAD = re.compile(r"Step\s*(\d+)\s*:\s*(.*)", re.DOTALL)
_ANSWER = re.compile(r"Correct answer\s*:\s*(.+)$", re.IGNORECASE | re.DOTALL)
_FRAC = re.compile(r"\(([^()]{1,40})\)/\(([^()]{1,40})\)")
_SIMPLE_FRAC = re.compile(r"\b(\d[\w.]*)/(\d[\w.]*)\b")


def _fractions(text):
    def frac(m):
        return ('<span class="frac"><span class="frac-num">%s</span>'
                '<span class="frac-den">%s</span></span>'
                % (m.group(1), m.group(2)))

    return _SIMPLE_FRAC.sub(frac, _FRAC.sub(frac, text))


def format_explanation(raw):
    """Return safe HTML for one explanation string (see module docstring)."""
    text = (raw or "").strip()
    if not text:
        return mark_safe('<p class="sol-lead">No explanation available.</p>')
    esc = html.escape(text)

    answer = ""
    m = _ANSWER.search(esc)
    if m:
        answer = m.group(1).strip().rstrip(".")
        esc = esc[:m.start()].rstrip()

    out = []
    for part in _STEP_SPLIT.split(esc):
        part = part.strip()
        if not part:
            continue
        sm = _STEP_HEAD.match(part)
        if sm:
            out.append(
                '<div class="sol-step"><span class="sol-chip">Step %s</span>'
                "<p>%s</p></div>" % (sm.group(1), _fractions(sm.group(2).strip()))
            )
        else:
            out.append('<p class="sol-lead">%s</p>' % _fractions(part))
    if answer:
        out.append('<div class="sol-answer">&#10003; Correct answer: %s</div>'
                   % _fractions(answer))
    return mark_safe("".join(out))


@register.filter(name="explain")
def explain_filter(raw):
    return format_explanation(raw)


# ---------------------------------------------------------------------------
# Question text: prose paragraphs + real code panels.
#
# Questions are stored as plain text; the ones with code/SQL/pseudocode use
# newlines ("What is the output?\nconsole.log('A'); ..."). Rendered raw, the
# browser collapses those newlines and the code runs into the sentence.
# This filter escapes the text, classifies each line as prose or code, and
# emits prose as paragraphs and code as an indented <pre> panel, so every
# question reads in standard form. A JS twin (formatQuestion) lives in the
# practice/test player templates and must be kept in step with this code.
# ---------------------------------------------------------------------------

_CODE_START = re.compile(
    r"^(SELECT|INSERT INTO|UPDATE|DELETE FROM|FROM|WHERE|ORDER BY|GROUP BY|"
    r"function|for|if|else|elif|while|return|print|var|let|const|class|def)\b")
_CODE_TOKENS = ("console.log", "setTimeout", "Promise.", "=>", "document.",
                "System.out")
_ASSIGN = re.compile(r"^[A-Za-z_][\w.\[\]]*\s*=[^=]")
_LABELLED = re.compile(r"^(Query|Code|Program)\s*:\s*(.+)$")


def _is_code(line, in_code):
    s = line.strip()
    if not s:
        return in_code
    if line[:1] in (" ", "\t") and in_code:
        return True
    if _CODE_START.match(s):
        return True
    if any(s.startswith(tok) for tok in _CODE_TOKENS):
        return True
    if _ASSIGN.match(s):
        return True
    if s in ("{", "}", "};") or s.endswith("{"):
        return True
    return False


def format_question(raw):
    """Return safe HTML for one question string (see section comment)."""
    text = (raw or "").strip()
    if not text:
        return mark_safe('<p class="q-text-p"></p>')
    out, prose, code = [], [], []

    def flush_prose():
        if prose:
            out.append('<p class="q-text-p">%s</p>' % " ".join(prose))
            prose.clear()

    def flush_code():
        if code:
            out.append('<pre class="q-code">%s</pre>' % "\n".join(code))
            code.clear()

    in_code = False
    for line in html.escape(text).split("\n"):
        s = line.strip()
        if not s:
            continue
        m = _LABELLED.match(s)
        if m and _is_code(m.group(2), False):
            flush_code()
            prose.append(m.group(1) + ":")
            flush_prose()
            code.append(m.group(2))
            in_code = True
            continue
        if _is_code(line, in_code):
            flush_prose()
            code.append(line.rstrip())
            in_code = True
        else:
            flush_code()
            prose.append(s)
            in_code = False
    flush_prose()
    flush_code()
    return mark_safe("".join(out))


@register.filter(name="qtext")
def qtext_filter(raw):
    return format_question(raw)
