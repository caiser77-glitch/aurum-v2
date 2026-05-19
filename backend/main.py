import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List, Dict

import requests
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


BASE = Path("/app")
UPLOADS = BASE / "uploads"
OUTPUTS = BASE / "outputs"
SCRIPTS = BASE / "scripts"
DATA = BASE / "data"
MEMORY_PATH = DATA / "memory.json"

OLLAMA_URL = "http://host.docker.internal:11434/api/generate"

MODEL_SIMPLE = "llama3.1:8b"
MODEL_WORK = "qwen2.5:14b"
MODEL_BIG = "qwen2.5:72b"
MODEL_REVIEW = "llama3.1:70b"
MODEL_IMAGE = "llava:latest"
MODEL_WRITE = "gemma2:27b"
MODEL_POLISH = "gemma2:9b"
MODEL_SMALL = "gemma:7b"

DEFAULT_CODE_PATH = "scripts/chat_generated.py"

app = FastAPI(title="AURUM v2 API", version="0.4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOADS.mkdir(parents=True, exist_ok=True)
OUTPUTS.mkdir(parents=True, exist_ok=True)
DATA.mkdir(parents=True, exist_ok=True)

app.mount("/outputs", StaticFiles(directory=str(OUTPUTS)), name="outputs")


class ChatRequest(BaseModel):
    message: str
    history: List[Dict[str, str]] = []
    last_code: str = ""
    code_path: str = DEFAULT_CODE_PATH
    selected_model: str = "AUTO"


class ChatResponse(BaseModel):
    answer: str
    model: str
    reason: str
    history: List[Dict[str, str]]
    last_code: str = ""
    code_path: str = DEFAULT_CODE_PATH
    run_result: str = ""
    memory_summary: str = ""


class MemoryUpdateRequest(BaseModel):
    summary: str = ""
    facts: List[str] = []


def call_ollama(model: str, prompt: str, temperature: float = 0.2, timeout: int = 600) -> str:
    r = requests.post(
        OLLAMA_URL,
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature, "top_p": 0.8},
        },
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json().get("response", "").strip()


def default_memory():
    return {"summary": "아직 저장된 장기 기억이 없습니다.", "facts": [], "updated_at": ""}


def load_memory():
    if not MEMORY_PATH.exists():
        save_memory(default_memory())
    try:
        return json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
    except Exception:
        mem = default_memory()
        save_memory(mem)
        return mem


def save_memory(memory: dict):
    memory["updated_at"] = datetime.now().isoformat(timespec="seconds")
    MEMORY_PATH.write_text(json.dumps(memory, ensure_ascii=False, indent=2), encoding="utf-8")


def memory_text():
    mem = load_memory()
    facts = mem.get("facts", [])
    fact_text = "\n".join(f"- {x}" for x in facts) if facts else "- 없음"
    return f"""
[장기 기억 요약]
{mem.get("summary", "")}

[중요 사실]
{fact_text}
"""


def update_memory_from_chat(history: List[Dict[str, str]]):
    if len(history) < 8:
        return load_memory()

    mem = load_memory()
    recent = "\n".join([f"{m.get('role')}: {m.get('content')}" for m in history[-12:]])

    prompt = f"""
너는 AURUM의 장기 기억 관리자다.
아래 기존 기억과 최근 대화를 보고, 앞으로도 유용한 프로젝트 맥락만 압축해서 갱신한다.
민감하거나 일시적인 내용은 저장하지 않는다.

기존 요약:
{mem.get("summary", "")}

기존 중요 사실:
{mem.get("facts", [])}

최근 대화:
{recent}

반드시 JSON만 출력:
{{
  "summary": "장기적으로 유용한 현재 프로젝트 요약",
  "facts": ["중요 사실 1", "중요 사실 2"]
}}
"""

    try:
        raw = call_ollama(MODEL_WORK, prompt, timeout=600)
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if not match:
            return mem

        new_mem = json.loads(match.group(0))
        summary = str(new_mem.get("summary", "")).strip()
        facts = new_mem.get("facts", [])

        if not isinstance(facts, list):
            facts = []

        facts = [str(x).strip() for x in facts if str(x).strip()]
        facts = facts[:30]

        if summary:
            mem["summary"] = summary
        mem["facts"] = facts
        save_memory(mem)
        return mem
    except Exception:
        return mem


def output_url(path: Path) -> str:
    return f"/outputs/{path.name}"


def save_upload(file: UploadFile) -> Path:
    safe_name = Path(file.filename).name
    target = UPLOADS / safe_name
    with target.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return target


