import * as maplibregl from 'https://unpkg.com/maplibre-gl@6.16.0/dist/maplibre-gl.mjs';

const center=[121.0244,14.5547];
let map=null,latest=null,parkMarkers=[],userMarker=null;

function popup(listing){
  const wrapper=document.createElement('div');wrapper.className='map-popup';
  const title=document.createElement('strong');title.textContent=listing.name;wrapper.append(title);
  const address=document.createElement('small');address.textContent=`${listing.city} · PHP ${listing.hourly_rate}/hr`;wrapper.append(address);
  const button=document.createElement('button');button.type='button';button.className='button small';button.textContent='Reserve';
  button.addEventListener('click',()=>window.dispatchEvent(new CustomEvent('parkar:reserve',{detail:{id:listing.id}})));
  wrapper.append(button);return wrapper;
}

function createMap(){
  const container=document.getElementById('liveMap');if(!container)return null;
  if(map){
    if(map.getContainer()!==container){
      map.remove();
      map=null;
    } else {
      return map;
    }
  }
  if(!maplibregl.supported()){container.innerHTML='<div class="map-unavailable">This device does not support the interactive 3D map. Use “Open map” from a listing instead.</div>';return null}
  const style=document.documentElement.dataset.mapStyle||'https://tiles.openfreemap.org/styles/bright';
  map=new maplibregl.Map({container,style,center,zoom:13,pitch:50,bearing:-12,antialias:true,attributionControl:true});
  map.addControl(new maplibregl.NavigationControl({visualizePitch:true}),'top-right');
  map.on('load',()=>{
    try{
      const styleLayers=map.getStyle().layers||[];let labelLayer;
      for(const layer of styleLayers){if(layer.type==='symbol'&&layer.layout?.['text-field']){labelLayer=layer.id;break}}
      if(!map.getSource('openfreemap'))map.addSource('openfreemap',{type:'vector',url:document.documentElement.dataset.mapVector||'https://tiles.openfreemap.org/planet'});
      if(!map.getLayer('parkar-3d-buildings'))map.addLayer({id:'parkar-3d-buildings',source:'openfreemap','source-layer':'building',type:'fill-extrusion',minzoom:14,filter:['!=',['get','hide_3d'],true],paint:{'fill-extrusion-color':['interpolate',['linear'],['get','render_height'],0,'#dce4d8',40,'#a9b99f',140,'#718b71'],'fill-extrusion-height':['interpolate',['linear'],['zoom'],14,0,15.5,['get','render_height']],'fill-extrusion-base':['interpolate',['linear'],['zoom'],14,0,15.5,['get','render_min_height']],'fill-extrusion-opacity':0.82}},labelLayer);
    }catch(e){console.warn('3D building layer warning:',e)}
    updateData(latest||{listings:[]});
  });
  map.on('error',(err)=>{
    console.error('Map error:',err);
    if(!container.querySelector('.map-error')){
      const note=document.createElement('div');note.className='map-error';
      note.textContent='Map tiles are loading or temporarily unavailable. Listing and booking functions remain fully active.';
      container.append(note);
    }
  });
  return map;
}

function updateData(data){
  latest=data||{listings:[]};const current=createMap();if(!current)return;
  for(const marker of parkMarkers)marker.remove();parkMarkers=[];
  const positioned=(latest.listings||[]).filter(l=>l.latitude!==null&&l.longitude!==null&&l.latitude!==''&&l.longitude!=='');
  for(const listing of positioned){const element=document.createElement('button');element.className='map-pin';element.type='button';element.setAttribute('aria-label',`Parking ${listing.name}`);element.textContent='P';const marker=new maplibregl.Marker({element,anchor:'bottom'}).setLngLat([Number(listing.longitude),Number(listing.latitude)]).setPopup(new maplibregl.Popup({offset:25}).setDOMContent(popup(listing))).addTo(current);parkMarkers.push(marker)}
  const route=latest.route?.geometry;
  if(current.isStyleLoaded())setRoute(route);else current.once('idle',()=>setRoute(route));
  if(positioned.length){if(positioned.length===1)current.flyTo({center:[Number(positioned[0].longitude),Number(positioned[0].latitude)],zoom:16,pitch:55});else{const bounds=positioned.reduce((b,l)=>b.extend([Number(l.longitude),Number(l.latitude)]),new maplibregl.LngLatBounds([Number(positioned[0].longitude),Number(positioned[0].latitude)],[Number(positioned[0].longitude),Number(positioned[0].latitude)]));current.fitBounds(bounds,{padding:60,maxZoom:16,duration:600,pitch:45})}}
  setTimeout(()=>current.resize(),60);
  setTimeout(()=>current.resize(),300);
  setTimeout(()=>current.resize(),800);
}

function setRoute(geometry){
  if(!map||!map.isStyleLoaded())return;
  const source=map.getSource('parkar-route');const data={type:'Feature',geometry:geometry||{type:'LineString',coordinates:[]},properties:{}};
  if(source)source.setData(data);else{map.addSource('parkar-route',{type:'geojson',data});map.addLayer({id:'parkar-route-line',type:'line',source:'parkar-route',paint:{'line-color':'#6e9650','line-width':5,'line-opacity':0.9,'line-dasharray':[2,1]}})}
}

window.addEventListener('parkar:map-data',event=>updateData(event.detail));
window.addEventListener('parkar:reserve',event=>window.dispatchEvent(new CustomEvent('parkar:open-booking',{detail:event.detail})));
window.addEventListener('parkar:user-location',event=>{
  const {latitude,longitude}=event.detail||{};
  if(!latitude||!longitude)return;
  const current=createMap();if(!current)return;
  if(userMarker)userMarker.remove();
  const el=document.createElement('div');
  el.style.width='16px';el.style.height='16px';el.style.borderRadius='50%';
  el.style.background='#3b82f6';el.style.border='3px solid white';
  el.style.boxShadow='0 0 10px #3b82f6';
  userMarker=new maplibregl.Marker({element:el}).setLngLat([Number(longitude),Number(latitude)]).addTo(current);
  current.flyTo({center:[Number(longitude),Number(latitude)],zoom:15,pitch:45});
});
window.__maplibreReady=true;
window.dispatchEvent(new Event('parkar:maplibre-ready'));
