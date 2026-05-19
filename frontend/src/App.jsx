import React, { useEffect, useRef, useState } from "react";
import { Send, RotateCcw, Cpu, Code2, Upload, FileText, Map, Table, Brain, Trash2, RefreshCw } from "lucide-react";
import { createRoot } from "react-dom/client";
import "./style.css";

const API_BASE = "http://100.98.149.128:7870";
const CHAT_URL = `${API_BASE}/chat`;

function App() {
  const [tab, setTab] = useState("chat");
  const [messages, setMessages] = useState([
    { role: "assistant", content: "안녕하세요. AURUM v2입니다.\nEnter는 전송, Shift+Enter는 줄바꿈입니다." },
  ]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [modelInfo, setModelInfo] = useState("대기 중");
  const [lastCode, setLastCode] = useState("");
  const [codePath, setCodePath] = useState("scripts/chat_generated.py");
  const [selectedModel, setSelectedModel] = useState("AUTO");
  const [toolBusy, setToolBusy] = useState(false);
  const [toolResult, setToolResult] = useState("");
  const [pages, setPages] = useState("1");
  const [memory, setMemory] = useState({ summary: "", facts: [], updated_at: "" });

  const bottomRef = useRef(null);
  const inputRef = useRef(null);
  const imageRef = useRef(null);
  const pdfRef = useRef(null);
  const cadRef = useRef(null);
  const excelRef = useRef(null);

  useEffect(() => {
    loadMemory();
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  useEffect(() => {
    inputRef.current?.focus();
  }, [busy, tab]);

  async function loadMemory() {
    try {
      const res = await fetch(`${API_BASE}/memory`);
      const data = await res.json();
      setMemory(data);
    } catch {
      setMemory({ summary: "기억을 불러오지 못했습니다.", facts: [], updated_at: "" });
    }
  }

  async function clearMemory() {
    if (!confirm("AURUM 장기 기억을 초기화할까요?")) return;
    const res = await fetch(`${API_BASE}/memory`, { method: "DELETE" });
    const data = await res.json();
    setMemory(data);
  }

  async function sendMessage() {
    const text = input.trim();
    if (!text || busy) return;

    const nextMessages = [...messages, { role: "user", content: text }];
    setMessages(nextMessages);
    setInput("");
    setBusy(true);
    setModelInfo("처리 중...");

    try {
      const response = await fetch(CHAT_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          history: messages,
          last_code: lastCode,
          code_path: codePath,
          selected_model: selectedModel,
        }),
      });

      if (!response.ok) throw new Error(`API 오류: ${response.status}`);

      const data = await response.json();
      setMessages(data.history || [...nextMessages, { role: "assistant", content: data.answer || "응답 없음" }]);
      setLastCode(data.last_code || "");
      setCodePath(data.code_path || "scripts/chat_generated.py");
      setModelInfo(`${data.model} / ${data.reason}`);
      await loadMemory();
    } catch (err) {
      setMessages([...nextMessages, { role: "assistant", content: `오류 발생:\n${err.message}` }]);
      setModelInfo("오류 발생");
    } finally {
      setBusy(false);
    }
  }

  function handleKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  function resetChat() {
    setMessages([{ role: "assistant", content: "대화를 초기화했습니다.\nEnter는 전송, Shift+Enter는 줄바꿈입니다." }]);
    setInput("");
    setBusy(false);
    setModelInfo("대기 중");
    setLastCode("");
    setCodePath("scripts/chat_generated.py");
    setTimeout(() => inputRef.current?.focus(), 100);
  }

  async function runTool(kind) {
    const map = {
      image: { ref: imageRef, url: "/tools/image-ocr", label: "이미지 OCR" },
      pdf: { ref: pdfRef, url: "/tools/pdf-ocr", label: "PDF OCR" },
      cad: { ref: cadRef, url: "/tools/cad-kml", label: "CAD/KML 변환" },
      excel: { ref: excelRef, url: "/tools/excel", label: "Excel 분석" },
    };

    const item = map[kind];
    const file = item.ref.current?.files?.[0];

    if (!file) {
      setToolResult("파일을 선택하세요.");
      return;
    }

    const form = new FormData();
    form.append("file", file);
    if (kind === "pdf") form.append("pages", pages);

    setToolBusy(true);
    setToolResult(`${item.label} 처리 중...`);

    try {
      const res = await fetch(`${API_BASE}${item.url}`, { method: "POST", body: form });
      const data = await res.json();

      if (!res.ok || data.status === "error") throw new Error(data.message || `API 오류: ${res.status}`);

      const download = data.url ? `${API_BASE}${data.url}` : "";
      setToolResult(`${data.message}\n결과 파일: ${data.file || "-"}\n${download ? `다운로드: ${download}` : ""}\n${data.log ? `\n로그:\n${data.log}` : ""}`);
    } catch (err) {
      setToolResult(`오류 발생:\n${err.message}`);
    } finally {
      setToolBusy(false);
    }
  }

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="logo">A</div>
          <div>
            <h1>AURUM v2</h1>
            <p>DGX 통합 AI</p>
          </div>
        </div>

        <button className={tab === "chat" ? "nav active" : "nav"} onClick={() => setTab("chat")}>AURUM Chat</button>
        <button className={tab === "tools" ? "nav active" : "nav"} onClick={() => setTab("tools")}>업무 도구</button>
        <button className={tab === "memory" ? "nav active" : "nav"} onClick={() => { setTab("memory"); loadMemory(); }}>기억 보기</button>

        <div className="panel">
          <div className="panel-title"><Cpu size={16} />모델 상태</div>
          <div className="model-info">{modelInfo}</div>
        </div>

        <div className="panel">
          <div className="panel-title"><Code2 size={16} />모델 선택</div>
          <select
            className="path-input"
            value={selectedModel}
            onChange={(e) => setSelectedModel(e.target.value)}
          >
            <option value="AUTO">AUTO / 자동 선택</option>
            <option value="llama3.1:8b">llama3.1:8b / 빠른 응답</option>
            <option value="qwen2.5:14b">qwen2.5:14b / 코드 작업</option>
            <option value="qwen2.5:72b">qwen2.5:72b / 대형 분석</option>
            <option value="llama3.1:70b">llama3.1:70b / 검토·검정</option>
            <option value="llava:latest">llava:latest / 이미지</option>
            <option value="gemma2:27b">gemma2:27b / 문서 작성</option>
            <option value="gemma2:9b">gemma2:9b / 문장 다듬기</option>
            <option value="gemma:7b">gemma:7b / 가벼운 대화</option>
          </select>
        </div>

        <div className="panel">
          <div className="panel-title"><Code2 size={16} />코드 경로</div>
          <input className="path-input" value={codePath} onChange={(e) => setCodePath(e.target.value)} />
        </div>

        <button className="reset-btn" onClick={resetChat}><RotateCcw size={16} />대화 초기화</button>
      </aside>

      {tab === "chat" && (
        <main className="chat">
          <header className="chat-header">
            <div>
              <h2>AURUM Chat</h2>
              <p>Enter 전송 · Shift+Enter 줄바꿈 · 장기 기억 활성화</p>
            </div>
            <div className={busy ? "status busy" : "status"}>{busy ? "응답 생성 중" : "대기 중"}</div>
          </header>

          <section className="messages">
            {messages.map((msg, idx) => (
              <div key={idx} className={`message-row ${msg.role}`}>
                <div className="avatar">{msg.role === "user" ? "U" : "A"}</div>
                <pre className="bubble">{msg.content}</pre>
              </div>
            ))}
            {busy && (
              <div className="message-row assistant">
                <div className="avatar">A</div>
                <pre className="bubble">⏳ 처리 중...</pre>
              </div>
            )}
            <div ref={bottomRef} />
          </section>

          <footer className="composer">
            <textarea ref={inputRef} value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={handleKeyDown} placeholder="메시지를 입력하세요..." rows={3} disabled={busy} />
            <button onClick={sendMessage} disabled={busy || !input.trim()}><Send size={18} /></button>
          </footer>
        </main>
      )}

      {tab === "tools" && (
        <main className="chat">
          <header className="chat-header">
            <div>
              <h2>업무 도구</h2>
              <p>파일 업로드 → 자동 처리 → 결과 다운로드</p>
            </div>
            <div className={toolBusy ? "status busy" : "status"}>{toolBusy ? "처리 중" : "대기 중"}</div>
          </header>

          <section className="tool-page">
            <div className="tool-grid">
              <div className="tool-card">
                <h3><Upload size={18} /> 이미지 조사표 OCR</h3>
                <input type="file" ref={imageRef} />
                <button onClick={() => runTool("image")} disabled={toolBusy}>이미지 OCR 실행</button>
              </div>

              <div className="tool-card">
                <h3><FileText size={18} /> PDF 조사표 OCR</h3>
                <input type="file" ref={pdfRef} />
                <input className="path-input" value={pages} onChange={(e) => setPages(e.target.value)} placeholder="예: 1,3-5,8" />
                <button onClick={() => runTool("pdf")} disabled={toolBusy}>PDF OCR 실행</button>
              </div>

              <div className="tool-card">
                <h3><Map size={18} /> CAD / KML 변환</h3>
                <input type="file" ref={cadRef} />
                <button onClick={() => runTool("cad")} disabled={toolBusy}>자동 변환 실행</button>
              </div>

              <div className="tool-card">
                <h3><Table size={18} /> Excel 분석</h3>
                <input type="file" ref={excelRef} />
                <button onClick={() => runTool("excel")} disabled={toolBusy}>Excel 분석 실행</button>
              </div>
            </div>

            <pre className="tool-result">{toolResult || "결과가 여기에 표시됩니다."}</pre>
          </section>
        </main>
      )}

      {tab === "memory" && (
        <main className="chat">
          <header className="chat-header">
            <div>
              <h2>장기 기억</h2>
              <p>대화 맥락을 요약 저장해서 다음 대화에 반영합니다.</p>
            </div>
            <div className="memory-actions">
              <button onClick={loadMemory}><RefreshCw size={16} />새로고침</button>
              <button onClick={clearMemory}><Trash2 size={16} />초기화</button>
            </div>
          </header>

          <section className="tool-page">
            <div className="memory-card">
              <h3><Brain size={18} /> 요약</h3>
              <pre>{memory.summary || "저장된 요약 없음"}</pre>
              <p className="muted">업데이트: {memory.updated_at || "-"}</p>
            </div>

            <div className="memory-card">
              <h3>중요 사실</h3>
              {(memory.facts || []).length === 0 ? (
                <p className="muted">저장된 중요 사실 없음</p>
              ) : (
                <ul>
                  {memory.facts.map((x, i) => <li key={i}>{x}</li>)}
                </ul>
              )}
            </div>
          </section>
        </main>
      )}
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);
