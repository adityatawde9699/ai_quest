(() => {
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const liveCameraAvailable = !!(window.isSecureContext && navigator.mediaDevices?.getUserMedia);
  let summary, cameraControls, cameraReader, cameraStarting=false, scanHandled=false;
  const toast = (message,error=false) => {const node=document.createElement('div');node.className=`toast${error?' error':''}`;node.textContent=message;$('toast-root').append(node);setTimeout(()=>node.remove(),6000);};
  async function api(path,options={}) {
    const response=await fetch(path,{credentials:'same-origin',...options,headers:{'Content-Type':'application/json','X-CSRFToken':csrf}});
    if(response.redirected) { location.assign('/team/login'); throw new Error('Please sign in again.'); }
    const value=await response.json();if(!response.ok)throw new Error(value.error||'Request failed');return value;
  }
  async function refresh() {
    try {
      const [dashboard, rounds, rows] = await Promise.all([
        api('/api/team/dashboard'), api('/api/team/rounds'), api('/api/leaderboard')
      ]);
      summary=dashboard;
      $('team-name').textContent=summary.team.team_name;
      $('team-id').textContent=summary.team.team_id;
      $('team-batch').textContent=summary.team.batch_number?`Batch ${summary.team.batch_number} · ${summary.team.batch_status.replaceAll('_',' ').toLowerCase()}`:'Batch assignment pending';
      $('team-status').textContent=summary.team.state.replaceAll('_',' ').toLowerCase().replace(/\b\w/g,c=>c.toUpperCase());
      $('team-status').dataset.state=summary.team.state;
      $('action-round').textContent=String(summary.round_number||3).padStart(2,'0');
      $('event-status').textContent=summary.team.state==='COMPLETED'?'Quest completed':summary.round_number===1&&!summary.session_active&&summary.team.batch_status==='PAUSED'?'Batch paused':summary.round_number===1&&!summary.session_active&&!['RELEASED','IN_PROGRESS'].includes(summary.team.batch_status)?'Waiting for batch':summary.round_status==='ACTIVE'?'Round open':summary.round_status==='PAUSED'?'Round paused':'Waiting for coordinator';
      $('team-score').textContent=summary.score ?? 'Pending';
      $('team-round').textContent=summary.current_round;
      $('team-round-status').textContent=summary.round_status;
      const active=summary.round_status==='ACTIVE';
      const batchReady=['RELEASED','IN_PROGRESS'].includes(summary.team.batch_status);
      $('start-round').hidden=!(active&&batchReady&&summary.round_number===1&&!summary.session_active);
      const canScan=active && ['ROUND_1_ACTIVE','ROUND_1_COMPLETED','ROUND_2_COMPLETED'].includes(summary.team.state);
      $('scan-open').hidden=!canScan;
      $('scan-open').textContent=liveCameraAvailable?'▦ Scan QR':'▦ Take QR photo';
      $('scan-photo').hidden=!canScan||!liveCameraAvailable;
      $('scan-mode-note').hidden=!canScan||liveCameraAvailable;
      $('scan-fallback').hidden=!canScan;
      $('manual-scan').hidden=!active;
      $('quiz-next').hidden=!['ROUND_2_ACTIVE','ROUND_2_COMPLETED'].includes(summary.team.state);
      $('desktop-open').hidden=!summary.desktop_id;
      $('desktop-open').href=summary.desktop_id?`/desktop/${summary.desktop_id}`:'#';
      const instructions={REGISTERED:['Ready for your first clue?','Start Round 1, then scan the QR matching the number on your envelope.'],ROUND_1_ACTIVE:['Find your assigned QR.','Scan the QR matching the number on your envelope to reveal your clue.'],ROUND_1_COMPLETED:['Follow the clue.','Solve the clue and scan the destination QR to open your ten-question quiz.'],ROUND_2_ACTIVE:['Your quiz is ready.','Open the quiz to continue. Answers save as you select them. Results are announced later.'],ROUND_2_COMPLETED:['Head to the desktop station.','Follow the coordinator’s instructions and scan your desktop QR.'],PASSWORD_CHALLENGE:['Solve the password clue.','Continue on your assigned desktop. Your attempt count is saved.'],FINAL_CHALLENGE:['Finish the final challenge.','Continue on your assigned desktop. Your questions and answers are saved.'],COMPLETED:['Quest complete.','Your submissions have been recorded. Results will be announced after judging.'],DISQUALIFIED:['Contact your coordinator.','Your team is unable to continue. Please speak to an event coordinator.']};
      const [heading,copy]=instructions[summary.team.state]||[summary.current_round,'Follow the coordinator’s instructions.'];
      $('action-heading').textContent=heading;
      $('action-copy').textContent=summary.round_number===1&&!summary.session_active&&summary.team.batch_status==='PAUSED'?'Your batch is paused. Please wait for the coordinator to resume it.':summary.round_number===1&&!summary.session_active&&!batchReady?'Your batch is waiting for release. Please wait for the coordinator.':summary.round_status==='PAUSED'?'This round is paused. Your progress is saved. Wait for the coordinator to resume it.':copy;
      if(summary.clue && summary.team.state==='ROUND_1_COMPLETED'){$('scan-result').hidden=false;$('scan-result').textContent=summary.clue;}
      if(summary.destination && summary.team.state==='ROUND_2_COMPLETED'){$('scan-result').hidden=false;$('scan-result').textContent=summary.destination;}
      $('team-round-track').innerHTML=rounds.map(r=>`<div class="team-round-step ${summary.team.state==='COMPLETED'||r.number<summary.round_number?'done':r.number===summary.round_number?'active':''}"><strong>${r.number} · ${esc(r.name)}</strong><small>${summary.team.state==='COMPLETED'||r.number<summary.round_number?'Completed':`${r.number===summary.round_number?'Your current round':'Up next'} · ${esc(r.status.toLowerCase())}`}</small></div>`).join('');
      $('team-leaderboard').innerHTML=rows.length?rows.map(r=>`<div class="team-rank"><span class="rank-num">${r.rank}</span><strong>${esc(r.team_name)}</strong><b>${r.score}</b></div>`).join(''):'<div class="empty-state">Results will be announced later.<br>Your scores stay private until the organizers publish them.</div>';
    } catch(error) {toast(error.message,true);}
  }
  if($('start-round'))$('start-round').onclick=async()=>{try{await api(`/api/team/rounds/${summary.round_id}/start`,{method:'POST',body:'{}'});await refresh();}catch(e){toast(e.message,true);}};
  async function submitToken(value) {
    let token=value.trim();try{const url=new URL(token);token=url.pathname.split('/scan/')[1]||token;}catch{}
    try {
      $('manual-scan').querySelector('button').disabled=true;
      const result=await api('/api/team/scan',{method:'POST',body:JSON.stringify({token})});
      $('scan-result').hidden=false;$('scan-result').textContent=`${result.qr_id}\n${result.prompt}\n${result.message}`;
      if(result.round===2)await openQuiz();
      await refresh();
    }catch(e){toast(e.message,true);}finally{$('manual-scan').querySelector('button').disabled=false;}
  }
  if($('manual-scan'))$('manual-scan').onsubmit=e=>{e.preventDefault();submitToken($('token-input').value);};
  function stopCamera(){cameraControls?.stop();cameraControls=null;$('camera-video').pause();$('camera-box').hidden=true;}
  if($('scan-photo'))$('scan-photo').onclick=()=>$('qr-image-input').click();
  $('qr-image-input').onchange=async event=>{
    const input=event.currentTarget, file=input.files?.[0];
    if(!file)return;
    if(!file.type.startsWith('image/')){input.value='';return toast('Choose a QR image or take a photo.',true);}
    if(!window.ZXingBrowser?.BrowserMultiFormatReader){input.value='';return toast('QR image scanner unavailable. Paste the QR link instead.',true);}
    stopCamera();
    const url=URL.createObjectURL(file);
    try{
      const result=await new ZXingBrowser.BrowserMultiFormatReader().decodeFromImageUrl(url);
      await submitToken(result.getText());
    }catch(error){toast('No readable QR code found. Retake the photo with the whole code in focus.',true);}
    finally{URL.revokeObjectURL(url);input.value='';}
  };
  if($('scan-open'))$('scan-open').onclick=async()=>{
    if(cameraStarting||cameraControls)return;
    if(!liveCameraAvailable){$('qr-image-input').click();return;}
    if(!window.ZXingBrowser?.BrowserMultiFormatReader){$('scan-fallback').open=true;return toast('Camera scanner unavailable. Paste the QR link.',true);}
    cameraStarting=true;scanHandled=false;$('scan-open').disabled=true;$('camera-box').hidden=false;
    try{
      cameraReader=new ZXingBrowser.BrowserMultiFormatReader();
      const onScan=result=>{if(!result||scanHandled)return;scanHandled=true;const value=result.getText();stopCamera();submitToken(value);};
      // Prefer the rear camera on phones; browsers without it may use the default camera.
      try{cameraControls=await cameraReader.decodeFromConstraints({audio:false,video:{facingMode:{ideal:'environment'}}},$('camera-video'),onScan);}
      catch(error){if(error.name==='OverconstrainedError'||error.name==='NotFoundError')cameraControls=await cameraReader.decodeFromVideoDevice(undefined,$('camera-video'),onScan);else throw error;}
      if(scanHandled)stopCamera();
    }catch(error){stopCamera();$('scan-fallback').open=true;toast(error.name==='NotAllowedError'||error.name==='PermissionDeniedError'?'Camera permission was denied. Allow camera access in your browser settings or paste the QR link.':error.name==='NotFoundError'?'No camera was found on this device. Paste the QR link.':'Camera could not start. Close other camera apps or paste the QR link.',true);}
    finally{cameraStarting=false;$('scan-open').disabled=false;}
  };
  if($('stop-camera'))$('stop-camera').onclick=stopCamera;
  document.addEventListener('visibilitychange',()=>{if(document.hidden&&cameraControls)stopCamera();});
  async function renderChallenge(kind, box) {
    const result=await api(`/api/team/${kind}`);
    box.hidden=false;
    if(result.submitted_at){box.innerHTML='<div class="completion-card" role="status"><h3>Submission confirmed.</h3><p>Your responses have been recorded. Results will be announced later.</p></div>';return;}
    box.innerHTML=`<div class="challenge-heading"><h3>${kind==='quiz'?'Round 2 quiz':'Final challenge'}</h3><span class="challenge-progress" id="answer-progress"></span></div><form id="challenge-form"><p id="save-status" role="status">Answers saved on the server are restored below.</p>${result.questions.map((q,i)=>`<label class="question-row">${i+1}. ${esc(q.prompt)}${q.kind==='MCQ'?`<select required data-question="${q.id}"><option value="">Choose an answer</option>${Object.entries(q.options).map(([key,value])=>`<option value="${key}">${key}. ${esc(value)}</option>`).join('')}</select>`:q.kind==='TRUE/FALSE'?`<select required data-question="${q.id}"><option value="">Choose an answer</option><option>TRUE</option><option>FALSE</option></select>`:`<textarea required maxlength="4000" rows="3" data-question="${q.id}"></textarea>`}</label>`).join('')}<button class="button primary" type="submit">Submit ${kind==='quiz'?'quiz':'final challenge'}</button></form>`;
    let pending=new Map(),saving=false;
    const progress=()=>{const fields=[...box.querySelectorAll('[data-question]')];box.querySelector('#answer-progress').textContent=`${fields.filter(f=>f.value.trim()).length} of ${fields.length} answered`;};
    const prefix=`quest:${summary?.team.team_id||document.body.dataset.team}:${kind}:`;
    const state=box.querySelector('#save-status');
    async function flush() {
      if(saving)return; saving=true;
      try {
        while(pending.size){const [id,value]=pending.entries().next().value;state.textContent='Saving…';await api(`/api/team/${kind}/answers/${id}`,{method:'PUT',body:JSON.stringify({answer:value})});if(pending.get(id)===value){pending.delete(id);try{sessionStorage.removeItem(prefix+id);}catch{}}}
        state.textContent='All answers saved on the server.';
      }catch(e){state.textContent=`Unsaved answers — ${e.message}. Keep this page open; retrying.`;}finally{saving=false;}
    }
    box.querySelectorAll('[data-question]').forEach(input=>{
      const id=input.dataset.question;
      let draft=null;try{draft=sessionStorage.getItem(prefix+id);}catch{}
      input.value=draft??result.answers[id]??'';
      if(draft){pending.set(id,draft);}
      let debounce;input.addEventListener('input',()=>{progress();if(input.value.trim()){pending.set(id,input.value);try{sessionStorage.setItem(prefix+id,input.value);}catch{}state.textContent='Unsaved changes…';clearTimeout(debounce);debounce=setTimeout(flush,700);}});input.addEventListener('change',()=>{progress();if(input.value.trim()){pending.set(id,input.value);try{sessionStorage.setItem(prefix+id,input.value);}catch{}flush();}});
    });
    progress();
    const retry=setInterval(()=>{if(!document.contains(state)){clearInterval(retry);return;}if(pending.size)flush();},5000);
    if(pending.size)flush();
    window.addEventListener('beforeunload',e=>{if(pending.size){e.preventDefault();e.returnValue='';}});
    box.querySelector('form').onsubmit=async e=>{
      e.preventDefault();box.querySelectorAll('[data-question]').forEach(input=>{if(input.value.trim())pending.set(input.dataset.question,input.value);});
      await flush();if(pending.size||saving)return toast('Wait until every answer is saved.',true);
      const button=box.querySelector('button');button.disabled=true;
      try{const response=await api(`/api/team/${kind}/submit`,{method:'POST',body:'{}'});box.innerHTML=`<div class="completion-card" role="status"><h3>Submission confirmed.</h3><p>${esc(response.message)}</p></div>`;if(!document.body.dataset.desktop)await refresh();}catch(e){toast(e.message,true);button.disabled=false;}
    };
  }
  async function openQuiz(){try{await renderChallenge('quiz',$('quiz-box'));}catch(e){toast(e.message,true);}}
  if($('quiz-next'))$('quiz-next').onclick=openQuiz;
  if(document.body.dataset.desktop){
    async function desktopRefresh(){try{const state=await api('/api/team/desktop');$('attempts').textContent=`Attempts remaining: ${state.attempts_remaining}`;$('password-form').hidden=state.unlocked;if(state.unlocked)await renderChallenge('final',$('quiz-box'));}catch(e){toast(e.message,true);}}
    $('password-form').onsubmit=async e=>{e.preventDefault();const button=e.currentTarget.querySelector('button');button.disabled=true;try{const response=await api('/api/team/desktop/password',{method:'POST',body:JSON.stringify({password:$('password').value})});$('password').value='';$('desktop-message').textContent=response.message;await desktopRefresh();}catch(e){toast(e.message,true);}finally{button.disabled=false;}};
    desktopRefresh();
  }else{
    const scan=new URLSearchParams(location.search).get('scan');
    if(scan){$('scan-fallback').open=true;refresh().then(()=>submitToken(scan));history.replaceState({},'',location.pathname);}
    else refresh();
    setInterval(refresh,20000);setInterval(()=>{if(summary)$('team-elapsed').textContent=summary.round_started_at?new Date(Math.max(0,Date.now()-new Date(summary.round_started_at))).toISOString().slice(11,19):'—';},1000);
  }
})();
