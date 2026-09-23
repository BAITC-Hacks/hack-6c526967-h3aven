const $ = (s) => document.querySelector(s);
let meeting = null;
const api = async (url, options = {}) => { const r = await fetch(url, options); const body = await r.json(); if (!r.ok) throw new Error(body.detail || "Не удалось выполнить запрос"); return body; };
const esc = (value = "") => String(value).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c]));
const time = (value) => `${String(Math.floor(value / 60)).padStart(2,"0")}:${String(Math.floor(value % 60)).padStart(2,"0")}`;

$("#meeting-date").value = new Date().toISOString().slice(0, 10);
$("#file").addEventListener("change", (event) => { if (event.target.files[0]) $("#file-label").textContent = event.target.files[0].name; });
$("#upload-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const data = new FormData(); data.append("file", $("#file").files[0]); data.append("meeting_date", $("#meeting-date").value); showLoader(true);
  try { meeting = await api("/api/meetings", {method:"POST", body:data}); meeting = await api(`/api/meetings/${meeting.id}/process`, {method:"POST"}); render(); }
  catch (error) { showLoader(false); showError(error.message); }
});
function showLoader(value) { $("#loader").hidden = !value; }
function showError(text) { $("#upload-view").hidden = true; $("#meeting-view").hidden = false; $("#error").hidden = false; $("#error").textContent = text; }
function render() {
  showLoader(false); $("#upload-view").hidden = true; $("#meeting-view").hidden = false;
  if (meeting.status === "failed") return showError(meeting.error || "Обработка не выполнена");
  const transcript = meeting.transcript || {segments:[], duration:0, language:"mixed"};
  $("#meeting-title").textContent = meeting.filename; $("#meeting-meta").textContent = `Совещание · ${meeting.meeting_date}`;
  $("#summary").textContent = meeting.summary; $("#task-count").textContent = meeting.tasks.length; $("#speaker-count").textContent = new Set(transcript.segments.map(x => x.speaker)).size; $("#duration").textContent = time(transcript.duration); $("#language").textContent = transcript.language.toUpperCase();
  $("#topics").innerHTML = meeting.key_topics.map(x => `<span>${esc(x)}</span>`).join("");
  $("#pdf").href = `/api/meetings/${meeting.id}/export/pdf`; $("#docx").href = `/api/meetings/${meeting.id}/export/docx`;
  renderMapping(transcript); renderTasks(); renderTranscript(transcript);
}
function renderMapping(transcript) {
  const speakers = [...new Set(transcript.segments.map(x => x.speaker))];
  $("#mapping").innerHTML = speakers.map((id, index) => `<label class="mapping-row"><span class="avatar a${index % 3}">${index + 1}</span><span>${id}</span><input data-speaker="${id}" value="${esc(meeting.speaker_mapping[id] || "")}" placeholder="Введите имя"></label>`).join("");
}
function renderTasks() {
  $("#task-list").innerHTML = meeting.tasks.length ? meeting.tasks.map((task, index) => `<article class="task-card" data-id="${task.id}"><div class="task-index">${String(index + 1).padStart(2,"0")}</div><div class="task-main"><textarea data-field="task">${esc(task.task)}</textarea><small>Источник: «${esc(task.source)}» · ${time(task.timestamp)}</small></div><div><label>Ответственный<input data-field="assignee" value="${esc(task.assignee || "")}" placeholder="Уточнить"></label></div><div><label>Срок<input data-field="deadline" type="date" value="${esc(task.deadline || "")}"></label></div><span class="confidence ${task.confidence >= .8 ? "high" : "mid"}">${Math.round(task.confidence * 100)}%</span></article>`).join("") : `<div class="empty">Поручения не найдены. Проверьте транскрипт или добавьте их после обработки.</div>`;
}
function renderTranscript(transcript) {
  $("#transcript-list").innerHTML = transcript.segments.map((segment, index) => `<div class="line"><time>${time(segment.start)}</time><span class="dot d${index % 3}"></span><div><b>${esc(meeting.speaker_mapping[segment.speaker] || segment.speaker)}</b><p>${esc(segment.text)}</p></div></div>`).join("");
}
$("#save-mapping").addEventListener("click", async () => { const mapping = Object.fromEntries([...document.querySelectorAll("[data-speaker]")].map(x => [x.dataset.speaker, x.value])); meeting = await api(`/api/meetings/${meeting.id}/speaker-mapping`, {method:"PUT", headers:{"Content-Type":"application/json"}, body:JSON.stringify(mapping)}); render(); });
$("#save-tasks").addEventListener("click", async () => { const tasks = meeting.tasks.map(task => { const card = document.querySelector(`[data-id="${task.id}"]`); return {...task, task: card.querySelector('[data-field="task"]').value, assignee: card.querySelector('[data-field="assignee"]').value || null, deadline: card.querySelector('[data-field="deadline"]').value || null}; }); meeting = await api(`/api/meetings/${meeting.id}/tasks`, {method:"PUT", headers:{"Content-Type":"application/json"}, body:JSON.stringify(tasks)}); render(); });