def run_cmd(args: list[str]) -> str:
    result = subprocess.run(args, cwd=str(BASE), capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout)
    return result.stdout.strip()


def get_weather() -> str:
    try:
        r = requests.get("https://wttr.in/Seoul?format=3", timeout=20)
        r.raise_for_status()
        return r.text
    except Exception as exc:
        return f"날씨 정보를 가져오지 못했습니다: {type(exc).__name__}: {exc}"


def select_model(message: str) -> tuple[str, str]:
    q = message.lower()
    length = len(message)

    if any(p in q for p in ["오늘 날씨", "내일 날씨", "지금 날씨", "현재 날씨", "서울 날씨", "날씨 알려", "날씨 어때"]):
        return "WEATHER_API", "명확한 날씨 질문"

    if any(k in q for k in ["이미지", "사진", "그림", "ocr", "캡처", "스캔"]):
        return MODEL_IMAGE, "이미지/OCR 질문"

    if any(k in message for k in ["코드 검정", "코드검정", "코드 분석", "코드 검토", "이 코드", "검토해", "수정할 점", "완결"]):
        return MODEL_REVIEW, "코드 검정/분석"

    if any(k in q for k in ["코드", "python", "파이썬", "에러", "오류", "스크립트", "터미널", "docker", "git", "vscode", "저장해", "실행해", "수정해"]):
        return MODEL_WORK, "코드/시스템 작업"

    if any(k in q for k in ["설계", "구조", "리팩토링", "검증", "반박", "재검토"]):
        return MODEL_REVIEW, "구조 설계/검토"

    if any(k in q for k in ["보고서", "분석", "요약", "환경영향평가", "전략"]) or length > 1200:
        return MODEL_BIG, "긴 문서/복잡 분석"

    if any(k in q for k in ["문장", "다듬", "이메일", "메일", "문체"]):
        return MODEL_POLISH, "문장 다듬기"

    if any(k in q for k in ["초안", "작성", "기획서", "제안서", "공문"]):
        return MODEL_WRITE, "문서 작성"

    if any(k in q for k in ["간단", "짧게", "빠르게", "한줄", "한 줄"]):
        return MODEL_SIMPLE, "간단 응답"

    if length < 80:
        return MODEL_SMALL, "짧은 일반 대화"

    return MODEL_WORK, "일반 업무"


def choose_model(message: str, selected_model: str) -> tuple[str, str]:
    allowed_models = {
        "llama3.1:8b",
        "qwen2.5:14b",
        "qwen2.5:72b",
        "llama3.1:70b",
        "llava:latest",
        "gemma2:27b",
        "gemma2:9b",
        "gemma:7b",
    }

    if selected_model and selected_model != "AUTO" and selected_model in allowed_models:
        return selected_model, "사용자 지정 모델"

    return select_model(message)


def build_context(history: List[Dict[str, str]], max_messages: int = 10) -> str:
    lines = []
    for msg in history[-max_messages:]:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "user":
            lines.append(f"사용자: {content}")
        elif role == "assistant":
            lines.append(f"AURUM: {content}")
    return "\n".join(lines)


def extract_code_block(text: str) -> str:
    patterns = [r"```python\n(.*?)```", r"```py\n(.*?)```", r"```\n(.*?)```"]
    matches = []
    for pattern in patterns:
        matches.extend(re.findall(pattern, text, flags=re.DOTALL | re.IGNORECASE))
    return max(matches, key=len).strip() if matches else ""


def safe_project_path(path_text: str) -> Path:
    rel = Path(path_text.strip() or DEFAULT_CODE_PATH)
    if rel.is_absolute():
        raise ValueError("절대경로는 사용할 수 없습니다.")
    target = (BASE / rel).resolve()
    if not str(target).startswith(str(BASE.resolve())):
        raise ValueError("프로젝트 폴더 밖에는 저장할 수 없습니다.")
    return target


def save_code(code: str, path_text: str) -> str:
    if not code.strip():
        return "저장할 코드가 없습니다."
    target = safe_project_path(path_text)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(code, encoding="utf-8")
    return f"저장 완료: {target}"


