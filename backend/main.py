import subprocess
from pathlib import Path
from typing import List, Dict, Any

import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


BASE = Path("/app")
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


app = FastAPI(title="AURUM v2 API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


def call_ollama(model: str, prompt: str, temperature: float = 0.2, timeout: int = 600) -> str:
    r = requests.post(
        OLLAMA_URL,
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "top_p": 0.8,
            },
        },
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json().get("response", "").strip()


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


def extract_code_block(text: str) -> str:
    import re

    patterns = [
        r"```python\n(.*?)```",
        r"```py\n(.*?)```",
        r"```\n(.*?)```",
    ]

    matches = []

    for pattern in patterns:
        matches.extend(re.findall(pattern, text, flags=re.DOTALL | re.IGNORECASE))

    if not matches:
        return ""

    return max(matches, key=len).strip()


def make_prompt(message: str, history: List[Dict[str, str]], model: str, reason: str) -> str:
    context = build_context(history)

    return f"""
너는 AURUM v2 통합 AI 시스템이다.
반드시 한국어로만 답변한다.

현재 선택 모델: {model}
선택 이유: {reason}

이전 대화:
{context}

중요 규칙:
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
def root() -> Dict[str, str]:
    return {"status": "ok", "service": "AURUM v2 API"}


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "healthy"}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
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
        )

    model, reason = select_model(message)

    history.append({"role": "user", "content": message})

    if "저장해" in message or "코드 저장" in message:
        result = save_code(req.last_code, req.code_path)
        answer = f"[AURUM 코드 저장]\n{result}"
        history.append({"role": "assistant", "content": answer})
        return ChatResponse(
            answer=answer,
            model="SYSTEM",
            reason="코드 저장 명령",
            history=history,
            last_code=req.last_code,
            code_path=req.code_path,
        )

    if "실행해" in message or "테스트해" in message or "돌려봐" in message:
        run_result = run_python(req.code_path)
        answer = f"[AURUM 코드 실행]\n{run_result}"
        history.append({"role": "assistant", "content": answer})
        return ChatResponse(
            answer=answer,
            model="SYSTEM",
            reason="코드 실행 명령",
            history=history,
            last_code=req.last_code,
            code_path=req.code_path,
            run_result=run_result,
        )

    if model == "WEATHER_API":
        answer = get_weather()
        history.append({"role": "assistant", "content": answer})
        return ChatResponse(
            answer=answer,
            model=model,
            reason=reason,
            history=history,
            last_code=req.last_code,
            code_path=req.code_path,
        )

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

    return ChatResponse(
        answer=answer,
        model=model,
        reason=reason,
        history=history,
        last_code=last_code,
        code_path=code_path,
        run_result=run_result,
    )
