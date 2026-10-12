(() => {
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const liveCameraAvailable = !!(window.isSecureContext && navigator.mediaDevices?.getUserMedia);
  let summary, summaryReceivedAt=Date.now(), cameraControls, cameraReader, cameraStarting=false, scanHandled=false;
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
      summary=dashboard;summaryReceivedAt=Date.now();renderElapsed();
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
      const canScan=active && ['ROUND_1_ACTIVE','ROUND_1_COMPLETED','ROUND_2_COMPLETED','ROUND_3_ACTIVE'].includes(summary.team.state) && !summary.round3?.sheet_received_at;
      $('scan-open').hidden=!canScan;
      $('scan-open').textContent=liveCameraAvailable?'▦ Scan QR':'▦ Take QR photo';
      $('scan-photo').hidden=!canScan||!liveCameraAvailable;
      $('scan-mode-note').hidden=!canScan||liveCameraAvailable;
      $('scan-fallback').hidden=!canScan;
      $('manual-scan').hidden=!active;
      $('quiz-next').hidden=!['ROUND_2_ACTIVE','ROUND_2_COMPLETED'].includes(summary.team.state);
      const r3=summary.round3;
      $('round3-box').hidden=!(r3?.configured && ['ROUND_2_COMPLETED','ROUND_3_ACTIVE','COMPLETED'].includes(summary.team.state));
      $('round3-completion').hidden=!(active&&r3?.password_solved&&!r3.completed_at&&summary.team.state==='ROUND_3_ACTIVE');
      if(r3?.configured){
        $('password-clue').hidden=!r3.password_clue;
        $('password-clue').textContent=`Password riddle: ${r3.password_clue||''}`;
        $('round3-password-form').hidden=!(active && r3.password_clue && !r3.password_solved && r3.attempts_remaining>0 && !r3.sheet_received_at && !r3.submitted_at);
        $('round3-attempts').textContent=`Password attempts remaining: ${r3.attempts_remaining}`;
        $('round3-status').textContent=r3.submitted_at?'Your paper submission is recorded. Results will be announced after judging.':r3.completed_at?'Quest complete. Your finish time is saved. The organizer will confirm your returned sheet and evaluate it.':r3.sheet_received_at?'Sheet collection confirmed. Answer on paper and return it to the organizer.':r3.password_solved?'Password accepted. Show this confirmation to the organizer to collect your question sheet.':r3.attempts_remaining===0?'No password attempts remain. Contact the organizer.':'Scan your Round 3 password QR, solve the riddle, and enter its answer here.';
      }
      const instructions={REGISTERED:['Ready for your first clue?','Start Round 1, then scan the QR matching the number on your envelope.'],ROUND_1_ACTIVE:['Find your assigned QR.','Scan the QR matching the number on your envelope to reveal your clue.'],ROUND_1_COMPLETED:['Follow the clue.','Solve the clue and scan the destination QR to open your ten-question quiz.'],ROUND_2_ACTIVE:['Your quiz is ready.','Open the quiz to continue. Answers save as you select them. Results are announced later.'],ROUND_2_COMPLETED:['Solve your Round 3 password riddle.','Scan your assigned password riddle QR.'],ROUND_3_ACTIVE:['Solve a riddle and get your sheet.','Enter the password here, then collect your sheet from the organizer. Answer on paper and return it to the organizer.'],COMPLETED:['Quest complete.','Your submissions have been recorded. Results will be announced after judging.'],DISQUALIFIED:['Contact your coordinator.','Your team is unable to continue. Please speak to an event coordinator.']};
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
      $('scan-result').hidden=false;$('scan-result').textContent=result.round===2?'Destination verified. Your quiz is ready below.':`${result.qr_id}\n${result.prompt}\n${result.message}`;
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
    if(result.submitted_at){box.innerHTML=`<div class="completion-card" role="status"><h3 tabindex="-1">Submission confirmed.</h3><p>Your responses have been recorded. Results will be announced later.</p>${kind==='quiz'&&result.riddle?`<p><strong>Round 2 riddle:</strong> ${esc(result.riddle)}</p>`:''}</div>`;box.scrollIntoView({behavior:'smooth',block:'start'});box.querySelector('h3')?.focus({preventScroll:true});return;}
    box.innerHTML=`<div class="challenge-heading"><h3 tabindex="-1">${kind==='quiz'?'Round 2 quiz':'Final challenge'}</h3><div class="challenge-progress-wrap"><span class="challenge-progress" id="answer-progress">0 of ${result.questions.length} answered</span><span class="progress-track" role="progressbar" aria-label="Quiz answers completed" aria-valuemin="0" aria-valuemax="${result.questions.length}" aria-valuenow="0"><i></i></span></div></div><form id="challenge-form"><p id="save-status" role="status">Your answers save as you go.</p>${result.questions.map((q,i)=>`<label class="question-row"><span class="question-number">${String(i+1).padStart(2,'0')}</span><span class="question-prompt">${esc(q.prompt)}</span>${q.kind==='MCQ'?`<select required data-question="${q.id}"><option value="">Choose an answer</option>${Object.entries(q.options).map(([key,value])=>`<option value="${key}">${key}. ${esc(value)}</option>`).join('')}</select>`:q.kind==='TRUE/FALSE'?`<select required data-question="${q.id}"><option value="">Choose an answer</option><option>TRUE</option><option>FALSE</option></select>`:`<textarea required maxlength="4000" rows="3" data-question="${q.id}"></textarea>`}</label>`).join('')}<button class="button primary" type="submit">Submit ${kind==='quiz'?'quiz':'final challenge'}</button></form>`;
    box.scrollIntoView({behavior:'smooth',block:'start'});box.querySelector('.challenge-heading h3')?.focus({preventScroll:true});
    let pending=new Map(),saving=false;
    const progress=()=>{const fields=[...box.querySelectorAll('[data-question]')],count=fields.filter(f=>f.value.trim()).length;box.querySelector('#answer-progress').textContent=`${count} of ${fields.length} answered`;const bar=box.querySelector('[role="progressbar"]');bar.setAttribute('aria-valuenow',count);bar.style.setProperty('--progress',`${fields.length?count/fields.length*100:0}%`);};
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
      try{const response=await api(`/api/team/${kind}/submit`,{method:'POST',body:'{}'});box.innerHTML=`<div class="completion-card" role="status"><h3>Submission confirmed.</h3><p>${esc(response.message)}</p>${kind==='quiz'&&response.riddle?`<p><strong>Round 2 riddle:</strong> ${esc(response.riddle)}</p>`:''}</div>`;if(!document.body.dataset.desktop)await refresh();}catch(e){toast(e.message,true);button.disabled=false;}
    };
  }
  async function openQuiz(){try{await renderChallenge('quiz',$('quiz-box'));}catch(e){toast(e.message,true);}}
  if($('quiz-next'))$('quiz-next').onclick=openQuiz;
  function renderElapsed(){
    if(!summary)return;
    const seconds=Math.max(0,(summary.elapsed_seconds||0)+(summary.session_active?Math.floor((Date.now()-summaryReceivedAt)/1000):0));
    $('team-elapsed').textContent=[Math.floor(seconds/3600),Math.floor(seconds/60)%60,seconds%60].map(n=>String(n).padStart(2,'0')).join(':');
  }
  if($('complete-round3'))$('complete-round3').onclick=async()=>{
    if(!confirm('Have you finished your paper answers and returned the sheet? Complete Round 3 now to save your final time. This cannot be undone.'))return;
    const button=$('complete-round3');button.disabled=true;
    try{const result=await api('/api/team/round3/complete',{method:'POST',body:'{}'});toast(result.message);await refresh();}
    catch(error){toast(error.message,true);}finally{button.disabled=false;}
  };
  if($('round3-password-form'))$('round3-password-form').onsubmit=async e=>{
    e.preventDefault();const button=e.currentTarget.querySelector('button');button.disabled=true;
    try{const result=await api('/api/team/round3/password',{method:'POST',body:JSON.stringify({password:$('round3-password').value})});$('round3-password').value='';toast(result.message,!result.password_solved);await refresh();}
    catch(error){toast(error.message,true);}finally{button.disabled=false;}
  };
  {
    const scan=new URLSearchParams(location.search).get('scan');
    if(scan){$('scan-fallback').open=true;refresh().then(()=>submitToken(scan));history.replaceState({},'',location.pathname);}
    else refresh();
    setInterval(refresh,20000);setInterval(renderElapsed,1000);
  }
})();