def run_python_detail(path_text: str) -> dict:
    target = safe_project_path(path_text)

    if not target.exists():
        return {"ok": False, "output": f"실행 실패: 파일이 없습니다: {target}", "returncode": -1}

    if target.suffix.lower() != ".py":
        return {"ok": False, "output": "실행 실패: 현재는 .py 파일만 실행 지원합니다.", "returncode": -1}

    try:
        result = subprocess.run(
            ["python", str(target)],
            cwd=str(BASE),
            capture_output=True,
            text=True,
            timeout=120,
        )

        output = f"실행 파일: {target}\n종료 코드: {result.returncode}\n\n"
        if result.stdout:
            output += "[STDOUT]\n" + result.stdout + "\n"
        if result.stderr:
            output += "[STDERR]\n" + result.stderr + "\n"
        if not result.stdout and not result.stderr:
            output += "출력 없음\n"

        return {"ok": result.returncode == 0, "output": output, "returncode": result.returncode}
    except subprocess.TimeoutExpired:
        return {"ok": False, "output": "실행 중단: 120초 시간 초과", "returncode": -1}


def run_python(path_text: str) -> str:
    return run_python_detail(path_text)["output"]


def make_prompt(message: str, history: List[Dict[str, str]], model: str, reason: str) -> str:
    context = build_context(history)
    mem = memory_text()
    return f"""
너는 AURUM v2 통합 AI 시스템이다.
반드시 한국어로만 답변한다.

현재 선택 모델: {model}
선택 이유: {reason}

{mem}

이전 대화:
{context}

중요 규칙:
- 장기 기억을 반영해서 사용자의 프로젝트 맥락을 이어간다.
- 코드 요청이면 반드시 실행 가능한 전체 Python 코드를 하나의 코드블록으로 제공한다.
- 코드블록 안에는 설명, bash 명령어, 마크다운 문장, PY 같은 heredoc 종료문자를 넣지 않는다.
- 코드블록 안에는 오직 Python 코드만 넣는다.
- Python 코드는 Python 3.12 기준으로 작성한다.
- 현재 Docker 프로젝트 루트는 /app 이다.
- 파일 경로는 상대경로만 사용한다.
- 불확실하면 단정하지 않는다.
- 핵심부터 답한다.

사용자 질문:
{message}
"""


def auto_fix_code(original_message: str, code: str, run_output: str, code_path: str, max_rounds: int = 2) -> tuple[str, str, str]:
    current_code = code
    logs = []

    for round_no in range(1, max_rounds + 1):
        fix_prompt = f"""
너는 AURUM 코드 자동 수정 AI다.
아래 Python 코드가 실행 실패했다.
에러 로그를 분석해서 수정된 전체 Python 코드만 하나의 코드블록으로 출력하라.

규칙:
- 반드시 Python 전체 코드만 제공한다.
- 코드블록 안에는 설명을 넣지 않는다.
- Docker 프로젝트 루트는 /app 이다.
- 상대경로를 우선 사용한다.
- Python 3.12 기준이다.

사용자 원래 요청:
{original_message}

현재 저장 경로:
{code_path}

실패한 코드:
```python
{current_code}

# ===== AURUM 자동 코드 수정 루프 추가 =====

def auto_fix_code_once(original_message: str, code: str, run_output: str, code_path: str) -> tuple[str, str]:
    prompt = f"""
너는 Python 코드 자동 수정 AI다.
아래 코드는 실행 실패했다.
에러 로그를 보고 수정된 전체 Python 코드만 코드블록으로 출력하라.

규칙:
- 설명 금지
- 전체 코드만 제공
- Python 3.12 기준
- Docker 프로젝트 루트는 /app

사용자 요청:
{original_message}

저장 경로:
{code_path}

실패한 코드:
{code}

실행 로그:
{run_output}
"""

    fixed_answer = call_ollama(MODEL_WORK, prompt, timeout=600)
    fixed_code = extract_code_block(fixed_answer)

    if not fixed_code:
        return code, "[자동 수정 실패] 수정 코드블록을 감지하지 못했습니다."

    save_code(fixed_code, code_path)
    result = run_python(code_path)

    return fixed_code, result


_original_chat = chat


@app.post("/chat-auto", response_model=ChatResponse)
def chat_auto(req: ChatRequest):
    res = _original_chat(req)

    if not res.last_code:
        return res

    if not res.run_result.strip():
        return res

    if "종료 코드: 0" in res.run_result:
        return res

    fixed_code, fixed_result = auto_fix_code_once(
        req.message,
        res.last_code,
        res.run_result,
        res.code_path,
    )

    final_answer = (
        res.answer
        + "\n\n[AURUM 자동 수정 루프]\n"
        + fixed_result
    )

    new_history = list(res.history)
    if new_history and new_history[-1].get("role") == "assistant":
        new_history[-1]["content"] = final_answer

    return ChatResponse(
        answer=final_answer,
        model=res.model,
        reason=res.reason + " + 자동 수정",
        history=new_history,
        last_code=fixed_code,
        code_path=res.code_path,
        run_result=fixed_result,
        memory_summary=res.memory_summary,
    )

