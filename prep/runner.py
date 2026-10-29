"""Sandboxed code execution for the coding module.

Runs untrusted student code in a child process with a hard timeout, capped
output, and temp-file cleanup. This is a local single-user sandbox (process
isolation + timeouts), NOT a hardened multi-tenant judge — the README says
so explicitly. Java is supported only when a JDK is present on the host.
"""
import os
import shutil
import subprocess
import tempfile

TIMEOUT_SEC = 5
MAX_OUTPUT = 64 * 1024


def available_languages():
    langs = {}
    if shutil.which("python3"):
        langs["python"] = "Python 3"
    if shutil.which("node"):
        langs["javascript"] = "JavaScript (Node)"
    if shutil.which("gcc"):
        langs["c"] = "C (gcc)"
    if shutil.which("g++"):
        langs["cpp"] = "C++ (g++)"
    if shutil.which("javac") and shutil.which("java"):
        langs["java"] = "Java"
    return langs


def _run(cmd, stdin_data, cwd):
    try:
        proc = subprocess.run(
            cmd, input=stdin_data, capture_output=True, text=True,
            timeout=TIMEOUT_SEC, cwd=cwd,
        )
        out = proc.stdout[:MAX_OUTPUT]
        err = proc.stderr[:MAX_OUTPUT]
        if proc.returncode != 0:
            return {"output": out, "error": err or f"Exited with code {proc.returncode}"}
        return {"output": out, "error": ""}
    except subprocess.TimeoutExpired:
        return {"output": "", "error": f"Time limit exceeded ({TIMEOUT_SEC}s)"}
    except Exception as exc:  # noqa: BLE001 - surfaced to the student as-is
        return {"output": "", "error": str(exc)}


def run_code(language, code, stdin_data=""):
    """Run code with the given stdin. Returns {output, error}."""
    available = available_languages()
    if language not in available:
        return {"output": "",
                "error": f"{language} is not available on this server."}
    with tempfile.TemporaryDirectory(prefix="cseprep_") as tmp:
        if language == "python":
            path = os.path.join(tmp, "solution.py")
            with open(path, "w") as f:
                f.write(code)
            return _run(["python3", path], stdin_data, tmp)
        if language == "javascript":
            path = os.path.join(tmp, "solution.js")
            with open(path, "w") as f:
                f.write(code)
            return _run(["node", path], stdin_data, tmp)
        if language in ("c", "cpp"):
            src = os.path.join(tmp, "solution.c" if language == "c" else "solution.cpp")
            exe = os.path.join(tmp, "solution")
            with open(src, "w") as f:
                f.write(code)
            compiler = "gcc" if language == "c" else "g++"
            comp = _run([compiler, src, "-o", exe], "", tmp)
            if comp["error"]:
                return {"output": "", "error": "Compilation error:\n" + comp["error"]}
            return _run([exe], stdin_data, tmp)
        if language == "java":
            path = os.path.join(tmp, "Solution.java")
            with open(path, "w") as f:
                f.write(code)
            comp = _run(["javac", path], "", tmp)
            if comp["error"]:
                return {"output": "", "error": "Compilation error:\n" + comp["error"]}
            return _run(["java", "-cp", tmp, "Solution"], stdin_data, tmp)
    return {"output": "", "error": "Unsupported language."}
