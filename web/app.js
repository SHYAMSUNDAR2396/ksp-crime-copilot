/* Native browser client: no raw audio is sent or stored. */
(function () {
  "use strict";
  const question = document.getElementById("question");
  const form = document.getElementById("composer");
  const mic = document.getElementById("mic");
  const conversation = document.getElementById("conversation");
  const status = document.getElementById("status");
  const roleBadge = document.getElementById("role-badge");
  const intelligenceOutput = document.getElementById("intelligence-output");
  const caseId = document.getElementById("case-id");
  const demographicDimension = document.getElementById("demographic-dimension");

  function createSessionId() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return "browser-" + window.crypto.randomUUID();
    }
    if (window.crypto && typeof window.crypto.getRandomValues === "function") {
      const bytes = new Uint8Array(16);
      window.crypto.getRandomValues(bytes);
      return "browser-" + Array.from(bytes).map(function (value) {
        return value.toString(16).padStart(2, "0");
      }).join("");
    }
    return "browser-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2);
  }

  function setAuthStatus(response) {
    if (response.status === 401 || response.status === 403) {
      roleBadge.textContent = "Authentication required";
    } else if (response.ok) {
      roleBadge.textContent = "Authenticated officer";
    } else {
      roleBadge.textContent = "Service unavailable";
    }
  }

  const sessionId = createSessionId();
  let turnId = 0;
  let activeRequest = null;
  let recognition = null;

  function renderNetwork(data, result) {
    intelligenceOutput.textContent = "";
    const summary = document.createElement("p");
    summary.appendChild(document.createTextNode("Evidence: " + result.evidence.status + " · citations: "));
    appendCitationLinks(summary, result.citations || []);
    intelligenceOutput.appendChild(summary);
    const graph = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    graph.setAttribute("class", "network-graph");
    graph.setAttribute("viewBox", "0 0 720 220");
    const nodes = data.nodes || [];
    const positions = {};
    nodes.forEach(function (node, index) {
      positions[node] = {x: 60 + (index % 6) * 120, y: 70 + Math.floor(index / 6) * 85};
    });
    (data.edges || []).forEach(function (edge) {
      if (!positions[edge.source] || !positions[edge.target]) return;
      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("x1", positions[edge.source].x);
      line.setAttribute("y1", positions[edge.source].y);
      line.setAttribute("x2", positions[edge.target].x);
      line.setAttribute("y2", positions[edge.target].y);
      graph.appendChild(line);
    });
    nodes.forEach(function (node) {
      const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
      const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      circle.setAttribute("cx", positions[node].x);
      circle.setAttribute("cy", positions[node].y);
      circle.setAttribute("r", "8");
      const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
      label.setAttribute("x", positions[node].x + 12);
      label.setAttribute("y", positions[node].y + 4);
      label.textContent = node;
      group.appendChild(circle);
      group.appendChild(label);
      graph.appendChild(group);
    });
    intelligenceOutput.appendChild(graph);
  }

  function renderIntelligence(result) {
    if (result.refused) {
      intelligenceOutput.textContent = result.answer || "The view was refused safely.";
      return;
    }
    if (result.data && result.data.nodes) {
      renderNetwork(result.data, result);
      return;
    }
    if (result.data && result.data.case) {
      renderCaseDetail(result.data, result);
      return;
    }
    if (result.data && (result.data.hotspots || result.data.trends)) {
      renderAnalytics(result.data, result);
      return;
    }
    if (result.data && result.data.rows) {
      renderAudit(result.data, result);
      return;
    }
    if (result.data && result.data.matches) {
      renderNarratives(result.data, result);
      return;
    }
    intelligenceOutput.textContent = "Evidence: " + result.evidence.status +
      "\nCitations: " + ((result.citations || []).join(", ") || "none") +
      "\n\n" + JSON.stringify(result.data, null, 2);
  }

  function renderCaseDetail(data, result) {
    intelligenceOutput.textContent = "";
    const summary = document.createElement("p");
    summary.appendChild(document.createTextNode("Exact visible case evidence · "));
    appendCitationLinks(summary, result.citations || []);
    intelligenceOutput.appendChild(summary);
    const table = document.createElement("table");
    table.className = "case-detail-table";
    const body = document.createElement("tbody");
    Object.keys(data.case || {}).forEach(function (key) {
      const row = document.createElement("tr");
      const heading = document.createElement("th");
      heading.textContent = key;
      const value = document.createElement("td");
      value.textContent = String(data.case[key] == null ? "" : data.case[key]);
      row.appendChild(heading);
      row.appendChild(value);
      body.appendChild(row);
    });
    table.appendChild(body);
    intelligenceOutput.appendChild(table);
  }

  function renderAnalytics(data, result) {
    intelligenceOutput.textContent = "";
    const summary = document.createElement("p");
    const warning = data.warning || {};
    summary.appendChild(document.createTextNode("Evidence: " + result.evidence.status +
      " · warning: " + (warning.warning ? "above baseline" : "none") +
      " · citations: "));
    appendCitationLinks(summary, result.citations || []);
    intelligenceOutput.appendChild(summary);
    const hotspots = data.hotspots || [];
    if (hotspots.length) {
      const map = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      map.setAttribute("class", "hotspot-map");
      map.setAttribute("viewBox", "0 0 720 260");
      map.setAttribute("role", "img");
      map.setAttribute("aria-label", "Schematic geographic hotspot map");
      const lats = hotspots.map(function (item) { return Number(item.latitude); });
      const lons = hotspots.map(function (item) { return Number(item.longitude); });
      const minLat = Math.min.apply(null, lats), maxLat = Math.max.apply(null, lats);
      const minLon = Math.min.apply(null, lons), maxLon = Math.max.apply(null, lons);
      const latSpan = Math.max(maxLat - minLat, 0.0001), lonSpan = Math.max(maxLon - minLon, 0.0001);
      hotspots.forEach(function (item) {
        const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        const x = 36 + ((Number(item.longitude) - minLon) / lonSpan) * 648;
        const y = 224 - ((Number(item.latitude) - minLat) / latSpan) * 188;
        circle.setAttribute("cx", x);
        circle.setAttribute("cy", y);
        circle.setAttribute("r", String(Math.max(7, Math.min(28, Number(item.radius_km || 0) * 18))));
        circle.setAttribute("aria-label", "Hotspot " + item.cluster_id);
        map.appendChild(circle);
      });
      intelligenceOutput.appendChild(map);
    }
    const trend = document.createElement("p");
    trend.textContent = "Trend points: " + (data.trends || []).length +
      " · hotspots: " + hotspots.length +
      ". Geographic and temporal decision support only.";
    intelligenceOutput.appendChild(trend);
    const leads = (data.prevention && data.prevention.repeat_offender_leads) || [];
    if (leads.length) {
      const leadHeading = document.createElement("p");
      leadHeading.textContent = "Command prevention leads · investigation only:";
      intelligenceOutput.appendChild(leadHeading);
      const leadList = document.createElement("ul");
      leadList.className = "prevention-leads";
      leads.forEach(function (lead) {
        const item = document.createElement("li");
        item.appendChild(document.createTextNode(
          (lead.names || []).join(" / ") + " · " +
          String(lead.case_count || 0) + " linked visible cases · citations: "
        ));
        appendCitationLinks(item, lead.citations || []);
        leadList.appendChild(item);
      });
      intelligenceOutput.appendChild(leadList);
    }
  }

  function renderAudit(data, result) {
    intelligenceOutput.textContent = "";
    const summary = document.createElement("p");
    summary.textContent = "Audit scope: " + data.visibility + " · evidence: " + result.evidence.status;
    intelligenceOutput.appendChild(summary);
    const table = document.createElement("table");
    table.className = "audit-table";
    const headings = ["Time", "Employee", "Question", "Rows", "Citations"];
    const head = document.createElement("thead");
    const headingRow = document.createElement("tr");
    headings.forEach(function (heading) {
      const cell = document.createElement("th");
      cell.textContent = heading;
      headingRow.appendChild(cell);
    });
    head.appendChild(headingRow);
    table.appendChild(head);
    const body = document.createElement("tbody");
    (data.rows || []).forEach(function (row) {
      const tableRow = document.createElement("tr");
      [row.LoggedAt, row.EmployeeID, row.Question, row.RowCount, row.CrimeNos || "none"].forEach(function (value) {
        const cell = document.createElement("td");
        cell.textContent = String(value == null ? "" : value);
        tableRow.appendChild(cell);
      });
      body.appendChild(tableRow);
    });
    table.appendChild(body);
    intelligenceOutput.appendChild(table);
  }

  function renderNarratives(data, result) {
    intelligenceOutput.textContent = "";
    const summary = document.createElement("p");
    summary.textContent = "Evidence: " + result.evidence.status +
      " · matches: " + (data.matches || []).length +
      (data.partial ? " · local fallback" : "") +
      " · citations: " + ((result.citations || []).join(", ") || "none");
    intelligenceOutput.appendChild(summary);
    const list = document.createElement("ul");
    list.className = "narrative-results";
    (data.matches || []).forEach(function (match) {
      const item = document.createElement("li");
      item.appendChild(citationButton(match.crime_no));
      item.appendChild(document.createTextNode(" · score " +
        String(match.score == null ? "" : match.score) + " — " +
        String(match.excerpt || "")));
      list.appendChild(item);
    });
    intelligenceOutput.appendChild(list);
  }

  function citationButton(crimeNo) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "citation-link";
    button.textContent = String(crimeNo || "citation");
    button.addEventListener("click", function () {
      loadCaseDetail(String(crimeNo || ""));
    });
    return button;
  }

  function appendCitationLinks(container, citations) {
    if (!citations.length) {
      container.appendChild(document.createTextNode("none"));
      return;
    }
    citations.forEach(function (crimeNo, index) {
      if (index) container.appendChild(document.createTextNode(", "));
      container.appendChild(citationButton(crimeNo));
    });
  }

  async function loadCaseDetail(crimeNo) {
    if (!crimeNo) return;
    intelligenceOutput.textContent = "Loading the scope-checked citation…";
    try {
      const response = await fetch("/functions/crime_query", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        credentials: "same-origin",
        body: JSON.stringify({operation: "case_detail", crime_no: crimeNo})
      });
      const result = await response.json();
      setAuthStatus(response);
      if (!response.ok || result.refused) {
        intelligenceOutput.textContent = result.answer || "Citation access refused safely.";
        return;
      }
      renderCaseDetail(result.data, result);
    } catch (error) {
      intelligenceOutput.textContent = "Citation service unavailable. Retry while authenticated.";
    }
  }

  function renderAlerts(data) {
    intelligenceOutput.textContent = "";
    const summary = document.createElement("p");
    summary.textContent = "Scope-checked alerts: " + ((data.alerts || []).length);
    intelligenceOutput.appendChild(summary);
    const table = document.createElement("table");
    table.className = "alert-table";
    const headings = ["Alert", "Type", "Cases", "Score", "Status", "Actions"];
    const head = document.createElement("thead");
    const headingRow = document.createElement("tr");
    headings.forEach(function (heading) {
      const cell = document.createElement("th");
      cell.textContent = heading;
      headingRow.appendChild(cell);
    });
    head.appendChild(headingRow);
    table.appendChild(head);
    const body = document.createElement("tbody");
    (data.alerts || []).forEach(function (alert) {
      const row = document.createElement("tr");
      [alert.AlertID, alert.AlertType,
        (alert.AnchorCrimeNo || "") + " / " + (alert.MatchedCrimeNo || ""),
        alert.Score, alert.Status].forEach(function (value) {
        const cell = document.createElement("td");
        cell.textContent = String(value == null ? "" : value);
        row.appendChild(cell);
      });
      const actions = document.createElement("td");
      actions.className = "alert-actions";
      if (alert.Status !== "Linked" && alert.Status !== "Dismissed") {
        if (alert.Status !== "Reviewing") {
          actions.appendChild(actionButton(alert.AlertID, "Review", "Reviewing"));
        }
        actions.appendChild(actionButton(alert.AlertID, "Link", "Linked"));
        actions.appendChild(actionButton(alert.AlertID, "Dismiss", "Dismissed"));
      } else {
        actions.textContent = "Closed";
      }
      row.appendChild(actions);
      body.appendChild(row);
    });
    table.appendChild(body);
    intelligenceOutput.appendChild(table);
  }

  function actionButton(alertId, label, statusValue) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary alert-action";
    button.textContent = label;
    button.addEventListener("click", function () {
      transitionAlert(alertId, statusValue);
    });
    return button;
  }

  async function transitionAlert(alertId, statusValue) {
    let note = "";
    if (statusValue === "Linked" || statusValue === "Dismissed") {
      note = window.prompt("A note is required for " + statusValue + ".", "") || "";
      if (!note.trim()) {
        intelligenceOutput.textContent = statusValue + " requires a non-empty note.";
        return;
      }
    }
    intelligenceOutput.textContent = "Updating alert safely…";
    try {
      const response = await fetch("/functions/silent_match/alerts/" + encodeURIComponent(alertId) + "/transition", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        credentials: "same-origin",
        body: JSON.stringify({to_status: statusValue, note: note})
      });
      const result = await response.json();
      if (!response.ok) {
        intelligenceOutput.textContent = result.error || "Alert transition refused safely.";
        return;
      }
      await loadAlerts();
    } catch (error) {
      intelligenceOutput.textContent = "Alert transition unavailable. Retry while authenticated.";
    }
  }

  async function loadAlerts() {
    intelligenceOutput.textContent = "Loading scope-checked alerts…";
    try {
      const response = await fetch("/functions/silent_match/alerts", {
        method: "GET", credentials: "same-origin"
      });
      const result = await response.json();
      setAuthStatus(response);
      if (!response.ok) {
        intelligenceOutput.textContent = result.error || "Alert access refused safely.";
        return;
      }
      renderAlerts(result);
    } catch (error) {
      intelligenceOutput.textContent = "Alert service unavailable. Retry while authenticated.";
    }
  }

  async function runIntelligence(operation) {
    const payload = {operation: operation};
    if (operation === "network" || operation === "profile") {
      const selected = Number(caseId.value);
      if (!Number.isInteger(selected) || selected < 1) {
        intelligenceOutput.textContent = "Enter a valid Case ID for this view.";
        return;
      }
      payload.case_master_id = selected;
    }
    if (operation === "demographics") payload.dimension = demographicDimension.value;
    if (operation === "narrative") {
      payload.question = question.value.trim();
      if (!payload.question) {
        intelligenceOutput.textContent = "Enter a narrative search question first.";
        return;
      }
    }
    intelligenceOutput.textContent = "Loading scope-checked evidence…";
    try {
      const response = await fetch("/functions/crime_query", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        credentials: "same-origin",
        body: JSON.stringify(payload)
      });
      const result = await response.json();
      setAuthStatus(response);
      if (!response.ok) {
        intelligenceOutput.textContent = result.answer || result.error ||
          "The requested intelligence view was refused safely.";
        return;
      }
      renderIntelligence(result);
    } catch (error) {
      intelligenceOutput.textContent = "Service unavailable. Retry when the authenticated session is active.";
    }
  }

  async function exportConversation() {
    intelligenceOutput.textContent = "Preparing the owned conversation export…";
    try {
      const response = await fetch("/functions/crime_query", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        credentials: "same-origin",
        body: JSON.stringify({operation: "export", session_id: sessionId})
      });
      setAuthStatus(response);
      if (!response.ok) {
        const refused = await response.json();
        intelligenceOutput.textContent = refused.error || refused.code || "Export refused safely.";
        return;
      }
      const link = document.createElement("a");
      link.href = URL.createObjectURL(await response.blob());
      link.download = response.headers.get("Content-Disposition")?.match(/filename=([^;]+)/i)?.[1]?.replace(/["']/g, "") || "ksp-conversation.pdf";
      link.click();
      URL.revokeObjectURL(link.href);
      intelligenceOutput.textContent = "Conversation export downloaded with its citations.";
    } catch (error) {
      intelligenceOutput.textContent = "Export unavailable. Retry while the authenticated session is active.";
    }
  }

  function addMessage(kind, text, citations) {
    const empty = conversation.querySelector(".empty-state");
    if (empty) empty.remove();
    const node = document.createElement("div");
    node.className = "message " + kind;
    node.textContent = text;
    if (citations && citations.length) {
      const cite = document.createElement("div");
      cite.className = "citations";
      cite.appendChild(document.createTextNode("Citations: "));
      appendCitationLinks(cite, citations);
      node.appendChild(cite);
    }
    conversation.appendChild(node);
    conversation.scrollTop = conversation.scrollHeight;
  }

  function cancelCurrentTurn() {
    if (activeRequest) activeRequest.abort();
    activeRequest = null;
    if (window.speechSynthesis) window.speechSynthesis.cancel();
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
        credentials: "same-origin",
        signal: controller.signal,
        body: JSON.stringify({
          session_id: sessionId,
          turn_id: currentTurn,
          input_mode: inputMode,
          question: transcript,
          transcript: transcript,
          response_language: /[\u0c80-\u0cff]/.test(transcript) ? "kn" : "en"
        })
      });
      const result = await response.json();
      setAuthStatus(response);
      if (currentTurn !== turnId || result.turn_id && result.turn_id !== currentTurn) return;
      addMessage("assistant", result.answer || "No answer was returned.", result.citations || []);
      status.textContent = result.refused
        ? "Request refused safely."
        : result.partial
          ? "Result set capped; additional matching cases may exist."
          : "";
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

  document.getElementById("network-view").addEventListener("click", function () {
    runIntelligence("network");
  });
  document.getElementById("analytics-view").addEventListener("click", function () {
    runIntelligence("analytics");
  });
  document.getElementById("profile-view").addEventListener("click", function () {
    runIntelligence("profile");
  });
  document.getElementById("narrative-view").addEventListener("click", function () {
    runIntelligence("narrative");
  });
  document.getElementById("demographics-view").addEventListener("click", function () {
    runIntelligence("demographics");
  });
  document.getElementById("audit-view").addEventListener("click", function () {
    runIntelligence("audit");
  });
  document.getElementById("alerts-view").addEventListener("click", loadAlerts);
  document.getElementById("export-view").addEventListener("click", exportConversation);

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
      if (window.speechSynthesis) window.speechSynthesis.cancel();
      recognition.start();
    });
  }
}());
