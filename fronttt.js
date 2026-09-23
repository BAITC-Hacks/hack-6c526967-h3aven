// Same-origin API adapter. No recordings or credentials are stored in the browser.
(() => {
  const $ = id => document.getElementById(id);
  const dialog = $('workspace');
  let current = null, history = [], previewUrl = null, busy = false;
  let jobId = null, polling = false;
  try { jobId = localStorage.getItem('sozde.activeJob'); } catch (_) {}
  function remember(id) {
    jobId = id;
    try { if (id) localStorage.setItem('sozde.activeJob', id); else localStorage.removeItem('sozde.activeJob'); } catch (_) {}
  }
  function setBusy(value) {
    busy = value; $('ws-process').disabled = value;
    $('ws-file').disabled = value; $('ws-sample').disabled = value;
    $('ws-process').textContent = value ? 'Processing…' : 'Create meeting protocol';
  }
  async function pollJob() {
    if (!jobId || polling) return;
    polling = true; setBusy(true); $('ws-progress').hidden = false;
    $('ws-reconnect').hidden = true;
    try {
      while (jobId) {
        const job = await api(`/jobs/${jobId}`);
        const stages = ['Waiting for another meeting to finish', 'Preparing audio', 'Transcribing speech', 'Identifying speakers', 'Extracting decisions and tasks', 'Creating documents', 'Protocol ready'];
        $('ws-stage').textContent = stages[job.stage] || 'Processing';
        $('ws-elapsed').textContent = `Elapsed: ${time(Date.now()/1000 - (job.started_at || job.created_at))}`;
        $('ws-stages').querySelectorAll('li').forEach((li, i) => {
          li.dataset.state = i + 1 < job.stage ? 'done' : i + 1 === job.stage ? 'active' : 'waiting';
          if (i + 1 === job.stage) li.setAttribute('aria-current', 'step'); else li.removeAttribute('aria-current');
        });
        $('ws-progress-hint').textContent = 'You can close this window and return later. Keep the server running. Long recordings and the first model download may take longer.';
        if (job.status === 'completed') {
          const result = await api(`/meetings/${jobId}`);
          render(result); remember(null); setBusy(false);
          status('Protocol ready. Review names, tasks and deadlines before sharing.');
          await loadHistory(); break;
        }
        if (['failed','interrupted'].includes(job.status)) {
          remember(null); setBusy(false); $('ws-stage').textContent = 'Processing stopped';
          $('ws-progress-hint').textContent = job.error; status(job.error, true); break;
        }
        await new Promise(resolve => setTimeout(resolve, 2000));
      }
    } catch (error) {
      status('Connection lost. Your task may still be running. Reconnect to check its status.', true);
      $('ws-reconnect').hidden = false;
    } finally { polling = false; }
  }
  const status = (text, error = false) => { $('ws-message').textContent = text; $('ws-message').dataset.error = error; };
  async function api(path, options = {}) {
    const response = await fetch(path, options);
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(typeof body.detail === 'string' ? body.detail : `Request failed (${response.status})`);
    }
    return response.json();
  }
  function node(tag, text, parent) {
    const element = document.createElement(tag);
    if (text != null) element.textContent = text;
    if (parent) parent.append(element);
    return element;
  }
  function view(name) {
    dialog.querySelectorAll('[data-ws-panel]').forEach(p => p.hidden = p.dataset.wsPanel !== name);
    dialog.querySelectorAll('[data-view]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.view === name)));
  }
  const time = value => { const n = Math.max(0, Math.floor(Number(value) || 0)); return `${String(Math.floor(n / 60)).padStart(2,'0')}:${String(n % 60).padStart(2,'0')}`; };
  function input(parent, value, field, multiline = false) {
    const element = node(multiline ? 'textarea' : 'input', null, parent);
    element.value = value ?? ''; element.dataset.field = field;
    element.setAttribute('aria-label', field);
    return element;
  }
  function select(parent, value, choices, field) {
    const element = node('select', null, parent); element.dataset.field = field;
    element.setAttribute('aria-label', field);
    [...new Set([...choices, value].filter(Boolean))].forEach(choice => { const option = node('option', choice.replaceAll('_',' '), element); option.value = choice; });
    element.value = value || choices[0]; return element;
  }
  function renderTranscript() {
    const target = $('ws-transcript'); target.replaceChildren();
    const query = $('ws-search').value.toLocaleLowerCase();
    (current?.segments || []).filter(s => `${s.speaker} ${s.text}`.toLocaleLowerCase().includes(query)).forEach(segment => {
      const row = node('div', null, target); row.className = 'ws-segment';
      node('time', time(segment.start), row); node('strong', segment.speaker, row); node('p', segment.text, row);
    });
  }
  function render(result) {
    current = result; $('ws-empty').hidden = true; $('ws-result').hidden = false;
    const analysis = result.analysis || {};
    $('ws-result-title').textContent = analysis.title || result.source_file;
    $('ws-metrics').textContent = `${time(result.duration)} · ${result.language} · ${result.num_speakers} speakers · ${result.model} · ${result.inference_device} · ${result.processing_seconds}s processing`;
    $('ws-summary').value = analysis.summary || '';
    for (const [id, values] of [['ws-agenda', analysis.agenda], ['ws-decisions', analysis.key_decisions], ['ws-risks', analysis.risks], ['ws-participants', (analysis.participants || []).map(p => `${p.name} ${p.role || ''}`)]]) {
      $(id).replaceChildren(); (values?.length ? values : ['None reported']).forEach(value => node('li', value, $(id)));
    }
    $('ws-warnings').replaceChildren();
    for (const warning of result.quality?.warnings || []) node('p', warning, $('ws-warnings'));
    if (analysis.analysis_engine) node('p', `Analysis: ${analysis.analysis_engine}`, $('ws-warnings'));
    $('ws-speakers').replaceChildren();
    [...new Set((result.segments || []).map(s => s.speaker))].forEach(speaker => input(node('label', speaker, $('ws-speakers')), speaker, speaker));
    $('ws-tasks').replaceChildren();
    (analysis.tasks || []).forEach(task => {
      const row = node('tr', null, $('ws-tasks'));
      for (const field of ['task','assignee','deadline']) input(node('td', null, row), task[field], field, field === 'task');
      select(node('td', null, row), task.priority, ['high','medium','low'], 'priority');
      select(node('td', null, row), task.status, ['pending','in_progress','done','blocked'], 'status');
      node('td', `${task.source_time || ''} ${task.evidence || ''} · confidence ${task.confidence ?? 'unknown'}`, row);
    });
    $('ws-downloads').replaceChildren();
    Object.entries(result.downloads || {}).forEach(([format, url]) => { const a = node('a', `Download ${format.toUpperCase()}`, $('ws-downloads')); a.href = url; a.download = ''; });
    renderTranscript(); view('protocol');
  }
  async function loadHistory() {
    history = await api('/meetings'); $('ws-history').replaceChildren();
    if (!history.length) node('p','No saved meetings yet.', $('ws-history'));
    history.forEach(result => {
      const box = node('div', null, $('ws-history')); box.className = 'ws-entry';
      node('h4', result.analysis?.title || result.source_file, box);
      node('p', `${result.source_file} · ${time(result.duration)} · ${(result.analysis?.tasks || []).length} tasks`, box);
      node('button', 'Open protocol', box).addEventListener('click', () => render(result));
    });
    renderControl();
  }
  function renderControl() {
    $('ws-control').replaceChildren(); const filter = $('ws-filter').value;
    history.forEach(result => (result.analysis?.tasks || []).forEach((task, index) => {
      if (filter && (task.status || 'pending') !== filter) return;
      const box = node('div', null, $('ws-control')); box.className = 'ws-entry';
      node('strong', task.task, box); node('p', `${task.assignee || 'Unassigned'} · ${task.deadline || 'No deadline'} · ${result.source_file}`, box);
      const control = select(box, task.status, ['pending','in_progress','done','blocked'], 'status');
      control.addEventListener('change', () => { history.find(r => r.id === result.id).analysis.tasks[index].status = control.value; result.dirty = true; });
    }));
    if (!$('ws-control').children.length) node('p', 'No matching tasks.', $('ws-control'));
  }
  async function save(result, summary, tasks, speaker_names = {}) {
    return api(`/meetings/${result.id}`, {method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({summary, tasks, speaker_names})});
  }
  async function health() { $('ws-health-result').textContent = JSON.stringify(await api('/health'), null, 2); }
  async function open() {
    if (!dialog.open) dialog.showModal();
    if (location.protocol === 'file:') { status('Start python run.py and open http://127.0.0.1:8000 to process meetings.', true); return; }
    if (jobId) pollJob();
    try {
      await loadHistory();
      const samples = await api('/samples');
      $('ws-sample').replaceChildren(); const blank = node('option', 'Choose a sample', $('ws-sample')); blank.value = '';
      samples.forEach(name => { const option = node('option', name, $('ws-sample')); option.value = name; });
    } catch (error) { status(error.message, true); }
  }
  $('workspace-open').addEventListener('click', open);
  $('workspace-close').addEventListener('click', () => dialog.close());
  document.querySelectorAll('a').forEach(link => { if (link.hasAttribute('data-open-workspace') || /Try the demo|Open demo|Open workspace|Get started|Start building/i.test(link.textContent.trim())) link.addEventListener('click', event => { event.preventDefault(); open(); }); });
  dialog.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => view(button.dataset.view)));
  $('ws-file').addEventListener('change', () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    const file = $('ws-file').files[0]; $('ws-sample').value = '';
    $('ws-preview').hidden = !file;
    if (file) { previewUrl = URL.createObjectURL(file); $('ws-preview').src = previewUrl; }
  });
  $('ws-sample').addEventListener('change', () => { $('ws-file').value = ''; $('ws-preview').hidden = !$('ws-sample').value; $('ws-preview').src = `/samples/${encodeURIComponent($('ws-sample').value)}`; });
  $('ws-upload').addEventListener('submit', async event => {
    event.preventDefault(); if (busy) return;
    let file = $('ws-file').files[0];
    setBusy(true); $('ws-progress').hidden = false;
    $('ws-stage').textContent = 'Uploading recording'; $('ws-elapsed').textContent = '';
    $('ws-progress-hint').textContent = 'Keep this page open until the upload finishes.';
    try {
      if (!file && $('ws-sample').value) {
        const response = await fetch(`/samples/${encodeURIComponent($('ws-sample').value)}`);
        if (!response.ok) throw new Error('Could not load sample');
        file = new File([await response.blob()], $('ws-sample').value, {type:'audio/mpeg'});
      }
      if (!file || !file.size) throw new Error('Choose a non-empty recording.');
      if (file.size > 500 * 1024 * 1024) throw new Error('Maximum file size is 500 MB.');
      const data = new FormData($('ws-upload')); data.set('file', file);
      status('Uploading your recording…');
      const job = await api('/jobs', {method:'POST', body:data});
      remember(job.id); status('Recording received. Processing continues on the server.');
      pollJob();
    } catch (error) { status(error.message, true); }
    finally { if (!jobId) { setBusy(false); $('ws-progress').hidden = true; } }
  });
  $('ws-save').addEventListener('click', async () => {
    if (!current) return; $('ws-save').disabled = true;
    try {
      const tasks = [...$('ws-tasks').rows].map((row, i) => { const task = {...current.analysis.tasks[i]}; row.querySelectorAll('[data-field]').forEach(el => task[el.dataset.field] = el.value); return task; });
      const names = Object.fromEntries([...$('ws-speakers').querySelectorAll('input')].map(el => [el.dataset.field, el.value]));
      render(await save(current, $('ws-summary').value, tasks, names)); await loadHistory(); status('Saved. All export formats regenerated.');
    } catch (error) { status(error.message, true); } finally { $('ws-save').disabled = false; }
  });
  $('ws-save-status').addEventListener('click', async () => {
    $('ws-save-status').disabled = true;
    try { for (const result of history.filter(r => r.dirty)) await save(result, result.analysis.summary || '', result.analysis.tasks); await loadHistory(); if (current) { const refreshed = history.find(r => r.id === current.id); if (refreshed) { render(refreshed); view('control'); } } status('Task statuses saved.'); }
    catch (error) { status(error.message, true); } finally { $('ws-save-status').disabled = false; }
  });
  $('ws-search').addEventListener('input', renderTranscript);
  $('ws-filter').addEventListener('change', renderControl);
  $('ws-refresh').addEventListener('click', () => loadHistory().catch(error => status(error.message, true)));
  $('ws-health').addEventListener('click', () => health().catch(error => status(error.message, true)));
  $('ws-reconnect').addEventListener('click', pollJob);
  if (jobId && location.protocol !== 'file:') { $('workspace-open').textContent = 'View meeting progress ↗'; pollJob(); }
})();
