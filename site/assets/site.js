document.querySelectorAll('.menu-button').forEach((button)=>button.addEventListener('click',()=>{
  const sidebar=document.getElementById('sidebar');const open=sidebar.classList.toggle('open');
  button.setAttribute('aria-expanded',String(open));
}));
const search=document.getElementById('book-search');
if(search){
  const results=document.getElementById('search-results');let index=[];
  fetch('search-index.json').then(r=>r.json()).then(data=>{index=data;run()});
  const run=()=>{const q=search.value.trim().toLocaleLowerCase();results.innerHTML='';
    if(q.length<2)return;
    index.filter(x=>(x.title+' '+x.text).toLocaleLowerCase().includes(q)).slice(0,50).forEach(x=>{
      const li=document.createElement('li'),a=document.createElement('a'),p=document.createElement('p');
      a.href='pages/'+x.file;a.textContent=x.title;
      const at=x.text.toLocaleLowerCase().indexOf(q),start=Math.max(0,at-80);
      p.textContent=(start?'…':'')+x.text.slice(start,start+240)+(x.text.length>start+240?'…':'');
      li.append(a,p);results.append(li);
    });
    if(!results.children.length)results.innerHTML='<li>No se encontraron resultados.</li>';
  };
  search.addEventListener('input',run);
  const initial=new URLSearchParams(location.search).get('q');if(initial){search.value=initial}
}
