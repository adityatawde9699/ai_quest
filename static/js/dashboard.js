(() => {
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  const root = document.getElementById('toast-root');
  const views = ['overview', 'teams', 'batches', 'qrs', 'questions', 'rounds', 'monitoring', 'scores', 'leaderboard', 'results', 'activity', 'settings', 'operations'];
  const titles = {overview:'Dashboard',teams:'Teams',batches:'Batches',qrs:'QR Management',questions:'Questions',rounds:'Round Control',monitoring:'Live Monitoring',scores:'Scores',leaderboard:'Leaderboard',results:'Final Results',activity:'Activity Logs',settings:'Settings',operations:'Event Operations'};
  let chart;
  const connectionState=document.getElementById('connection-status')||document.querySelector('.system-state');
  if(connectionState){connectionState.id='connection-status';connectionState.innerHTML='<i class="live-dot"></i><span>Connecting…</span>';}

  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const date = value => value ? new Date(value).toLocaleString([], {hour:'2-digit',minute:'2-digit',second:'2-digit',month:'short',day:'numeric'}) : '—';
  const clock = value => {
    const seconds = Math.max(0, Number(value) || 0);
    return `${Math.floor(seconds / 3600) ? `${String(Math.floor(seconds / 3600)).padStart(2,'0')}:` : ''}${String(Math.floor(seconds / 60) % 60).padStart(2,'0')}:${String(seconds % 60).padStart(2,'0')}`;
  };
  const status = value => `<span class="badge ${esc(String(value).toLowerCase())}">${esc(value)}</span>`;
  const toast = (message, error=false) => {
    const node = document.createElement('div'); node.className = `toast${error ? ' error' : ''}`; node.textContent = message; root.append(node); setTimeout(() => node.remove(), 4000);
  };
  async function api(path, options={}) {
    const headers = {'X-CSRFToken':csrf,...(options.headers || {})};
    if (options.body !== undefined && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
    const response = await fetch(path, {credentials:'same-origin', ...options, headers});
    const data = response.status === 204 ? {} : await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
    return data;
  }
  function modal(title, body, onOpen) {
    const host = document.getElementById('modal-root');
    host.innerHTML = `<div class="modal-backdrop"><div class="modal" role="dialog" aria-modal="true"><div class="modal-head"><h3>${esc(title)}</h3><button class="modal-close" aria-label="Close">×</button></div><div class="modal-content">${body}</div></div></div>`;
    const previouslyFocused=document.activeElement;
    const close=()=>{host.innerHTML='';document.removeEventListener('keydown',keyboard);previouslyFocused?.focus();};
    const keyboard=e=>{if(!host.childElementCount){document.removeEventListener('keydown',keyboard);return;}if(e.key==='Escape'){close();return;}if(e.key==='Tab'){const controls=[...host.querySelectorAll('button,input,select,textarea,a[href]')].filter(n=>!n.disabled&&n.getClientRects().length);const first=controls[0],last=controls.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}}};
    document.addEventListener('keydown',keyboard);
    host.querySelector('.modal-close').onclick = close;
    host.querySelector('.modal-head h3').id='dialog-title';host.querySelector('.modal').setAttribute('aria-labelledby','dialog-title');
    requestAnimationFrame(()=>(host.querySelector('input:not([type=hidden]),select,textarea')||host.querySelector('.modal-close'))?.focus());
    host.querySelector('.modal-backdrop').addEventListener('click', event => { if (event.target.classList.contains('modal-backdrop')) close(); });
    onOpen?.(host);
  }
  function showView(name) {
    if (!views.includes(name)) return;
    document.querySelectorAll('.view').forEach(view => view.classList.toggle('active', view.id === `view-${name}`));
    document.querySelectorAll('.nav-item').forEach(item => item.classList.toggle('active', item.dataset.view === name));
    document.getElementById('page-title').textContent = titles[name];
    document.querySelectorAll('.nav-item').forEach(item=>item.setAttribute('aria-current',item.dataset.view===name?'page':'false'));
    history.replaceState({},'',`#${name}`);
    document.title=`${titles[name]} · SWAYAMBHU 2026`;
    document.getElementById('sidebar').classList.remove('open');
    if (name === 'operations') window.loadOperations?.();
    if (name === 'overview') loadOverview();
    if (name === 'teams') loadTeams();
    if (name === 'batches') loadBatches();
    if (name === 'qrs') loadQrs();
    if (name === 'questions') loadQuestions();
    if (name === 'rounds') loadRounds();
    if (name === 'monitoring') loadMonitoring();
    if (name === 'scores') loadScores();
    if (name === 'leaderboard') loadLeaderboard();
    if (name === 'results') loadResults();
    if (name === 'activity') loadActivity();
    if (name === 'settings') loadManagingTeam();
  }
  async function loadManagingTeam() {
    const host = document.getElementById('managing-team-list');
    if (!host) return;
    try {
      const accounts = await api('/api/admin/accounts');
      host.innerHTML = accounts.map(account => `<p><strong>${esc(account.username)}</strong> · ${esc(account.role)} · ${account.active?'Active':'Disabled'}${account.role==='admin'?` <button class="text-button" data-assistant-toggle="${account.id}" data-active="${account.active}">${account.active?'Disable':'Enable'}</button>`:''}</p>`).join('') || '<p>No managing team members yet.</p>';
      host.querySelectorAll('[data-assistant-toggle]').forEach(button => button.onclick = async () => {
        try {
          await api(`/api/admin/accounts/${button.dataset.assistantToggle}`, {method:'PATCH',body:JSON.stringify({active:button.dataset.active!=='true'})});
          toast('Managing team member updated'); loadManagingTeam();
        } catch (error) { toast(error.message, true); }
      });
    } catch (error) { toast(error.message, true); }
  }
  const assistantForm = document.getElementById('assistant-form');
  if (assistantForm) assistantForm.onsubmit = async event => {
    event.preventDefault();
    try {
      const values = Object.fromEntries(new FormData(assistantForm));
      await api('/api/admin/accounts', {method:'POST',body:JSON.stringify({...values,role:'admin'})});
      assistantForm.reset(); toast('Assistant added'); loadManagingTeam();
    } catch (error) { toast(error.message, true); }
  };
  document.querySelectorAll('.nav-item').forEach(item => item.addEventListener('click', () => showView(item.dataset.view)));
  document.querySelectorAll('[data-goto]').forEach(item => item.addEventListener('click', () => showView(item.dataset.goto)));
  document.getElementById('menu-toggle').onclick = () => document.getElementById('sidebar').classList.toggle('open');
  function drawLeaderboard(rows, target, includeStatus=true) {
    const body = document.getElementById(target);
    if (!body) return;
    body.innerHTML = rows.length ? rows.map((row,index) => `<tr><td><span class="rank-num ${index===0?'top':''}">${index+1}</span></td><td>${esc(row.team_id)}</td><td class="team-cell">${esc(row.team_name)}</td><td>R${row.round || '—'}</td><td><b>${row.score}</b></td><td>${clock(row.time)}</td>${includeStatus?`<td>${status(row.status)}</td>`:''}</tr>`).join('') : `<tr><td colspan="${includeStatus?7:6}" class="empty-cell">No teams have scored yet.</td></tr>`;
  }
  async function loadOverview() {
    try {
      const data = await api('/api/overview');
      document.getElementById('stat-teams').textContent = data.total_teams;
      document.getElementById('stat-active').textContent = data.active_teams;
      document.getElementById('stat-completed').textContent = data.completed_teams;
      document.getElementById('stat-scans').textContent = data.total_scans;
      [1,2,3].forEach(n=>document.getElementById(`stat-round-${n}`).textContent=data.teams_by_round[String(n)]||0);
      document.getElementById('current-round').textContent = data.current_round;
      document.getElementById('overview-batches').textContent=(data.batches||[]).map(b=>`Batch ${b.number}: ${b.status}${b.triggered?' · next batch triggered':''}`).join('   |   ') || 'No batches yet';
      document.getElementById('rounds-done').textContent = `${data.completed_rounds} / 3 complete`;
      document.getElementById('overview-rounds').innerHTML = data.rounds.map(round => `<div class="round-row ${round.status==='ACTIVE'?'active':''}"><span class="round-number">0${round.number}</span><div><strong>${esc(round.name)}</strong><small>${status(round.status)}</small></div></div>`).join('');
      document.getElementById('overview-activity').innerHTML = data.activity.length ? data.activity.map(item => `<div class="activity-item"><time>${date(item.timestamp)}</time><span>${esc(item.action)} · ${esc(item.target)}</span></div>`).join('') : '<div class="empty-state">No activity recorded yet.</div>';
      const rows = data.leaderboard || [];
      document.getElementById('overview-leaderboard').innerHTML = rows.length ? rows.slice(0,6).map((row,index) => `<tr><td><span class="rank-num ${index===0?'top':''}">${index+1}</span></td><td><span class="team-cell">${esc(row.team_name)}</span><small style="display:block;color:#929bae;margin-top:3px">${esc(row.team_id)}</small></td><td>R${row.round || '—'}</td><td><b>${row.score}</b></td><td>${clock(row.time)}</td></tr>`).join('') : '<tr><td colspan="5" class="empty-cell">No teams yet</td></tr>';
      const ctx = document.getElementById('score-chart');
      const labels = data.rounds.map(round => `Round ${round.number}`);
      const scores = data.rounds.map(round => data.round_scores[String(round.number)] || 0);
      if (window.Chart && ctx) {
        if (chart) chart.destroy();
        chart = new Chart(ctx, {type:'bar',data:{labels,datasets:[{data:scores,backgroundColor:['#3768eb','#7954d9','#19a7bb'],borderRadius:5,maxBarThickness:34}]},options:{plugins:{legend:{display:false}},scales:{x:{grid:{display:false},ticks:{color:'#8993a7',font:{size:10}}},y:{beginAtZero:true,grid:{color:'#eef0f5'},ticks:{color:'#8993a7',font:{size:9}}}}}});
      }
    } catch (error) { toast(error.message, true); }
  }
  let teamsCache = [];
  async function loadTeams() {
    try {
      teamsCache = await api('/api/teams');
      const term = document.getElementById('team-search').value.toLowerCase();
      const rows = teamsCache.filter(team => `${team.team_id} ${team.team_name}`.toLowerCase().includes(term));
      document.getElementById('team-count').textContent = `${rows.length} teams`;
      const canDeletePermanently = document.body.dataset.adminRole === 'super-admin';
      document.getElementById('teams-table').innerHTML = rows.length ? rows.map(team => `<tr><td class="team-cell">${esc(team.team_id)}<small style="display:block">Batch ${esc(team.batch_number||'—')} · ${esc(team.batch_status)}</small></td><td>${esc(team.team_name)}</td><td>${[team.member_1,team.member_2,team.member_3].filter(Boolean).map(esc).join(', ') || '—'}</td><td><b>${team.score}</b></td><td><select class="status-select" data-team-status="${team.id}">${['READY','ACTIVE','COMPLETED','DISQUALIFIED','DISABLED'].map(value=>`<option ${team.status===value?'selected':''}>${value}</option>`).join('')}</select></td><td><div class="row-actions"><button class="text-button" data-edit-team="${team.id}">Edit</button><button class="text-button" data-timeline="${team.id}">Timeline</button><button class="text-button" data-reset-pin="${team.id}">Reset PIN</button><button class="text-button danger-text" data-delete-team="${team.id}">Archive</button>${canDeletePermanently?`<button class="text-button danger-text" data-purge-team="${team.id}">Delete</button>`:''}</div></td></tr>`).join('') : '<tr><td colspan="6" class="empty-cell">No teams match this search.</td></tr>';
      bindTeamActions();
    } catch (error) { toast(error.message, true); }
  }
  document.getElementById('team-search').addEventListener('input', loadTeams);
  async function teamForm(team={}) {
    try {
      const [qrs, batchData] = await Promise.all([api('/api/qrs'), api('/api/admin/batches')]);
      const qrOptions = qrs.filter(qr => qr.round === 1 && qr.status !== 'ARCHIVED').map(qr => `<option value="${qr.id}" ${qr.id===team.assigned_qr_id?'selected':''}>${esc(qr.qr_id)} · ${esc(qr.title || qr.room || 'Round 1')}</option>`).join('');
      const round2Options = qrs.filter(qr => qr.round === 2 && qr.quiz_id && (qr.status !== 'ARCHIVED' || qr.id===team.assigned_round2_qr_id)).map(qr => `<option value="${qr.id}" ${qr.id===team.assigned_round2_qr_id?'selected':''}>${esc(qr.qr_id)} · ${esc(qr.title || 'Round 2 quiz')}</option>`).join('');
      const round3Options = qrs.filter(qr => qr.round === 3 && qr.has_password && (qr.status !== 'ARCHIVED' || qr.id===team.round3_qr_id)).map(qr => `<option value="${qr.id}" ${qr.id===team.round3_qr_id?'selected':''}>${esc(qr.qr_id)} · ${esc(qr.title || 'Round 3 password riddle')}</option>`).join('');
      const batchOptions = batchData.batches.filter(batch => batch.id === team.batch_id || !['COMPLETED','PAUSED'].includes(batch.status)).map(batch => `<option value="${batch.id}" ${batch.id===team.batch_id?'selected':''}>Batch ${batch.number} · ${esc(batch.status)} (${batch.teams.length}/${batch.capacity})</option>`).join('');
      modal(team.id ? `Edit ${team.team_id}` : 'Add team', `<form id="team-form" class="form-panel"><label>Team name<input name="team_name" required maxlength="120" value="${esc(team.team_name||'')}"></label><div class="form-grid two"><label>Member 1<input name="member_1" required maxlength="100" value="${esc(team.member_1||'')}"></label><label>Member 2<input name="member_2" maxlength="100" value="${esc(team.member_2||'')}"></label></div><label>Member 3<input name="member_3" maxlength="100" value="${esc(team.member_3||'')}"></label><label>Assigned Round 1 QR<select name="assigned_qr_id"><option value="">Select an envelope QR</option>${qrOptions}</select></label><label>Assigned Round 2 quiz QR<select name="assigned_round2_qr_id"><option value="">No Round 2 QR assigned</option>${round2Options}</select></label><p class="subtle">Assign a configured Round 2 quiz QR here. Teams assigned the same Round 2 QR can share it across batches, but only once within a batch.</p><label>Assigned Round 3 password QR<select name="round3_qr_id"><option value="">No Round 3 QR assigned</option>${round3Options}</select></label><label>Round 3 paper maximum marks<input name="round3_max_points" type="number" min="0" max="100000" value="${esc(team.round3_max_points??100)}"></label><p class="subtle">Create Round 3 password QRs in QR Management, then assign them here. Teams assigned the same QR share its riddle and password.</p><label>Batch<select name="batch_id"><option value="">${team.id?'Keep current batch':'Assign automatically'}</option>${batchOptions}</select></label><label>Position in batch<input name="batch_position" type="number" min="1" value="${esc(team.batch_position||'')}"></label><p class="subtle">QR assignments can be changed before the team starts the corresponding round.</p>${team.id?'':'<label>Login PIN · optional, generated if blank<input name="login_pin" inputmode="numeric" minlength="4" maxlength="12"></label>'}<button class="button primary" type="submit">${team.id?'Save changes':'Create team'}</button></form>`, host => {
      host.querySelector('[name=batch_id]').onchange = () => { host.querySelector('[name=batch_position]').value = ''; };
      host.querySelector('#team-form').onsubmit = async event => {
        event.preventDefault(); const form = Object.fromEntries(new FormData(event.currentTarget)); for(const field of ['assigned_qr_id','batch_id','batch_position'])if(!form[field])delete form[field];if(team.id){if(Number(form.batch_id)===team.batch_id)delete form.batch_id;if(Number(form.batch_position)===team.batch_position)delete form.batch_position;}
        try { const data = await api(team.id ? `/api/teams/${team.id}` : '/api/teams', {method:team.id?'PUT':'POST',body:JSON.stringify(form)}); host.innerHTML=''; toast(team.id?'Team updated':`Created ${data.team.team_id} · PIN ${data.login_pin}`); loadTeams(); loadBatches(); }
        catch(error) { toast(error.message,true); }
      };
    });
    } catch (error) { toast(error.message, true); }
  }
  document.getElementById('add-team').onclick = () => teamForm();
  let batchesCache=[];
  async function loadBatches() {
    try {
      const data=await api('/api/admin/batches');
      batchesCache=data.batches;
      const isSuperAdmin = document.body.dataset.adminRole === 'super-admin';
      document.getElementById('batch-list').innerHTML=data.batches.length?data.batches.map(batch=>{const deletable=!batch.teams.length;return `<article class="panel form-panel"><div class="panel-heading"><h3>Batch ${batch.number} · ${esc(batch.status)}</h3><span>${batch.teams.filter(t=>!['DISABLED','DISQUALIFIED'].includes(t.status)).length} / ${batch.capacity} active teams</span></div><p>Released: ${date(batch.released_at)} · Round 3 trigger: ${date(batch.triggered_at)}</p><div>${batch.teams.map((t,index)=>`<p>${esc(t.position)}. ${esc(t.team_id)} · ${esc(t.state)} <button class="text-button" data-batch-move="${batch.id}:${index}:-1" ${index===0?'disabled':''} aria-label="Move ${esc(t.team_id)} up">↑</button><button class="text-button" data-batch-move="${batch.id}:${index}:1" ${index===batch.teams.length-1?'disabled':''} aria-label="Move ${esc(t.team_id)} down">↓</button></p>`).join('')||'No teams assigned yet'}</div><div class="button-row">${batch.status==='WAITING'?`<button class="button secondary" data-batch-action="release" data-batch-id="${batch.id}">Release now</button>`:''}${['RELEASED','IN_PROGRESS'].includes(batch.status)?`<button class="button secondary" data-batch-action="pause" data-batch-id="${batch.id}">Pause</button>`:''}${batch.status==='PAUSED'?`<button class="button secondary" data-batch-action="resume" data-batch-id="${batch.id}">Resume</button>`:''}${isSuperAdmin?`<button class="button secondary danger-text" data-batch-delete="${batch.id}" ${deletable?'':'disabled title="Move every team out of this batch before deleting it."'}>Delete batch</button>`:''}</div></article>`}).join(''):'<div class="empty-state">Create teams to generate the first batch.</div>';
      document.querySelectorAll('[data-batch-delete]:not(:disabled)').forEach(button=>button.onclick=async()=>{if(!confirm('Delete this empty batch? Its audit history remains available.'))return;try{await api(`/api/admin/batches/${button.dataset.batchDelete}`,{method:'DELETE'});toast('Batch deleted');loadBatches();}catch(error){toast(error.message,true);}});
      document.querySelectorAll('[data-batch-action]').forEach(button=>button.onclick=async()=>{const reason=prompt(`Reason to ${button.dataset.batchAction} batch?`);if(!reason)return;try{await api(`/api/admin/batches/${button.dataset.batchId}/${button.dataset.batchAction}`,{method:'POST',body:JSON.stringify({reason})});loadBatches();loadTeams();}catch(error){toast(error.message,true);}});
      batchesCache.forEach(batch => batch.teams.forEach((team, index) => {
        const row = document.querySelector(`[data-batch-move="${batch.id}:${index}:-1"]`)?.parentElement;
        if (!row) return;
        const edit = document.createElement('button');
        edit.type = 'button'; edit.className = 'text-button'; edit.textContent = 'Edit team / batch';
        edit.onclick = async () => {
          try {
            const teams = await api('/api/teams');
            const detail = teams.find(item => item.id === team.id);
            if (detail) await teamForm(detail);
          } catch (error) { toast(error.message, true); }
        };
        row.append(edit);
      }));
      document.querySelectorAll('[data-batch-move]').forEach(button=>button.onclick=async()=>{const [id,index,step]=button.dataset.batchMove.split(':').map(Number);const batch=batchesCache.find(b=>b.id===id);const ids=batch.teams.map(t=>t.id);[ids[index],ids[index+step]]=[ids[index+step],ids[index]];try{await api(`/api/admin/batches/${id}/reorder`,{method:'POST',body:JSON.stringify({team_ids:ids})});loadBatches();}catch(error){toast(error.message,true);}});
    }catch(error){toast(error.message,true);}
  }
  document.getElementById('add-batch').onclick=async()=>{try{await api('/api/admin/batches',{method:'POST',body:'{}'});loadBatches();}catch(error){toast(error.message,true);}};
  function bindTeamActions() {
    document.querySelectorAll('[data-edit-team]').forEach(button => button.onclick = () => teamForm(teamsCache.find(team => team.id === Number(button.dataset.editTeam))));
    document.querySelectorAll('[data-delete-team]').forEach(button => button.onclick = async () => { if(!confirm('Archive this team?'))return; try{await api(`/api/teams/${button.dataset.deleteTeam}`,{method:'DELETE'});toast('Team archived');loadTeams();}catch(error){toast(error.message,true);} });
    document.querySelectorAll('[data-purge-team]').forEach(button => button.onclick = async () => { if(!confirm('Permanently delete this team? This is available only when the team has no recorded event activity or results.'))return; try{await api(`/api/teams/${button.dataset.purgeTeam}?permanent=true`,{method:'DELETE'});toast('Team permanently deleted');loadTeams();loadBatches();}catch(error){toast(error.message,true);} });
    document.querySelectorAll('[data-reset-pin]').forEach(button => button.onclick = async () => { try{const data=await api(`/api/teams/${button.dataset.resetPin}/reset-pin`,{method:'POST',body:'{}'});modal('New team PIN',`<p>Share this one-time display with the team:</p><p><strong>${esc(data.team_id)} · ${esc(data.login_pin)}</strong></p>`);}catch(error){toast(error.message,true);} });
    document.querySelectorAll('[data-timeline]').forEach(button => button.onclick = async () => { try{const data=await api(`/api/teams/${button.dataset.timeline}/timeline`);modal(`${data.team.team_id} · ${data.team.state}`,`<p>Members: ${[data.team.member_1,data.team.member_2,data.team.member_3].filter(Boolean).map(esc).join(', ')}</p><p>Scores: ${esc(JSON.stringify(data.scores))} · Bonus ${data.team.bonus} · Penalty ${data.team.penalty}</p><p>Progress: ${data.rounds.map(r=>`Round ${r.number}: ${esc(r.status)}`).join(' · ')}</p>`+(data.timeline.length?`<ul class="timeline">${data.timeline.map(item=>`<li><time>${date(item.at)}</time>${esc(item.label)}</li>`).join('')}</ul>`:'<div class="empty-state">No events recorded for this team.</div>'));}catch(error){toast(error.message,true);} });
    document.querySelectorAll('[data-team-status]').forEach(select => select.onchange = async () => {try{await api(`/api/teams/${select.dataset.teamStatus}`,{method:'PUT',body:JSON.stringify({status:select.value})});toast('Team status updated');loadTeams();}catch(error){toast(error.message,true);loadTeams();}});
  }
  async function loadQrs() {
    try {
      const term=document.getElementById('qr-search').value.toLowerCase();
      const rows = (await api('/api/qrs')).filter(qr=>`${qr.qr_id} ${qr.title} ${qr.room}`.toLowerCase().includes(term));
      document.getElementById('qrs-table').innerHTML = rows.length ? rows.map(qr => `<tr><td class="team-cell">${esc(qr.qr_id)}</td><td>R${qr.round} · ${esc(qr.round_name)}</td><td>${esc(qr.room || 'Unassigned')}</td><td>${qr.expires_at && new Date(qr.expires_at) < new Date() ? status('EXPIRED') : status(qr.status)}</td><td>${date(qr.expires_at)}</td><td>${date(qr.created_at)}</td><td>${date(qr.activated_at)}</td><td>${qr.scans}</td><td><div class="row-actions"><button class="text-button" data-qr-image="${qr.id}">Download</button><button class="text-button" data-qr-scans="${qr.id}">Scans</button><button class="text-button" data-qr-action="${qr.status==='ACTIVE'?'deactivate':'activate'}" data-qr-id="${qr.id}">${qr.status==='ACTIVE'?'Deactivate':'Activate'}</button><button class="text-button danger-text" data-qr-action="delete" data-qr-id="${qr.id}">Archive</button></div></td></tr>`).join('') : '<tr><td colspan="9" class="empty-cell">Generate your first QR challenge.</td></tr>';
      rows.forEach(qr => {
        const controls = document.querySelector(`[data-qr-image="${qr.id}"]`)?.parentElement;
        if (!controls) return;
        const purge = document.createElement('button');
        purge.type = 'button'; purge.className = 'text-button danger-text'; purge.textContent = 'Delete';
        purge.dataset.qrPurge = qr.id;
        if (document.body.dataset.adminRole === 'super-admin') controls.append(purge);
        if (qr.status === 'ARCHIVED') controls.querySelectorAll('[data-qr-action]').forEach(button => button.remove());
        const edit = document.createElement('button');
        edit.type = 'button'; edit.className = 'text-button'; edit.textContent = 'Edit';
        edit.onclick = async () => {
          try {
            const [quizzes, questions] = await Promise.all([api('/api/admin/quizzes'),api('/api/admin/questions')]);
            const questionOptions = (roundId, selected) => '<option value="">No attached question</option>' + questions.filter(question=>question.round===Number(roundId)).map(question=>`<option value="${question.id}" ${question.id===selected?'selected':''}>R${question.round} · ${esc(question.prompt.slice(0,90))}</option>`).join('');
            const quizOptions = selected => '<option value="">Select a quiz</option>' + quizzes.map(quiz=>`<option value="${quiz.id}" ${quiz.id===selected?'selected':''}>${esc(quiz.title)}</option>`).join('');
            const expiry = qr.expires_at ? new Date(new Date(qr.expires_at).getTime()-new Date(qr.expires_at).getTimezoneOffset()*60000).toISOString().slice(0,16) : '';
            modal(`Edit QR · ${qr.qr_id}`, `<form id="edit-qr" class="form-panel"><div class="form-grid two"><label>QR number<input name="qr_id" required maxlength="30" pattern="[A-Za-z0-9-]+" value="${esc(qr.qr_id)}"></label><label>Round<select name="round_id" required><option value="1" ${qr.round===1?'selected':''}>Round 1 · QR Riddle</option><option value="2" ${qr.round===2?'selected':''}>Round 2 · Quiz</option><option value="3" ${qr.round===3?'selected':''}>Round 3 · Offline riddles</option></select></label></div><label>Title<input name="title" maxlength="120" value="${esc(qr.title)}"></label><label>Clue / instructions<textarea name="clue" maxlength="2000" rows="4">${esc(qr.clue)}</textarea></label><div class="form-grid two"><label>Room / destination<input name="room" maxlength="120" value="${esc(qr.room)}"></label><label>Question attached to QR<select name="question_id">${questionOptions(qr.round,qr.question_id)}</select></label></div><label id="edit-qr-quiz-field" ${qr.round===2?'':'hidden'}>Round 2 quiz<select name="quiz_id" ${qr.round===2?'required':''}>${quizOptions(qr.quiz_id)}</select></label><div class="form-grid two"><label>QR status<select name="status">${['ACTIVE','INACTIVE','ARCHIVED'].map(value=>`<option value="${value}" ${value===qr.status?'selected':''}>${value}</option>`).join('')}</select></label><label>Expires at · optional<input name="expires_at" type="datetime-local" value="${expiry}"></label></div><div class="subtle">Created ${date(qr.created_at)} · Updated ${date(qr.updated_at)} · Activated ${date(qr.activated_at)} · Deactivated ${date(qr.deactivated_at)} · ${qr.scans} recorded scans. Secure token is hidden.</div><p class="subtle">Changing round, QR number, attached question, or quiz is blocked while assigned to a team. QR records with scans are read-only.</p><button class="button primary" type="submit">Save all QR details</button></form>`, host => {
              const form = host.querySelector('#edit-qr');
              const roundSelect = form.elements.round_id;
              const questionSelect = form.elements.question_id;
              const quizField = host.querySelector('#edit-qr-quiz-field');
              const quizSelect = form.elements.quiz_id;
              roundSelect.onchange = () => {
                questionSelect.innerHTML = questionOptions(roundSelect.value,'');
                const isQuizRound = Number(roundSelect.value) === 2;
                quizField.hidden = !isQuizRound;
                quizSelect.required = isQuizRound;
                if (!isQuizRound) quizSelect.value = '';
              };
            form.onsubmit = async event => {
              event.preventDefault();
              try { const values=Object.fromEntries(new FormData(form)); if(!values.question_id)values.question_id=null; if(!values.quiz_id)values.quiz_id=null; if(values.expires_at)values.expires_at=new Date(values.expires_at).toISOString(); else values.expires_at=null; await api(`/api/qrs/${qr.id}`, {method:'PATCH',body:JSON.stringify(values)}); host.innerHTML=''; toast('QR details updated'); loadQrs(); }
              catch (error) { toast(error.message, true); }
            };
            });
          } catch (error) { toast(error.message, true); }
        };
        controls.prepend(edit);
      });
      document.querySelectorAll('[data-qr-purge]').forEach(button => button.onclick = async () => {
        if (!confirm('Permanently delete this QR? This is allowed only when it has no scan history and is not assigned to a team.')) return;
        try { await api(`/api/qrs/${button.dataset.qrPurge}`, {method:'DELETE'}); toast('QR permanently deleted'); loadQrs(); }
        catch (error) { toast(error.message, true); }
      });
      document.querySelectorAll('[data-qr-action]').forEach(button => button.onclick = async () => {try{await api(`/api/qrs/${button.dataset.qrId}/${button.dataset.qrAction}`,{method:'POST',body:'{}'});toast(`QR ${button.dataset.qrAction}d`);loadQrs();}catch(error){toast(error.message,true);}});
      document.querySelectorAll('[data-qr-image]').forEach(button => button.onclick = () => {const image=`/api/qrs/${button.dataset.qrImage}/image`;modal('QR challenge',`<img class="qr-preview" src="${image}" alt="QR challenge"><p class="subtle">This QR contains an opaque secure token. Correct answers are never encoded in the image.</p><a class="button primary" href="${image}" download>Download PNG</a>`);});
      document.querySelectorAll('[data-qr-scans]').forEach(button => button.onclick = async () => {try{const scans=await api(`/api/qrs/${button.dataset.qrScans}/scans`);modal('QR scan history',scans.length?`<div class="table-wrap"><table><thead><tr><th>Team</th><th>Scan time</th><th>Status</th><th>IP address</th></tr></thead><tbody>${scans.map(scan=>`<tr><td>${esc(scan.team_id)} · ${esc(scan.team_name)}</td><td>${date(scan.scan_time)}</td><td>${status(scan.answer_status)}</td><td>${esc(scan.ip_address)}</td></tr>`).join('')}</tbody></table></div>`:'<div class="empty-state">No scans recorded for this QR.</div>');}catch(error){toast(error.message,true);}});
    } catch (error) { toast(error.message,true); }
  }
  document.getElementById('qr-search').oninput=loadQrs;
  document.getElementById('add-qr').onclick = () => modal('Create QR', `<form id="qr-form" class="form-panel"><label>Round<select name="round_id" required><option value="1">Round 1 · QR Riddle</option><option value="2">Round 2 · Quiz</option><option value="3">Round 3 · Password riddle</option></select></label><label id="qr-count-field">Number of QR codes<input name="count" type="number" min="1" max="100" value="1" required></label><label>QR number<input name="qr_number" maxlength="30" pattern="[A-Za-z0-9-]+" placeholder="QR-R3-001"></label><label>Title<input name="title" maxlength="120" required></label><label>Riddle / clue<textarea name="clue" maxlength="2000" required></textarea></label><div class="form-grid two"><label>Expiry date · optional<input name="expiry_date" type="date"></label><label>Expiry time · optional<input name="expiry_time" type="time"></label></div><div id="qr-quiz-field" hidden><label>Question set<select name="quiz_id"><option value="">Select a question set</option></select></label><p class="subtle">Create and manage Round 2 question sets in Questions.</p><button type="button" class="button secondary small" id="qr-open-questions">Manage question sets</button></div><div id="qr-round3-fields" hidden><label>Round 3 password<input name="password" type="password" maxlength="300" autocomplete="new-password" disabled required></label><p class="subtle">Create this Round 3 QR here. Then go to Teams and assign it to the appropriate team. The riddle and password belong to this QR, so teams assigned this QR share both.</p></div><details><summary>Additional event options</summary><label>Room / destination<input name="room" maxlength="120" placeholder="Optional location for route matching"></label><label>Attached question / clue<select name="question_id"><option value="">No attached question</option></select></label></details><p class="subtle">QRs start inactive. Activate them when their round is ready. Round 3 QRs are assigned to teams from Team Management.</p><div class="button-row"><button type="button" class="button secondary" id="qr-cancel">Cancel</button><button class="button primary" type="submit" id="qr-submit">Generate QR codes</button></div></form>`,async host=>{
    const form=host.querySelector('#qr-form'), round=form.elements.round_id;
    let questions=[];
    const update=()=>{
      const number=Number(round.value);
      host.querySelector('#qr-count-field').hidden=number!==1;
      form.elements.count.disabled=number!==1;
      host.querySelector('#qr-quiz-field').hidden=number!==2;
      form.elements.quiz_id.disabled=number!==2;
      form.elements.quiz_id.required=number===2;
      host.querySelector('#qr-round3-fields').hidden=number!==3;
      form.elements.password.disabled=number!==3;
      form.elements.qr_number.required=number===3;
      form.elements.qr_number.placeholder=number===3?'QR-R3-001':'Automatic if blank';
      form.elements.question_id.disabled=number===3;
      form.elements.question_id.innerHTML='<option value="">No attached question</option>'+questions.filter(q=>q.round===number).map(q=>`<option value="${q.id}">${esc(q.prompt.slice(0,75))}</option>`).join('');
    };
    update();
    try{
      const [quizzes,bank]=await Promise.all([api('/api/admin/quizzes'),api('/api/admin/questions')]);
      questions=bank;
      form.elements.quiz_id.innerHTML='<option value="">Select a question set</option>'+quizzes.filter(q=>q.active&&q.question_ids.length===10).map(q=>`<option value="${q.id}">${esc(q.title)} · 10 questions</option>`).join('');
      update();
    }catch(error){toast(error.message,true);}
    round.onchange=update;
    host.querySelector('#qr-cancel').onclick=()=>host.querySelector('.modal-close').click();
    host.querySelector('#qr-open-questions').onclick=()=>{host.querySelector('.modal-close').click();showView('questions');};
    form.onsubmit=async event=>{
      event.preventDefault();const button=host.querySelector('#qr-submit');button.disabled=true;
      try{
        const payload=Object.fromEntries(new FormData(form));
        if(payload.expiry_date&&payload.expiry_time)payload.expires_at=new Date(`${payload.expiry_date}T${payload.expiry_time}`).toISOString();else if(payload.expiry_date||payload.expiry_time)throw new Error('Enter both expiry date and time, or leave both blank.');
        delete payload.expiry_date;delete payload.expiry_time;
        if(Number(payload.round_id)!==1)payload.count=1;
        if(!payload.qr_number)delete payload.qr_number;
        if(!payload.question_id)delete payload.question_id;
        const data=await api('/api/qrs',{method:'POST',body:JSON.stringify(payload)});
        host.querySelector('.modal-close').click();showView('qrs');
        toast(`${data.qrs.length} QR code${data.qrs.length===1?'':'s'} generated`);
        if(data.qrs.length===1)setTimeout(()=>document.querySelector(`[data-qr-image="${data.qr.id}"]`)?.click(),150);
      }catch(error){toast(error.message,true);}finally{button.disabled=false;}
    };
  });
  async function loadQuestionSets() {
    const host=document.getElementById('question-sets');
    if(!host)return;
    try{
      const [sets,questions]=await Promise.all([api('/api/admin/quizzes'),api('/api/admin/questions')]);
      const candidates=questions.filter(q=>q.round===2&&q.active);
      host.innerHTML=`<form id="set-form"><label>Set name<input name="title" required maxlength="120" placeholder="AI Challenge · Set 01"></label><fieldset class="quiz-picker"><legend>Select exactly ten questions</legend><div class="quiz-picker-list">${candidates.map(q=>`<label><input type="checkbox" name="question_ids" value="${q.id}"><span>${esc(q.prompt)}</span></label>`).join('')||'<p>Add active Round 2 questions first.</p>'}</div><p id="set-count" role="status">0 of 10 selected</p></fieldset><div class="button-row"><button class="button primary" id="set-save" disabled>Save question set</button><button type="button" class="button secondary" id="set-clear" hidden>Cancel edit</button></div></form><div class="question-list">${sets.map(set=>`<div class="question-row"><strong>${esc(set.title)}</strong><small>${set.question_ids.length} questions · ${set.active?'Active':'Inactive'} <button type="button" class="text-button" data-set-edit="${set.id}">Edit</button> <button type="button" class="text-button" data-set-toggle="${set.id}">${set.active?'Deactivate':'Activate'}</button> <button type="button" class="text-button danger-text" data-set-delete="${set.id}">Delete</button></small></div>`).join('')||'<p>No question sets saved yet.</p>'}</div>`;
      const form=host.querySelector('#set-form'), checkboxes=[...form.querySelectorAll('[name=question_ids]')];
      let editing=null;
      const update=()=>{const count=checkboxes.filter(q=>q.checked).length;host.querySelector('#set-count').textContent=`${count} of 10 selected`;host.querySelector('#set-save').disabled=count!==10;checkboxes.forEach(q=>q.disabled=count===10&&!q.checked);};
      form.onchange=update;
      const clear=()=>{editing=null;form.reset();host.querySelector('#set-clear').hidden=true;host.querySelector('#set-save').textContent='Save question set';update();};
      host.querySelector('#set-clear').onclick=clear;
      host.querySelectorAll('[data-set-edit]').forEach(button=>button.onclick=()=>{
        const set=sets.find(q=>q.id===Number(button.dataset.setEdit));editing=set.id;
        form.elements.title.value=set.title;checkboxes.forEach(q=>q.checked=set.question_ids.includes(Number(q.value)));
        host.querySelector('#set-clear').hidden=false;host.querySelector('#set-save').textContent='Save changes';update();form.scrollIntoView({block:'nearest'});
      });
      host.querySelectorAll('[data-set-toggle]').forEach(button=>button.onclick=async()=>{
        const set=sets.find(q=>q.id===Number(button.dataset.setToggle));
        try{await api(`/api/admin/quizzes/${set.id}`,{method:'PATCH',body:JSON.stringify({active:!set.active})});loadQuestionSets();}catch(error){toast(error.message,true);}
      });
      host.querySelectorAll('[data-set-delete]').forEach(button=>button.onclick=async()=>{
        if(!confirm('Delete this question set?'))return;
        try{await api(`/api/admin/quizzes/${button.dataset.setDelete}`,{method:'DELETE'});loadQuestionSets();}catch(error){toast(error.message,true);}
      });
      form.onsubmit=async event=>{
        event.preventDefault();const title=form.elements.title.value.trim(),question_ids=checkboxes.filter(q=>q.checked).map(q=>Number(q.value));
        if(question_ids.length!==10)return;
        const button=host.querySelector('#set-save');button.disabled=true;
        try{await api(editing?`/api/admin/quizzes/${editing}`:'/api/admin/quizzes',{method:editing?'PATCH':'POST',body:JSON.stringify({title,question_ids})});toast('Question set saved');loadQuestionSets();}catch(error){toast(error.message,true);button.disabled=false;}
      };
    }catch(error){host.textContent=error.message;}
  }
  async function loadQuestions() {
    try {
      const rows = await api('/api/admin/questions');
      loadQuestionSets();
      document.getElementById('questions-list').innerHTML = rows.length ? rows.map(q => `<div class="question-row"><strong>R${q.round} · ${esc(q.prompt)}</strong><small>${q.points} pts · ${q.time_limit}s · key ${esc(q.correct_answer)} <button class="text-button" data-question-edit="${q.id}">Edit</button> <button class="text-button" data-question-toggle="${q.id}" data-active="${q.active}">${q.active?'Deactivate':'Activate'}</button> <button class="text-button danger-text" data-question-delete="${q.id}">Delete</button></small></div>`).join('') : '<div class="empty-state">No questions added yet.</div>';
      document.querySelectorAll('[data-question-edit]').forEach(button => button.onclick = () => {
        const question = rows.find(item => item.id === Number(button.dataset.questionEdit));
        modal('Edit question', `<form id="edit-question" class="form-panel"><label>Question<textarea name="prompt" maxlength="2000" required rows="3">${esc(question.prompt)}</textarea></label><div class="form-grid two"><label>Type<select name="kind">${['MCQ','TRUE/FALSE','SHORT ANSWER','NUMERICAL','LOGICAL','CODE OUTPUT','AI/TECHNICAL'].map(kind=>`<option value="${kind}" ${kind===question.kind?'selected':''}>${kind}</option>`).join('')}</select></label><label>Order<input name="position" type="number" min="0" value="${question.position}"></label></div><div class="form-grid two">${['a','b','c','d'].map(key => `<label>Option ${key.toUpperCase()}<input name="option_${key}" value="${esc(question[`option_${key}`])}" maxlength="300"></label>`).join('')}</div><div class="form-grid two"><label>Correct answer / key<input name="correct_answer" maxlength="300" required value="${esc(question.correct_answer)}"></label><label>Points<input name="points" type="number" min="0" max="10000" value="${question.points}"></label><label>Time limit · seconds<input name="time_limit" type="number" min="5" max="3600" value="${question.time_limit}"></label></div><p class="subtle">Questions already used by a quiz cannot be changed.</p><button class="button primary" type="submit">Save changes</button></form>`, host => {
          host.querySelector('#edit-question').onsubmit = async event => {
            event.preventDefault();
            try { await api(`/api/admin/questions/${question.id}`, {method:'PATCH',body:JSON.stringify(Object.fromEntries(new FormData(event.currentTarget)))}); host.innerHTML=''; toast('Question updated'); loadQuestions(); }
            catch(error) { toast(error.message,true); }
          };
        });
      });
      document.querySelectorAll('[data-question-toggle]').forEach(button=>button.onclick=async()=>{try{await api(`/api/admin/questions/${button.dataset.questionToggle}`,{method:'PATCH',body:JSON.stringify({active:button.dataset.active!=='true'})});loadQuestions();}catch(error){toast(error.message,true);}});
      document.querySelectorAll('[data-question-delete]').forEach(button=>button.onclick=async()=>{if(!confirm('Delete this question?'))return;try{await api(`/api/admin/questions/${button.dataset.questionDelete}`,{method:'DELETE'});loadQuestions();}catch(error){toast(error.message,true);}});
    }
    catch(error){toast(error.message,true);}
  }
  document.getElementById('question-form').onsubmit=async event=>{event.preventDefault();const data=Object.fromEntries(new FormData(event.currentTarget));try{await api('/api/admin/questions',{method:'POST',body:JSON.stringify(data)});event.currentTarget.reset();toast('Question saved');loadQuestions();}catch(error){toast(error.message,true);}};
  async function loadRounds() {
    try {
      const rounds = await api('/api/rounds');
      const host = document.getElementById('round-control-list');
      const hasEnded = rounds.some(round => round.status === 'ENDED');
      const canOpenAll = rounds.length === 3 && rounds.some(round => round.status !== 'ACTIVE');
      const recovery = hasEnded ? await Promise.all([api('/api/admin/event'),api('/api/admin/profile')]) : null;
      const canReopenTest = recovery && recovery[0].mode === 'TEST' && !recovery[0].results_locked && recovery[1].role === 'super-admin';
      const showOpen = canOpenAll && (!hasEnded || canReopenTest);
      const openingCopy = hasEnded ? 'These are saved round states from an earlier test. A super-admin may reopen them only while no team progress or results exist.' : 'Open all three rounds for the event. Team order stays enforced, and only released batches may enter Round 1.';
      host.innerHTML = `${showOpen?`<div class="panel form-panel"><p>${openingCopy}</p><button class="button primary" id="start-all-rounds">${hasEnded?'Reopen test rounds':'Open all rounds'}</button></div>`:hasEnded?'<div class="panel form-panel"><p>One or more rounds have ended. Existing progress and results are protected; contact a super-admin to review the event state.</p></div>':''}` + rounds.map(round => `<article class="round-control-card"><span class="round-number">0${round.number}</span><h3>${esc(round.name)}</h3><p>${status(round.status)}${round.started_at?` · Started ${date(round.started_at)}`:''}</p><div class="round-actions">${round.status==='PAUSED'?`<button class="button secondary" data-round-action="resume" data-round-id="${round.id}">Resume</button>`:''}${round.status==='ACTIVE'?`<button class="button secondary" data-round-action="pause" data-round-id="${round.id}">Pause</button><button class="button primary" data-round-action="end" data-round-id="${round.id}">End round</button>`:''}</div></article>`).join('');
      const open = host.querySelector('#start-all-rounds');
      if (open) open.onclick = async () => {
        try { if (hasEnded && !confirm('Reopen all three TEST rounds? This is allowed only before any team progress or results exist.')) return; await api('/api/rounds/start-all', {method:'POST',body:'{}'}); toast('All three rounds are open'); loadRounds(); loadOverview(); }
        catch (error) { toast(error.message, true); }
      };
      host.querySelectorAll('[data-round-action]').forEach(button => button.onclick = async () => {
        try {
          if (button.dataset.roundAction === 'end' && !confirm('End this global round? Teams in later batches may still need it. Incomplete teams will remain incomplete.')) return;
          await api(`/api/rounds/${button.dataset.roundId}/${button.dataset.roundAction}`, {method:'POST',body:'{}'});
          toast({pause:'Round paused',resume:'Round resumed',end:'Round ended'}[button.dataset.roundAction]); loadRounds(); loadOverview();
        } catch (error) { toast(error.message, true); }
      });
    } catch (error) { toast(error.message, true); }
  }
  async function loadMonitoring(){try{const rows=await api('/api/admin/monitoring');const filter=document.getElementById('monitor-filter').value;const filtered=rows.filter(row=>filter==='all'||(filter==='active'?row.status==='ACTIVE':filter==='completed'?row.status==='COMPLETED':row.round===Number(filter)));document.getElementById('monitor-table').innerHTML=filtered.length?filtered.map(row=>`<tr><td><b>${esc(row.team_id)}</b><small style="display:block;margin-top:3px;color:#929bae">${esc(row.team_name)} · Batch ${esc(row.batch_number||'—')} ${esc(row.batch_status)}</small></td><td>${row.round?`R${row.round}`:'—'}</td><td>${esc(row.current_qr)}</td><td>${date(row.last_scan)}</td><td><b>${row.score}</b></td><td>${date(row.round_start)}</td><td>${date(row.last_activity)}</td><td>${status(row.status)}</td></tr>`).join(''):'<tr><td colspan="8" class="empty-cell">No teams match this filter.</td></tr>';}catch(error){toast(error.message,true);}}
  document.getElementById('monitor-filter').onchange=loadMonitoring;
  async function loadScores(){try{const rows=await api('/api/admin/scores');document.getElementById('scores-table').innerHTML=rows.length?rows.map(row=>`<tr><td>${esc(row.team_id)}</td><td>${esc(row.team_name)}</td><td>Round ${row.round}</td><td><b>${row.points}</b></td><td>${date(row.updated_at)}</td></tr>`).join(''):'<tr><td colspan="5" class="empty-cell">No scores have been recorded.</td></tr>';loadTeams();}catch(error){toast(error.message,true);}}
  async function loadLeaderboard(){try{const rows=await api('/api/leaderboard');drawLeaderboard(rows,'leaderboard-table');document.getElementById('podium').innerHTML=rows.slice(0,3).map((row,index)=>`<div class="podium-card"><span class="podium-rank">${['1st place','2nd place','3rd place'][index]}</span><strong>${esc(row.team_name)}</strong><small>${esc(row.team_id)} · ${row.score} points · ${clock(row.time)}</small></div>`).join('');}catch(error){toast(error.message,true);}}
  async function loadResults(){try{const rows=await api('/api/results');document.getElementById('results-table').innerHTML=rows.length?rows.map(row=>`<tr><td><span class="rank-num ${row.rank===1?'top':''}">${row.rank}</span></td><td><b>${esc(row.team_id)}</b> · ${esc(row.team_name)}</td><td>${row.score}</td><td>${clock(row.time)}</td><td>${date(row.completed_at)}</td><td>${row.locked?'LOCKED':'Editable'}</td></tr>`).join(''):'<tr><td colspan="6" class="empty-cell">Results have not been generated.</td></tr>';document.getElementById('results-podium').innerHTML=rows.slice(0,3).map((row,index)=>`<div class="podium-card"><span class="podium-rank">${['1st place','2nd place','3rd place'][index]}</span><strong>${esc(row.team_name)}</strong><small>${row.score} pts · ${clock(row.time)}</small></div>`).join('');}catch(error){toast(error.message,true);}}
  document.getElementById('generate-results').onclick=async()=>{if(!confirm('Generate the final ranking from current server-side scores?'))return;try{await api('/api/results/generate',{method:'POST',body:'{}'});toast('Final results generated');loadResults();}catch(error){toast(error.message,true);}};
  document.getElementById('lock-results').onclick=async()=>{if(!confirm('Lock final results? Only a super-admin can unlock them.'))return;try{await api('/api/results/lock',{method:'POST',body:'{}'});toast('Final results locked');loadResults();}catch(error){toast(error.message,true);}};
  async function loadActivity(){try{const rows=await api('/api/admin/activity');document.getElementById('activity-table').innerHTML=rows.length?rows.map(row=>`<tr><td>${date(row.timestamp)}</td><td><b>${esc(row.action)}</b></td><td>${esc(row.target)}</td><td class="activity-table-cell">${esc(JSON.stringify(row.metadata||{}))}</td></tr>`).join(''):'<tr><td colspan="4" class="empty-cell">No audit events yet.</td></tr>';}catch(error){toast(error.message,true);}}
  const updateClock=()=>document.getElementById('clock').textContent=new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'});
  updateClock();setInterval(updateClock,1000);
  window.addEventListener('hashchange',()=>showView(location.hash.slice(1)));
  showView(views.includes(location.hash.slice(1))?location.hash.slice(1):'overview');
  let liveRefreshTimer;
  const scheduleLiveRefresh = () => {
    clearTimeout(liveRefreshTimer);
    liveRefreshTimer = setTimeout(() => {
      if(document.getElementById('view-leaderboard').classList.contains('active')) loadLeaderboard();
      if(document.getElementById('view-overview').classList.contains('active')) loadOverview();
    }, 100);
  };
  if(window.io){
    const socket=io();
    socket.on('connect',()=>{
      const state=document.getElementById('connection-status');
      state.classList.remove('reconnecting');
      state.querySelector('span').textContent='Live updates connected';
      socket.emit('join_admin');
    });
    socket.on('disconnect',()=>{
      const state=document.getElementById('connection-status');
      state.classList.add('reconnecting');
      state.querySelector('span').textContent='Reconnecting · polling active';
    });
    socket.on('activity',item=>{
      toast(item.message);
      if(document.getElementById('view-batches').classList.contains('active'))loadBatches();
      if(document.getElementById('view-scores').classList.contains('active'))loadScores();
      if(document.getElementById('view-operations').classList.contains('active'))window.refreshRound3Monitor?.();
      if(document.getElementById('view-activity').classList.contains('active'))loadActivity();
      if(document.getElementById('view-monitoring').classList.contains('active'))loadMonitoring();
      scheduleLiveRefresh();
    });
    socket.on('leaderboard_update',scheduleLiveRefresh);
  }
  setInterval(()=>{if(document.getElementById('view-monitoring').classList.contains('active'))loadMonitoring();if(document.getElementById('view-batches').classList.contains('active'))loadBatches();if(document.getElementById('view-overview').classList.contains('active'))loadOverview();},15000);
})();
