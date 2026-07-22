/* Native browser client: no raw audio is sent or stored. */
(function () {
  "use strict";
  const question = document.getElementById("question");
  const form = document.getElementById("composer");
  const mic = document.getElementById("mic");
  const conversation = document.getElementById("conversation");
  const status = document.getElementById("status");
  const sessionId = "browser-" + crypto.randomUUID();
  let turnId = 0;
  let activeRequest = null;
  let recognition = null;

  function addMessage(kind, text, citations) {
    const empty = conversation.querySelector(".empty-state");
    if (empty) empty.remove();
    const node = document.createElement("div");
    node.className = "message " + kind;
    node.textContent = text;
    if (citations && citations.length) {
      const cite = document.createElement("div");
      cite.className = "citations";
      cite.textContent = "Citations: " + citations.join(", ");
      node.appendChild(cite);
    }
    conversation.appendChild(node);
    conversation.scrollTop = conversation.scrollHeight;
  }

  function cancelCurrentTurn() {
    if (activeRequest) activeRequest.abort();
    activeRequest = null;
    window.speechSynthesis.cancel();
  }

  async function submit(text, inputMode) {
    const transcript = (text || "").trim();
    if (!transcript) return;
    cancelCurrentTurn();
    const currentTurn = ++turnId;
    addMessage("user", transcript);
    status.textContent = "Checking authorised evidence…";
    const controller = new AbortController();
    activeRequest = controller;
    try {
      const response = await fetch("/functions/crime_query", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        signal: controller.signal,
        body: JSON.stringify({
          employee_id: window.KSP_EMPLOYEE_ID,
          session_id: sessionId,
          turn_id: currentTurn,
          input_mode: inputMode,
          question: transcript,
          response_language: /[\u0c80-\u0cff]/.test(transcript) ? "kn" : "en"
        })
      });
      const result = await response.json();
      if (currentTurn !== turnId || result.turn_id && result.turn_id !== currentTurn) return;
      addMessage("assistant", result.answer || "No answer was returned.", result.citations || []);
      status.textContent = result.refused ? "Request refused safely." : "";
      if (result.voice && result.voice.speak && window.speechSynthesis) {
        const utterance = new SpeechSynthesisUtterance(result.voice.text);
        utterance.lang = result.voice.language || "en-IN";
        window.speechSynthesis.speak(utterance);
      }
    } catch (error) {
      if (error.name !== "AbortError") status.textContent = "Service unavailable. You can retry or continue by typing.";
    } finally {
      if (currentTurn === turnId) activeRequest = null;
    }
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    const text = question.value;
    question.value = "";
    submit(text, "text");
  });

  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) {
    mic.disabled = true;
    mic.textContent = "Voice unavailable";
  } else {
    recognition = new Recognition();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = "kn-IN";
    recognition.onstart = function () {
      cancelCurrentTurn();
      mic.classList.add("listening");
      status.textContent = "Listening…";
    };
    recognition.onresult = function (event) {
      let finalText = "";
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        if (event.results[index].isFinal) finalText += event.results[index][0].transcript;
      }
      if (finalText) {
        question.value = finalText;
        submit(finalText, "voice");
      }
    };
    recognition.onerror = function () { status.textContent = "Voice input failed. Please type your question."; };
    recognition.onend = function () { mic.classList.remove("listening"); };
    mic.addEventListener("click", function () {
      window.speechSynthesis.cancel();
      recognition.start();
    });
  }
}());
