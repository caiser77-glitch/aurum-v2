import React, { useEffect, useRef, useState } from "react";
import { Send, RotateCcw, Cpu, Code2 } from "lucide-react";
import { createRoot } from "react-dom/client";
import "./style.css";

const API_URL = "http://100.98.149.128:7870/chat";

function App() {
  const [messages, setMessages] = useState([
    {
      role: "assistant",
      content:
        "안녕하세요. AURUM v2입니다.\nEnter는 전송, Shift+Enter는 줄바꿈입니다.",
    },
  ]);

  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [modelInfo, setModelInfo] = useState("대기 중");
  const [lastCode, setLastCode] = useState("");
  const [codePath, setCodePath] = useState("scripts/chat_generated.py");

  const bottomRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  useEffect(() => {
    inputRef.current?.focus();
  }, [busy]);

  async function sendMessage() {
    const text = input.trim();
    if (!text || busy) return;

    const nextMessages = [...messages, { role: "user", content: text }];
    setMessages(nextMessages);
    setInput("");
    setBusy(true);
    setModelInfo("처리 중...");

    try {
      const response = await fetch(API_URL, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          message: text,
          history: messages,
          last_code: lastCode,
          code_path: codePath,
        }),
      });

      if (!response.ok) {
        throw new Error(`API 오류: ${response.status}`);
      }

      const data = await response.json();

      setMessages(data.history || [
        ...nextMessages,
        { role: "assistant", content: data.answer || "응답 없음" },
      ]);

      setLastCode(data.last_code || "");
      setCodePath(data.code_path || "scripts/chat_generated.py");
      setModelInfo(`${data.model} / ${data.reason}`);
    } catch (err) {
      setMessages([
        ...nextMessages,
        {
          role: "assistant",
          content: `오류 발생:\n${err.message}`,
        },
      ]);
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
    setMessages([
      {
        role: "assistant",
        content:
          "대화를 초기화했습니다.\nEnter는 전송, Shift+Enter는 줄바꿈입니다.",
      },
    ]);
    setInput("");
    setBusy(false);
    setModelInfo("대기 중");
    setLastCode("");
    setCodePath("scripts/chat_generated.py");
    setTimeout(() => inputRef.current?.focus(), 100);
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

        <div className="panel">
          <div className="panel-title">
            <Cpu size={16} />
            모델 상태
          </div>
          <div className="model-info">{modelInfo}</div>
        </div>

        <div className="panel">
          <div className="panel-title">
            <Code2 size={16} />
            코드 경로
          </div>
          <input
            className="path-input"
            value={codePath}
            onChange={(e) => setCodePath(e.target.value)}
          />
        </div>

        <button className="reset-btn" onClick={resetChat}>
          <RotateCcw size={16} />
          대화 초기화
        </button>

        <div className="hint">
          <p>사용 예시</p>
          <span>csv 정리 코드 짜줘</span>
          <span>코드 검정해줘</span>
          <span>저장해줘</span>
          <span>실행해줘</span>
        </div>
      </aside>

      <main className="chat">
        <header className="chat-header">
          <div>
            <h2>AURUM Chat</h2>
            <p>Enter 전송 · Shift+Enter 줄바꿈</p>
          </div>
          <div className={busy ? "status busy" : "status"}>
            {busy ? "응답 생성 중" : "대기 중"}
          </div>
        </header>

        <section className="messages">
          {messages.map((msg, idx) => (
            <div key={idx} className={`message-row ${msg.role}`}>
              <div className="avatar">
                {msg.role === "user" ? "U" : "A"}
              </div>
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
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="메시지를 입력하세요..."
            rows={3}
            disabled={busy}
          />
          <button onClick={sendMessage} disabled={busy || !input.trim()}>
            <Send size={18} />
          </button>
        </footer>
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")).render(<App />);
