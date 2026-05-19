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

app = FastAPI(title="AURUM v2 API", version="0.3.0")

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


def default_memory():
    return {
        "summary": "아직 저장된 장기 기억이 없습니다.",
        "facts": [],
        "updated_at": "",
    }


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
    result = subprocess.run(
        args,
        cwd=str(BASE),
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout)
    return result.stdout.strip()


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
    patterns = [
        r"```python\n(.*?)```",
        r"```py\n(.*?)```",
        r"```\n(.*?)```",
    ]
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


def run_python(path_text: str) -> str:
    target = safe_project_path(path_text)
    if not target.exists():
        return f"실행 실패: 파일이 없습니다: {target}"
    if target.suffix.lower() != ".py":
        return "실행 실패: 현재는 .py 파일만 실행 지원합니다."

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
    return output


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


@app.get("/")
def root():
    return {"status": "ok", "service": "AURUM v2 API"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/memory")
def get_memory():
    return load_memory()


@app.post("/memory")
def update_memory(req: MemoryUpdateRequest):
    mem = load_memory()
    if req.summary.strip():
        mem["summary"] = req.summary.strip()
    if req.facts:
        mem["facts"] = [x.strip() for x in req.facts if x.strip()]
    save_memory(mem)
    return mem


@app.delete("/memory")
def clear_memory():
    mem = default_memory()
    save_memory(mem)
    return mem


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    message = req.message.strip()
    history = list(req.history or [])

    if not message:
        return ChatResponse(
            answer="메시지가 비어 있습니다.",
            model="none",
            reason="empty",
            history=history,
            last_code=req.last_code,
            code_path=req.code_path,
            memory_summary=load_memory().get("summary", ""),
        )

    model, reason = select_model(message)
    history.append({"role": "user", "content": message})

    if "저장해" in message or "코드 저장" in message:
        result = save_code(req.last_code, req.code_path)
        answer = f"[AURUM 코드 저장]\n{result}"
        history.append({"role": "assistant", "content": answer})
        update_memory_from_chat(history)
        return ChatResponse(answer=answer, model="SYSTEM", reason="코드 저장 명령", history=history, last_code=req.last_code, code_path=req.code_path, memory_summary=load_memory().get("summary", ""))

    if "실행해" in message or "테스트해" in message or "돌려봐" in message:
        run_result = run_python(req.code_path)
        answer = f"[AURUM 코드 실행]\n{run_result}"
        history.append({"role": "assistant", "content": answer})
        update_memory_from_chat(history)
        return ChatResponse(answer=answer, model="SYSTEM", reason="코드 실행 명령", history=history, last_code=req.last_code, code_path=req.code_path, run_result=run_result, memory_summary=load_memory().get("summary", ""))

    if model == "WEATHER_API":
        answer = get_weather()
        history.append({"role": "assistant", "content": answer})
        update_memory_from_chat(history)
        return ChatResponse(answer=answer, model=model, reason=reason, history=history, last_code=req.last_code, code_path=req.code_path, memory_summary=load_memory().get("summary", ""))

    prompt = make_prompt(message, req.history, model, reason)
    answer = call_ollama(model, prompt)

    code = extract_code_block(answer)
    run_result = ""
    last_code = req.last_code
    code_path = req.code_path

    if code:
        last_code = code
        save_result = save_code(code, code_path)
        run_result = run_python(code_path)
        answer += f"\n\n[AURUM 자동 처리]\n1. 코드 감지 완료\n2. {save_result}\n3. 실행 결과:\n{run_result}"

    history.append({"role": "assistant", "content": answer})
    mem = update_memory_from_chat(history)

    return ChatResponse(
        answer=answer,
        model=model,
        reason=reason,
        history=history,
        last_code=last_code,
        code_path=code_path,
        run_result=run_result,
        memory_summary=mem.get("summary", ""),
    )


@app.post("/tools/image-ocr")
def tool_image_ocr(file: UploadFile = File(...)):
    path = save_upload(file)
    run_cmd(["python", str(SCRIPTS / "taxa_table_ocr.py"), str(path)])
    out = OUTPUTS / f"{path.stem}_taxa.xlsx"
    return {"status": "ok", "message": "이미지 OCR 완료", "file": out.name, "url": output_url(out)}


@app.post("/tools/pdf-ocr")
def tool_pdf_ocr(file: UploadFile = File(...), pages: str = Form("1")):
    path = save_upload(file)
    page_text = pages.strip() if pages and pages.strip() else ""
    run_cmd(["python", str(SCRIPTS / "taxa_pdf_ocr.py"), str(path), page_text])
    safe_pages = page_text.replace(",", "_").replace("-", "to").replace(" ", "") if page_text else "all"
    out = OUTPUTS / f"{path.stem}_pages_{safe_pages}_taxa.xlsx"
    return {"status": "ok", "message": "PDF OCR 완료", "file": out.name, "url": output_url(out)}


@app.post("/tools/cad-kml")
def tool_cad_kml(file: UploadFile = File(...)):
    path = save_upload(file)
    ext = path.suffix.lower()

    if ext == ".kml":
        mode = "kml_to_dxf"
        out = OUTPUTS / f"{path.stem}.dxf"
    elif ext == ".dxf":
        mode = "dxf_to_kml"
        out = OUTPUTS / f"{path.stem}.kml"
    else:
        return {"status": "error", "message": "KML 또는 DXF 파일만 지원합니다."}

    log = run_cmd(["python", str(SCRIPTS / "cad_kml_convert.py"), mode, str(path), str(out)])
    return {"status": "ok", "message": "CAD/KML 변환 완료", "file": out.name, "url": output_url(out), "log": log}


@app.post("/tools/excel")
def tool_excel(file: UploadFile = File(...)):
    path = save_upload(file)
    run_cmd(["python", str(SCRIPTS / "excel_summary.py"), str(path)])
    out = OUTPUTS / f"{path.stem}_summary.xlsx"
    return {"status": "ok", "message": "Excel 분석 완료", "file": out.name, "url": output_url(out)}
