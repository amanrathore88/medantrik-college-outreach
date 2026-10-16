const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const statusNames = {'verified':'Verified on institution site','directory-listed':'Official directory only','unverified':'Unverified','missing':'Email missing'};
let records=[], filtered=[], selected=new Set(), page=1, token='', editing=null, importToken='';
const fieldLabels = {College_Name:'Institution name',City:'Area',Campus:'Campus / branch',Location:'Address / locality',District:'District',Type:'Institution type / disciplines',Institution_ID:'Official institution identifier',Aliases:'Alternate names',Website:'Official website',TPO_Email:'Contact email',contact_type:'Contact type',Contact_Person:'Public office / contact role',Phone:'Public office phone',source_url:'Email evidence URL',institution_source:'Institution listing source URL',checked_on:'Email checked on',verification_status:'Verification status',notes:'Review notes'};
async function api(url, body) {
  const response=await fetch(url,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':token},body:JSON.stringify(body)});
  const data=await response.json(); if(!response.ok) throw new Error(data.message||'Could not load directory.'); return data;
}
function message(error){$('notice').textContent=error.message||error;}
async function refresh(){
  records=await api('/api/colleges');
  const blocked=new Set(records.filter(r=>r.do_not_contact).map(r=>r.TPO_Email));
  records.forEach(r=>{if(blocked.has(r.TPO_Email))r.sendable=false;});
  selected=new Set([...selected].filter(id=>records.some(r=>r.id===id&&r.sendable)));
  const coverage=await api('/api/coverage');
  $('coverage').innerHTML=coverage.areas.map(a=>`<article>${esc(a.area)}<strong>${a.identified}</strong><small>${a.verified} verified · ${a.missing} missing email<br>${a.contact_found} contact found · ${a.needs_review} need review</small></article>`).join('');
  $('sources').innerHTML=`<p>${esc(coverage.note)} (Inventory date: ${esc(coverage.inventory_date||'2026-10-16')})</p>`+coverage.sources.map(s=>`<p><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.name)}</a> — ${esc(s.status)}. ${esc(s.notes||'')}</p>`).join('');
  filter();
}
function filter(){
  const q=$('query').value.toLowerCase().replaceAll('gurgaon','gurugram');
  filtered=records.filter(r=>(!$('city').value||r.City===$('city').value)&&(!$('status').value||r.verification_status===$('status').value)&&(!$('kind').value||r.contact_type===$('kind').value)&&(!q||[r.College_Name,r.Aliases,r.Location,r.City,r.District,r.Campus,r.TPO_Email,r.Type].join(' ').toLowerCase().replaceAll('gurgaon','gurugram').includes(q)));
  page=1;render();
}
function render(){
  const shown=filtered.slice((page-1)*25,page*25);
  $('rows').innerHTML=shown.map(r=>`<tr><td><input type="checkbox" aria-label="Select ${esc(r.College_Name)}" data-id="${r.id}" ${selected.has(r.id)?'checked':''} ${r.sendable?'':'disabled'}></td><td><strong>${esc(r.College_Name)}</strong><small>${esc(r.Campus||r.Type)}${r.Website?` · <a href="${esc(r.Website)}" target="_blank" rel="noopener">Website</a>`:''}</small></td><td>${esc(r.City)}<small>${esc(r.Location)}</small></td><td>${r.TPO_Email?esc(r.TPO_Email):'Not yet found'}<small>${esc(r.contact_type==='general'?'General contact':r.contact_type==='placement'?'Placement':'Role unconfirmed')}${r.Contact_Person?' · '+esc(r.Contact_Person):''}${r.do_not_contact?' · Do not contact':''}</small></td><td><span class="badge ${r.verification_status==='verified'?'verified':''}">${statusNames[r.verification_status]}</span><small>${r.checked_on?'Checked '+esc(r.checked_on):'Not checked'} ${r.source_url?`· <a href="${esc(r.source_url)}" target="_blank" rel="noopener">Source</a>`:''}</small></td><td><button data-edit="${r.id}">View / edit</button></td></tr>`).join('')||'<tr><td colspan="6">No colleges match these filters.</td></tr>';
  $('results').textContent=`${filtered.length} matching institutions. Only verified, contactable records can be selected for sending.`;
  $('selected').textContent=`${selected.size} selected across pages and filters`;
  $('compose').disabled=!selected.size;
  $('pageLabel').textContent=`Page ${page} of ${Math.max(1,Math.ceil(filtered.length/25))}`;
  $('previous').disabled=page===1;$('next').disabled=page*25>=filtered.length;
}
function openEditor(id){
  editing=records.find(r=>r.id===id)||null;
  $('editorTitle').textContent=editing?'Review institution':'Add institution';
  $('fields').innerHTML=Object.entries(fieldLabels).map(([key,label])=>{
    const value=editing?.[key]||'';let control;
    const options=key==='City'?['Delhi','Noida','Greater Noida','Ghaziabad','Gurugram']:key==='contact_type'?['unknown','placement','general']:key==='verification_status'?['missing','unverified','directory-listed','verified']:null;
    if(options) control=`<select id="field_${key}">${options.map(o=>`<option value="${o}" ${o===value?'selected':''}>${esc(statusNames[o]||o)}</option>`).join('')}</select>`;
    else control=`<input id="field_${key}" value="${esc(value)}" ${key==='College_Name'?'required':''} type="${key==='checked_on'?'date':key==='TPO_Email'?'email':['Website','source_url','institution_source'].includes(key)?'url':'text'}">`;
    return `<label>${label}${control}</label>`;
  }).join('');
  $('blocked').checked=!!editing?.do_not_contact;$('confirmed').checked=false;$('formError').textContent='';$('historyText').textContent='';$('history').disabled=!editing;$('editor').showModal();
}
$('rows').addEventListener('click',event=>{if(event.target.dataset.edit)openEditor(Number(event.target.dataset.edit));});
$('rows').addEventListener('change',event=>{const id=Number(event.target.dataset.id);if(id){event.target.checked?selected.add(id):selected.delete(id);render();}});
['query','city','status','kind'].forEach(id=>$(id).addEventListener(id==='query'?'input':'change',filter));
$('selectMatches').onclick=()=>{filtered.filter(r=>r.sendable).forEach(r=>selected.add(r.id));render();};
$('clear').onclick=()=>{selected.clear();render();};
$('previous').onclick=()=>{page--;render();};$('next').onclick=()=>{page++;render();};
$('compose').onclick=()=>{sessionStorage.setItem('directorySelection',JSON.stringify([...selected]));location.href='/';};
$('add').onclick=()=>openEditor();$('closeEditor').onclick=()=>$('editor').close();
$('collegeForm').onsubmit=async event=>{event.preventDefault();try{
  const record=Object.fromEntries(Object.keys(fieldLabels).map(key=>[key,$('field_'+key).value]));record.do_not_contact=$('blocked').checked;
  await api('/api/directory/save',{record,id:editing?.id,version:editing?.version,verification_confirmed:$('confirmed').checked});$('editor').close();await refresh();message('Record saved.');
}catch(error){$('formError').textContent=error.message;}};
$('history').onclick=async()=>{try{$('historyText').textContent=JSON.stringify(await api('/api/history?id='+editing.id),null,2);}catch(error){$('formError').textContent=error.message;}};
$('import').onclick=()=>{$('importDialog').showModal();};$('closeImport').onclick=()=>$('importDialog').close();
function invalidateImport(){importToken='';$('commitImport').disabled=true;}
$('importText').oninput=invalidateImport;
$('importFile').onchange=async()=>{invalidateImport();const file=$('importFile').files[0];if(file){if(file.size>2000000){$('importSummary').textContent='File exceeds 2 MB.';return;}$('importText').value=await file.text();}};
$('previewImport').onclick=async()=>{invalidateImport();try{const data=await api('/api/import/preview',{text:$('importText').value});importToken=data.token;$('importSummary').textContent=`${data.add} additions · ${data.duplicates} exact duplicates skipped · ${data.errors} errors`;$('commitImport').disabled=!!data.errors||!data.add;$('importRows').innerHTML='<table><tr><th>Row</th><th>Action</th><th>Institution / error</th></tr>'+data.rows.map(r=>`<tr><td>${r.row}</td><td>${esc(r.action)}</td><td>${esc(r.record?.College_Name||r.message)}</td></tr>`).join('')+'</table>';}catch(error){$('importSummary').textContent=error.message;}};
$('commitImport').onclick=async()=>{const current=importToken;invalidateImport();try{const result=await api('/api/import/commit',{token:current});$('importSummary').textContent=`Saved ${result.added}; skipped ${result.skipped}.`;await refresh();}catch(error){$('importSummary').textContent=error.message;}};
$('export').onclick=()=>{const blob=new Blob([JSON.stringify(filtered,null,2)],{type:'application/json'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='college-directory.json';a.click();URL.revokeObjectURL(a.href);};
$('duplicates').onclick=async()=>{try{const pairs=await api('/api/duplicates');$('duplicateRows').innerHTML=pairs.map(p=>{const a=records.find(r=>r.id===p.first),b=records.find(r=>r.id===p.second);return `<article><strong>${esc(a.College_Name)} (#${a.id})</strong> ↔ <strong>${esc(b.College_Name)} (#${b.id})</strong><p>${esc(p.reason)}</p><button data-review="${a.id}">Review first</button> <button data-review="${b.id}">Review second</button> <button data-source="${a.id}" data-target="${b.id}">Merge first into second</button></article>`;}).join('')||'<p>No likely duplicate pairs found. This does not prove the inventory is duplicate-free.</p>';$('duplicateDialog').showModal();}catch(error){message(error);}};
$('duplicateRows').onclick=async event=>{const d=event.target.dataset;if(d.review){$('duplicateDialog').close();openEditor(Number(d.review));return;}if(!d.source)return;
 const a=records.find(r=>r.id===Number(d.source)),b=records.find(r=>r.id===Number(d.target));
 if(!confirm(`Merge ${a.College_Name} into ${b.College_Name}? The target keeps its contact; original details stay in history. Only merge the same campus.`))return;
 try{await api('/api/directory/merge',{source_id:a.id,target_id:b.id,source_version:a.version,target_version:b.version,confirmed:true});$('duplicateDialog').close();await refresh();message('Records merged; original details retained in history.');}catch(error){message(error);$('duplicateDialog').close();}
};
$('closeDuplicates').onclick=()=>$('duplicateDialog').close();
(async()=>{try{token=(await api('/api/settings')).csrf_token;await refresh();}catch(error){message(error);}})();
