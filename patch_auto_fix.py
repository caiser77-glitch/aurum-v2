from pathlib import Path

backend = Path("backend/main.py")
frontend = Path("frontend/src/App.jsx")

s = backend.read_text(encoding="utf-8")

marker = "# ===== AURUM 자동 코드 수정 루프 추가 ====="
if marker in s:
    s = s.split(marker)[0].rstrip() + "\n\n"

add = '''
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
        + "\\n\\n[AURUM 자동 수정 루프]\\n"
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
'''

backend.write_text(s + add + "\n", encoding="utf-8")

fs = frontend.read_text(encoding="utf-8")
fs = fs.replace(
    "const CHAT_URL = `${API_BASE}/chat`;",
    "const CHAT_URL = `${API_BASE}/chat-auto`;"
)
frontend.write_text(fs, encoding="utf-8")

print("자동 수정 루프 패치 완료")
