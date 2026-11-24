import React, {useMemo, useState} from 'react';
import {createRoot} from 'react-dom/client';
import './styles.css';

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000';

function App(){
  const sessionId = useMemo(()=>`s-${crypto.randomUUID()}`, []);
  const [messages,setMessages]=useState([]);
  const [input,setInput]=useState('');
  const [systemPrompt,setSystemPrompt]=useState('');
  const [loading,setLoading]=useState(false);

  async function send(){
    const message=input.trim(); if(!message || loading) return;
    setInput(''); setMessages(m=>[...m,{role:'user',content:message}]); setLoading(true);
    try{
      const body={session_id:sessionId,message};
      if(systemPrompt.trim()) body.system_prompt=systemPrompt.trim();
      const r=await fetch(`${API}/chat`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      const data=await r.json();
      if(!r.ok) throw new Error(data.detail || 'Request failed');
      setMessages(m=>[...m,{role:'assistant',content:data.reply,metadata:data.metadata}]);
    }catch(e){ setMessages(m=>[...m,{role:'error',content:`Error: ${e.message}`}]); }
    finally{setLoading(false)}
  }

  return <main className="shell">
    <header><div><span className="eyebrow">FULL-STACK AI</span><h1>Lyftr Chat</h1><p>Resilient LLM chat with cache, failover and persistent sessions.</p></div><span className="status">● Ready</span></header>
    <section className="prompt"><label>Session system prompt <span>optional</span></label><input data-testid="system-prompt-input" value={systemPrompt} onChange={e=>setSystemPrompt(e.target.value)} placeholder="You are a concise, helpful assistant."/></section>
    <section className="chat">
      {messages.length===0 && <div className="empty"><h2>Start a conversation</h2><p>Every assistant response includes its inference metadata.</p></div>}
      {messages.map((m,i)=>m.role==='assistant' ? <article className="message assistant" data-testid="assistant-message" key={i}><div className="role">AI</div><p>{m.content}</p><div className="meta"><span data-testid="meta-source">{m.metadata.resolution_source}</span><span data-testid="meta-model">{m.metadata.model}</span><span data-testid="meta-latency">{m.metadata.latency_ms} ms</span><span>IN <b data-testid="meta-input-tokens">{m.metadata.input_tokens}</b></span><span>OUT <b data-testid="meta-output-tokens">{m.metadata.output_tokens}</b></span></div></article> : <article className={`message ${m.role}`} key={i}><div className="role">{m.role==='user'?'YOU':'!'}</div><p>{m.content}</p></article>)}
      {loading && <div className="thinking">Thinking…</div>}
    </section>
    <footer><textarea data-testid="chat-input" value={input} onChange={e=>setInput(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send()}}} placeholder="Message Lyftr AI…"/><button data-testid="send-button" disabled={loading||!input.trim()} onClick={send}>Send ↑</button></footer>
  </main>
}
createRoot(document.getElementById('root')).render(<App/>);
