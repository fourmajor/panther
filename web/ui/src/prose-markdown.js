import {marked} from 'marked';
// Parse Markdown structure without HTML execution, remote resources or
// artifact-supplied navigation. Only the application's typed resolver links text.
export function renderProseMarkdown(parent,markdown,appendText){
 const text=(node,value)=>appendText(node,String(value??''));
 const inline=(node,tokens=[])=>{for(const token of tokens){
  if(['strong','em','del'].includes(token.type)){const el=document.createElement(token.type);inline(el,token.tokens);node.append(el);}
  else if(token.type==='codespan'){const el=document.createElement('code');el.textContent=token.text;node.append(el);}
  else if(token.type==='br')node.append(document.createElement('br'));
  else if(token.type==='link'||token.type==='image'||token.type==='html')text(node,token.raw);
  else if(token.tokens)inline(node,token.tokens);else text(node,token.text??token.raw);
 }};
 const blocks=(node,tokens=[])=>{for(const token of tokens){
  if(token.type==='space')continue;
  if(token.type==='heading'){const el=document.createElement(`h${Math.min(token.depth+1,6)}`);inline(el,token.tokens);node.append(el);}
  else if(token.type==='paragraph'||token.type==='text'){const el=document.createElement('p');inline(el,token.tokens||[{type:'text',text:token.text}]);node.append(el);}
  else if(token.type==='blockquote'){const el=document.createElement('blockquote');blocks(el,token.tokens);node.append(el);}
  else if(token.type==='list'){const el=document.createElement(token.ordered?'ol':'ul');if(token.ordered&&token.start!==1)el.start=token.start;for(const item of token.items){const li=document.createElement('li');if(item.task)li.append(document.createTextNode(item.checked?'☑ ':'☐ '));blocks(li,item.tokens);el.append(li);}node.append(el);}
  else if(token.type==='code'){const pre=document.createElement('pre'),code=document.createElement('code');code.textContent=token.text;pre.append(code);node.append(pre);}
  else if(token.type==='hr')node.append(document.createElement('hr'));
  else if(token.type==='table'){const wrapper=document.createElement('div');wrapper.className='novel-table';const table=document.createElement('table'),head=document.createElement('thead'),row=document.createElement('tr');for(const cell of token.header){const th=document.createElement('th');th.scope='col';inline(th,cell.tokens);row.append(th);}head.append(row);table.append(head);const body=document.createElement('tbody');for(const cells of token.rows){const tr=document.createElement('tr');for(const cell of cells){const td=document.createElement('td');inline(td,cell.tokens);tr.append(td);}body.append(tr);}table.append(body);wrapper.append(table);node.append(wrapper);}
  else {const el=document.createElement('p');text(el,token.raw||token.text);node.append(el);}
 }};
 parent.replaceChildren();blocks(parent,marked.lexer(String(markdown||''),{gfm:true}));
}
