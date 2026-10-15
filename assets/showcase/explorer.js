import { assetUrl, element, log, sourceLink, startShowcase } from './ui.js';

function renderPipeline(root, data, base) {
  const controls=root.querySelector('.sc-controls');
  const stage=root.querySelector('.sc-stage');
  const detail=root.querySelector('.sc-details');
  const live=root.querySelector('[role="status"]');
  controls.className='sc-stage-tabs';
  const buttons=data.stages.map((item)=>{
    const button=element('button','',item.label);
    button.type='button';
    button.addEventListener('click',()=>show(item.id));
    controls.append(button);
    return button;
  });
  function show(id) {
    const index=data.stages.findIndex(item=>item.id===id);
    const item=data.stages[index];
    const image=element('img');
    image.src=assetUrl(item.image,base);
    image.alt=item.caption;
    stage.replaceChildren(image,element('figcaption','',item.caption));
    detail.replaceChildren(element('h3','',item.label),element('p','',item.caption),sourceLink(item.source));
    for(let position=0;position<buttons.length;position++)buttons[position].setAttribute('aria-pressed',String(position===index));
    live.textContent=`Stage ${index+1} of ${data.stages.length}: ${item.label}.`;
    log('pipeline:update',{stage:id});
  }
  show('geometry');
}

startShowcase('pipeline',renderPipeline,new URL('./data.json',import.meta.url));
